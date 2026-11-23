#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Voice Design Module for Roblox Town Director.

Creates original synthetic voice profiles from descriptive specifications while
respecting each provider's actual declared capabilities and adjustable controls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .profile_manager import VoiceProfile, VoiceProfileManager
from .providers import ProviderCapabilityError, VoiceProviderAdapter


@dataclass
class VoiceDesignSpec:
    voice_id: str
    display_name: str
    voice_description: str
    sample_text: str = ""
    language: str = "en"
    accent: str = "neutral"
    intended_character: Optional[str] = None
    intended_roles: List[str] = field(default_factory=list)
    requested_controls: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.voice_id or not self.voice_id.strip():
            raise ValueError("voice_id is required.")
        if not self.display_name or not self.display_name.strip():
            raise ValueError("display_name is required.")
        if not self.voice_description or len(self.voice_description.strip()) < 20:
            raise ValueError("voice_description must be at least 20 characters.")
        if self.sample_text and len(self.sample_text.strip()) > 1000:
            raise ValueError("sample_text must not exceed 1000 characters.")


class VoiceDesigner:
    """Orchestrates original synthetic voice creation across compatible providers."""

    def __init__(self, profile_manager: VoiceProfileManager):
        self.profile_manager = profile_manager

    def create_designed_voice(
        self,
        adapter: VoiceProviderAdapter,
        spec: VoiceDesignSpec,
        *,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        spec.validate()
        # F-09: Pre-validate local ID uniqueness & profile shape BEFORE creating remote provider resources
        if not overwrite and self.profile_manager.get_profile(spec.voice_id) is not None:
            raise ValueError(
                f"Voice profile {spec.voice_id!r} already exists; aborted before remote voice creation."
            )
        VoiceProfile(
            voice_id=spec.voice_id,
            display_name=spec.display_name,
            voice_type="original_synthetic",
            provider=adapter.provider_id,
            language=spec.language,
            accent=spec.accent,
            intended_character=spec.intended_character,
            intended_roles=list(spec.intended_roles),
            consent_status="not_required_synthetic",
            availability_status="available",
        ).validate()

        caps = adapter.capabilities()
        if not caps.implemented or not caps.voice_design:
            raise ProviderCapabilityError(
                f"Provider {adapter.provider_id!r} does not support voice_design."
            )

        supported_controls = set(caps.voice_design_controls)
        applied_controls: Dict[str, Any] = {}
        ignored_controls: List[str] = []
        for key, value in spec.requested_controls.items():
            if key in supported_controls:
                applied_controls[key] = value
            else:
                ignored_controls.append(key)

        provider_spec: Dict[str, Any] = {
            "display_name": spec.display_name,
            "voice_description": spec.voice_description,
            "sample_text": spec.sample_text,
            **applied_controls,
        }

        result = adapter.design_voice(provider_spec)
        provider_voice_id = result["provider_voice_id"]

        profile = VoiceProfile(
            voice_id=spec.voice_id,
            display_name=spec.display_name,
            voice_type="original_synthetic",
            provider=adapter.provider_id,
            provider_voice_id=provider_voice_id,
            language=spec.language,
            accent=spec.accent,
            characteristics={
                "voice_description": spec.voice_description,
                "applied_controls": applied_controls,
                "ignored_controls": ignored_controls,
            },
            intended_character=spec.intended_character,
            intended_roles=list(spec.intended_roles),
            consent_status="not_required_synthetic",
            availability_status="available",
            notes="Original synthetic voice created via VoiceDesigner.",
        )
        try:
            saved_profile = self.profile_manager.create_profile(profile, overwrite=overwrite)
        except Exception as save_exc:
            rollback_status = "not_attempted"
            try:
                adapter.delete_voice(provider_voice_id)
                rollback_status = "remote_voice_deleted"
            except Exception as del_exc:
                rollback_status = f"remote_rollback_failed: {del_exc}"
            raise RuntimeError(
                f"Local profile persistence failed for {spec.voice_id!r} after remote voice "
                f"{provider_voice_id!r} was created (rollback={rollback_status}): {save_exc}"
            ) from save_exc
        return {
            "profile": saved_profile.to_dict(),
            "provider_result": result,
            "applied_controls": applied_controls,
            "ignored_controls": ignored_controls,
        }
