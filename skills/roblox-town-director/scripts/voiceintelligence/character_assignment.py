#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Automatic Character Voice Assignment for Roblox Town Director.

Reads scripts, identifies speaking characters, matches or assigns persistent
VoiceProfiles, preserves assignments across scenes, and refuses silent voice
substitution when an assigned voice becomes unavailable.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .profile_manager import VoiceProfile, VoiceProfileManager, utc_now_iso

SCENE_HEADER_RE = re.compile(r"^\[?(?:SCENE|S)\s*0*(\d+)\]?\b", re.IGNORECASE)
DIALOGUE_LINE_RE = re.compile(
    r"^(?:\[(?P<scene>S\d+)\]\s*)?"
    r"(?P<speaker>[A-Za-z][A-Za-z0-9 _.-]{0,40}?)"
    r"(?:\s*\((?P<cue>[^)]+)\))?\s*:\s*(?P<text>.+)$"
)


class VoiceUnavailableError(RuntimeError):
    """Raised when an assigned voice profile is unavailable and no approved fallback is provided."""

    def __init__(self, character_id: str, voice_id: str, reason: str, suggested_fallbacks: List[str]):
        super().__init__(
            f"Assigned voice {voice_id!r} for character {character_id!r} is unavailable ({reason}). "
            f"Silent substitution is prohibited; approve a fallback from: {suggested_fallbacks}"
        )
        self.character_id = character_id
        self.voice_id = voice_id
        self.reason = reason
        self.suggested_fallbacks = suggested_fallbacks


