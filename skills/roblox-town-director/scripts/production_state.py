#!/usr/bin/env python3
"""Persistent Per-Scene Production State, Recovery, Resource Check & Final Delivery Gate (v0.2.0).

Fixes:
  - F-12: `get_pending_or_failed_scenes()` verifies cached scene assets via
    `inspect_video_file()` rather than trusting mere file existence. Missing,
    0-byte, corrupt, or non-video files are NOT skipped.
  - F-13: `evaluate_final_delivery_gate()` does NOT accept an unverified
    `captions_burned_in=True` boolean as proof of captions. Burned-in captions
    require a SHA-256 hash-verified `caption_render_receipt` matching the actual
    output file on disk (or a real FFprobe-detected embedded subtitle stream).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from visual_qc import detect_black_segments  # noqa: E402
from voice_intelligence.audio_qc import inspect_video_file  # noqa: E402

VALID_OPERATING_MODES = ("autonomous", "interactive", "user_script")
VALID_OUTPUT_CLASSIFICATIONS = (
    "real_roblox_production",
    "code_driven_roblox_style_animation",
    "ai_generated_video",
    "animatic",
)
VALID_SCENE_STATUSES = ("pending", "completed", "failed")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_host_resources() -> Dict[str, Any]:
    """Inspect available host RAM honestly if exposed (e.g. Linux /proc/meminfo)."""
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return {
            "available": False,
            "scope": "unavailable",
            "note": "Host environment does not expose /proc/meminfo; resource monitoring unavailable.",
        }
    try:
        vals: Dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                num = parts[1].strip().split()[0]
                if num.isdigit():
                    vals[key] = int(num)
        total_mb = round(vals.get("MemTotal", 0) / 1024.0, 1)
        avail_mb = round(vals.get("MemAvailable", vals.get("MemFree", 0)) / 1024.0, 1)
        return {
            "available": True,
            "scope": "local_host_environment",
            "mem_total_mb": total_mb,
            "mem_available_mb": avail_mb,
            "low_memory_batch_recommended": avail_mb < 1500.0,
        }
    except Exception as exc:
        return {
            "available": False,
            "scope": "error",
            "note": f"Could not inspect host memory: {exc}",
        }


class ProductionStateManager:
    """Atomic per-scene production state & crash recovery manager."""

    SCHEMA_VERSION = "2.0.0"

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self.state: Dict[str, Any] = {}
        if self.state_path.exists():
            self.load()

    def load(self) -> Dict[str, Any]:
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        return self.state

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated_at"] = _utc_now_iso()
        fd, tmp_name = tempfile.mkstemp(
            prefix=".prod_state_", suffix=".tmp", dir=str(self.state_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(self.state, indent=2) + "\n")
            os.replace(tmp_name, self.state_path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def initialize(
        self,
        *,
        project_id: str,
        title: str,
        operating_mode: str = "autonomous",
        output_classification: str = "animatic",
        scene_ids: List[str],
        script_text: str,
        user_script_locked: bool = False,
        caption_style_id: str = "C16",
        voice_assignments: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if operating_mode not in VALID_OPERATING_MODES:
            raise ValueError(f"Invalid operating_mode: {operating_mode!r}")
        if output_classification not in VALID_OUTPUT_CLASSIFICATIONS:
            raise ValueError(f"Invalid output_classification: {output_classification!r}")
        now = _utc_now_iso()
        self.state = {
            "schema_version": self.SCHEMA_VERSION,
            "project_id": project_id,
            "title": title,
            "operating_mode": operating_mode,
            "output_classification": output_classification,
            "user_script_locked": bool(user_script_locked),
            "script_text": script_text,
            "caption_style_id": caption_style_id,
            "voice_assignments": dict(voice_assignments or {}),
            "providers_used": [],
            "errors": [],
            "created_at": now,
            "updated_at": now,
            "scenes": {
                sid: {
                    "scene_id": sid,
                    "status": "pending",
                    "asset_path": None,
                    "attempts": 0,
                    "error": None,
                }
                for sid in scene_ids
            },
            "final_delivery": None,
        }
        self.save()
        return self.state

    def update_script(self, new_script: str, *, user_authorized_rewrite: bool = False) -> None:
        if self.state.get("user_script_locked") and not user_authorized_rewrite:
            raise PermissionError(
                "User-supplied script is locked; silent rewriting is prohibited without explicit authorization."
            )
        self.state["script_text"] = new_script
        self.save()

    def mark_scene_completed(self, scene_id: str, asset_path: Path, provider: Optional[str] = None) -> None:
        scene = self.state["scenes"][scene_id]
        scene["status"] = "completed"
        scene["asset_path"] = str(asset_path)
        scene["attempts"] = int(scene.get("attempts", 0)) + 1
        scene["error"] = None
        if provider and provider not in self.state["providers_used"]:
            self.state["providers_used"].append(provider)
        self.save()

    def mark_scene_failed(self, scene_id: str, error: str) -> None:
        scene = self.state["scenes"][scene_id]
        scene["status"] = "failed"
        scene["attempts"] = int(scene.get("attempts", 0)) + 1
        scene["error"] = str(error)
        self.state["errors"].append({"scene_id": scene_id, "error": str(error), "at": _utc_now_iso()})
        self.save()

    def get_pending_or_failed_scenes(self) -> List[str]:
        """Return scenes that still need execution (F-12: verifies cached assets via FFprobe)."""
        todo: List[str] = []
        for sid, info in self.state.get("scenes", {}).items():
            asset_ref = info.get("asset_path")
            if info.get("status") == "completed" and asset_ref:
                qc = inspect_video_file(Path(asset_ref))
                if qc["valid"] and qc["duration_sec"] > 0 and qc["width"] > 0 and qc["height"] > 0:
                    continue
            todo.append(sid)
        return todo

    def record_final_delivery(self, gate_result: Dict[str, Any]) -> None:
        self.state["final_delivery"] = gate_result
        self.save()


def verify_output_classification(
    requested_classification: str,
    *,
    production_provenance: Optional[Dict[str, Any]] = None,
    scene_source_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Verify output_classification honestly for the local FFmpeg pipeline (F-23, F-25).

    In v0.2.0, the local executable pipeline (`autopilot.py` / `video_assembler.py`)
    runs `ffmpeg_multi_scene_assembler` on supplied inputs. It does NOT execute
    Roblox Studio, Blender/3D renderers, or external AI video providers directly.

    Neither caller-supplied strings, file existence, nor SHA-256 file hashes can
    prove which external application created an MP4 file. Therefore:
      - `animatic` is verified as an honest local assembly classification.
      - Any request for `real_roblox_production`, `code_driven_roblox_style_animation`,
        or `ai_generated_video` is ALWAYS conservatively downgraded to `animatic` with
        `provenance_verified=False` and `provenance_status="unverifiable_external_origin"`.
      - Any caller-supplied `production_provenance` metadata is preserved strictly as
        unverified `declared_provenance` for transparency.
    """
    if requested_classification not in VALID_OUTPUT_CLASSIFICATIONS:
        raise ValueError(f"Invalid output_classification: {requested_classification!r}")

    declared = dict(production_provenance or {})
    src_types = [str(t).strip().lower() for t in (scene_source_types or [])]
    has_video_scene = "video" in src_types

    if requested_classification == "animatic":
        return {
            "requested_classification": "animatic",
            "effective_classification": "animatic",
            "provenance_verified": True,
            "provenance_status": "animatic_verified_local_assembly",
            "classification_downgraded": False,
            "actual_production_route": "ffmpeg_multi_scene_assembler",
            "reason": "Conservative animatic classification matches local FFmpeg assembly.",
            "declared_provenance": declared,
        }

    if not has_video_scene:
        reason = (
            f"Cannot classify still-image-only or video-less assembly as {requested_classification}; "
            "downgraded conservatively to animatic."
        )
    else:
        reason = (
            f"Cannot independently verify external production origin for {requested_classification}: "
            "the local FFmpeg pipeline has no integrated Roblox Studio, code-renderer, or AI video "
            "execution adapter, and neither metadata strings nor file hashes prove which application "
            "created external video inputs. Preserved caller metadata as unverified declared_provenance "
            "and downgraded conservatively to animatic."
        )

    return {
        "requested_classification": requested_classification,
        "effective_classification": "animatic",
        "provenance_verified": False,
        "provenance_status": "unverifiable_external_origin",
        "classification_downgraded": True,
        "actual_production_route": "ffmpeg_multi_scene_assembler",
        "reason": reason,
        "declared_provenance": declared,
    }

