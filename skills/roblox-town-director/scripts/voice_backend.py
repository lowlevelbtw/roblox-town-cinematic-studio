#!/usr/bin/env python3
"""
Recorded Voice Backend & Shared Voice Manager for Roblox Town Director.

Implements an interchangeable backend architecture:
  - RecordedVoiceBackend: Imports, validates, trims, normalizes, and additively
    mixes user-provided WAV/MP3/FFmpeg-supported recordings mapped to V01-V06.
  - ExternalTTSBackend: Placeholder adapter contract (TTS is NOT implemented
    in this module; reports BLOCKED honestly without fabricating audio).

Requires: Python 3.9+ and FFmpeg/FFprobe installed on PATH.
No external Python packages or API keys required.
"""

from __future__ import annotations

import argparse
import array
import json
import shutil
import subprocess
import sys
import wave
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


TARGET_SAMPLE_RATE = 44100
TARGET_CHANNELS = 2
ALLOWED_VOICE_IDS = {"V01", "V02", "V03", "V04", "V05", "V06"}
MAX_SAFE_PEAK = int(32767 * 0.891)  # ~ -1.0 dBFS headroom


class VoiceBackend(ABC):
    """Interchangeable voice backend interface."""

    adapter_id: str
    adapter_type: str

    @abstractmethod
    def discover_capabilities(self) -> Dict[str, Any]:
        """Return verified runtime capabilities for this backend."""

    @abstractmethod
    def process_line(
        self,
        line_spec: Dict[str, Any],
        output_dir: Path,
        base_dir: Path,
    ) -> Dict[str, Any]:
        """Process a single dialogue line and return a structured job result."""


class ExternalTTSBackend(VoiceBackend):
    """Contract stub for external TTS providers (not implemented here)."""

    adapter_id = "external_tts_unconfigured"
    adapter_type = "hosted_api"

    def discover_capabilities(self) -> Dict[str, Any]:
        return {
            "text_to_speech": False,
            "voice_reference_input": False,
            "authorized_voice_cloning": False,
            "custom_voice_creation": False,
            "emotion_delivery_controls": False,
            "pronunciation_dictionaries": False,
            "speech_speed_controls": False,
            "audio_file_export": False,
            "batch_generation": False,
            "persistent_voice_ids": False,
            "notes": "External TTS is not implemented in this local backend.",
        }

    def process_line(
        self,
        line_spec: Dict[str, Any],
        output_dir: Path,
        base_dir: Path,
    ) -> Dict[str, Any]:
        return {
            "line_id": line_spec.get("line_id"),
            "character_id": line_spec.get("character_id"),
            "voice_id": line_spec.get("voice_id"),
            "status": "blocked",
            "reason": "External TTS backend is not implemented or configured.",
            "source_path": None,
            "processed_path": None,
        }


