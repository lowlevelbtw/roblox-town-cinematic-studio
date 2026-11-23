#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Modular Voice Profile Manager for Roblox Town Director.

Manages permanent internal voice IDs (V01-V06 and custom roles), provider
bindings, consent/authorization records, availability status, and JSON
persistence without storing secrets or private audio binaries.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_VOICE_TYPES = (
    "original_synthetic",
    "authorized_cloned",
    "recorded_human",
)

VALID_CONSENT_STATUSES = (
    "not_required_synthetic",
    "self_attested_unverified",
    "pending_independent_verification",
    "verified_authorized",
    "pending_authorization",
    "revoked",
    "rejected_unauthorized",
)

VALID_AVAILABILITY_STATUSES = (
    "available",
    "unavailable",
    "disabled",
    "unverified",
)

VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,31}$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class VoiceProfile:
    voice_id: str
    display_name: str
    voice_type: str
    provider: str
    provider_voice_id: Optional[str] = None
    language: str = "en"
    accent: str = "neutral"
    characteristics: Dict[str, Any] = field(default_factory=dict)
    intended_character: Optional[str] = None
    intended_roles: List[str] = field(default_factory=list)
    audio_format: Dict[str, Any] = field(
        default_factory=lambda: {
            "container": "wav",
            "sample_rate_hz": 48000,
            "channels": 1,
        }
    )
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    consent_status: str = "not_required_synthetic"
    consent_record: Dict[str, Any] = field(default_factory=dict)
    availability_status: str = "available"
    notes: str = ""

    def validate(self) -> None:
        if not self.voice_id or not VOICE_ID_PATTERN.match(self.voice_id):
            raise ValueError(f"Invalid voice_id: {self.voice_id!r}")
        if not self.display_name or not self.display_name.strip():
            raise ValueError("display_name must be non-empty.")
        if self.voice_type not in VALID_VOICE_TYPES:
            raise ValueError(
                f"Invalid voice_type {self.voice_type!r}. Expected one of {VALID_VOICE_TYPES}."
            )
        if not self.provider or not self.provider.strip():
            raise ValueError("provider must be non-empty.")
        if self.consent_status not in VALID_CONSENT_STATUSES:
            raise ValueError(
                f"Invalid consent_status {self.consent_status!r}. Expected one of {VALID_CONSENT_STATUSES}."
            )
        if self.availability_status not in VALID_AVAILABILITY_STATUSES:
            raise ValueError(
                f"Invalid availability_status {self.availability_status!r}. "
                f"Expected one of {VALID_AVAILABILITY_STATUSES}."
            )
        if self.voice_type == "authorized_cloned":
            indep = bool(self.consent_record.get("independent_identity_verified", False))
            if self.consent_status == "verified_authorized" and not indep:
                raise ValueError(
                    "Self-attestation cannot be recorded as consent_status='verified_authorized' "
                    "when independent_identity_verified is False."
                )
            if self.availability_status == "available" and (self.consent_status != "verified_authorized" or not indep):
                raise ValueError(
                    "An authorized_cloned voice profile cannot be marked available without "
                    "independent identity, age, and authorization verification."
                )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoiceProfile":
        profile = cls(
            voice_id=str(data["voice_id"]),
            display_name=str(data["display_name"]),
            voice_type=str(data["voice_type"]),
            provider=str(data["provider"]),
            provider_voice_id=data.get("provider_voice_id"),
            language=str(data.get("language", "en")),
            accent=str(data.get("accent", "neutral")),
            characteristics=dict(data.get("characteristics", {})),
            intended_character=data.get("intended_character"),
            intended_roles=list(data.get("intended_roles", [])),
            audio_format=dict(
                data.get(
                    "audio_format",
                    {"container": "wav", "sample_rate_hz": 48000, "channels": 1},
                )
            ),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            consent_status=str(data.get("consent_status", "not_required_synthetic")),
            consent_record=dict(data.get("consent_record", {})),
            availability_status=str(data.get("availability_status", "available")),
            notes=str(data.get("notes", "")),
        )
        profile.validate()
        return profile


