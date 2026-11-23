#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Visual Quality Control Module for Roblox Town Director v0.2.0.

Provides:
  - detect_black_segments: FFmpeg `blackdetect` blank/black-frame detection.
  - generate_scene_contact_sheet: Extracts 1 representative frame per scene (or
    evenly spaced samples) and tiles them into a labeled PNG contact sheet via
    PIL for character-continuity and caption-readability inspection.

Explicitly reports detection limitations: automated blackdetect catches dark/blank
frames, while semantic character continuity and caption aesthetics require human
or multimodal visual inspection of the generated contact sheet.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from voice_intelligence.audio_qc import inspect_video_file  # noqa: E402

BLACK_DETECT_RE = re.compile(
    r"black_start:(?P<start>\d+(?:\.\d+)?)\s+black_end:(?P<end>\d+(?:\.\d+)?)\s+black_duration:(?P<dur>\d+(?:\.\d+)?)"
)


class VisualQCError(RuntimeError):
    """Raised when visual QC extraction or contact-sheet generation fails."""


def detect_black_segments(
    video_path: Path,
    *,
    min_duration_sec: float = 0.4,
    pixel_black_th: float = 0.10,
    picture_black_ratio_th: float = 0.98,
    timeout_sec: float = 120.0,
) -> Dict[str, Any]:
    """Detect black or blank video segments using FFmpeg's `blackdetect` filter."""
    vp = Path(video_path)
    qc = inspect_video_file(vp)
    if not qc["valid"]:
        return {
            "valid": False,
            "file": str(vp),
            "black_segments": [],
            "total_black_duration_sec": 0.0,
            "has_unexpected_blank_segments": True,
            "errors": list(qc["errors"]),
            "limitations": "Source video failed FFprobe validation.",
        }

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "info",
        "-i",
        str(vp),
        "-vf",
        f"blackdetect=d={float(min_duration_sec):.3f}:pix_th={float(pixel_black_th):.3f}:pic_th={float(picture_black_ratio_th):.3f}",
        "-an",
        "-f",
        "null",
        "-",
    ]
    try:
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=timeout_sec)
    except FileNotFoundError:
        return {
            "valid": False,
            "file": str(vp),
            "black_segments": [],
            "total_black_duration_sec": 0.0,
            "has_unexpected_blank_segments": False,
            "errors": ["Required binary 'ffmpeg' not found on PATH."],
            "limitations": "blackdetect could not run without ffmpeg.",
        }
    except subprocess.TimeoutExpired:
        return {
            "valid": False,
            "file": str(vp),
            "black_segments": [],
            "total_black_duration_sec": 0.0,
            "has_unexpected_blank_segments": False,
            "errors": [f"FFmpeg blackdetect timed out after {timeout_sec}s."],
            "limitations": "blackdetect timed out before completing.",
        }

    if res.returncode != 0:
        return {
            "valid": False,
            "file": str(vp),
            "black_segments": [],
            "total_black_duration_sec": 0.0,
            "has_unexpected_blank_segments": False,
            "errors": [f"FFmpeg blackdetect failed: {res.stderr[-250:].strip()}"],
            "limitations": "blackdetect exited non-zero.",
        }

    segments: List[Dict[str, float]] = []
    for m in BLACK_DETECT_RE.finditer(res.stderr or ""):
        segments.append(
            {
                "start_sec": round(float(m.group("start")), 3),
                "end_sec": round(float(m.group("end")), 3),
                "duration_sec": round(float(m.group("dur")), 3),
            }
        )

    total_black = round(sum(s["duration_sec"] for s in segments), 3)
    return {
        "valid": True,
        "file": str(vp),
        "video_duration_sec": qc["duration_sec"],
        "black_segments": segments,
        "total_black_duration_sec": total_black,
        "has_unexpected_blank_segments": len(segments) > 0,
        "errors": [],
        "limitations": (
            "FFmpeg blackdetect identifies uniformly dark/blank frames above threshold. "
            "It does not assess semantic character continuity, facial distortion, or subjective caption readability; "
            "inspect the generated scene contact sheet for visual review."
        ),
    }