class RecordedVoiceBackend(VoiceBackend):
    """Executable recorded-audio backend powered by FFmpeg and FFprobe."""

    adapter_id = "recorded_voice_ffmpeg"
    adapter_type = "local_recorded_audio"

    def __init__(self, target_sr: int = TARGET_SAMPLE_RATE, target_ch: int = TARGET_CHANNELS):
        self.target_sr = target_sr
        self.target_ch = target_ch
        self.ffmpeg_bin = shutil.which("ffmpeg")
        self.ffprobe_bin = shutil.which("ffprobe")

    def discover_capabilities(self) -> Dict[str, Any]:
        tools_ok = bool(self.ffmpeg_bin and self.ffprobe_bin)
        return {
            "text_to_speech": False,
            "voice_reference_input": False,
            "authorized_voice_cloning": False,
            "custom_voice_creation": False,
            "emotion_delivery_controls": False,
            "pronunciation_dictionaries": False,
            "speech_speed_controls": False,
            "audio_file_export": tools_ok,
            "batch_generation": tools_ok,
            "persistent_voice_ids": True,
            "recorded_audio_import": tools_ok,
            "additive_dialogue_mixing": True,
            "ffmpeg_path": self.ffmpeg_bin,
            "ffprobe_path": self.ffprobe_bin,
        }

    def probe_audio(self, audio_path: Path) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """Validate audio file via ffprobe and return (ok, metadata, error_reason)."""
        if not self.ffprobe_bin:
            return False, {}, "ffprobe not found on PATH."
        if not audio_path.exists():
            return False, {}, f"Missing audio file: {audio_path}"
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            return False, {}, f"Empty or non-file audio path: {audio_path}"

        cmd = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,duration:format=duration,format_name,size",
            "-of",
            "json",
            str(audio_path),
        ]
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60.0)
        except FileNotFoundError:
            return False, {}, "ffprobe executable not found on PATH."
        except subprocess.TimeoutExpired:
            return False, {}, "ffprobe timed out after 60.0s." 
        if proc.returncode != 0:
            err = proc.stderr.strip() or "ffprobe failed to parse audio file."
            return False, {}, f"Invalid audio file ({err})"

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return False, {}, "ffprobe returned unreadable JSON metadata."

        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        if not streams:
            return False, {}, "No valid audio stream found in file."

        stream = streams[0]
        raw_dur = stream.get("duration") or fmt.get("duration")
        try:
            duration = float(raw_dur)
        except (TypeError, ValueError):
            duration = 0.0

        if duration <= 0.0:
            return False, {}, "Audio duration is zero or unreadable."

        try:
            sample_rate = int(stream.get("sample_rate") or 0)
        except (TypeError, ValueError):
            sample_rate = 0
        try:
            channels = int(stream.get("channels") or 0)
        except (TypeError, ValueError):
            channels = 0

        if sample_rate <= 0 or channels <= 0:
            return False, {}, f"Invalid sample_rate ({sample_rate}) or channels ({channels})."

        meta = {
            "codec": stream.get("codec_name"),
            "format_name": fmt.get("format_name"),
            "duration_sec": round(duration, 4),
            "sample_rate": sample_rate,
            "channels": channels,
            "size_bytes": int(fmt.get("size") or audio_path.stat().st_size),
        }
        return True, meta, None

    def process_line(
        self,
        line_spec: Dict[str, Any],
        output_dir: Path,
        base_dir: Path,
    ) -> Dict[str, Any]:
        line_id = line_spec.get("line_id", "UNKNOWN_LINE")
        character_id = line_spec.get("character_id", "unknown_character")
        voice_id = line_spec.get("voice_id", "UNASSIGNED")

        if not self.ffmpeg_bin or not self.ffprobe_bin:
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "blocked",
                "reason": "ffmpeg and/or ffprobe not available on PATH.",
                "source_path": None,
                "processed_path": None,
            }

        if voice_id not in ALLOWED_VOICE_IDS:
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": f"Invalid voice_id '{voice_id}'. Must be one of {sorted(ALLOWED_VOICE_IDS)}.",
                "source_path": None,
                "processed_path": None,
            }

        raw_ref = line_spec.get("recording_path") or line_spec.get("audio_asset_ref")
        if not raw_ref:
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "missing",
                "reason": "No recording_path supplied for this dialogue line.",
                "source_path": None,
                "processed_path": None,
            }

        src_path = Path(raw_ref)
        if not src_path.is_absolute():
            base_resolved = base_dir.resolve()
            src_path = (base_resolved / src_path).resolve()
            if not src_path.is_relative_to(base_resolved):
                return {
                    "line_id": line_id,
                    "character_id": character_id,
                    "voice_id": voice_id,
                    "status": "failed",
                    "reason": f"Unsafe relative recording_path escapes project base_dir: {raw_ref!r}",
                    "source_path": str(raw_ref),
                    "processed_path": None,
                }

        if not src_path.exists():
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "missing",
                "reason": f"Recording file does not exist: {raw_ref}",
                "source_path": str(raw_ref),
                "processed_path": None,
            }

        ok, src_meta, err = self.probe_audio(src_path)
        if not ok:
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": err,
                "source_path": str(raw_ref),
                "processed_path": None,
            }

        output_dir.mkdir(parents=True, exist_ok=True)
        for _fname, _fval in (("line_id", line_id), ("character_id", character_id), ("voice_id", voice_id)):
            _raw = str(_fval or "").strip()
            if not _raw or ".." in _raw or "/" in _raw or "\\" in _raw or "\x00" in _raw:
                return {
                    "line_id": line_id,
                    "character_id": character_id,
                    "voice_id": voice_id,
                    "status": "failed",
                    "reason": f"Unsafe path characters in {_fname}: {_raw!r}",
                    "source_path": str(src_path),
                    "processed_path": None,
                }
        safe_line = "".join(c if (c.isalnum() or c in "_-") else "_" for c in str(line_id).strip()).strip("._-")
        safe_char = "".join(c if (c.isalnum() or c in "_-") else "_" for c in str(character_id).strip()).strip("._-")
        safe_voice = "".join(c if (c.isalnum() or c in "_-") else "_" for c in str(voice_id).strip()).strip("._-")
        out_name = f"{safe_line}_{safe_char}_{safe_voice}.wav"
        out_path = (output_dir.resolve() / out_name).resolve()
        if out_path.parent != output_dir.resolve():
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": f"Resolved stem output path escapes output_dir: {out_name!r}",
                "source_path": str(src_path),
                "processed_path": None,
            }

        filters: List[str] = []
        if line_spec.get("trim_silence", True):
            filters.append(
                "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-45dB"
                ":stop_periods=-1:stop_silence=0.10:stop_threshold=-45dB"
            )
        if line_spec.get("normalize", True):
            filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

        cmd: List[str] = [self.ffmpeg_bin, "-nostdin", "-y"]
        trim_start = line_spec.get("trim_start_sec")
        trim_end = line_spec.get("trim_end_sec")
        if trim_start is not None:
            cmd.extend(["-ss", str(float(trim_start))])
        if trim_end is not None:
            cmd.extend(["-to", str(float(trim_end))])

        cmd.extend(["-i", str(src_path)])
        if filters:
            cmd.extend(["-af", ",".join(filters)])
        cmd.extend([
            "-ar",
            str(self.target_sr),
            "-ac",
            str(self.target_ch),
            "-c:a",
            "pcm_s16le",
            str(out_path),
        ])

        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120.0)
        except FileNotFoundError:
            out_path.unlink(missing_ok=True)
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": "ffmpeg executable not found on PATH.",
                "source_path": str(src_path),
                "processed_path": None,
            }
        except subprocess.TimeoutExpired:
            out_path.unlink(missing_ok=True)
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": "ffmpeg processing timed out after 120.0s.",
                "source_path": str(src_path),
                "processed_path": None,
            }
        if proc.returncode != 0 or not out_path.exists():
            out_path.unlink(missing_ok=True)
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": f"FFmpeg processing error: {proc.stderr.strip()[-300:]}",
                "source_path": str(raw_ref),
                "processed_path": None,
            }

        ok_out, out_meta, err_out = self.probe_audio(out_path)
        if not ok_out:
            return {
                "line_id": line_id,
                "character_id": character_id,
                "voice_id": voice_id,
                "status": "failed",
                "reason": f"Processed clip failed validation: {err_out}",
                "source_path": str(raw_ref),
                "processed_path": None,
            }

        return {
            "line_id": line_id,
            "character_id": character_id,
            "voice_id": voice_id,
            "status": "approved",
            "reason": "Imported, validated, normalized, and converted cleanly.",
            "source_path": str(raw_ref),
            "source_meta": src_meta,
            "processed_path": str(out_path),
            "processed_meta": out_meta,
        }