def normalize_character_id(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return cleaned or "speaker"


@dataclass
class DialogueSegment:
    scene_id: str
    line_id: str
    character_id: str
    display_name: str
    text: str
    delivery_cue: str = ""
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None


def parse_script_dialogue(
    script_text: str,
    *,
    default_scene_id: str = "S01",
) -> List[DialogueSegment]:
    """Parse plain-text or Markdown script lines into structured DialogueSegments."""
    segments: List[DialogueSegment] = []
    current_scene = default_scene_id
    per_scene_counter: Dict[str, int] = {}

    for raw_line in script_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            # Still detect scene headers inside markdown headings
            stripped_heading = line.lstrip("# ").strip()
            scene_match = SCENE_HEADER_RE.match(stripped_heading)
            if scene_match:
                current_scene = f"S{int(scene_match.group(1)):02d}"
            continue

        scene_match = SCENE_HEADER_RE.match(line)
        if scene_match and ":" not in line:
            current_scene = f"S{int(scene_match.group(1)):02d}"
            continue

        match = DIALOGUE_LINE_RE.match(line)
        if not match:
            continue

        scene_id = (match.group("scene") or current_scene).upper()
        speaker = match.group("speaker").strip()
        cue = (match.group("cue") or "").strip()
        text = match.group("text").strip().strip('"')
        if not text:
            continue

        per_scene_counter[scene_id] = per_scene_counter.get(scene_id, 0) + 1
        line_num = per_scene_counter[scene_id]
        segments.append(
            DialogueSegment(
                scene_id=scene_id,
                line_id=f"{scene_id}_L{line_num:02d}",
                character_id=normalize_character_id(speaker),
                display_name=speaker,
                text=text,
                delivery_cue=cue,
            )
        )
    return segments


class CharacterVoiceAssigner:
    """Assigns and persists character-to-voice mappings across scenes without silent substitution."""

    def __init__(self, profile_manager: VoiceProfileManager):
        self.profile_manager = profile_manager

    def _score_profile_match(
        self,
        character_id: str,
        display_name: str,
        description: str,
        profile: VoiceProfile,
    ) -> int:
        score = 0
        char_tokens = set(re.findall(r"[a-z0-9]+", f"{character_id} {display_name} {description}".lower()))
        if profile.intended_character and normalize_character_id(profile.intended_character) == character_id:
            score += 100
        role_text = " ".join(profile.intended_roles + [profile.display_name, str(profile.characteristics)])
        role_tokens = set(re.findall(r"[a-z0-9]+", role_text.lower()))
        overlap = char_tokens & role_tokens
        score += len(overlap) * 10
        if "narrator" in char_tokens and profile.voice_id == "V01":
            score += 50
        return score

    def assign_characters(
        self,
        segments: List[DialogueSegment],
        *,
        existing_state: Optional[Dict[str, Any]] = None,
        character_descriptions: Optional[Dict[str, str]] = None,
        explicit_assignments: Optional[Dict[str, str]] = None,
        approved_fallbacks: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        """Resolve voice assignments for all speaking characters in segments.

        Returns `(character_voice_map, blockers)`.
        Never silently substitutes an unavailable voice; emits a blocker unless
        `approved_fallbacks` explicitly supplies an available replacement voice_id.
        """
        descriptions = character_descriptions or {}
        explicit = explicit_assignments or {}
        fallbacks = approved_fallbacks or {}

        state_map: Dict[str, Dict[str, Any]] = {}
        if existing_state:
            for item in existing_state.get("character_voice_map", []):
                state_map[item["character_id"]] = dict(item)

        available_profiles = self.profile_manager.list_profiles(only_available=True)
        available_ids = [p.voice_id for p in available_profiles]
        used_voice_ids = {
            item["voice_id"]
            for item in state_map.values()
            if item.get("voice_id") in available_ids
        }

        blockers: List[Dict[str, Any]] = []
        seen_characters: Dict[str, str] = {}
        for seg in segments:
            seen_characters.setdefault(seg.character_id, seg.display_name)

        for char_id, display_name in seen_characters.items():
            # 1. Explicit assignment override or existing persisted lock
            locked_vid = explicit.get(char_id) or (state_map.get(char_id, {}).get("voice_id"))
            if locked_vid:
                profile = self.profile_manager.get_profile(locked_vid)
                if profile is not None and profile.availability_status == "available":
                    state_map[char_id] = {
                        "character_id": char_id,
                        "display_name": display_name,
                        "voice_id": profile.voice_id,
                        "provider": profile.provider,
                        "provider_voice_id": profile.provider_voice_id,
                        "lock_scope": state_map.get(char_id, {}).get("lock_scope", "project_wide"),
                        "assignment_source": "explicit" if char_id in explicit else "persisted_lock",
                        "assigned_at": state_map.get(char_id, {}).get("assigned_at") or utc_now_iso(),
                    }
                    used_voice_ids.add(profile.voice_id)
                    continue

                # Assigned voice is missing, disabled, or unavailable -> check approved fallback
                reason = (
                    "profile not found"
                    if profile is None
                    else f"availability_status={profile.availability_status}, consent_status={profile.consent_status}"
                )
                fallback_vid = fallbacks.get(char_id)
                if fallback_vid:
                    fb_profile = self.profile_manager.get_profile(fallback_vid)
                    if fb_profile is not None and fb_profile.availability_status == "available":
                        state_map[char_id] = {
                            "character_id": char_id,
                            "display_name": display_name,
                            "voice_id": fb_profile.voice_id,
                            "provider": fb_profile.provider,
                            "provider_voice_id": fb_profile.provider_voice_id,
                            "lock_scope": "approved_fallback",
                            "assignment_source": "approved_fallback",
                            "replaced_unavailable_voice_id": locked_vid,
                            "assigned_at": utc_now_iso(),
                        }
                        used_voice_ids.add(fb_profile.voice_id)
                        continue

                # Never silently substitute!
                blockers.append(
                    {
                        "type": "voice_unavailable",
                        "character_id": char_id,
                        "display_name": display_name,
                        "locked_voice_id": locked_vid,
                        "reason": reason,
                        "suggested_fallbacks": [vid for vid in available_ids if vid not in used_voice_ids] or available_ids,
                        "action_required": "User approval required to assign a fallback voice profile.",
                    }
                )
                continue

            # 2. Automatic matching for unassigned characters
            desc = descriptions.get(char_id, "")
            unused_candidates = [p for p in available_profiles if p.voice_id not in used_voice_ids]
            candidates = unused_candidates or available_profiles
            if not candidates:
                blockers.append(
                    {
                        "type": "no_available_voices",
                        "character_id": char_id,
                        "display_name": display_name,
                        "reason": "No available voice profiles exist in VoiceProfileManager.",
                        "suggested_fallbacks": [],
                        "action_required": "Create, design, or enable at least one voice profile.",
                    }
                )
                continue

            ranked = sorted(
                candidates,
                key=lambda p: (-self._score_profile_match(char_id, display_name, desc, p), p.voice_id),
            )
            chosen = ranked[0]
            used_voice_ids.add(chosen.voice_id)
            state_map[char_id] = {
                "character_id": char_id,
                "display_name": display_name,
                "voice_id": chosen.voice_id,
                "provider": chosen.provider,
                "provider_voice_id": chosen.provider_voice_id,
                "lock_scope": "project_wide",
                "assignment_source": "auto_matched",
                "assigned_at": utc_now_iso(),
            }

        return state_map, blockers


def persist_project_voice_state(state_path: Path, state: Dict[str, Any]) -> None:
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".project_voice_state_", suffix=".tmp", dir=str(state_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(state, indent=2) + "\n")
        os.replace(tmp_name, state_path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def load_project_voice_state(state_path: Path) -> Dict[str, Any]:
    state_path = Path(state_path)
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))
