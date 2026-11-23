#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Automated Audio & Media Quality Control Module for Roblox Town Director.

Uses FFprobe and FFmpeg to validate technical audio integrity, duration, sample
rate, channel count, clipping, silence/empty output, dialogue timing, missing
dialogue, character-to-voice mapping, video stream preservation, and A/V sync
offset. Explicitly marks subjective speech naturalness as requiring human listening.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_VOL_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _run_cmd(cmd: List[str], timeout_sec: float = 60.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=timeout_sec)
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            args=cmd, returncode=127, stdout="", stderr=f"Required binary not found on PATH: {cmd[0]}"
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=cmd, returncode=124, stdout="", stderr=f"Command timed out after {timeout_sec}s: {cmd[0]}"
        )


def _parse_fps(rate_str: str) -> float:
    if not rate_str or rate_str == "0/0":
        return 0.0
    if "/" in rate_str:
        num, den = rate_str.split("/", 1)
        try:
            d = float(den)
            return round(float(num) / d, 4) if d != 0 else 0.0
        except ValueError:
            return 0.0
    try:
        return round(float(rate_str), 4)
    except ValueError:
        return 0.0


def inspect_video_file(video_path: Path) -> Dict[str, Any]:
    """Inspect a video container via FFprobe for video, audio, and subtitle streams."""
    p = Path(video_path)
    report: Dict[str, Any] = {
        "file": str(p),
        "exists": p.exists(),
        "valid": False,
        "duration_sec": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "r_frame_rate": "",
        "video_codec": "",
        "has_audio": False,
        "audio_codec": "",
        "has_subtitles": False,
        "subtitle_codec": "",
        "errors": [],
    }
    if not p.exists():
        report["errors"].append("Video file does not exist.")
        return report
    if p.stat().st_size == 0:
        report["errors"].append("Video file is 0 bytes (empty).")
        return report

    probe = _run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(p),
        ]
    )
    if probe.returncode != 0:
        report["errors"].append(f"FFprobe failed (corrupt or unreadable video): {probe.stderr.strip()}")
        return report

    try:
        data = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        report["errors"].append(f"FFprobe returned invalid JSON: {exc}")
        return report

    streams = data.get("streams", [])
    v_streams = [s for s in streams if s.get("codec_type") == "video"]
    a_streams = [s for s in streams if s.get("codec_type") == "audio"]
    s_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    if not v_streams:
        report["errors"].append("File contains no decodable video stream.")
        return report

    vs = v_streams[0]
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except ValueError:
        duration = 0.0

    report["duration_sec"] = round(duration, 4)
    report["width"] = int(vs.get("width") or 0)
    report["height"] = int(vs.get("height") or 0)
    report["r_frame_rate"] = str(vs.get("r_frame_rate") or "")
    report["fps"] = _parse_fps(report["r_frame_rate"])
    report["video_codec"] = str(vs.get("codec_name") or "")

    if report["width"] <= 0 or report["height"] <= 0:
        report["errors"].append("Invalid video resolution.")
    if duration <= 0.0:
        report["errors"].append("Video duration is zero or negative.")

    if a_streams:
        report["has_audio"] = True
        report["audio_codec"] = str(a_streams[0].get("codec_name") or "")
    if s_streams:
        report["has_subtitles"] = True
        report["subtitle_codec"] = str(s_streams[0].get("codec_name") or "")

    report["valid"] = len(report["errors"]) == 0
    return report


