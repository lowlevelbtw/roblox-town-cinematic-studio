#!/usr/bin/env python3
"""End-to-End Audio Generation & Video Synchronization Pipeline for Roblox Town Director.

Implements:
  SCRIPT -> CHARACTER IDENTIFICATION -> VOICE PROFILE SELECTION ->
  DIALOGUE SEGMENTATION -> PROVIDER API REQUEST -> AUDIO GENERATION ->
  AUDIO DOWNLOAD -> FILE VALIDATION -> DIALOGUE TIMING ->
  VIDEO SYNCHRONIZATION -> FINAL AUDIO MIX

Reuses scripts/voice_backend.py (RecordedVoiceBackend & SharedVoiceManager) for
deterministic FFmpeg normalization, additive multi-speaker timeline assembly,
peak clipping protection, and SRT subtitle synchronization, and provides FFmpeg
audio/BGM/SFX/subtitle muxing onto an existing video stream.

NOTE: FFmpeg audio/video muxing and Python-assembled animatics are post-production
composition steps, NOT real Roblox Studio 3D rendering.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audio_qc import inspect_audio_file, inspect_video_file, run_project_audio_qc
from .character_assignment import (
    CharacterVoiceAssigner,
    DialogueSegment,
    load_project_voice_state,
    parse_script_dialogue,
    persist_project_voice_state,
)
from .profile_manager import VoiceProfileManager, utc_now_iso
from .providers import (
    ProviderRegistry,
    SynthesisRequest,
    VoiceProviderAdapter,
    VoiceProviderError,
)

# Import existing hardened Recorded Voice Backend utilities cleanly
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import voice_backend  # noqa: E402
import caption_styles  # noqa: E402


class VideoMuxError(RuntimeError):
    """Raised when FFmpeg audio/video/subtitle synchronization or muxing fails."""


_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9_-]+")
_SAFE_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,10}$")


def sanitize_filename_token(value: str, field_name: str = "id") -> str:
    """Reject path traversal/separators and normalize an ID token for safe filenames."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"Empty filename token for {field_name}.")
    if ".." in raw or "/" in raw or "\\" in raw or "\x00" in raw:
        raise ValueError(f"Unsafe path traversal or separator in {field_name}: {raw!r}")
    cleaned = _SAFE_TOKEN_RE.sub("_", raw).strip("._-")
    if not cleaned:
        raise ValueError(f"Filename token for {field_name} contains no safe characters: {raw!r}")
    return cleaned


def resolve_safe_child_path(parent_dir: Path, filename: str) -> Path:
    """Resolve `parent_dir / filename` and verify it stays strictly inside `parent_dir`."""
    parent_resolved = Path(parent_dir).resolve()
    candidate = (parent_resolved / filename).resolve()
    if candidate.parent != parent_resolved:
        raise ValueError(f"Resolved output path escapes target directory: {filename!r}")
    return candidate


def build_predictable_filename(
    scene_id: str,
    line_id: str,
    character_id: str,
    voice_id: str,
    ext: str = "mp3",
) -> str:
    safe_scene = sanitize_filename_token(scene_id, "scene_id")
    safe_line = sanitize_filename_token(line_id, "line_id")
    safe_char = sanitize_filename_token(character_id, "character_id")
    safe_voice = sanitize_filename_token(voice_id, "voice_id")
    safe_ext = str(ext or "").lstrip(".").lower()
    if not _SAFE_EXT_RE.match(safe_ext):
        raise ValueError(f"Unsafe file extension: {ext!r}")
    return f"{safe_scene}_{safe_line}_{safe_char}_{safe_voice}.{safe_ext}"