class SharedVoiceManager:
    """Provider-independent voice manager coordinating manifest, backend, timeline, and reports."""

    def __init__(self, registry_path: Path, backend: VoiceBackend):
        self.registry_path = registry_path
        self.backend = backend
        self.registry = self._load_json(registry_path)
        self.valid_voice_ids = {v["voice_id"] for v in self.registry.get("voices", [])}

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _save_json(path: Path, data: Dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")

    @staticmethod
    def _fmt_srt_time(seconds: float) -> str:
        ms_total = max(0, int(round(seconds * 1000)))
        hh = ms_total // 3600000
        mm = (ms_total % 3600000) // 60000
        ss = (ms_total % 60000) // 1000
        ms = ms_total % 1000
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    @staticmethod
    def validate_timeline_and_subtitles(
        assets: List[Dict[str, Any]],
        jobs: List[Dict[str, Any]],
        total_duration_sec: Optional[float],
    ) -> Dict[str, Any]:
        """Validate timestamps, out-of-range events, overlaps, and subtitle sync without silent truncation."""
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        overlaps: List[Dict[str, Any]] = []

        intervals: List[Tuple[str, float, float]] = []
        required_end_sec = 0.0

        for asset, job in zip(assets, jobs):
            lid = str(asset.get("line_id", "UNKNOWN"))
            start_raw = asset.get("start_sec")
            end_raw = asset.get("end_sec")

            try:
                start_s = float(start_raw)
            except (TypeError, ValueError):
                errors.append({"line_id": lid, "type": "invalid_start_sec", "detail": f"Unreadable start_sec: {start_raw}"})
                continue

            try:
                end_s = float(end_raw)
            except (TypeError, ValueError):
                errors.append({"line_id": lid, "type": "invalid_end_sec", "detail": f"Unreadable end_sec: {end_raw}"})
                continue

            if start_s < 0.0:
                errors.append({"line_id": lid, "type": "negative_start_sec", "detail": f"start_sec ({start_s}) < 0"})
            if end_s <= start_s:
                errors.append({"line_id": lid, "type": "contradictory_subtitle_timing", "detail": f"end_sec ({end_s}) <= start_sec ({start_s})"})

            actual_end = end_s
            if job.get("status") == "approved" and job.get("processed_meta"):
                clip_dur = float(job["processed_meta"]["duration_sec"])
                clip_end = round(start_s + clip_dur, 4)
                actual_end = max(actual_end, clip_end)
                slot_dur = end_s - start_s
                if slot_dur > 0 and clip_dur > slot_dur + 0.15:
                    warnings.append({
                        "line_id": lid,
                        "type": "subtitle_window_shorter_than_audio",
                        "detail": f"Clip duration ({clip_dur:.2f}s) exceeds subtitle window ({slot_dur:.2f}s).",
                    })

            if total_duration_sec is not None and actual_end > total_duration_sec + 1e-6:
                errors.append({
                    "line_id": lid,
                    "type": "out_of_range_timeline_event",
                    "detail": f"Dialogue extends to {actual_end:.3f}s, beyond project duration {total_duration_sec:.3f}s (will NOT silently truncate).",
                })

            required_end_sec = max(required_end_sec, actual_end)
            if start_s >= 0.0 and end_s > start_s:
                intervals.append((lid, start_s, actual_end))

        # Detect overlapping dialogue intervals
        for i in range(len(intervals)):
            id_a, a0, a1 = intervals[i]
            for j in range(i + 1, len(intervals)):
                id_b, b0, b1 = intervals[j]
                ov_start = max(a0, b0)
                ov_end = min(a1, b1)
                if ov_end > ov_start + 1e-4:
                    overlaps.append({
                        "line_a": id_a,
                        "line_b": id_b,
                        "overlap_start_sec": round(ov_start, 3),
                        "overlap_end_sec": round(ov_end, 3),
                    })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "overlaps": overlaps,
            "required_end_sec": round(required_end_sec, 4),
        }

    def run_project(
        self,
        manifest_path: Path,
        output_dir: Path,
        total_duration_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        base_dir = manifest_path.parent
        manifest = self._load_json(manifest_path)
        stems_dir = output_dir / "processed_stems"
        stems_dir.mkdir(parents=True, exist_ok=True)

        char_map: Dict[str, Dict[str, Any]] = {}
        invalid_char_entries: List[str] = []
        for entry in manifest.get("character_voice_map", []):
            cid = entry["character_id"]
            vid = entry["voice_id"]
            if vid not in self.valid_voice_ids:
                invalid_char_entries.append(f"Character '{cid}' maps to unknown voice_id '{vid}'.")
            char_map[cid] = entry

        caps = self.backend.discover_capabilities()
        manifest["active_provider"] = {
            "adapter_id": self.backend.adapter_id,
            "provider_name": "Recorded Voice Backend (FFmpeg)"
            if isinstance(self.backend, RecordedVoiceBackend)
            else "External TTS (Unconfigured)",
            "verified_capabilities": caps,
        }

        jobs: List[Dict[str, Any]] = []
        assets = sorted(
            manifest.get("dialogue_assets", []),
            key=lambda x: (float(x.get("start_sec") or 0.0), str(x.get("line_id", ""))),
        )

        for asset in assets:
            cid = asset.get("character_id")
            vid = asset.get("voice_id")
            if vid not in self.valid_voice_ids:
                res = {
                    "line_id": asset.get("line_id"),
                    "character_id": cid,
                    "voice_id": vid,
                    "status": "failed",
                    "reason": f"Invalid voice_id '{vid}' not found in voice-registry.json.",
                    "source_path": asset.get("recording_path"),
                    "processed_path": None,
                }
            elif cid not in char_map:
                res = {
                    "line_id": asset.get("line_id"),
                    "character_id": cid,
                    "voice_id": vid,
                    "status": "failed",
                    "reason": f"Character '{cid}' is missing from character_voice_map.",
                    "source_path": asset.get("recording_path"),
                    "processed_path": None,
                }
            elif vid != char_map[cid]["voice_id"]:
                res = {
                    "line_id": asset.get("line_id"),
                    "character_id": cid,
                    "voice_id": vid,
                    "status": "failed",
                    "reason": (
                        f"Voice continuity mismatch: line uses '{vid}' "
                        f"but character '{cid}' is locked to '{char_map[cid]['voice_id']}'."
                    ),
                    "source_path": asset.get("recording_path"),
                    "processed_path": None,
                }
            else:
                res = self.backend.process_line(asset, stems_dir, base_dir)

            asset["status"] = res["status"]
            asset["audio_asset_ref"] = res["processed_path"]
            asset["locked_from_regeneration"] = res["status"] == "approved"
            jobs.append(res)

        validation = self.validate_timeline_and_subtitles(assets, jobs, total_duration_sec)
        for msg in invalid_char_entries:
            validation["errors"].append({"line_id": "CHARACTER_MAP", "type": "invalid_voice_assignment", "detail": msg})
            validation["valid"] = False

        # Never silently truncate: if audio extends past total_duration_sec, expand buffer to required_end_sec
        effective_duration = max(
            1.0,
            float(total_duration_sec) if total_duration_sec is not None else 0.0,
            float(validation["required_end_sec"]),
        )

        timeline_wav = output_dir / "dialogue_timeline.wav"
        mix_stats = self._assemble_timeline_wav(assets, jobs, timeline_wav, effective_duration)

        timeline_meta: Dict[str, Any] = {}
        if isinstance(self.backend, RecordedVoiceBackend):
            ok_tl, meta_tl, err_tl = self.backend.probe_audio(timeline_wav)
            timeline_meta = meta_tl if ok_tl else {"error": err_tl}

        srt_path = output_dir / "subtitles.srt"
        self._write_srt(assets, char_map, srt_path)

        approved_ids = [j["line_id"] for j in jobs if j["status"] == "approved"]
        pending_or_failed = [j for j in jobs if j["status"] != "approved"]
        manifest["resume_checkpoint"] = {
            "last_completed_line_id": approved_ids[-1] if approved_ids else None,
            "next_pending_line_id": pending_or_failed[0]["line_id"] if pending_or_failed else None,
            "blockers": [f"{j['line_id']} ({j['status']}): {j['reason']}" for j in pending_or_failed],
        }
        self._save_json(manifest_path, manifest)

        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "project_id": manifest.get("project_id"),
            "backend_adapter": self.backend.adapter_id,
            "timeline_wav": str(timeline_wav),
            "timeline_meta": timeline_meta,
            "mix_stats": mix_stats,
            "timeline_validation": validation,
            "subtitles_srt": str(srt_path),
            "summary": {
                "total_lines": len(jobs),
                "successful": sum(1 for j in jobs if j["status"] == "approved"),
                "failed": sum(1 for j in jobs if j["status"] == "failed"),
                "missing": sum(1 for j in jobs if j["status"] == "missing"),
                "blocked": sum(1 for j in jobs if j["status"] == "blocked"),
                "overlaps_detected": len(validation["overlaps"]),
                "timeline_errors": len(validation["errors"]),
            },
            "jobs": jobs,
        }
        self._save_json(output_dir / "voice_job_report.json", report)
        self._write_markdown_report(report, output_dir / "voice_job_report.md")
        return report

    @staticmethod
    def _assemble_timeline_wav(
        assets: List[Dict[str, Any]],
        jobs: List[Dict[str, Any]],
        out_wav: Path,
        total_duration_sec: float,
    ) -> Dict[str, Any]:
        """Additively mix approved dialogue stems onto a silent PCM timeline with clipping prevention."""
        total_frames = int(round(total_duration_sec * TARGET_SAMPLE_RATE))
        total_samples = total_frames * TARGET_CHANNELS
        acc = array.array("q", [0] * total_samples)  # 64-bit signed accumulator prevents int16 overflow

        for asset, job in zip(assets, jobs):
            if job["status"] != "approved" or not job.get("processed_path"):
                continue
            start_s = max(0.0, float(asset.get("start_sec", 0.0)))
            start_sample = int(round(start_s * TARGET_SAMPLE_RATE)) * TARGET_CHANNELS
            with wave.open(job["processed_path"], "rb") as wf:
                if wf.getframerate() != TARGET_SAMPLE_RATE or wf.getnchannels() != TARGET_CHANNELS or wf.getsampwidth() != 2:
                    raise ValueError(f"Unexpected PCM format in {job['processed_path']}")
                raw = wf.readframes(wf.getnframes())

            clip_samples = array.array("h")
            clip_samples.frombytes(raw)
            needed_len = start_sample + len(clip_samples)
            if needed_len > len(acc):
                acc.extend([0] * (needed_len - len(acc)))

            for i, val in enumerate(clip_samples):
                acc[start_sample + i] += val

        raw_peak = max((abs(x) for x in acc), default=0)
        gain_scale = 1.0
        if raw_peak > MAX_SAFE_PEAK:
            gain_scale = MAX_SAFE_PEAK / float(raw_peak)

        out_samples = array.array("h", (
            max(-32768, min(32767, int(round(x * gain_scale)))) for x in acc
        ))

        with wave.open(str(out_wav), "wb") as out_wf:
            out_wf.setnchannels(TARGET_CHANNELS)
            out_wf.setsampwidth(2)
            out_wf.setframerate(TARGET_SAMPLE_RATE)
            out_wf.writeframes(out_samples.tobytes())

        final_peak = max((abs(x) for x in out_samples), default=0)
        return {
            "raw_peak_int16": raw_peak,
            "final_peak_int16": final_peak,
            "clipping_prevented": raw_peak > 32767,
            "gain_scale_applied": round(gain_scale, 6),
        }

    def _write_srt(
        self,
        assets: List[Dict[str, Any]],
        char_map: Dict[str, Dict[str, Any]],
        srt_path: Path,
    ) -> None:
        blocks: List[str] = []
        for idx, asset in enumerate(assets, 1):
            start_s = max(0.0, float(asset.get("start_sec") or 0.0))
            end_s = max(start_s, float(asset.get("end_sec") or start_s))
            t0 = self._fmt_srt_time(start_s)
            t1 = self._fmt_srt_time(end_s)
            cid = asset.get("character_id", "")
            disp = char_map.get(cid, {}).get("display_name", cid).upper()
            vid = asset.get("voice_id", "")
            text = asset.get("text", "")
            blocks.append(f"{idx}\n{t0} --> {t1}\n[{disp} · {vid}]\n{text}\n")
        srt_path.write_text("\n".join(blocks), encoding="utf-8")

    @staticmethod
    def _write_markdown_report(report: Dict[str, Any], md_path: Path) -> None:
        s = report["summary"]
        tv = report["timeline_validation"]
        ms = report["mix_stats"]
        lines = [
            f"# Voice Job Report — `{report['project_id']}`",
            "",
            f"- **Backend Adapter:** `{report['backend_adapter']}`",
            f"- **Timeline Output:** `{report['timeline_wav']}`",
            f"- **Timeline Validation:** `{json.dumps(report['timeline_meta'])}`",
            f"- **Additive Mix Stats:** `raw_peak={ms['raw_peak_int16']}`, `final_peak={ms['final_peak_int16']}`, `gain_scale={ms['gain_scale_applied']}`, `clipping_prevented={ms['clipping_prevented']}`",
            f"- **Summary:** `{s['successful']}` successful | `{s['failed']}` failed | `{s['missing']}` missing | `{s['blocked']}` blocked | `{s['overlaps_detected']}` overlaps | `{s['timeline_errors']}` timeline errors (Total lines: `{s['total_lines']}`)",
            "",
            "| Line ID | Character | Voice ID | Status | Details |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for j in report["jobs"]:
            lines.append(
                f"| `{j['line_id']}` | `{j['character_id']}` | `{j['voice_id']}` | **{j['status'].upper()}** | {j['reason']} |"
            )
        if tv["overlaps"]:
            lines.extend(["", "## Detected Dialogue Overlaps"])
            for ov in tv["overlaps"]:
                lines.append(f"- `{ov['line_a']}` + `{ov['line_b']}` overlap `{ov['overlap_start_sec']}s`–`{ov['overlap_end_sec']}s`")
        if tv["errors"]:
            lines.extend(["", "## Timeline & Subtitle Validation Errors"])
            for er in tv["errors"]:
                lines.append(f"- `{er['line_id']}` ({er['type']}): {er['detail']}")
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Roblox Town Director Recorded Voice Backend")
    parser.add_argument("--manifest", required=True, help="Path to project-voice-manifest.json")
    parser.add_argument(
        "--registry",
        default=str(Path(__file__).resolve().parent.parent / "templates" / "voice-registry.json"),
        help="Path to voice-registry.json",
    )
    parser.add_argument("--output-dir", required=True, help="Directory for processed stems, timeline WAV, SRT, and reports")
    parser.add_argument("--backend", choices=["recorded", "external_tts"], default="recorded")
    parser.add_argument("--duration", type=float, default=None, help="Optional project timeline duration in seconds")
    args = parser.parse_args()

    backend: VoiceBackend = (
        RecordedVoiceBackend() if args.backend == "recorded" else ExternalTTSBackend()
    )
    manager = SharedVoiceManager(Path(args.registry), backend)
    report = manager.run_project(Path(args.manifest), Path(args.output_dir), total_duration_sec=args.duration)
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
