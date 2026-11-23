#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Executable 16-Preset Caption System (C01-C16) for Roblox Town Director v0.2.0.

Provides:
  - 15 genuinely distinct ASS/FFmpeg rendering presets (C01-C15)
  - C16 Auto Adaptive selector (picks from C01-C15 by genre, pacing, speaker count, tone)
  - Dynamic PlayResX/PlayResY scaling for 9:16 (1080x1920) and 16:9 (1920x1080)
  - Safe Unicode & ASS-control escaping, word/line wrapping, karaoke \\kf timing,
    per-speaker color coding, and FFmpeg burn-in rendering with timeout & verification.
"""

from __future__ import annotations

import functools
import json
import math
import re
import subprocess
import textwrap
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
DEFAULT_STYLES_PATH = TEMPLATES_DIR / "caption-styles.json"

SPEAKER_COLOR_PALETTE = (
    "&H00FFFFFF",  # Crisp white
    "&H0078E6FF",  # Warm amber-gold
    "&H00FFDC78",  # Sky cyan
    "&H00A8FF9E",  # Mint green
    "&H00C4B5FF",  # Soft rose
    "&H009EEBFF",  # Soft yellow
)

EMPHASIS_STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "have", "were", "your",
    "into", "just", "then", "than", "when", "what", "they", "them", "been", "will",
    "about", "would", "could", "there", "their", "here", "only", "very", "some",
}


MIN_PAGE_DURATION_SEC = 0.25
MIN_PAGE_DURATION_CS = 25


class CaptionRenderError(RuntimeError):
    """Raised when caption generation or FFmpeg ASS rendering fails."""


@dataclass
class CaptionCue:
    start_sec: float
    end_sec: float
    text: str
    speaker: str = ""

    def validate(self) -> None:
        if (
            isinstance(self.start_sec, bool)
            or isinstance(self.end_sec, bool)
            or not math.isfinite(float(self.start_sec))
            or not math.isfinite(float(self.end_sec))
            or float(self.start_sec) < 0.0
            or float(self.end_sec) <= float(self.start_sec)
        ):
            raise ValueError(f"Invalid caption timing: start={self.start_sec!r}, end={self.end_sec!r}")
        if not self.text or not self.text.strip():
            raise ValueError("Caption cue text must be non-empty.")


def load_caption_presets(styles_path: Path = DEFAULT_STYLES_PATH) -> Dict[str, Dict[str, Any]]:
    raw = json.loads(Path(styles_path).read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in raw.get("presets", [])}


def select_caption_style(
    *,
    genre: str = "story",
    pacing: str = "medium",
    speaker_count: int = 1,
    tone: str = "neutral",
    visual_complexity: str = "medium",
    styles_path: Path = DEFAULT_STYLES_PATH,
) -> str:
    """C16 Auto Adaptive selector: deterministically chooses from C01-C15."""
    g = (genre or "").strip().lower()
    p = (pacing or "").strip().lower()
    t = (tone or "").strip().lower()
    vc = (visual_complexity or "").strip().lower()

    if g in ("comedy", "meme", "funny", "parody"):
        return "C05" if p == "fast" else "C06"
    if g in ("reaction", "chaos", "challenge"):
        return "C14"
    if g in ("gaming", "roblox_gameplay", "obby", "rpg"):
        return "C09"
    if g in ("documentary", "explainer", "educational"):
        return "C10"
    if g in ("suspense", "mystery", "horror", "thriller") or t in ("tense", "suspenseful", "dark"):
        return "C11" if vc == "high" else "C13"
    if g in ("emotional", "heartfelt", "wholesome", "drama") or t in ("warm", "heartfelt", "emotional"):
        return "C12" if speaker_count <= 2 else "C08"
    if speaker_count >= 3:
        return "C08"
    if speaker_count == 2 and g in ("dialogue", "roleplay", "skit"):
        return "C07"
    if p == "fast":
        return "C02" if t in ("energetic", "hype") else "C01"
    if vc == "high":
        return "C04"
    if g in ("cinematic", "short_film"):
        return "C15" if t == "dramatic" else "C03"
    return "C01"


def resolve_preset(
    style_id: str,
    *,
    genre: str = "story",
    pacing: str = "medium",
    speaker_count: int = 1,
    tone: str = "neutral",
    visual_complexity: str = "medium",
    styles_path: Path = DEFAULT_STYLES_PATH,
) -> Dict[str, Any]:
    presets = load_caption_presets(styles_path)
    sid = (style_id or "C16").strip().upper()
    if sid not in presets:
        raise ValueError(f"Unknown caption style ID {style_id!r}. Valid IDs: {sorted(presets.keys())}")
    if sid == "C16" or presets[sid].get("adaptive_selector"):
        chosen_id = select_caption_style(
            genre=genre,
            pacing=pacing,
            speaker_count=speaker_count,
            tone=tone,
            visual_complexity=visual_complexity,
            styles_path=styles_path,
        )
        preset = dict(presets[chosen_id])
        preset["selected_via"] = "C16"
        return preset
    preset = dict(presets[sid])
    preset["selected_via"] = sid
    return preset


def escape_ass_text(text: str) -> str:
    """Escape ASS override braces and backslashes while preserving Unicode and punctuation."""
    s = text.replace("\\", r"\\")
    s = s.replace("{", r"\{").replace("}", r"\}")
    s = s.replace("\r\n", " ").replace("\n", " ").strip()
    return s


def _fmt_ass_cs(cs_total: int) -> str:
    cs_val = max(0, int(cs_total))
    h = cs_val // 360000
    rem = cs_val % 360000
    m = rem // 6000
    rem %= 6000
    s = rem // 100
    cs = rem % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fmt_ass_time(seconds: float) -> str:
    return _fmt_ass_cs(max(0, int(round(seconds * 100))))


@functools.lru_cache(maxsize=64)
def _resolve_system_font_path(fontname: str, bold: bool = False, italic: bool = False) -> Optional[str]:
    """Resolve the actual font file libass/fontconfig selects for accurate width measurement."""
    weight = "bold" if bold else "regular"
    slant = "italic" if italic else "roman"
    pattern = f"{fontname}:weight={weight}:slant={slant}"
    try:
        proc = subprocess.run(
            ["fc-match", "-f", "%{file}", pattern],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        candidate = (proc.stdout or "").strip()
        if proc.returncode == 0 and candidate and Path(candidate).is_file():
            return candidate
    except Exception:
        pass

    fallbacks = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    )
    for fb in fallbacks:
        if Path(fb).is_file():
            return fb
    return None


@functools.lru_cache(maxsize=128)
def _load_pil_font(font_path: str, fontsize: int):
    try:
        from PIL import ImageFont  # type: ignore

        return ImageFont.truetype(font_path, size=max(8, int(fontsize)))
    except Exception:
        return None


def _estimate_text_width_fallback(text: str, fontsize: int, bold: bool = False, outline: float = 0.0) -> float:
    """Conservative Unicode-aware glyph width estimate when PIL/TrueType metrics are unavailable."""
    scale = 1.08 if bold else 1.0
    total = 0.0
    for ch in text:
        if ch.isspace():
            total += fontsize * 0.30
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            total += fontsize * 1.10
        elif ch in "WM@#%&":
            total += fontsize * 0.85
        elif ch.isupper():
            total += fontsize * 0.72
        elif ch in "ilI1|!.,;:'`":
            total += fontsize * 0.36
        else:
            total += fontsize * 0.58
    return total * scale + (2.0 * max(0.0, float(outline)))


def measure_text_width_px(
    text: str,
    *,
    fontname: str = "DejaVu Sans",
    fontsize: int = 48,
    bold: bool = False,
    italic: bool = False,
    outline: float = 0.0,
) -> float:
    """Measure rendered horizontal pixel width for ASS text using system font metrics."""
    if not text:
        return 0.0
    # Unescape ASS literal sequences for visual width measurement
    visible = text.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
    font_path = _resolve_system_font_path(fontname, bold=bold, italic=italic)
    if font_path:
        font = _load_pil_font(font_path, fontsize)
        if font is not None:
            try:
                # libass renders ASS fontsize slightly wider than PIL nominal height; apply 1.08x safety factor
                raw_w = float(font.getlength(visible))
                return raw_w * 1.08 + (2.0 * max(0.0, float(outline)))
            except Exception:
                try:
                    bbox = font.getbbox(visible)
                    if bbox:
                        return float(bbox[2] - bbox[0]) * 1.08 + (2.0 * max(0.0, float(outline)))
                except Exception:
                    pass
    return _estimate_text_width_fallback(visible, fontsize=fontsize, bold=bold, outline=outline)


def _split_grapheme_clusters(text: str) -> List[str]:
    """Split text into user-perceived grapheme clusters (combining marks, ZWJ emojis, modifiers, ASS escapes)."""
    clusters: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        # Preserve ASS 2-char escapes (\{, \}, \) as indivisible units
        if text[i] == "\\" and i + 1 < n and text[i + 1] in ("{", "}", "\\"):
            clusters.append(text[i : i + 2])
            i += 2
            continue
        cluster = text[i]
        i += 1
        # Regional indicator flag pairs (two consecutive U+1F1E6..U+1F1FF)
        if 0x1F1E6 <= ord(cluster) <= 0x1F1FF and i < n and 0x1F1E6 <= ord(text[i]) <= 0x1F1FF:
            cluster += text[i]
            i += 1
        while i < n:
            ch = text[i]
            cp = ord(ch)
            cat = unicodedata.category(ch)
            if cat in ("Mn", "Mc", "Me") or cp in (0xFE0E, 0xFE0F) or (0x1F3FB <= cp <= 0x1F3FF):
                cluster += ch
                i += 1
            elif cp == 0x200D and i + 1 < n:
                # Zero-Width Joiner binds the following emoji base into the same grapheme cluster
                cluster += ch + text[i + 1]
                i += 2
            else:
                break
        clusters.append(cluster)
    return clusters


def _split_long_token(
    token: str,
    max_width_px: float,
    measure_fn: Callable[[str], float],
) -> List[str]:
    """Split a single overflowing token cleanly on grapheme boundaries so no piece exceeds max_width_px."""
    clusters = _split_grapheme_clusters(token)
    if measure_fn(token) <= max_width_px or len(clusters) <= 1:
        return [token]

    pieces: List[str] = []
    idx = 0
    total = len(clusters)
    while idx < total:
        rem_str = "".join(clusters[idx:])
        if measure_fn(rem_str) <= max_width_px:
            pieces.append(rem_str)
            break
        lo, hi = 1, total - idx
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = "".join(clusters[idx : idx + mid])
            if cand and measure_fn(cand) <= max_width_px:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        # Prefer natural separator near the end of the fitting grapheme slice
        chosen_end = idx + best
        for sep_idx in range(chosen_end - 1, max(idx + 1, idx + int(best * 0.4)) - 1, -1):
            if clusters[sep_idx] in ("-", "/", "_", "—"):
                chosen_end = sep_idx + 1
                break
        pieces.append("".join(clusters[idx:chosen_end]))
        idx = chosen_end
    return pieces

def _wrap_lines(
    text: str,
    max_chars: int,
    max_lines: int,
    *,
    max_width_px: Optional[float] = None,
    measure_fn: Optional[Callable[[str], float]] = None,
    first_line_prefix_px: float = 0.0,
) -> List[str]:
    """Wrap text strictly within rendered pixel width (or character budget fallback).

    Never concatenates overflowing lines into an unbounded tail line (D-MT05-02).
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return [text]

    if max_width_px is not None and measure_fn is not None:
        budget = max(40.0, float(max_width_px))
        first_budget = max(40.0, budget - max(0.0, float(first_line_prefix_px)))
        raw_tokens = cleaned.split(" ")
        lines: List[str] = []
        current = ""

        def _active_budget() -> float:
            return first_budget if len(lines) == 0 else budget

        for tok in raw_tokens:
            # Break unbreakable long tokens first if they cannot fit on an empty line
            sub_tokens = _split_long_token(tok, budget, measure_fn)
            for st in sub_tokens:
                lim = _active_budget()
                if not current:
                    if measure_fn(st) <= lim:
                        current = st
                    else:
                        # First line had a wide prefix; split to fit first line or start on next line
                        for piece in _split_long_token(st, lim, measure_fn):
                            if not current:
                                current = piece
                            else:
                                lines.append(current)
                                current = piece
                else:
                    candidate = f"{current} {st}"
                    if measure_fn(candidate) <= lim:
                        current = candidate
                    else:
                        lines.append(current)
                        current = st
        if current:
            lines.append(current)
        return lines or [cleaned]

    # Backward-compatible character-based fallback (still NEVER joins overflow into an unbounded tail)
    width_limit = max(10, int(max_chars))
    wrapped = textwrap.wrap(cleaned, width=width_limit, break_long_words=True, break_on_hyphens=True)
    return wrapped or [cleaned]


