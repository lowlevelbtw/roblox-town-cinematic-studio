#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Multi-Scene Cinematic Assembler & Dialogue-Aware BGM Ducking (v0.2.0).

Supports:
  - Mixed scene inputs: video clips, Roblox gameplay captures, and still images.
  - Normalization to target width, height, FPS, yuv420p H.264.
  - Deterministic Ken Burns motion for still-image scenes.
  - Real FFmpeg `xfade` transitions (`fade`, `fadeblack`, `slideleft`, `wipeleft`, `none`).
  - Dialogue-aware BGM ducking via FFmpeg `sidechaincompress` + `alimiter=limit=0.95`.
  - Per-scene `ProductionStateManager` checkpoints (F-12 FFprobe-verified recovery).
"""

from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from production_state import ProductionStateManager  # noqa: E402
from voice_intelligence.audio_qc import inspect_audio_file, inspect_video_file  # noqa: E402
from voice_intelligence.pipeline import resolve_safe_child_path, sanitize_filename_token  # noqa: E402

SUPPORTED_TRANSITIONS = ("fade", "fadeblack", "slideleft", "wipeleft", "none")
SUPPORTED_MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "static")


class VideoAssemblyError(RuntimeError):
    """Raised when scene normalization, transition assembly, or audio ducking fails."""


@dataclass
class SceneSpec:
    scene_id: str
    source_type: str  # "video" | "image"
    source_path: Path
    duration_sec: float = 3.0
    motion: str = "zoom_in"
    transition: str = "fade"
    transition_duration_sec: float = 0.4

    def validate(self) -> None:
        sanitize_filename_token(self.scene_id, "scene_id")
        if self.source_type not in ("video", "image"):
            raise VideoAssemblyError(
                f"Scene {self.scene_id}: unsupported source_type {self.source_type!r} (expected 'video' or 'image')."
            )
        if not Path(self.source_path).exists():
            raise VideoAssemblyError(f"Scene {self.scene_id}: source file not found: {self.source_path}")
        if not math.isfinite(self.duration_sec) or self.duration_sec <= 0.1:
            raise VideoAssemblyError(f"Scene {self.scene_id}: invalid duration_sec {self.duration_sec!r}")
        if self.motion not in SUPPORTED_MOTIONS:
            raise VideoAssemblyError(f"Scene {self.scene_id}: unsupported motion {self.motion!r}")
        if self.transition not in SUPPORTED_TRANSITIONS:
            raise VideoAssemblyError(f"Scene {self.scene_id}: unsupported transition {self.transition!r}")
        if self.transition != "none" and (self.transition_duration_sec <= 0 or self.transition_duration_sec >= self.duration_sec * 0.5):
            raise VideoAssemblyError(
                f"Scene {self.scene_id}: transition_duration_sec ({self.transition_duration_sec}) "
                f"must be > 0 and < half of duration_sec ({self.duration_sec})."
            )


def _run_ffmpeg(cmd: List[str], out_path: Path, timeout_sec: float, context: str) -> None:
    try:
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=timeout_sec)
    except FileNotFoundError as exc:
        out_path.unlink(missing_ok=True)
        raise VideoAssemblyError(f"Required binary 'ffmpeg' not found on PATH during {context}.") from exc
    except subprocess.TimeoutExpired as exc:
        out_path.unlink(missing_ok=True)
        raise VideoAssemblyError(f"FFmpeg timed out after {timeout_sec}s during {context}.") from exc
    if res.returncode != 0 or not out_path.exists():
        out_path.unlink(missing_ok=True)
        raise VideoAssemblyError(f"FFmpeg failed during {context}: {res.stderr[-300:].strip()}")


def normalize_scene_clip(
    spec: SceneSpec,
    output_mp4_path: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    timeout_sec: float = 180.0,
) -> Dict[str, Any]:
    """Normalize a single still-image or video/capture scene into target resolution & FPS."""
    spec.validate()
    if int(width) <= 0 or int(height) <= 0 or int(fps) <= 0:
        raise VideoAssemblyError(f"Invalid target video parameters: {width}x{height}@{fps}fps.")
    out_p = Path(output_mp4_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    src_p = Path(spec.source_path)

    if spec.source_type == "image":
        n_frames = max(2, int(round(spec.duration_sec * fps)))
        if spec.motion == "zoom_in":
            zp = f"zoompan=z='min(zoom+0.0008,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n_frames}:s={width}x{height}:fps={fps}"
        elif spec.motion == "zoom_out":
            zp = f"zoompan=z='max(1.12-0.0008*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n_frames}:s={width}x{height}:fps={fps}"
        elif spec.motion == "pan_left":
            zp = f"zoompan=z='1.08':x='max(0,(iw-iw/zoom)*(1-on/{n_frames}))':y='ih/2-(ih/zoom/2)':d={n_frames}:s={width}x{height}:fps={fps}"
        elif spec.motion == "pan_right":
            zp = f"zoompan=z='1.08':x='min(iw-iw/zoom,(iw-iw/zoom)*(on/{n_frames}))':y='ih/2-(ih/zoom/2)':d={n_frames}:s={width}x{height}:fps={fps}"
        else:
            zp = f"fps={fps}"
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},{zp},format=yuv420p"
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-loop", "1", "-i", str(src_p),
            "-vf", vf,
            "-t", f"{spec.duration_sec:.4f}",
            "-r", str(fps),
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(out_p),
        ]
    else:
        v_qc = inspect_video_file(src_p)
        if not v_qc["valid"]:
            raise VideoAssemblyError(f"Scene {spec.scene_id}: invalid video input {src_p}: {'; '.join(v_qc['errors'])}")
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},format=yuv420p,setpts=PTS-STARTPTS"
        )
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-i", str(src_p),
            "-vf", vf,
            "-t", f"{spec.duration_sec:.4f}",
            "-r", str(fps),
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(out_p),
        ]

    _run_ffmpeg(cmd, out_p, timeout_sec, f"scene normalization ({spec.scene_id})")
    out_qc = inspect_video_file(out_p)
    if not out_qc["valid"]:
        out_p.unlink(missing_ok=True)
        raise VideoAssemblyError(f"Normalized clip for {spec.scene_id} failed FFprobe: {'; '.join(out_qc['errors'])}")

    return {
        "scene_id": spec.scene_id,
        "clip_path": str(out_p),
        "duration_sec": out_qc["duration_sec"],
        "width": out_qc["width"],
        "height": out_qc["height"],
        "fps": out_qc["fps"],
    }


def assemble_scenes_with_transitions(
    scenes: Sequence[SceneSpec],
    *,
    work_dir: Path,
    output_video_path: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    state_manager: Optional[ProductionStateManager] = None,
    timeout_sec: float = 300.0,
) -> Dict[str, Any]:
    """Normalize scenes with per-scene recovery and join them via FFmpeg `xfade` transitions."""
    if not scenes:
        raise VideoAssemblyError("At least one SceneSpec is required for assembly.")

    work_p = Path(work_dir)
    clips_dir = work_p / "scene_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    out_p = Path(output_video_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    pending_ids: Optional[set[str]] = None
    if state_manager is not None and state_manager.state.get("scenes"):
        pending_ids = set(state_manager.get_pending_or_failed_scenes())

    normalized_clips: List[Dict[str, Any]] = []
    skipped_scenes: List[str] = []
    rendered_scenes: List[str] = []

    for spec in scenes:
        safe_sid = sanitize_filename_token(spec.scene_id, "scene_id")
        clip_path = resolve_safe_child_path(clips_dir, f"{safe_sid}_norm.mp4")

        # Skip only if state_manager verified via FFprobe (F-12) that the scene is valid & completed
        if pending_ids is not None and spec.scene_id not in pending_ids:
            cached_ref = Path(state_manager.state["scenes"][spec.scene_id]["asset_path"])
            cached_qc = inspect_video_file(cached_ref)
            if cached_qc["valid"]:
                normalized_clips.append(
                    {
                        "scene_id": spec.scene_id,
                        "clip_path": str(cached_ref),
                        "duration_sec": cached_qc["duration_sec"],
                        "transition": spec.transition,
                        "transition_duration_sec": spec.transition_duration_sec,
                    }
                )
                skipped_scenes.append(spec.scene_id)
                continue

        try:
            info = normalize_scene_clip(
                spec,
                clip_path,
                width=width,
                height=height,
                fps=fps,
            )
            if state_manager is not None and spec.scene_id in state_manager.state.get("scenes", {}):
                state_manager.mark_scene_completed(spec.scene_id, clip_path, provider="ffmpeg_video_assembler")
            normalized_clips.append(
                {
                    "scene_id": spec.scene_id,
                    "clip_path": info["clip_path"],
                    "duration_sec": info["duration_sec"],
                    "transition": spec.transition,
                    "transition_duration_sec": spec.transition_duration_sec,
                }
            )
            rendered_scenes.append(spec.scene_id)
        except Exception as exc:
            if state_manager is not None and spec.scene_id in state_manager.state.get("scenes", {}):
                state_manager.mark_scene_failed(spec.scene_id, str(exc))
            raise

    # Calculate scene midpoint timestamps for visual QC contact sheet
    scene_midpoints: List[float] = []
    cursor = 0.0
    for idx, clip in enumerate(normalized_clips):
        dur = float(clip["duration_sec"])
        scene_midpoints.append(round(cursor + dur * 0.5, 3))
        overlap = 0.0
        if idx < len(normalized_clips) - 1 and clip["transition"] != "none":
            overlap = float(clip["transition_duration_sec"])
        cursor += max(0.1, dur - overlap)

    # Single-scene fast path
    if len(normalized_clips) == 1:
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-v", "error",
            "-i", normalized_clips[0]["clip_path"],
            "-c:v", "copy",
            str(out_p),
        ]
        _run_ffmpeg(cmd, out_p, timeout_sec, "single-scene assembly")
    else:
        use_xfade = any(c["transition"] != "none" for c in normalized_clips[:-1])
        if not use_xfade:
            concat_file = work_p / "scenes_concat.txt"
            def _esc_concat(path_str: str) -> str:
                return path_str.replace("'", "'\\''")

            concat_file.write_text(
                "\n".join(f"file '{_esc_concat(c['clip_path'])}'" for c in normalized_clips) + "\n",
                encoding="utf-8",
            )
            cmd = [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c:v", "copy",
                str(out_p),
            ]
            _run_ffmpeg(cmd, out_p, timeout_sec, "multi-scene concat")
        else:
            cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
            for c in normalized_clips:
                cmd.extend(["-i", c["clip_path"]])

            filter_parts: List[str] = []
            for idx in range(len(normalized_clips)):
                filter_parts.append(f"[{idx}:v]settb=AVTB,fps={fps},format=yuv420p[v{idx}]")

            prev_label = "v0"
            cumulative_dur = float(normalized_clips[0]["duration_sec"])
            for idx in range(1, len(normalized_clips)):
                prev_clip = normalized_clips[idx - 1]
                tr = prev_clip["transition"] if prev_clip["transition"] != "none" else "fade"
                td = float(prev_clip["transition_duration_sec"]) if prev_clip["transition"] != "none" else 0.05
                offset = max(0.0, round(cumulative_dur - td, 4))
                out_label = f"xf{idx}"
                filter_parts.append(
                    f"[{prev_label}][v{idx}]xfade=transition={tr}:duration={td:.3f}:offset={offset:.4f}[{out_label}]"
                )
                prev_label = out_label
                cumulative_dur = offset + float(normalized_clips[idx]["duration_sec"])

            cmd.extend(
                [
                    "-filter_complex",
                    ";".join(filter_parts),
                    "-map",
                    f"[{prev_label}]",
                    "-r",
                    str(fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    str(out_p),
                ]
            )
            _run_ffmpeg(cmd, out_p, timeout_sec, "multi-scene xfade transition assembly")

    final_qc = inspect_video_file(out_p)
    if not final_qc["valid"]:
        raise VideoAssemblyError(f"Assembled video failed FFprobe: {'; '.join(final_qc['errors'])}")

    return {
        "output_video_path": str(out_p),
        "video_qc": final_qc,
        "scene_count": len(normalized_clips),
        "rendered_scenes": rendered_scenes,
        "skipped_cached_scenes": skipped_scenes,
        "scene_midpoints_sec": scene_midpoints,
        "scene_labels": [c["scene_id"] for c in normalized_clips],
    }


def mix_dialogue_and_ducked_bgm(
    *,
    dialogue_audio_path: Path,
    bgm_audio_path: Path,
    output_wav_path: Path,
    sfx_audio_path: Optional[Path] = None,
    bgm_base_volume: float = 0.30,
    sfx_volume: float = 0.65,
    duck_threshold: float = 0.03,
    duck_ratio: float = 8.0,
    duck_attack_ms: float = 20.0,
    duck_release_ms: float = 250.0,
    target_duration_sec: Optional[float] = None,
    timeout_sec: float = 180.0,
) -> Dict[str, Any]:
    """Mix dialogue with BGM that automatically ducks when dialogue speaks (`sidechaincompress`)."""
    for vname, vval in (("bgm_base_volume", bgm_base_volume), ("sfx_volume", sfx_volume)):
        vf = float(vval)
        if not math.isfinite(vf) or vf < 0.0 or vf > 5.0:
            raise VideoAssemblyError(f"{vname} must be finite and between 0.0 and 5.0, got {vval!r}.")

    dlg_p = Path(dialogue_audio_path)
    bgm_p = Path(bgm_audio_path)
    out_p = Path(output_wav_path)

    dlg_qc = inspect_audio_file(dlg_p, check_volume=True)
    if not dlg_qc["valid"]:
        raise VideoAssemblyError(f"Invalid dialogue audio {dlg_p}: {'; '.join(dlg_qc['errors'])}")
    bgm_qc = inspect_audio_file(bgm_p, check_volume=False)
    if not bgm_qc["valid"]:
        raise VideoAssemblyError(f"Invalid BGM audio {bgm_p}: {'; '.join(bgm_qc['errors'])}")

    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(dlg_p), "-i", str(bgm_p)]
    has_sfx = False
    if sfx_audio_path is not None:
        sfx_p = Path(sfx_audio_path)
        sfx_qc = inspect_audio_file(sfx_p, check_volume=False)
        if not sfx_qc["valid"]:
            raise VideoAssemblyError(f"Invalid SFX audio {sfx_p}: {'; '.join(sfx_qc['errors'])}")
        cmd.extend(["-i", str(sfx_p)])
        has_sfx = True

    out_p.parent.mkdir(parents=True, exist_ok=True)
    # Split dialogue into main + sidechain key; sidechaincompress ducks BGM whenever dialogue is active
    fc_parts = [
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[dlg_main][dlg_sc]",
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={float(bgm_base_volume):.3f}[bgm_scaled]",
        (
            f"[bgm_scaled][dlg_sc]sidechaincompress=threshold={float(duck_threshold):.4f}:"
            f"ratio={float(duck_ratio):.2f}:attack={float(duck_attack_ms):.1f}:release={float(duck_release_ms):.1f}[bgm_ducked]"
        ),
    ]
    trim_dur = max(float(dlg_qc["duration_sec"]), float(target_duration_sec)) if target_duration_sec is not None else None
    trim_filter = f",atrim=0:{trim_dur:.4f},asetpts=PTS-STARTPTS" if trim_dur is not None else ""
    if has_sfx:
        fc_parts.append(f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={float(sfx_volume):.3f}[sfx_scaled]")
        fc_parts.append(f"[dlg_main][bgm_ducked][sfx_scaled]amix=inputs=3:duration=longest:normalize=0,alimiter=limit=0.95{trim_filter}[aout]")
    else:
        fc_parts.append(f"[dlg_main][bgm_ducked]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95{trim_filter}[aout]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(fc_parts),
            "-map",
            "[aout]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(out_p),
        ]
    )
    _run_ffmpeg(cmd, out_p, timeout_sec, "dialogue-aware BGM ducking")
    mix_qc = inspect_audio_file(out_p, check_volume=True)
    if not mix_qc["valid"]:
        out_p.unlink(missing_ok=True)
        raise VideoAssemblyError(f"Ducked audio mix failed QC: {'; '.join(mix_qc['errors'])}")

    return {
        "output_wav_path": str(out_p),
        "audio_qc": mix_qc,
        "bgm_ducking_applied": True,
        "sfx_included": has_sfx,
    }