def inspect_audio_file(
    audio_path: Path,
    *,
    check_volume: bool = True,
    clipping_threshold_db: float = -0.1,
    silence_mean_threshold_db: float = -60.0,
) -> Dict[str, Any]:
    """Run FFprobe + optional FFmpeg volumedetect on a single audio file."""
    p = Path(audio_path)
    report: Dict[str, Any] = {
        "file": str(p),
        "exists": p.exists(),
        "valid": False,
        "duration_sec": 0.0,
        "sample_rate_hz": 0,
        "channels": 0,
        "codec": "",
        "max_volume_db": None,
        "mean_volume_db": None,
        "clipping_detected": False,
        "is_effectively_silent": False,
        "errors": [],
        "warnings": [],
        "requires_human_listening": True,
        "subjective_naturalness_assessed": False,
    }

    if not p.exists():
        report["errors"].append("Audio file does not exist.")
        return report
    if p.stat().st_size == 0:
        report["errors"].append("Audio file is 0 bytes (empty).")
        return report

    probe = _run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,sample_rate,channels",
            "-of",
            "json",
            str(p),
        ]
    )
    if probe.returncode != 0:
        report["errors"].append(f"FFprobe failed (corrupt or unreadable audio): {probe.stderr.strip()}")
        return report

    try:
        data = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        report["errors"].append(f"FFprobe returned invalid JSON: {exc}")
        return report

    audio_streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        report["errors"].append("File contains no decodable audio stream.")
        return report

    stream = audio_streams[0]
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except ValueError:
        duration = 0.0
    sample_rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)
    codec = str(stream.get("codec_name") or "")

    report["duration_sec"] = round(duration, 4)
    report["sample_rate_hz"] = sample_rate
    report["channels"] = channels
    report["codec"] = codec

    if duration <= 0.0:
        report["errors"].append("Audio duration is zero or negative.")
    if sample_rate <= 0:
        report["errors"].append("Invalid sample rate.")
    if channels <= 0:
        report["errors"].append("Invalid channel count.")

    if check_volume and not report["errors"]:
        vol = _run_cmd(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "info",
                "-i",
                str(p),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ]
        )
        stderr = vol.stderr or ""
        if vol.returncode != 0:
            report["errors"].append(f"FFmpeg decode/volumedetect failed: {stderr[-200:].strip()}")
        else:
            m_max = MAX_VOL_RE.search(stderr)
            m_mean = MEAN_VOL_RE.search(stderr)
            if m_max:
                max_db = float(m_max.group(1))
                report["max_volume_db"] = max_db
                if max_db >= clipping_threshold_db:
                    report["clipping_detected"] = True
                    report["warnings"].append(
                        f"Potential peak clipping detected (max_volume={max_db:.1f} dB >= {clipping_threshold_db:.1f} dB)."
                    )
            if m_mean:
                mean_db = float(m_mean.group(1))
                report["mean_volume_db"] = mean_db
                if mean_db <= silence_mean_threshold_db:
                    report["is_effectively_silent"] = True
                    report["errors"].append(
                        f"Audio appears silent or empty (mean_volume={mean_db:.1f} dB <= {silence_mean_threshold_db:.1f} dB)."
                    )

    report["valid"] = len(report["errors"]) == 0
    return report