class VoiceProfileManager:
    """Persists and queries voice profiles in a local JSON store."""

    SCHEMA_VERSION = "1.1.0"

    def __init__(self, store_path: Path):
        self.store_path = Path(store_path)
        self._profiles: Dict[str, VoiceProfile] = {}
        if self.store_path.exists():
            self.load()

    def load(self) -> None:
        raw = json.loads(self.store_path.read_text(encoding="utf-8"))
        profiles_list = raw.get("profiles", [])
        loaded: Dict[str, VoiceProfile] = {}
        for entry in profiles_list:
            profile = VoiceProfile.from_dict(entry)
            loaded[profile.voice_id] = profile
        self._profiles = loaded

    def save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "profiles": [
                self._profiles[vid].to_dict() for vid in sorted(self._profiles.keys())
            ],
        }
        fd, tmp_name = tempfile.mkstemp(prefix=".voice_profiles_", suffix=".tmp", dir=str(self.store_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, indent=2) + "\n")
            os.replace(tmp_name, self.store_path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def create_profile(self, profile: VoiceProfile, overwrite: bool = False) -> VoiceProfile:
        profile.validate()
        if profile.voice_id in self._profiles and not overwrite:
            raise ValueError(f"Voice profile {profile.voice_id!r} already exists.")
        now = utc_now_iso()
        if not profile.created_at:
            profile.created_at = now
        profile.updated_at = now
        self._profiles[profile.voice_id] = profile
        self.save()
        return profile

    def get_profile(self, voice_id: str) -> Optional[VoiceProfile]:
        return self._profiles.get(voice_id)

    def require_profile(self, voice_id: str) -> VoiceProfile:
        profile = self._profiles.get(voice_id)
        if profile is None:
            raise KeyError(f"Voice profile not found: {voice_id!r}")
        return profile

    def list_profiles(
        self,
        *,
        provider: Optional[str] = None,
        voice_type: Optional[str] = None,
        only_available: bool = False,
    ) -> List[VoiceProfile]:
        result: List[VoiceProfile] = []
        for vid in sorted(self._profiles.keys()):
            prof = self._profiles[vid]
            if provider is not None and prof.provider != provider:
                continue
            if voice_type is not None and prof.voice_type != voice_type:
                continue
            if only_available and prof.availability_status != "available":
                continue
            result.append(prof)
        return result

    def update_profile(self, voice_id: str, **updates: Any) -> VoiceProfile:
        profile = self.require_profile(voice_id)
        data = profile.to_dict()
        for key, value in updates.items():
            if key not in data:
                raise ValueError(f"Unknown VoiceProfile field: {key!r}")
            data[key] = value
        data["updated_at"] = utc_now_iso()
        updated = VoiceProfile.from_dict(data)
        self._profiles[voice_id] = updated
        self.save()
        return updated

    def disable_profile(self, voice_id: str, reason: str = "") -> VoiceProfile:
        profile = self.require_profile(voice_id)
        note = profile.notes
        if reason:
            note = f"{note}\nDisabled: {reason}".strip()
        return self.update_profile(
            voice_id,
            availability_status="disabled",
            notes=note,
        )

    def revoke_cloned_consent(self, voice_id: str, reason: str = "User revoked consent") -> VoiceProfile:
        profile = self.require_profile(voice_id)
        consent_record = dict(profile.consent_record)
        consent_record["revoked_at"] = utc_now_iso()
        consent_record["revocation_reason"] = reason
        return self.update_profile(
            voice_id,
            consent_status="revoked",
            availability_status="disabled",
            consent_record=consent_record,
        )

    def remove_profile(self, voice_id: str) -> VoiceProfile:
        profile = self.require_profile(voice_id)
        del self._profiles[voice_id]
        self.save()
        return profile

    def migrate_provider(
        self,
        *,
        from_provider: str,
        to_provider: str,
        voice_id_mapping: Dict[str, str],
        project_state_path: Optional[Path] = None,
        voice_ids: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Migrate voice profiles from one provider to another with validation, rollback,
        and preservation of internal voice IDs and project dialogue assignments (D-MT04-01).
        """
        src_prov = str(from_provider or "").strip()
        dst_prov = str(to_provider or "").strip()
        if not src_prov or not dst_prov:
            raise ValueError("Both from_provider and to_provider must be non-empty strings.")
        if src_prov == dst_prov:
            raise ValueError(f"from_provider and to_provider must differ (both {src_prov!r}).")
        if not isinstance(voice_id_mapping, dict) or not voice_id_mapping:
            raise ValueError("voice_id_mapping must be a non-empty dict mapping voice_id/old_provider_voice_id -> new_provider_voice_id.")

        if voice_ids is not None:
            targets = [self.require_profile(vid) for vid in voice_ids]
            mismatched = [p.voice_id for p in targets if p.provider != src_prov]
            if mismatched:
                raise ValueError(
                    f"Specified voice_ids do not belong to from_provider={src_prov!r}: {mismatched}"
                )
        else:
            targets = [p for p in self.list_profiles(provider=src_prov)]

        if not targets:
            raise ValueError(f"No voice profiles found for from_provider={src_prov!r}.")

        # Phase 1: Pre-flight validation in memory (zero mutations yet)
        now = utc_now_iso()
        staged_profiles: Dict[str, VoiceProfile] = {}
        migrated_records: List[Dict[str, Any]] = []
        for prof in targets:
            mapped_id = voice_id_mapping.get(prof.voice_id)
            if mapped_id is None and prof.provider_voice_id:
                mapped_id = voice_id_mapping.get(prof.provider_voice_id)
            mapped_str = str(mapped_id or "").strip()
            if not mapped_str:
                raise ValueError(
                    f"Missing or empty target provider_voice_id mapping for internal voice_id={prof.voice_id!r} "
                    f"(old provider_voice_id={prof.provider_voice_id!r})."
                )
            updated_data = prof.to_dict()
            updated_data["provider"] = dst_prov
            updated_data["provider_voice_id"] = mapped_str
            updated_data["updated_at"] = now
            note_line = f"Migrated provider {src_prov} -> {dst_prov} ({prof.provider_voice_id} -> {mapped_str}) at {now}"
            updated_data["notes"] = f"{prof.notes}\n{note_line}".strip()
            validated_prof = VoiceProfile.from_dict(updated_data)
            staged_profiles[prof.voice_id] = validated_prof
            migrated_records.append(
                {
                    "voice_id": prof.voice_id,
                    "from_provider": src_prov,
                    "to_provider": dst_prov,
                    "old_provider_voice_id": prof.provider_voice_id,
                    "new_provider_voice_id": mapped_str,
                }
            )

        # Validate optional project state file in memory
        state_path_obj: Optional[Path] = Path(project_state_path) if project_state_path is not None else None
        original_state_bytes: Optional[bytes] = None
        updated_state_payload: Optional[Dict[str, Any]] = None
        preserved_assignments: List[Dict[str, Any]] = []

        if state_path_obj is not None and state_path_obj.exists():
            original_state_bytes = state_path_obj.read_bytes()
            raw_state = json.loads(original_state_bytes.decode("utf-8"))
            if not isinstance(raw_state, dict):
                raise ValueError(f"Invalid project voice state JSON in {state_path_obj}.")
            new_char_map = []
            for entry in raw_state.get("character_voice_map", []):
                item = dict(entry)
                vid = item.get("voice_id")
                if vid in staged_profiles:
                    item["provider"] = dst_prov
                    item["provider_voice_id"] = staged_profiles[vid].provider_voice_id
                new_char_map.append(item)
                preserved_assignments.append(
                    {
                        "character_id": item.get("character_id"),
                        "voice_id": item.get("voice_id"),
                        "provider": item.get("provider"),
                        "provider_voice_id": item.get("provider_voice_id"),
                    }
                )
            updated_state_payload = dict(raw_state)
            updated_state_payload["character_voice_map"] = new_char_map
            updated_state_payload["updated_at"] = now
            history = list(updated_state_payload.get("migration_history", []))
            history.append(
                {
                    "migrated_at": now,
                    "from_provider": src_prov,
                    "to_provider": dst_prov,
                    "migrated_voice_ids": sorted(staged_profiles.keys()),
                }
            )
            updated_state_payload["migration_history"] = history

        if dry_run:
            return {
                "dry_run": True,
                "rolled_back": False,
                "from_provider": src_prov,
                "to_provider": dst_prov,
                "migrated_count": len(migrated_records),
                "migrated_voices": migrated_records,
                "project_state_updated": updated_state_payload is not None,
                "preserved_character_assignments": preserved_assignments,
            }

        # Phase 2: Snapshot & atomic persist with automatic rollback on any write failure
        original_profiles_snapshot = {vid: VoiceProfile.from_dict(p.to_dict()) for vid, p in self._profiles.items()}
        original_store_bytes: Optional[bytes] = self.store_path.read_bytes() if self.store_path.exists() else None

        try:
            for vid, prof in staged_profiles.items():
                self._profiles[vid] = prof
            self.save()

            if state_path_obj is not None and updated_state_payload is not None:
                state_path_obj.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_state = tempfile.mkstemp(
                    prefix=".project_voice_state_",
                    suffix=".tmp",
                    dir=str(state_path_obj.parent),
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(json.dumps(updated_state_payload, indent=2) + "\n")
                    os.replace(tmp_state, state_path_obj)
                except Exception:
                    if os.path.exists(tmp_state):
                        os.unlink(tmp_state)
                    raise
        except Exception:
            # Full rollback of in-memory profiles and on-disk files
            self._profiles = original_profiles_snapshot
            if original_store_bytes is not None:
                self.store_path.write_bytes(original_store_bytes)
            elif self.store_path.exists():
                self.store_path.unlink(missing_ok=True)
            if state_path_obj is not None and original_state_bytes is not None:
                state_path_obj.write_bytes(original_state_bytes)
            raise

        return {
            "dry_run": False,
            "rolled_back": False,
            "from_provider": src_prov,
            "to_provider": dst_prov,
            "migrated_count": len(migrated_records),
            "migrated_voices": migrated_records,
            "project_state_updated": updated_state_payload is not None,
            "preserved_character_assignments": preserved_assignments,
        }


    def import_from_canonical_registry(
        self,
        registry_path: Path,
        default_provider: str = "unassigned",
    ) -> List[VoiceProfile]:
        """Bootstrap V01-V06 voice profiles from templates/voice-registry.json."""
        raw = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        imported: List[VoiceProfile] = []
        for entry in raw.get("voices", []):
            vid = str(entry["voice_id"])
            if vid in self._profiles:
                continue
            is_ref = vid == "V01"
            profile = VoiceProfile(
                voice_id=vid,
                display_name=str(entry.get("voice_name", vid)),
                voice_type="recorded_human" if is_ref else "original_synthetic",
                provider=default_provider,
                provider_voice_id=None,
                language="en",
                accent=str(entry.get("accent_and_pronunciation_profile", "neutral")),
                characteristics={
                    "character_category": entry.get("character_category", ""),
                    "description": entry.get("description", ""),
                    "pitch_and_vocal_texture": entry.get("pitch_and_vocal_texture_profile", ""),
                    "speaking_pace": entry.get("speaking_pace", ""),
                    "emotional_delivery_range": entry.get("emotional_delivery_range", ""),
                },
                intended_roles=list(entry.get("intended_roles", [])),
                consent_status="pending_authorization" if is_ref else "not_required_synthetic",
                availability_status="unverified",
            )
            self.create_profile(profile)
            imported.append(profile)
        return imported