def _verify_caption_render_receipt(video_path: Path, receipt: Optional[Dict[str, Any]]) -> bool:
    """Verify a trusted pipeline caption receipt against the actual video file SHA-256."""
    if not isinstance(receipt, dict):
        return False
    if not receipt.get("burned_in"):
        return False
    preset_id = str(receipt.get("preset_id") or "")
    if not (preset_id.startswith("C") and preset_id[1:].isdigit() and 1 <= int(preset_id[1:]) <= 15):
        return False
    if int(receipt.get("cue_count") or 0) <= 0:
        return False
    expected_sha = str(receipt.get("output_sha256") or "").strip().lower()
    if len(expected_sha) != 64:
        return False
    actual_sha = compute_file_sha256(video_path).lower()
    return actual_sha == expected_sha


def evaluate_final_delivery_gate(
    *,
    video_path: Optional[Path],
    expected_duration_sec: Optional[float] = None,
    duration_tolerance_sec: float = 1.5,
    expected_width: Optional[int] = None,
    expected_height: Optional[int] = None,
    expected_fps: Optional[float] = None,
    require_audio: bool = True,
    require_captions: bool = False,
    captions_burned_in: bool = False,
    caption_render_receipt: Optional[Dict[str, Any]] = None,
    check_black_frames: bool = False,
    output_classification: str = "animatic",
    production_provenance: Optional[Dict[str, Any]] = None,
    scene_source_types: Optional[List[str]] = None,
    decode_timeout_sec: float = 180.0,
) -> Dict[str, Any]:
    """Hard Final Delivery Gate (AT-11, F-13): returns COMPLETE only if a playable verified video exists.

    F-13 enforcement: Setting `captions_burned_in=True` alone is NOT accepted as
    proof of captions. When `require_captions=True`, either FFprobe must detect
    an embedded subtitle stream (`has_subtitles=True`) OR `caption_render_receipt`
    must carry a valid preset ID, `cue_count > 0`, and a matching SHA-256 hash of
    the delivered `video_path`.
    """
    provenance_check = verify_output_classification(
        output_classification,
        production_provenance=production_provenance,
        scene_source_types=scene_source_types,
    )
    effective_classification = provenance_check["effective_classification"]

    failures: List[str] = []
    if video_path is None:
        return {
            "status": "FAILED",
            "playable_video_delivered": False,
            "output_classification": effective_classification,
            "requested_classification": provenance_check["requested_classification"],
            "provenance_verified": provenance_check["provenance_verified"],
        "provenance_status": provenance_check["provenance_status"],
        "declared_provenance": provenance_check["declared_provenance"],
            "provenance_status": provenance_check["provenance_status"],
            "declared_provenance": provenance_check["declared_provenance"],
            "classification_downgraded": provenance_check["classification_downgraded"],
            "provenance_check": provenance_check,
            "failures": ["No output video path provided."],
            "video_qc": None,
            "black_frame_qc": None,
            "captions_verified": False,
            "full_decode_passed": False,
        }

    vp = Path(video_path)
    qc = inspect_video_file(vp)
    if not qc["valid"]:
        return {
            "status": "FAILED",
            "playable_video_delivered": False,
            "output_classification": effective_classification,
            "requested_classification": provenance_check["requested_classification"],
            "provenance_verified": provenance_check["provenance_verified"],
            "provenance_status": provenance_check["provenance_status"],
            "declared_provenance": provenance_check["declared_provenance"],
            "classification_downgraded": provenance_check["classification_downgraded"],
            "provenance_check": provenance_check,
            "failures": list(qc["errors"]),
            "video_qc": qc,
            "black_frame_qc": None,
            "captions_verified": False,
            "full_decode_passed": False,
        }

    full_decode_passed = False
    try:
        dec = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(vp), "-f", "null", "-"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=decode_timeout_sec,
        )
        if dec.returncode == 0:
            full_decode_passed = True
        else:
            failures.append(f"Full FFmpeg decode failed: {dec.stderr.strip()}")
    except FileNotFoundError:
        failures.append("Required binary 'ffmpeg' not found on PATH for decode verification.")
    except subprocess.TimeoutExpired:
        failures.append(f"Full FFmpeg decode timed out after {decode_timeout_sec}s.")

    if expected_duration_sec is not None:
        if abs(qc["duration_sec"] - float(expected_duration_sec)) > float(duration_tolerance_sec):
            failures.append(
                f"Duration {qc['duration_sec']:.2f}s outside expected "
                f"{expected_duration_sec:.2f}s +/- {duration_tolerance_sec:.2f}s."
            )
    if expected_width is not None and qc["width"] != int(expected_width):
        failures.append(f"Width {qc['width']} != expected {expected_width}.")
    if expected_height is not None and qc["height"] != int(expected_height):
        failures.append(f"Height {qc['height']} != expected {expected_height}.")
    if expected_fps is not None and abs(qc["fps"] - float(expected_fps)) > 0.1:
        failures.append(f"FPS {qc['fps']} != expected {expected_fps}.")
    if require_audio and not qc["has_audio"]:
        failures.append("Required audio stream is missing.")

    # F-13: Defensible caption verification (embedded FFprobe stream OR SHA-256 verified render receipt)
    receipt_verified = _verify_caption_render_receipt(vp, caption_render_receipt)
    captions_verified = bool(qc["has_subtitles"] or receipt_verified)
    if require_captions and not captions_verified:
        if captions_burned_in:
            failures.append(
                "Unverified captions_burned_in=True claim rejected: no embedded subtitle stream "
                "and no SHA-256 verified caption_render_receipt matching the output video."
            )
        else:
            failures.append("Required captions are missing (no embedded subtitle stream or verified caption receipt).")

    black_qc: Optional[Dict[str, Any]] = None
    if check_black_frames:
        black_qc = detect_black_segments(vp)
        if not black_qc["valid"]:
            failures.append("Black-frame QC failed: " + "; ".join(black_qc["errors"]))
        elif black_qc["has_unexpected_blank_segments"]:
            failures.append(
                f"Unexpected blank/black segments detected ({len(black_qc['black_segments'])} segment(s), "
                f"total {black_qc['total_black_duration_sec']}s)."
            )

    status = "COMPLETE" if (full_decode_passed and not failures) else "INCOMPLETE"
    return {
        "status": status,
        "playable_video_delivered": status == "COMPLETE",
        "output_classification": effective_classification,
        "requested_classification": provenance_check["requested_classification"],
        "provenance_verified": provenance_check["provenance_verified"],
        "provenance_status": provenance_check["provenance_status"],
        "declared_provenance": provenance_check["declared_provenance"],
        "classification_downgraded": provenance_check["classification_downgraded"],
        "provenance_check": provenance_check,
        "failures": failures,
        "video_qc": qc,
        "black_frame_qc": black_qc,
        "captions_verified": captions_verified,
        "caption_verification_method": (
            "ffprobe_subtitle_stream" if qc["has_subtitles"] else ("sha256_render_receipt" if receipt_verified else "none")
        ),
        "full_decode_passed": full_decode_passed,
    }
