#!/usr/bin/env python3
"""Authorized Voice Cloning Module for Roblox Town Director.

SAFETY & VERIFICATION BOUNDARY (F-08):
  - Self-attested declarations (`ConsentAttestation`) are NOT independent
    verification of speaker identity, adult age, or legal authorization.
  - Remote voice cloning submission is COMPLETELY DISABLED in v0.1.1.
    `clone_authorized_voice()` NEVER sends audio samples to any provider and
    NEVER creates remote voice resources in v0.1.1.
  - By default (`allow_unverified_staging=False`), `clone_authorized_voice()`
    raises `VoiceCloningConsentError`.
  - When `allow_unverified_staging=True` (strictly local offline staging only),
    it validates consent gates and local sample quality via FFprobe/FFmpeg and
    persists a local-only profile with `provider_voice_id=None`,
    `consent_status="self_attested_unverified"`, and
    `availability_status="unavailable"`—making ZERO provider API calls.
  - Cloning voices of minors or unauthorized impersonation is strictly blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audio_qc import inspect_audio_file
from .profile_manager import VoiceProfile, VoiceProfileManager, utc_now_iso
from .providers import VoiceProviderAdapter


class VoiceCloningConsentError(PermissionError):
    """Raised when required speaker authorization, safety, or verification gates fail."""


class VoiceSampleValidationError(ValueError):
    """Raised when imported reference samples fail technical validation."""


@dataclass
class ConsentAttestation:
    explicit_authorization_confirmed: bool
    speaker_is_adult: bool
    authorized_by: str
    speaker_relationship: str  # e.g., "self_creator", "contracted_voice_actor"
    scope_note: str = "Authorized for Roblox Town Cinematic Studio productions"
    no_impersonation_confirmed: bool = True
    independent_identity_verified: bool = False
    confirmed_at: str = field(default_factory=utc_now_iso)

    def validate(self) -> None:
        if self.independent_identity_verified:
            raise VoiceCloningConsentError(
                "Voice cloning blocked: independent_identity_verified cannot be asserted True "
                "without an integrated external identity-verification system."
            )
        if not self.explicit_authorization_confirmed:
            raise VoiceCloningConsentError(
                "Voice cloning blocked: explicit user authorization confirmation is required."
            )
        if not self.speaker_is_adult:
            raise VoiceCloningConsentError(
                "Voice cloning blocked: cloning voices of minors is strictly prohibited."
            )
        if not self.no_impersonation_confirmed:
            raise VoiceCloningConsentError(
                "Voice cloning blocked: unauthorized impersonation is strictly prohibited."
            )
        if not self.authorized_by or not self.authorized_by.strip():
            raise VoiceCloningConsentError(
                "Voice cloning blocked: authorized_by identifier must be provided."
            )
        if not self.speaker_relationship or not self.speaker_relationship.strip():
            raise VoiceCloningConsentError(
                "Voice cloning blocked: speaker_relationship must be documented."
            )


class AuthorizedVoiceCloner:
    """Consent-gated voice cloning orchestrator (remote cloning disabled in v0.1.1)."""

    SUPPORTED_SAMPLE_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}

    def __init__(
        self,
        profile_manager: VoiceProfileManager,
        *,
        min_sample_duration_sec: float = 1.0,
        min_sample_rate_hz: int = 16000,
    ):
        self.profile_manager = profile_manager
        self.min_sample_duration_sec = min_sample_duration_sec
        self.min_sample_rate_hz = min_sample_rate_hz

    def validate_samples(self, sample_paths: List[Path]) -> List[Dict[str, Any]]:
        if not sample_paths:
            raise VoiceSampleValidationError("At least one audio sample file is required.")

        reports: List[Dict[str, Any]] = []
        errors: List[str] = []
        for raw_path in sample_paths:
            p = Path(raw_path)
            if not p.exists():
                errors.append(f"Missing sample file: {p}")
                continue
            if p.suffix.lower() not in self.SUPPORTED_SAMPLE_EXTENSIONS:
                errors.append(f"Unsupported sample extension {p.suffix!r} for {p.name}")
                continue
            qc = inspect_audio_file(p, check_volume=True)
            if not qc["valid"]:
                errors.append(f"Unreadable or corrupt sample {p.name}: {'; '.join(qc['errors'])}")
                continue
            if qc["duration_sec"] < self.min_sample_duration_sec:
                errors.append(
                    f"Sample {p.name} too short ({qc['duration_sec']:.2f}s < {self.min_sample_duration_sec:.2f}s)."
                )
                continue
            if qc["sample_rate_hz"] < self.min_sample_rate_hz:
                errors.append(
                    f"Sample {p.name} sample rate too low ({qc['sample_rate_hz']} Hz < {self.min_sample_rate_hz} Hz)."
                )
                continue
            if qc.get("is_effectively_silent"):
                errors.append(f"Sample {p.name} is silent or empty.")
                continue
            reports.append(qc)

        if errors:
            raise VoiceSampleValidationError("Voice sample validation failed: " + " | ".join(errors))
        return reports

    def clone_authorized_voice(
        self,
        adapter: VoiceProviderAdapter,
        *,
        voice_id: str,
        display_name: str,
        description: str,
        sample_paths: List[Path],
        consent: ConsentAttestation,
        language: str = "en",
        accent: str = "neutral",
        intended_character: Optional[str] = None,
        intended_roles: Optional[List[str]] = None,
        overwrite: bool = False,
        allow_unverified_staging: bool = False,
    ) -> Dict[str, Any]:
        """Validate consent & samples; remote provider cloning is disabled in v0.1.1.

        - Default (`allow_unverified_staging=False`): raises `VoiceCloningConsentError`.
        - Offline local staging (`allow_unverified_staging=True`): validates local
          uniqueness and sample files via FFprobe/FFmpeg and persists a local-only
          staged profile (`provider_voice_id=None`, `consent_status="self_attested_unverified"`,
          `availability_status="unavailable"`) WITHOUT calling `adapter.create_authorized_clone()`
          or transmitting any audio to a remote provider.
        """
        # Step 1: Enforce explicit consent, adult-only, and anti-impersonation gates
        consent.validate()

        if not allow_unverified_staging:
            raise VoiceCloningConsentError(
                "Voice cloning is disabled in v0.1.1: self-attested consent does not "
                "provide independent verification of speaker identity, adult age, or authorization."
            )

        # Step 2 (F-09): Pre-validate local ID uniqueness BEFORE any further work
        if not overwrite and self.profile_manager.get_profile(voice_id) is not None:
            raise ValueError(
                f"Voice profile {voice_id!r} already exists; aborted local voice staging."
            )

        # Step 3: Validate sample files technically via FFprobe/FFmpeg (strictly local; zero network/provider calls)
        resolved_paths = [Path(p) for p in sample_paths]
        sample_reports = self.validate_samples(resolved_paths)

        # Step 4 (F-08): NEVER call adapter.create_authorized_clone() in v0.1.1.
        # Persist strictly local-only staged profile with provider_voice_id=None and availability_status="unavailable".
        profile = VoiceProfile(
            voice_id=voice_id,
            display_name=display_name,
            voice_type="authorized_cloned",
            provider=adapter.provider_id,
            provider_voice_id=None,
            language=language,
            accent=accent,
            characteristics={
                "description": description,
                "sample_count": len(sample_reports),
                "total_sample_duration_sec": round(
                    sum(r["duration_sec"] for r in sample_reports), 3
                ),
            },
            intended_character=intended_character,
            intended_roles=list(intended_roles or []),
            consent_status="self_attested_unverified",
            consent_record={
                "authorized_by": consent.authorized_by,
                "speaker_relationship": consent.speaker_relationship,
                "speaker_is_adult": consent.speaker_is_adult,
                "explicit_authorization_confirmed": consent.explicit_authorization_confirmed,
                "no_impersonation_confirmed": consent.no_impersonation_confirmed,
                "independent_identity_verified": False,
                "attestation_type": "user_self_attestation",
                "remote_submission_performed": False,
                "scope_note": consent.scope_note,
                "confirmed_at": consent.confirmed_at,
            },
            availability_status="unavailable",
            notes=(
                "Local-only staged voice profile (user_self_attestation; independent_identity_verified=false; "
                "remote cloning disabled in v0.1.1—no audio uploaded and no remote voice created). "
                "Private source recordings not stored in repo."
            ),
        )
        try:
            saved_profile = self.profile_manager.create_profile(profile, overwrite=overwrite)
        except Exception as save_exc:
            raise RuntimeError(
                f"Local profile persistence failed for staged voice {voice_id!r} "
                f"(no remote voice was created): {save_exc}"
            ) from save_exc

        return {
            "profile": saved_profile.to_dict(),
            "remote_submission_performed": False,
            "provider_result": None,
            "sample_reports": sample_reports,
        }

    def disable_or_remove_cloned_voice(
        self,
        voice_id: str,
        *,
        adapter: Optional[VoiceProviderAdapter] = None,
        delete_remote: bool = False,
        remove_local_profile: bool = False,
        reason: str = "User requested disable/removal",
    ) -> Dict[str, Any]:
        profile = self.profile_manager.require_profile(voice_id)
        remote_result: Optional[Dict[str, Any]] = None
        if delete_remote and adapter is not None and profile.provider_voice_id:
            remote_result = adapter.delete_voice(profile.provider_voice_id)

        if remove_local_profile:
            removed = self.profile_manager.remove_profile(voice_id)
            return {
                "action": "removed",
                "voice_id": removed.voice_id,
                "remote_result": remote_result,
            }

        revoked = self.profile_manager.revoke_cloned_consent(voice_id, reason=reason)
        return {
            "action": "disabled_and_revoked",
            "voice_id": revoked.voice_id,
            "availability_status": revoked.availability_status,
            "consent_status": revoked.consent_status,
            "remote_result": remote_result,
        }