def generate_scene_contact_sheet(
    video_path: Path,
    output_png_path: Path,
    *,
    scene_timestamps: Optional[Sequence[float]] = None,
    scene_labels: Optional[Sequence[str]] = None,
    num_samples: int = 6,
    thumb_width: int = 320,
    columns: int = 3,
    timeout_sec: float = 120.0,
) -> Dict[str, Any]:
    """Extract representative frames and assemble a labeled PNG contact sheet for visual QC."""
    vp = Path(video_path)
    out_png = Path(output_png_path)
    qc = inspect_video_file(vp)
    if not qc["valid"]:
        raise VisualQCError(f"Cannot generate contact sheet for invalid video {vp}: {'; '.join(qc['errors'])}")

    dur = max(0.05, float(qc["duration_sec"]))
    fps = float(qc.get("fps") or 24.0)
    eof_guard = max(0.15, 2.0 / max(fps, 1.0))
    max_seek_ts = max(0.0, dur - eof_guard)
    if scene_timestamps:
        timestamps = [max(0.0, min(max_seek_ts, float(t))) for t in scene_timestamps]
    else:
        n = max(1, int(num_samples))
        timestamps = [round((dur * (i + 0.5)) / n, 3) for i in range(n)]

    labels = list(scene_labels) if scene_labels else [f"Frame {i+1} ({t:.2f}s)" for i, t in enumerate(timestamps)]
    if len(labels) < len(timestamps):
        labels.extend(f"Frame {i+1} ({timestamps[i]:.2f}s)" for i in range(len(labels), len(timestamps)))

    thumbs: List[Image.Image] = []
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        for idx, ts in enumerate(timestamps):
            frame_jpg = td_path / f"frame_{idx:03d}.jpg"
            try:
                res = subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-y",
                        "-v",
                        "error",
                        "-ss",
                        f"{ts:.3f}",
                        "-i",
                        str(vp),
                        "-frames:v",
                        "1",
                        str(frame_jpg),
                    ],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout_sec,
                )
            except FileNotFoundError as exc:
                raise VisualQCError("Required binary 'ffmpeg' not found on PATH.") from exc
            except subprocess.TimeoutExpired as exc:
                raise VisualQCError(f"FFmpeg frame extraction timed out after {timeout_sec}s.") from exc

            if res.returncode != 0 or not frame_jpg.exists():
                raise VisualQCError(f"Failed to extract frame at {ts:.3f}s: {res.stderr.strip()}")

            with Image.open(frame_jpg) as im:
                im_rgb = im.convert("RGB")
                aspect = im_rgb.height / max(1, im_rgb.width)
                th_h = max(64, int(round(thumb_width * aspect)))
                resized = im_rgb.resize((thumb_width, th_h), Image.Resampling.LANCZOS)
                # Add dark label footer bar for clean human/agent inspection
                bar_h = 28
                tile = Image.new("RGB", (thumb_width, th_h + bar_h), (18, 20, 26))
                tile.paste(resized, (0, 0))
                draw = ImageDraw.Draw(tile)
                draw.text((8, th_h + 7), labels[idx][:38], fill=(240, 244, 248))
                thumbs.append(tile)

    cols = max(1, min(int(columns), len(thumbs)))
    rows = int(math.ceil(len(thumbs) / cols))
    pad = 10
    tile_w, tile_h = thumbs[0].size
    sheet_w = cols * tile_w + (cols + 1) * pad
    sheet_h = rows * tile_h + (rows + 1) * pad
    sheet = Image.new("RGB", (sheet_w, sheet_h), (10, 12, 16))
    for i, tile in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet.paste(tile, (pad + c * (tile_w + pad), pad + r * (tile_h + pad)))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png, format="PNG")
    return {
        "contact_sheet_path": str(out_png),
        "frame_count": len(thumbs),
        "timestamps_sec": timestamps,
        "sheet_width": sheet_w,
        "sheet_height": sheet_h,
        "requires_human_or_multimodal_inspection": True,
        "note": "Contact sheet provides 1 representative frame per scene for character continuity and caption readability review.",
    }