def run_project_audio_qc(
    *,
    dialogue_jobs: List[Dict[str, Any]],
    character_voice_map: Dict[str, Dict[str, Any]],
    master_audio_path: Optional[Path] = None,
    video_duration_sec: Optional[float] = None,
    max_av_sync_drift_sec: float = 0.25,
) -> Dict[str, Any]:
    """Run project-wide technical QC across dialogue lines, mapping, and optional A/V sync."""
    missing_dialogue: List[str] = []
    blocked_dialogue: List[str] = []
    blocked_details: List[Dict[str, Any]] = []
    failed_dialogue: List[str] = []
    production_mechanism_failures: List[str] = []
    mapping_errors: List[str] = []
    timing_warnings: List[str] = []
    approved_count = 0

    for job in dialogue_jobs:
        line_id = job["line_id"]
        char_id = job["character_id"]
        status = str(job.get("status", "pending"))
        is_intentional_block = status.startswith("blocked")
        expected_map = character_voice_map.get(char_id)
        if not expected_map:
            if not is_intentional_block:
                mapping_errors.append(f"{line_id}: character {char_id!r} missing from character_voice_map.")
        elif job.get("voice_id") and job["voice_id"] != expected_map.get("voice_id"):
            mapping_errors.append(
                f"{line_id}: voice mismatch ({job.get('voice_id')} != locked {expected_map.get('voice_id')})."
            )

        if status == "approved":
            approved_count += 1
        elif is_intentional_block:
            blocked_dialogue.append(line_id)
            missing_dialogue.append(line_id)
            blocked_details.append(
                {
                    "line_id": line_id,
                    "character_id": char_id,
                    "status": status,
                    "reason": str(job.get("error") or "Intentionally blocked by policy or voice-continuity rule."),
                }
            )
        elif status in ("missing", "pending"):
            missing_dialogue.append(line_id)
            production_mechanism_failures.append(line_id)
        else:
            failed_dialogue.append(line_id)
            production_mechanism_failures.append(line_id)

        qc = job.get("qc") or {}
        start = job.get("start_sec")
        end = job.get("end_sec")
        if start is not None and end is not None and qc.get("duration_sec"):
            slot = float(end) - float(start)
            if qc["duration_sec"] > slot + 0.15:
                timing_warnings.append(
                    f"{line_id}: audio duration {qc['duration_sec']:.2f}s exceeds timeline slot {slot:.2f}s."
                )

    master_qc = (
        inspect_audio_file(master_audio_path, check_volume=True)
        if master_audio_path and Path(master_audio_path).exists()
        else None
    )
    av_sync_ok: Optional[bool] = None
    av_sync_drift_sec: Optional[float] = None
    if master_qc and master_qc["valid"] and video_duration_sec is not None:
        av_sync_drift_sec = round(abs(master_qc["duration_sec"] - float(video_duration_sec)), 4)
        av_sync_ok = av_sync_drift_sec <= max_av_sync_drift_sec

    has_mechanism_failure = (
        len(production_mechanism_failures) > 0
        or len(mapping_errors) > 0
        or (master_qc is not None and not master_qc["valid"])
        or (av_sync_ok is False)
    )
    has_intentional_blocks = len(blocked_dialogue) > 0

    if not has_mechanism_failure and not has_intentional_blocks:
        qc_outcome_category = "passed"
    elif has_intentional_blocks and not has_mechanism_failure:
        qc_outcome_category = "blocked_by_policy_or_assignment"
    elif has_mechanism_failure and not has_intentional_blocks:
        qc_outcome_category = "failed_production_mechanism"
    else:
        qc_outcome_category = "mixed_blocked_and_failed"

    technical_pass = (
        len(missing_dialogue) == 0
        and len(failed_dialogue) == 0
        and len(mapping_errors) == 0
        and (master_qc is None or master_qc["valid"])
        and (av_sync_ok is None or av_sync_ok)
    )

    return {
        "technical_qc_passed": technical_pass,
        "qc_outcome_category": qc_outcome_category,
        "total_lines": len(dialogue_jobs),
        "approved_lines": approved_count,
        "blocked_dialogue_lines": blocked_dialogue,
        "blocked_line_details": blocked_details,
        "production_mechanism_failures": production_mechanism_failures,
        "missing_dialogue_lines": missing_dialogue,
        "failed_dialogue_lines": failed_dialogue,
        "character_mapping_errors": mapping_errors,
        "timing_warnings": timing_warnings,
        "master_audio_qc": master_qc,
        "av_sync_drift_sec": av_sync_drift_sec,
        "av_sync_ok": av_sync_ok,
        "requires_human_listening": True,
        "subjective_naturalness_assessed": False,
        "qc_note": (
            "Technical audio checks (integrity, duration, sample rate, channels, clipping, "
            "silence, mapping, timing, and A/V sync) are automated. Subjective speech naturalness, "
            "pronunciation nuance, and emotional acting require human listening."
        ),
    }