def _highlight_keywords(escaped_line: str, accent_colour: str, primary_colour: str) -> str:
    words = escaped_line.split(" ")
    if not words:
        return escaped_line
    # Pick up to 2 longest non-stopword tokens for accent highlight
    scored = []
    for idx, w in enumerate(words):
        clean = re.sub(r"[^A-Za-z0-9]", "", w).lower()
        if len(clean) >= 4 and clean not in EMPHASIS_STOPWORDS:
            scored.append((len(clean), idx))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chosen = {idx for _, idx in scored[:2]}
    out = []
    for idx, w in enumerate(words):
        if idx in chosen:
            out.append(f"{{\\c{accent_colour}}}{w}{{\\c{primary_colour}}}")
        else:
            out.append(w)
    return " ".join(out)


def _format_karaoke_lines(lines: List[str], duration_sec: float) -> str:
    all_words = [w for line in lines for w in line.split(" ") if w]
    if not all_words:
        return r"\N".join(lines)
    total_cs = max(10, int(round(duration_sec * 100)))
    per_word = max(5, total_cs // len(all_words))
    rendered_lines: List[str] = []
    for line in lines:
        parts = []
        for w in line.split(" "):
            if not w:
                continue
            parts.append(f"{{\\kf{per_word}}}{w}")
        rendered_lines.append(" ".join(parts))
    return r"\N".join(rendered_lines)


def _coalesce_short_cues(
    cues: Sequence[CaptionCue],
    *,
    min_duration_cs: int = MIN_PAGE_DURATION_CS,
    max_merge_gap_cs: int = 5,
) -> List[CaptionCue]:
    """Enforce minimum readable display duration (>= 0.25s) across all cues (D-RC9-01).

    If a cue is shorter than `min_duration_cs`, merge it with an immediately adjacent
    same-speaker cue ONLY when timing/synchronization permits (gap <= 0.05s) without
    inventing timeline duration or discarding dialogue. Otherwise raise CaptionRenderError.
    """
    validated: List[CaptionCue] = []
    for c in cues:
        c.validate()
        validated.append(
            CaptionCue(
                start_sec=float(c.start_sec),
                end_sec=float(c.end_sec),
                text=c.text.strip(),
                speaker=c.speaker.strip(),
            )
        )

    merged: List[CaptionCue] = []
    i = 0
    n = len(validated)
    while i < n:
        cur = validated[i]
        cur_st = max(0, int(round(cur.start_sec * 100)))
        cur_en = max(0, int(round(cur.end_sec * 100)))
        cur_dur = cur_en - cur_st
        if cur_dur <= 0:
            raise CaptionRenderError(
                f"Caption cue [{cur.start_sec:.3f}s -> {cur.end_sec:.3f}s] rounds to 0 centiseconds "
                "and cannot produce a readable ASS event."
            )
        if cur_dur >= min_duration_cs:
            merged.append(cur)
            i += 1
            continue

        # Attempt sync-preserving backward merge with previous same-speaker cue
        if merged:
            prev = merged[-1]
            prev_st = max(0, int(round(prev.start_sec * 100)))
            prev_en = max(0, int(round(prev.end_sec * 100)))
            gap_back = cur_st - prev_en
            if (
                prev.speaker == cur.speaker
                and 0 <= gap_back <= max_merge_gap_cs
                and (cur_en - prev_st) >= min_duration_cs
            ):
                merged[-1] = CaptionCue(
                    start_sec=prev.start_sec,
                    end_sec=cur.end_sec,
                    text=f"{prev.text} {cur.text}".strip(),
                    speaker=prev.speaker,
                )
                i += 1
                continue

        # Attempt sync-preserving forward merge with next same-speaker cue
        if i + 1 < n:
            nxt = validated[i + 1]
            nxt_st = max(0, int(round(nxt.start_sec * 100)))
            nxt_en = max(0, int(round(nxt.end_sec * 100)))
            gap_fwd = nxt_st - cur_en
            if (
                nxt.speaker == cur.speaker
                and 0 <= gap_fwd <= max_merge_gap_cs
                and (nxt_en - cur_st) >= min_duration_cs
            ):
                validated[i + 1] = CaptionCue(
                    start_sec=cur.start_sec,
                    end_sec=nxt.end_sec,
                    text=f"{cur.text} {nxt.text}".strip(),
                    speaker=cur.speaker,
                )
                i += 1
                continue

        raise CaptionRenderError(
            f"Caption cue [{cur.start_sec:.2f}s -> {cur.end_sec:.2f}s] (duration {cur_dur / 100.0:.2f}s) "
            f"is shorter than the minimum readable display duration ({min_duration_cs / 100.0:.2f}s) "
            "and cannot be merged with an adjacent same-speaker cue without breaking synchronization. "
            "Extend the cue timing in the source script/SRT."
        )

    return merged


def generate_ass_document(
    cues: Sequence[CaptionCue],
    *,
    style_id: str = "C16",
    width: int = 1080,
    height: int = 1920,
    genre: str = "story",
    pacing: str = "medium",
    tone: str = "neutral",
    visual_complexity: str = "medium",
    styles_path: Path = DEFAULT_STYLES_PATH,
) -> Dict[str, Any]:
    """Generate a complete ASS subtitle document for the selected preset (C01-C16)."""
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid video dimensions: {width}x{height}")

    speakers = sorted({c.speaker.strip() for c in cues if c.speaker and c.speaker.strip()})
    preset = resolve_preset(
        style_id,
        genre=genre,
        pacing=pacing,
        speaker_count=max(1, len(speakers)),
        tone=tone,
        visual_complexity=visual_complexity,
        styles_path=styles_path,
    )

    # Dynamic scaling for both 9:16 vertical and 16:9 horizontal
    ref_dim = max(width, height)
    fontsize = max(24, int(round(ref_dim * float(preset["font_size_ratio"]))))
    if width > height:
        # Landscape 16:9 needs slightly larger horizontal wrap width and tighter vertical margin
        max_chars = int(round(int(preset["max_chars_per_line"]) * 1.45))
        margin_v = max(40, int(round(height * float(preset["margin_v_ratio"]) * 0.75)))
    else:
        max_chars = int(preset["max_chars_per_line"])
        margin_v = max(60, int(round(height * float(preset["margin_v_ratio"]))))
    # Enforce safe horizontal margins (>= 6% on both left & right edges for 9:16 and 16:9)
    margin_lr = max(24, int(round(width * max(float(preset["margin_lr_ratio"]), 0.06))))

    effect = preset.get("effect", "none")
    is_bold = int(preset.get("bold", 0)) != 0
    is_italic = int(preset.get("italic", 0)) != 0
    outline_px = float(preset.get("outline", 0.0))
    headroom = 0.80 if effect == "bounce_pop" else 0.88
    safe_text_width_px = max(60.0, (float(width) - 2.0 * float(margin_lr)) * headroom)

    def _measure(s: str) -> float:
        return measure_text_width_px(
            s,
            fontname=str(preset["fontname"]),
            fontsize=fontsize,
            bold=is_bold,
            italic=is_italic,
            outline=outline_px,
        )

    style_line = (
        f"Style: Active,{preset['fontname']},{fontsize},"
        f"{preset['primary_colour']},{preset['secondary_colour']},"
        f"{preset['outline_colour']},{preset['back_colour']},"
        f"{preset['bold']},{preset['italic']},0,0,100,100,0,0,"
        f"{preset['border_style']},{preset['outline']},{preset['shadow']},"
        f"{preset['alignment']},{margin_lr},{margin_lr},{margin_v},1"
    )

    header = "\n".join(
        [
            "[Script Info]",
            f"; Roblox Town Director Caption Style {preset['id']} ({preset['name']})",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            style_line,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    speaker_color_map = {
        sp: SPEAKER_COLOR_PALETTE[i % len(SPEAKER_COLOR_PALETTE)]
        for i, sp in enumerate(speakers)
    }

    max_lines_per_page = max(1, int(preset.get("max_lines", 2)))
    effective_cues = _coalesce_short_cues(cues)
    events: List[str] = []
    max_rendered_line_px = 0.0

    for cue in effective_cues:
        cue.validate()
        raw_text = cue.text.strip()
        if preset.get("uppercase"):
            raw_text = raw_text.upper()
        esc_text = escape_ass_text(raw_text)

        # Measure speaker prefix width so line 1 never overflows past safe margins
        first_prefix_px = 0.0
        badge_on_own_line = False
        sp_prefix_visible = ""
        if effect == "speaker_badge" and cue.speaker:
            sp_prefix_visible = f"[{cue.speaker.upper()}] "
            first_prefix_px = _measure(sp_prefix_visible)
            if first_prefix_px > safe_text_width_px * 0.45:
                badge_on_own_line = True
                first_prefix_px = 0.0
        elif effect == "color_coded_speaker" and cue.speaker:
            sp_prefix_visible = f"{cue.speaker.strip()}: "
            first_prefix_px = _measure(sp_prefix_visible)
            if first_prefix_px > safe_text_width_px * 0.45:
                badge_on_own_line = True
                first_prefix_px = 0.0

        start_cs = max(0, int(round(float(cue.start_sec) * 100)))
        end_cs = max(0, int(round(float(cue.end_sec) * 100)))
        total_cs = end_cs - start_cs
        if total_cs <= 0:
            raise CaptionRenderError(
                f"Caption cue [{cue.start_sec:.3f}s -> {cue.end_sec:.3f}s] rounds to 0 centiseconds "
                "and cannot produce a non-zero-duration ASS event."
            )

        max_readable_pages = total_cs // MIN_PAGE_DURATION_CS
        if max_readable_pages < 1:
            raise CaptionRenderError(
                f"Caption cue [{cue.start_sec:.2f}s -> {cue.end_sec:.2f}s] (duration {total_cs / 100.0:.2f}s) "
                f"is shorter than minimum readable duration ({MIN_PAGE_DURATION_SEC:.2f}s)."
            )

        def _layout_for_fontsize(fs: int, lines_per_page: int) -> Tuple[List[List[str]], float, bool, Callable[[str], float]]:
            def _m(s: str) -> float:
                return measure_text_width_px(
                    s,
                    fontname=str(preset["fontname"]),
                    fontsize=fs,
                    bold=is_bold,
                    italic=is_italic,
                    outline=outline_px,
                )
            p_px = 0.0
            own_ln = False
            if sp_prefix_visible:
                p_px = _m(sp_prefix_visible)
                if p_px > safe_text_width_px * 0.45:
                    own_ln = True
                    p_px = 0.0
            wrapped = _wrap_lines(
                esc_text,
                max_chars=max_chars,
                max_lines=lines_per_page,
                max_width_px=safe_text_width_px,
                measure_fn=_m,
                first_line_prefix_px=p_px,
            )
            pgs = [wrapped[i : i + lines_per_page] for i in range(0, len(wrapped), lines_per_page)]
            return pgs, p_px, own_ln, _m

        # Primary layout at preset's native fontsize & max_lines
        active_fontsize = fontsize
        pages, first_prefix_px, badge_on_own_line, active_measure = _layout_for_fontsize(
            fontsize, max_lines_per_page
        )

        # D-RC8-01 safe fallback: if cue duration cannot accommodate required pages at >= MIN_PAGE_DURATION_SEC,
        # try compacting with reduced local \fs (never discarding text or inventing timeline duration).
        if len(pages) > max_readable_pages:
            min_fs = max(16, int(round(fontsize * 0.55)))
            fallback_candidates = [
                (max(min_fs, int(round(fontsize * 0.85))), max_lines_per_page + 1),
                (max(min_fs, int(round(fontsize * 0.72))), max_lines_per_page + 2),
                (min_fs, max_lines_per_page + 2),
            ]
            for cand_fs, cand_lines in fallback_candidates:
                cand_pages, cand_pfx, cand_own, cand_m = _layout_for_fontsize(cand_fs, cand_lines)
                if len(cand_pages) <= max_readable_pages:
                    active_fontsize = cand_fs
                    pages, first_prefix_px, badge_on_own_line, active_measure = (
                        cand_pages, cand_pfx, cand_own, cand_m
                    )
                    break

        if len(pages) > max_readable_pages:
            raise CaptionRenderError(
                f"Caption cue [{cue.start_sec:.2f}s -> {cue.end_sec:.2f}s] (duration {total_cs / 100.0:.2f}s) "
                f"requires {len(pages)} page(s) to fit inside safe margins, exceeding the maximum "
                f"{max_readable_pages} readable page(s) allowed at minimum {MIN_PAGE_DURATION_SEC:.2f}s/page. "
                "Extend cue duration or split the dialogue text across multiple cues."
            )

        # Integer centisecond allocation: guarantees every page has >= MIN_PAGE_DURATION_CS (when >1 page),
        # exact sum == total_cs, exact [start_cs, end_cs] bounds, and ZERO zero-duration events.
        num_pages = len(pages)
        if num_pages == 1:
            page_cs_spans = [(start_cs, end_cs)]
        else:
            base_cs = MIN_PAGE_DURATION_CS
            extra_cs = total_cs - (num_pages * base_cs)
            weights = [max(1, sum(len(ln) for ln in pg)) for pg in pages]
            w_sum = sum(weights)
            allocs = [base_cs + (extra_cs * w) // w_sum for w in weights]
            remainder = total_cs - sum(allocs)
            for r_i in range(remainder):
                allocs[r_i % num_pages] += 1
            page_cs_spans = []
            cur_cs = start_cs
            for dur_cs in allocs:
                page_cs_spans.append((cur_cs, cur_cs + dur_cs))
                cur_cs += dur_cs

        for p_idx, (page_lines, (p_start_cs, p_end_cs)) in enumerate(zip(pages, page_cs_spans)):
            for l_idx, ln in enumerate(page_lines):
                extra = first_prefix_px if (p_idx == 0 and l_idx == 0 and not badge_on_own_line) else 0.0
                max_rendered_line_px = max(max_rendered_line_px, active_measure(ln) + extra)

            fs_tag = f"{{\\fs{active_fontsize}}}" if active_fontsize != fontsize else ""
            prefix_tags = fs_tag
            if effect == "pop_in":
                prefix_tags += r"{\fscx85\fscy85\t(0,110,\fscx100\fscy100)}"
            elif effect == "bounce_pop":
                prefix_tags += r"{\fscx75\fscy75\t(0,90,\fscx108\fscy108)\t(90,170,\fscx100\fscy100)}"
            elif effect == "fade":
                prefix_tags += r"{\fad(120,120)}"
            elif effect == "slow_fade":
                prefix_tags += r"{\fad(240,240)}"

            p_dur_sec = max(0.01, (p_end_cs - p_start_cs) / 100.0)
            if effect == "karaoke":
                body = _format_karaoke_lines(page_lines, p_dur_sec)
            elif effect == "keyword_highlight":
                hl_lines = [
                    _highlight_keywords(ln, preset["secondary_colour"], preset["primary_colour"])
                    for ln in page_lines
                ]
                body = r"\N".join(hl_lines)
            elif effect == "speaker_badge" and cue.speaker:
                sp_esc = escape_ass_text(cue.speaker.upper())
                badge = f"{{\\c{preset['secondary_colour']}}}[{sp_esc}]{{\\c{preset['primary_colour']}}}"
                sep = r"\N" if badge_on_own_line else " "
                body = (badge + sep + r"\N".join(page_lines)) if p_idx == 0 else r"\N".join(page_lines)
            elif effect == "color_coded_speaker" and cue.speaker:
                sp_col = speaker_color_map.get(cue.speaker.strip(), preset["primary_colour"])
                sp_esc = escape_ass_text(cue.speaker.strip())
                prefix_tags = fs_tag + f"{{\\c{sp_col}}}"
                sep = r"\N" if badge_on_own_line else " "
                body = (f"{sp_esc}:{sep}" + r"\N".join(page_lines)) if p_idx == 0 else r"\N".join(page_lines)
            else:
                body = r"\N".join(page_lines)

            speaker_name = escape_ass_text(cue.speaker) if cue.speaker else ""
            events.append(
                f"Dialogue: 0,{_fmt_ass_cs(p_start_cs)},{_fmt_ass_cs(p_end_cs)},"
                f"Active,{speaker_name},0,0,0,,{prefix_tags}{body}"
            )


    ass_content = header + "\n" + "\n".join(events) + "\n"
    return {
        "preset_id": preset["id"],
        "preset_name": preset["name"],
        "selected_via": preset["selected_via"],
        "width": width,
        "height": height,
        "fontsize": fontsize,
        "margin_lr": margin_lr,
        "safe_text_width_px": round(safe_text_width_px, 2),
        "max_rendered_line_px": round(max_rendered_line_px, 2),
        "cue_count": len(events),
        "source_cue_count": len(cues),
        "ass_content": ass_content,
    }


def parse_srt_to_cues(srt_path: Path) -> List[CaptionCue]:
    """Parse a standard SRT file into CaptionCue objects (extracting `Speaker: text` if present)."""
    raw = Path(srt_path).read_text(encoding="utf-8")
    blocks = re.split(r"\r?\n\r?\n+", raw.strip())
    time_re = re.compile(
        r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
    )
    cues: List[CaptionCue] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        tm = None
        text_start_idx = 0
        for idx, ln in enumerate(lines):
            m = time_re.match(ln)
            if m:
                tm = m
                text_start_idx = idx + 1
                break
        if tm is None or text_start_idx >= len(lines):
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in tm.groups())
        start_sec = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end_sec = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        joined = " ".join(lines[text_start_idx:]).strip()
        speaker = ""
        text = joined
        sp_match = re.match(r"^([A-Za-z][A-Za-z0-9 _.-]{0,30}):\s*(.+)$", joined)
        if sp_match:
            speaker = sp_match.group(1).strip()
            text = sp_match.group(2).strip()
        cues.append(CaptionCue(start_sec=start_sec, end_sec=end_sec, text=text, speaker=speaker))
    return cues


def render_ass_captions_onto_video(
    *,
    video_path: Path,
    ass_path: Path,
    output_video_path: Path,
    timeout_sec: float = 300.0,
) -> Dict[str, Any]:
    """Burn an ASS subtitle file onto a video via FFmpeg while preserving FPS and audio."""
    v_path = Path(video_path)
    a_path = Path(ass_path)
    out_path = Path(output_video_path)
    if not v_path.exists():
        raise CaptionRenderError(f"Source video does not exist: {v_path}")
    if not a_path.exists() or a_path.stat().st_size == 0:
        raise CaptionRenderError(f"ASS subtitle file missing or empty: {a_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Escape path characters for FFmpeg filtergraph
    escaped_ass = str(a_path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-i",
        str(v_path),
        "-vf",
        f"ass='{escaped_ass}'",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(out_path),
    ]
    try:
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False, timeout=timeout_sec)
    except FileNotFoundError as exc:
        out_path.unlink(missing_ok=True)
        raise CaptionRenderError("Required binary 'ffmpeg' not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        out_path.unlink(missing_ok=True)
        raise CaptionRenderError(f"FFmpeg caption burn-in timed out after {timeout_sec}s.") from exc

    if res.returncode != 0 or not out_path.exists():
        out_path.unlink(missing_ok=True)
        raise CaptionRenderError(f"FFmpeg caption burn-in failed: {res.stderr.strip()}")

    return {
        "output_video_path": str(out_path),
        "ass_path": str(a_path),
        "bytes_written": out_path.stat().st_size,
    }