def _normalize_stem_to_pcm_wav(src_path: Path, dst_path: Path, timeout_sec: float = 120.0) -> None:
    """Convert any validated audio file into canonical 44.1kHz stereo 16-bit PCM WAV for SharedVoiceManager."""
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-y",
                "-v",
                "error",
                "-i",
                str(src_path),
                "-af",
                "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar",
                str(voice_backend.TARGET_SAMPLE_RATE),
                "-ac",
                str(voice_backend.TARGET_CHANNELS),
                "-c:a",
                "pcm_s16le",
                str(dst_path),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except FileNotFoundError as exc:
        if dst_path.exists():
            dst_path.unlink(missing_ok=True)
        raise RuntimeError("Required binary 'ffmpeg' not found on PATH during stem normalization.") from exc
    except subprocess.TimeoutExpired as exc:
        if dst_path.exists():
            dst_path.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg stem normalization timed out after {timeout_sec}s.") from exc
    if res.returncode != 0:
        if dst_path.exists():
            dst_path.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg stem normalization failed: {res.stderr.strip()}")


def _write_srt_file(entries: List[Dict[str, Any]], srt_path: Path) -> None:
    lines: List[str] = []
    for idx, item in enumerate(entries, 1):
        start = voice_backend.SharedVoiceManager._fmt_srt_time(float(item["start_sec"]))
        end = voice_backend.SharedVoiceManager._fmt_srt_time(float(item["end_sec"]))
        speaker = item.get("display_name") or item.get("character_id", "Speaker")
        lines.append(f"{idx}\n{start} --> {end}\n{speaker}: {item['text']}\n")
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def mux_audio_and_subtitles_to_video(
    *,
    video_path: Path,
    dialogue_audio_path: Path,
    output_video_path: Path,
    bgm_path: Optional[Path] = None,
    sfx_path: Optional[Path] = None,
    subtitles_srt_path: Optional[Path] = None,
    embed_subtitles: bool = True,
    bgm_volume: float = 0.18,
    sfx_volume: float = 0.65,
    preserve_source_audio: bool = False,
    source_audio_volume: float = 0.5,
    caption_style_id: Optional[str] = None,
    caption_genre: str = "story",
    caption_pacing: str = "medium",
    caption_tone: str = "neutral",
    max_audio_overrun_sec: float = 0.25,
    allow_audio_tail_sec: float = 0.0,
    allow_audio_truncation: bool = False,
) -> Dict[str, Any]:
    """Mux dialogue audio (+ optional BGM/SFX and SRT subtitles) onto an existing video.

    Audio mixing behavior:
      - When `preserve_source_audio=False` (default), any existing source-video audio
        track is replaced by dialogue audio (+ optional BGM/SFX).
      - When `preserve_source_audio=True` and the source video has an audio stream,
        the original track is attenuated by `source_audio_volume` and mixed with
        dialogue (+ optional BGM/SFX) through `amix` and `alimiter=limit=0.95` to
        prevent clipping. Videos without an audio stream are handled gracefully.

    Preserves the source video's original resolution and frame rate via `-c:v copy`.
    Explicitly notes that FFmpeg muxing is not Roblox Studio rendering.
    """
    for vname, vval in (
        ("bgm_volume", bgm_volume),
        ("sfx_volume", sfx_volume),
        ("source_audio_volume", source_audio_volume),
    ):
        try:
            vf = float(vval)
        except (TypeError, ValueError) as exc:
            raise VideoMuxError(f"Invalid {vname}: {vval!r}") from exc
        if not math.isfinite(vf) or vf < 0.0 or vf > 5.0:
            raise VideoMuxError(f"{vname} must be finite and between 0.0 and 5.0, got {vval!r}.")

    v_path = Path(video_path)
    d_path = Path(dialogue_audio_path)
    out_path = Path(output_video_path)

    src_video_qc = inspect_video_file(v_path)
    if not src_video_qc["valid"]:
        raise VideoMuxError(
            f"Invalid source video {v_path}: {'; '.join(src_video_qc['errors'])}"
        )

    dlg_qc = inspect_audio_file(d_path, check_volume=True)
    if not dlg_qc["valid"]:
        raise VideoMuxError(
            f"Invalid dialogue audio {d_path}: {'; '.join(dlg_qc['errors'])}"
        )

    # F-15, F-21 & F-24: Validate individual tolerances AND their sum as finite and >= 0.0
    parsed_tolerances: List[float] = []
    for tname, tval in (
        ("max_audio_overrun_sec", max_audio_overrun_sec),
        ("allow_audio_tail_sec", allow_audio_tail_sec),
    ):
        if isinstance(tval, bool):
            raise VideoMuxError(f"Invalid boolean {tname}: {tval!r}")
        try:
            tf = float(tval)
        except (TypeError, ValueError) as exc:
            raise VideoMuxError(f"Invalid {tname}: {tval!r}") from exc
        if not math.isfinite(tf) or tf < 0.0:
            raise VideoMuxError(f"{tname} must be finite and >= 0.0, got {tval!r}.")
        parsed_tolerances.append(tf)
    audio_overrun_sec = round(float(dlg_qc["duration_sec"]) - float(src_video_qc["duration_sec"]), 4)
    allowed_overrun = parsed_tolerances[0] + parsed_tolerances[1]
    if not math.isfinite(allowed_overrun) or allowed_overrun < 0.0:
        raise VideoMuxError(
            f"Combined audio overrun tolerance (max_audio_overrun_sec + allow_audio_tail_sec) "
            f"overflowed or is invalid: {allowed_overrun!r}."
        )
    if audio_overrun_sec > allowed_overrun and not allow_audio_truncation:
        raise VideoMuxError(
            f"Dialogue audio ({dlg_qc['duration_sec']:.2f}s) exceeds video duration "
            f"({src_video_qc['duration_sec']:.2f}s) by {audio_overrun_sec:.2f}s "
            f"(tolerance {allowed_overrun:.2f}s). Silent dialogue truncation is prohibited; "
            f"extend scene durations or pass allow_audio_tail_sec/allow_audio_truncation explicitly."
        )

    optional_audio_inputs: List[tuple[str, Path, float]] = []
    if bgm_path is not None:
        bp = Path(bgm_path)
        b_qc = inspect_audio_file(bp, check_volume=False)
        if not b_qc["valid"]:
            raise VideoMuxError(f"Invalid BGM audio {bp}: {'; '.join(b_qc['errors'])}")
        optional_audio_inputs.append(("bgm", bp, float(bgm_volume)))

    if sfx_path is not None:
        sp = Path(sfx_path)
        s_qc = inspect_audio_file(sp, check_volume=False)
        if not s_qc["valid"]:
            raise VideoMuxError(f"Invalid SFX audio {sp}: {'; '.join(s_qc['errors'])}")
        optional_audio_inputs.append(("sfx", sp, float(sfx_volume)))

    srt_p: Optional[Path] = None
    if subtitles_srt_path is not None:
        srt_p = Path(subtitles_srt_path)
        if not srt_p.exists() or srt_p.stat().st_size == 0:
            raise VideoMuxError(f"Missing or empty SRT subtitle file: {srt_p}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Optional v0.2.0 styled ASS caption burn-in (C01-C16) + muxing under one try/finally cleanup boundary (F-22)
    effective_video_path = v_path
    caption_render_info: Optional[Dict[str, Any]] = None
    temp_captioned_video: Optional[Path] = None
    temp_ass_path: Optional[Path] = None
    source_audio_preserved = False
    srt_input_idx: Optional[int] = None

    try:
        if caption_style_id is not None:
            if srt_p is None:
                raise VideoMuxError("caption_style_id requires subtitles_srt_path to be provided.")
            cues = caption_styles.parse_srt_to_cues(srt_p)
            if not cues:
                raise VideoMuxError(f"No valid subtitle cues found in {srt_p} for caption rendering.")
            ass_doc = caption_styles.generate_ass_document(
                cues,
                style_id=caption_style_id,
                width=src_video_qc["width"],
                height=src_video_qc["height"],
                genre=caption_genre,
                pacing=caption_pacing,
                tone=caption_tone,
            )
            temp_ass_path = out_path.parent / f".{out_path.stem}_{ass_doc['preset_id']}.ass"
            temp_ass_path.write_text(ass_doc["ass_content"], encoding="utf-8")
            temp_captioned_video = out_path.parent / f".{out_path.stem}_{ass_doc['preset_id']}_cap.mp4"
            caption_styles.render_ass_captions_onto_video(
                video_path=v_path,
                ass_path=temp_ass_path,
                output_video_path=temp_captioned_video,
            )
            effective_video_path = temp_captioned_video
            caption_render_info = {
                "preset_id": ass_doc["preset_id"],
                "preset_name": ass_doc["preset_name"],
                "selected_via": ass_doc["selected_via"],
                "cue_count": ass_doc["cue_count"],
                "burned_in": True,
            }

        cmd: List[str] = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(effective_video_path), "-i", str(d_path)]
        audio_labels: List[str] = ["[1:a]apad[dlg]"]
        mix_inputs: List[str] = ["[dlg]"]
        if preserve_source_audio and src_video_qc.get("has_audio"):
            audio_labels.append(f"[0:a]volume={float(source_audio_volume):.3f},apad[srca]")
            mix_inputs.append("[srca]")
            source_audio_preserved = True

        next_idx = 2
        for label, apath, vol in optional_audio_inputs:
            cmd.extend(["-i", str(apath)])
            audio_labels.append(f"[{next_idx}:a]volume={vol:.3f},apad[{label}]")
            mix_inputs.append(f"[{label}]")
            next_idx += 1

        if srt_p is not None and embed_subtitles:
            cmd.extend(["-i", str(srt_p)])
            srt_input_idx = next_idx

        dur = src_video_qc["duration_sec"]
        if len(mix_inputs) == 1:
            filter_complex = (
                f"[1:a]apad,atrim=0:{dur:.4f},asetpts=PTS-STARTPTS[aout]"
            )
        else:
            n_inputs = len(mix_inputs)
            filter_complex = (
                ";".join(audio_labels)
                + f";{''.join(mix_inputs)}amix=inputs={n_inputs}:duration=first:dropout_transition=2:normalize=0,"
                + f"alimiter=limit=0.95,atrim=0:{dur:.4f},asetpts=PTS-STARTPTS[aout]"
            )

        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
            ]
        )

        if srt_input_idx is not None:
            cmd.extend(
                [
                    "-map",
                    f"{srt_input_idx}:s:0",
                    "-c:s",
                    "mov_text",
                    "-metadata:s:s:0",
                    "language=eng",
                ]
            )

        cmd.append(str(out_path))
        try:
            res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=300.0)
        except FileNotFoundError as exc:
            out_path.unlink(missing_ok=True)
            raise VideoMuxError("Required binary 'ffmpeg' not found on PATH.") from exc
        except subprocess.TimeoutExpired as exc:
            out_path.unlink(missing_ok=True)
            raise VideoMuxError("FFmpeg muxing timed out after 300s.") from exc
        if res.returncode != 0:
            out_path.unlink(missing_ok=True)
            raise VideoMuxError(f"FFmpeg muxing failed: {res.stderr.strip()}")
    finally:
        if temp_captioned_video and temp_captioned_video.exists():
            temp_captioned_video.unlink(missing_ok=True)
        if temp_ass_path and temp_ass_path.exists():
            temp_ass_path.unlink(missing_ok=True)

    out_video_qc = inspect_video_file(out_path)
    if not out_video_qc["valid"]:
        raise VideoMuxError(
            f"Muxed output video failed FFprobe verification: {'; '.join(out_video_qc['errors'])}"
        )

    preserved_res = (
        out_video_qc["width"] == src_video_qc["width"]
        and out_video_qc["height"] == src_video_qc["height"]
    )
    preserved_fps = abs(out_video_qc["fps"] - src_video_qc["fps"]) <= 0.05
    if not preserved_res or not preserved_fps:
        raise VideoMuxError(
            f"Video stream geometry/FPS changed unexpectedly: "
            f"source={src_video_qc['width']}x{src_video_qc['height']}@{src_video_qc['fps']} "
            f"output={out_video_qc['width']}x{out_video_qc['height']}@{out_video_qc['fps']}"
        )

    if caption_render_info is not None and out_path.exists():
        h = hashlib.sha256()
        with open(out_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        caption_render_info["output_sha256"] = h.hexdigest()

    return {
        "output_video_path": str(out_path),
        "caption_style": caption_render_info,
        "source_video_qc": src_video_qc,
        "output_video_qc": out_video_qc,
        "preserved_resolution": preserved_res,
        "preserved_fps": preserved_fps,
        "subtitle_sidecar_path": str(srt_p) if srt_p else None,
        "subtitle_embedded": bool(srt_input_idx is not None and out_video_qc["has_subtitles"]),
        "bgm_included": bgm_path is not None,
        "sfx_included": sfx_path is not None,
        "preserve_source_audio_requested": bool(preserve_source_audio),
        "source_audio_preserved": source_audio_preserved,
        "dialogue_duration_sec": dlg_qc["duration_sec"],
        "video_duration_sec": src_video_qc["duration_sec"],
        "audio_overrun_sec": audio_overrun_sec,
        "render_origin_note": "FFmpeg post-production audio/subtitle muxing onto existing video; not Roblox Studio 3D rendering.",
    }


class VoiceGenerationPipeline:
    """Crash-safe, resumable multi-character dialogue audio generation pipeline."""

    def __init__(
        self,
        *,
        profile_manager: VoiceProfileManager,
        provider_registry: ProviderRegistry,
        max_retries: int = 2,
    ):
        self.profile_manager = profile_manager
        self.provider_registry = provider_registry
        self.assigner = CharacterVoiceAssigner(profile_manager)
        self.max_retries = max(0, int(max_retries))

    def run_script_pipeline(
        self,
        *,
        project_id: str,
        project_title: str,
        script_text: str,
        output_dir: Path,
        state_path: Path,
        preferred_provider: Optional[str] = None,
        character_descriptions: Optional[Dict[str, str]] = None,
        explicit_assignments: Optional[Dict[str, str]] = None,
        approved_fallbacks: Optional[Dict[str, str]] = None,
        gap_between_lines_sec: float = 0.35,
        project_duration_sec: Optional[float] = None,
        video_duration_sec: Optional[float] = None,
        source_video_path: Optional[Path] = None,
        output_video_path: Optional[Path] = None,
        bgm_path: Optional[Path] = None,
        sfx_path: Optional[Path] = None,
        embed_subtitles: bool = True,
        preserve_source_audio: bool = False,
        output_format: str = "mp3_44100_128",
        raw_ext: str = "mp3",
    ) -> Dict[str, Any]:
        out_dir = Path(output_dir)
        raw_dir = out_dir / "raw_audio"
        stems_dir = out_dir / "processed_stems"
        raw_dir.mkdir(parents=True, exist_ok=True)
        stems_dir.mkdir(parents=True, exist_ok=True)

        # Stage 1-4: Load state, parse script, assign characters persistently
        existing_state = load_project_voice_state(state_path)
        existing_jobs_by_id = {
            job["line_id"]: dict(job)
            for job in existing_state.get("dialogue_jobs", [])
        }

        segments: List[DialogueSegment] = parse_script_dialogue(script_text)
        char_map, assignment_blockers = self.assigner.assign_characters(
            segments,
            existing_state=existing_state,
            character_descriptions=character_descriptions,
            explicit_assignments=explicit_assignments,
            approved_fallbacks=approved_fallbacks,
        )

        state: Dict[str, Any] = {
            "schema_version": "1.1.0",
            "project_id": project_id,
            "project_title": project_title,
            "updated_at": utc_now_iso(),
            "character_voice_map": list(char_map.values()),
            "assignment_blockers": assignment_blockers,
            "dialogue_jobs": [],
        }

        cursor_sec = 0.0
        assembled_assets: List[Dict[str, Any]] = []
        assembled_jobs: List[Dict[str, Any]] = []
        jobs_out: List[Dict[str, Any]] = []

        for seg in segments:
            prev_job = existing_jobs_by_id.get(seg.line_id)
            mapping = char_map.get(seg.character_id)

            if (
                prev_job
                and prev_job.get("status") == "approved"
                and prev_job.get("processed_stem_path")
                and Path(prev_job["processed_stem_path"]).exists()
            ):
                job = dict(prev_job)
                job["skipped_existing_approved"] = True
                jobs_out.append(job)
                assembled_assets.append(
                    {
                        "line_id": job["line_id"],
                        "character_id": job["character_id"],
                        "display_name": job.get("display_name", job["character_id"]),
                        "voice_id": job["voice_id"],
                        "text": job["text"],
                        "start_sec": job["start_sec"],
                        "end_sec": job["end_sec"],
                    }
                )
                assembled_jobs.append(
                    {
                        "status": "approved",
                        "processed_path": job["processed_stem_path"],
                    }
                )
                cursor_sec = max(cursor_sec, float(job["end_sec"]) + gap_between_lines_sec)
                continue

            if mapping is None:
                job = {
                    "scene_id": seg.scene_id,
                    "line_id": seg.line_id,
                    "character_id": seg.character_id,
                    "display_name": seg.display_name,
                    "voice_id": None,
                    "provider": None,
                    "provider_voice_id": None,
                    "text": seg.text,
                    "delivery_cue": seg.delivery_cue,
                    "status": "blocked_voice_unavailable",
                    "attempts": 0,
                    "error": "No available or approved voice profile for character.",
                    "raw_audio_path": None,
                    "processed_stem_path": None,
                    "start_sec": None,
                    "end_sec": None,
                    "qc": None,
                    "skipped_existing_approved": False,
                }
                jobs_out.append(job)
                state["dialogue_jobs"] = jobs_out
                persist_project_voice_state(state_path, state)
                continue

            voice_id = mapping["voice_id"]
            provider_id = preferred_provider or mapping["provider"]
            provider_voice_id = mapping.get("provider_voice_id")
            raw_filename = build_predictable_filename(
                seg.scene_id, seg.line_id, seg.character_id, voice_id, ext=raw_ext
            )
            raw_path = resolve_safe_child_path(raw_dir, raw_filename)
            stem_path = resolve_safe_child_path(
                stems_dir,
                build_predictable_filename(seg.scene_id, seg.line_id, seg.character_id, voice_id, ext="wav"),
            )

            job = {
                "scene_id": seg.scene_id,
                "line_id": seg.line_id,
                "character_id": seg.character_id,
                "display_name": seg.display_name,
                "voice_id": voice_id,
                "provider": provider_id,
                "provider_voice_id": provider_voice_id,
                "text": seg.text,
                "delivery_cue": seg.delivery_cue,
                "status": "pending",
                "attempts": 0,
                "error": None,
                "raw_audio_path": str(raw_path),
                "processed_stem_path": None,
                "start_sec": None,
                "end_sec": None,
                "qc": None,
                "skipped_existing_approved": False,
            }

            try:
                adapter: VoiceProviderAdapter = self.provider_registry.select_provider(
                    preferred_provider=provider_id,
                    required_capability="text_to_speech",
                    require_configured=True,
                )
            except Exception as exc:
                job["status"] = "failed"
                job["error"] = str(exc)
                jobs_out.append(job)
                state["dialogue_jobs"] = jobs_out
                persist_project_voice_state(state_path, state)
                continue

            last_error: Optional[str] = None
            approved = False
            for attempt in range(1, self.max_retries + 2):
                job["attempts"] = attempt
                try:
                    adapter.synthesize_speech(
                        SynthesisRequest(
                            text=seg.text,
                            provider_voice_id=str(provider_voice_id or ""),
                            output_path=raw_path,
                            output_format=output_format,
                        )
                    )
                    raw_qc = inspect_audio_file(raw_path, check_volume=True)
                    if not raw_qc["valid"]:
                        last_error = "Audio validation failed: " + "; ".join(raw_qc["errors"])
                        continue

                    _normalize_stem_to_pcm_wav(raw_path, stem_path)
                    stem_qc = inspect_audio_file(stem_path, check_volume=True)
                    if not stem_qc["valid"]:
                        last_error = "Normalized stem validation failed: " + "; ".join(stem_qc["errors"])
                        continue

                    start_sec = round(cursor_sec, 3)
                    end_sec = round(start_sec + stem_qc["duration_sec"], 3)
                    job["status"] = "approved"
                    job["error"] = None
                    job["processed_stem_path"] = str(stem_path)
                    job["start_sec"] = start_sec
                    job["end_sec"] = end_sec
                    job["qc"] = stem_qc
                    cursor_sec = round(end_sec + gap_between_lines_sec, 3)
                    assembled_assets.append(
                        {
                            "line_id": job["line_id"],
                            "character_id": job["character_id"],
                            "display_name": job["display_name"],
                            "voice_id": job["voice_id"],
                            "text": job["text"],
                            "start_sec": start_sec,
                            "end_sec": end_sec,
                        }
                    )
                    assembled_jobs.append(
                        {
                            "status": "approved",
                            "processed_path": str(stem_path),
                        }
                    )
                    approved = True
                    break
                except VoiceProviderError as exc:
                    last_error = str(exc)
                    if not exc.retryable:
                        break
                except Exception as exc:
                    last_error = str(exc)
                    break

            if not approved:
                job["status"] = "failed"
                job["error"] = last_error or "Unknown audio generation failure."

            jobs_out.append(job)
            state["dialogue_jobs"] = jobs_out
            state["updated_at"] = utc_now_iso()
            persist_project_voice_state(state_path, state)

        master_wav_path = out_dir / "dialogue_timeline.wav"
        srt_path = out_dir / "subtitles.srt"
        assembly_stats: Optional[Dict[str, Any]] = None

        effective_video_dur = video_duration_sec
        if source_video_path is not None and effective_video_dur is None:
            v_qc = inspect_video_file(source_video_path)
            if v_qc["valid"]:
                effective_video_dur = v_qc["duration_sec"]

        if assembled_assets:
            total_dur = max(
                float(project_duration_sec or 0.0),
                float(effective_video_dur or 0.0),
                max(float(e["end_sec"]) for e in assembled_assets),
            )
            assembly_stats = voice_backend.SharedVoiceManager._assemble_timeline_wav(
                assembled_assets,
                assembled_jobs,
                master_wav_path,
                total_dur,
            )
            _write_srt_file(assembled_assets, srt_path)

        mux_report: Optional[Dict[str, Any]] = None
        if source_video_path is not None and assembled_assets:
            if output_video_path is not None:
                target_video = Path(output_video_path)
            else:
                safe_pid = sanitize_filename_token(project_id, "project_id")
                target_video = resolve_safe_child_path(out_dir, f"{safe_pid}_final_muxed.mp4")
            mux_report = mux_audio_and_subtitles_to_video(
                video_path=Path(source_video_path),
                dialogue_audio_path=master_wav_path,
                output_video_path=target_video,
                bgm_path=Path(bgm_path) if bgm_path else None,
                sfx_path=Path(sfx_path) if sfx_path else None,
                subtitles_srt_path=srt_path,
                embed_subtitles=embed_subtitles,
                preserve_source_audio=preserve_source_audio,
            )

        qc_report = run_project_audio_qc(
            dialogue_jobs=jobs_out,
            character_voice_map=char_map,
            master_audio_path=master_wav_path if assembled_assets else None,
            video_duration_sec=effective_video_dur,
        )

        state["updated_at"] = utc_now_iso()
        state["dialogue_jobs"] = jobs_out
        state["assembly_stats"] = assembly_stats
        state["mux_report"] = mux_report
        state["qc_report"] = qc_report
        state["artifacts"] = {
            "master_dialogue_wav": str(master_wav_path) if assembled_assets else None,
            "subtitles_srt": str(srt_path) if assembled_assets else None,
            "muxed_video_mp4": mux_report["output_video_path"] if mux_report else None,
            "state_json": str(state_path),
        }
        persist_project_voice_state(state_path, state)

        qc_report_path = out_dir / "audio_qc_report.json"
        fd, tmp_qc = tempfile.mkstemp(prefix=".audio_qc_report_", suffix=".tmp", dir=str(out_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(qc_report, indent=2) + "\n")
            os.replace(tmp_qc, qc_report_path)
        except Exception:
            if os.path.exists(tmp_qc):
                os.unlink(tmp_qc)
            raise
        return state
