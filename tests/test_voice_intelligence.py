#!/usr/bin/env python3
"""Automated unit & mocked integration tests for the Voice Intelligence & Cloning Module.

IMPORTANT TEST SCOPE DISTINCTION:
  - All provider HTTP calls in this suite use an injected in-memory mock transport.
  - Audio file validation, clipping/silence detection, normalization, timeline mixing,
    and SRT synchronization use REAL local FFmpeg/FFprobe execution.
  - NO live ElevenLabs API calls are executed here (live API testing requires an
    active ELEVENLABS_API_KEY and outbound internet access).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "roblox-town-director" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from voice_intelligence import (  # noqa: E402
    AuthorizedVoiceCloner,
    CharacterVoiceAssigner,
    ConsentAttestation,
    ElevenLabsAdapter,
    GoogleCloudTTSAdapter,
    HTTPResponseData,
    OpenAITTSAdapter,
    ProviderAuthError,
    ProviderCapabilityError,
    ProviderQuotaError,
    ProviderRegistry,
    ProviderResponseError,
    ProviderVoiceNotFoundError,
    RecordedVoiceProviderAdapter,
    SynthesisRequest,
    VideoMuxError,
    VoiceCloningConsentError,
    VoiceDesignSpec,
    VoiceDesigner,
    VoiceGenerationPipeline,
    VoiceProfile,
    VoiceProfileManager,
    inspect_audio_file,
    build_predictable_filename,
    inspect_video_file,
    mux_audio_and_subtitles_to_video,
    resolve_safe_child_path,
    sanitize_filename_token,
    parse_script_dialogue,
)


def _generate_wav_bytes(duration_sec: float = 1.2, freq_hz: int = 330, volume: float = 0.25) -> bytes:
    """Generate a real valid WAV audio payload via FFmpeg for deterministic testing."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "sample.wav"
        res = subprocess.run(
            [
                "ffmpeg",
                "-nostdin", "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={freq_hz}:sample_rate=44100:duration={duration_sec}",
                "-filter:a",
                f"volume={volume}",
                "-ac",
                "1",
                str(out),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg test audio generation failed: {res.stderr}")
        return out.read_bytes()


def _generate_silent_wav_file(path: Path, duration_sec: float = 1.0) -> None:
    res = subprocess.run(
        [
            "ffmpeg",
            "-nostdin", "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=mono:d={duration_sec}",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg silent audio generation failed: {res.stderr}")


class VoiceIntelligenceTestSuite(unittest.TestCase):
    """Covers all 16 mandatory Phase 03 test areas (unit + mocked HTTP + real FFmpeg)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.valid_wav_bytes = _generate_wav_bytes(duration_sec=1.2, freq_hz=330, volume=0.25)
        cls.valid_wav_bytes_alt = _generate_wav_bytes(duration_sec=1.0, freq_hz=440, volume=0.25)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.store_path = self.tmp_dir / "voice_profiles.json"
        self.old_el_key = os.environ.get("ELEVENLABS_API_KEY")
        os.environ["ELEVENLABS_API_KEY"] = "test_mock_key_never_sent_over_network"

    def tearDown(self) -> None:
        if self.old_el_key is None:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        else:
            os.environ["ELEVENLABS_API_KEY"] = self.old_el_key
        self._tmp.cleanup()

    # 1. Voice profile creation
    def test_01_voice_profile_creation(self) -> None:
        mgr = VoiceProfileManager(self.store_path)
        prof = mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Primary Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_voice_001",
                language="en",
                accent="US English",
                intended_character="narrator",
                intended_roles=["narrator", "storyteller"],
            )
        )
        self.assertEqual(prof.voice_id, "V01")
        self.assertEqual(prof.availability_status, "available")
        with self.assertRaises(ValueError):
            mgr.create_profile(prof, overwrite=False)

    # 2. Voice profile persistence
    def test_02_voice_profile_persistence(self) -> None:
        mgr1 = VoiceProfileManager(self.store_path)
        mgr1.create_profile(
            VoiceProfile(
                voice_id="V03",
                display_name="Protagonist Leo",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_leo_003",
                intended_character="leo",
            )
        )
        mgr2 = VoiceProfileManager(self.store_path)
        reloaded = mgr2.require_profile("V03")
        self.assertEqual(reloaded.display_name, "Protagonist Leo")
        self.assertEqual(reloaded.provider_voice_id, "el_leo_003")

    # 3. Character-to-voice assignment (across multiple scenes)
    def test_03_character_to_voice_assignment(self) -> None:
        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Main Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
                intended_roles=["narrator"],
            )
        )
        mgr.create_profile(
            VoiceProfile(
                voice_id="V03",
                display_name="Leo",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v03",
                intended_character="leo",
            )
        )
        script = (
            "[S01]\n"
            "Narrator (suspense): In this town, nobody can lie.\n"
            "Leo (worried): Did you hear the bell?\n"
            "[S02]\n"
            "Leo (urgent): We have to leave now.\n"
        )
        segments = parse_script_dialogue(script)
        self.assertEqual(len(segments), 3)
        assigner = CharacterVoiceAssigner(mgr)
        char_map, blockers = assigner.assign_characters(segments)
        self.assertEqual(blockers, [])
        self.assertEqual(char_map["narrator"]["voice_id"], "V01")
        self.assertEqual(char_map["leo"]["voice_id"], "V03")

    # 4. Provider selection
    def test_04_provider_selection(self) -> None:
        registry = ProviderRegistry(
            [
                ElevenLabsAdapter(),
                OpenAITTSAdapter(),
                GoogleCloudTTSAdapter(),
                RecordedVoiceProviderAdapter(),
            ]
        )
        selected = registry.select_provider(required_capability="text_to_speech", require_configured=True)
        self.assertEqual(selected.provider_id, "elevenlabs")

        rec = registry.select_provider(required_capability="recorded_audio_import", require_configured=True)
        self.assertEqual(rec.provider_id, "recorded_voice_backend")

        with self.assertRaises(ProviderCapabilityError):
            registry.select_provider(
                preferred_provider="recorded_voice_backend",
                required_capability="text_to_speech",
            )

    # 5. API authentication failure (missing env var & HTTP 401)
    def test_05_api_authentication_failure(self) -> None:
        os.environ.pop("ELEVENLABS_API_KEY", None)
        adapter_missing = ElevenLabsAdapter()
        with self.assertRaises(ProviderAuthError):
            adapter_missing.check_authentication()

        os.environ["ELEVENLABS_API_KEY"] = "invalid_key_mock"

        def mock_401(method, url, headers, body, timeout):
            return HTTPResponseData(401, {"content-type": "application/json"}, b'{"detail":"Invalid API key"}')

        adapter_401 = ElevenLabsAdapter(transport=mock_401)
        with self.assertRaises(ProviderAuthError):
            adapter_401.check_authentication()

    # 6. Invalid voice ID (HTTP 404)
    def test_06_invalid_voice_id(self) -> None:
        def mock_404(method, url, headers, body, timeout):
            return HTTPResponseData(404, {"content-type": "application/json"}, b'{"detail":"Voice ID not found"}')

        adapter = ElevenLabsAdapter(transport=mock_404)
        with self.assertRaises(ProviderVoiceNotFoundError):
            adapter.synthesize_speech(
                SynthesisRequest(
                    text="Testing invalid voice ID.",
                    provider_voice_id="nonexistent_voice_999",
                    output_path=self.tmp_dir / "bad.mp3",
                )
            )

    # 7. Quota or provider error (HTTP 429 & 402)
    def test_07_quota_or_provider_error(self) -> None:
        def mock_429(method, url, headers, body, timeout):
            return HTTPResponseData(429, {"content-type": "application/json"}, b'{"detail":"Quota exceeded"}')

        adapter = ElevenLabsAdapter(transport=mock_429)
        with self.assertRaises(ProviderQuotaError) as ctx:
            adapter.synthesize_speech(
                SynthesisRequest(
                    text="Quota check line.",
                    provider_voice_id="el_v01",
                    output_path=self.tmp_dir / "quota.mp3",
                )
            )
        self.assertTrue(ctx.exception.retryable)

    # 8. Mocked TTS generation + Voice Design
    def test_08_mocked_tts_generation_and_voice_design(self) -> None:
        def mock_transport(method, url, headers, body, timeout):
            if url.endswith("/v1/text-to-voice/design"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"previews": [{"generated_voice_id": "gen_prev_123"}]}).encode("utf-8"),
                )
            if url.endswith("/v1/text-to-voice"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"voice_id": "el_designed_123"}).encode("utf-8"),
                )
            if "/text-to-speech/" in url:
                return HTTPResponseData(200, {"content-type": "audio/wav"}, self.valid_wav_bytes)
            return HTTPResponseData(404, {}, b"{}")

        adapter = ElevenLabsAdapter(transport=mock_transport)
        mgr = VoiceProfileManager(self.store_path)
        designer = VoiceDesigner(mgr)
        designed = designer.create_designed_voice(
            adapter,
            VoiceDesignSpec(
                voice_id="V02",
                display_name="Mystery Narrator",
                voice_description="Calm, warm young adult male narrator with crisp articulation for suspense shorts.",
                sample_text="In this town, every secret echoes through the streetlights at midnight.",
                requested_controls={"loudness": 0.5, "stability": 0.6, "unsupported_slider": 99},
            ),
        )
        self.assertEqual(designed["profile"]["provider_voice_id"], "el_designed_123")
        self.assertEqual(designed["applied_controls"], {"loudness": 0.5})
        self.assertIn("stability", designed["ignored_controls"])
        self.assertIn("unsupported_slider", designed["ignored_controls"])

        out_file = self.tmp_dir / "tts_out.wav"
        res = adapter.synthesize_speech(
            SynthesisRequest(
                text="Hello from mocked ElevenLabs TTS.",
                provider_voice_id="el_designed_123",
                output_path=out_file,
                output_format="wav",
            )
        )
        self.assertGreater(res.bytes_written, 1000)
        qc = inspect_audio_file(out_file)
        self.assertTrue(qc["valid"])
        self.assertTrue(qc["requires_human_listening"])

    # 9. Mocked cloning workflow (including consent & minor refusal + disable/remove)
    def test_09_mocked_cloning_workflow_and_consent_gates(self) -> None:
        sample_path = self.tmp_dir / "authorized_sample.wav"
        sample_path.write_bytes(self.valid_wav_bytes)

        def mock_clone_transport(method, url, headers, body, timeout):
            if method == "POST" and url.endswith("/voices/add"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"voice_id": "el_clone_777", "requires_verification": False}).encode("utf-8"),
                )
            if method == "POST" and "/text-to-speech/" in url:
                return HTTPResponseData(200, {"content-type": "audio/wav"}, self.valid_wav_bytes)
            if method == "DELETE" and "/voices/el_clone_777" in url:
                return HTTPResponseData(200, {"content-type": "application/json"}, b'{"status":"ok"}')
            return HTTPResponseData(404, {}, b"{}")

        adapter = ElevenLabsAdapter(transport=mock_clone_transport)
        mgr = VoiceProfileManager(self.store_path)
        cloner = AuthorizedVoiceCloner(mgr, min_sample_duration_sec=0.5)

        # Must block missing consent
        with self.assertRaises(VoiceCloningConsentError):
            cloner.clone_authorized_voice(
                adapter,
                voice_id="V01",
                display_name="Blocked Unconsented",
                description="Should fail",
                sample_paths=[sample_path],
                consent=ConsentAttestation(
                    explicit_authorization_confirmed=False,
                    speaker_is_adult=True,
                    authorized_by="creator",
                    speaker_relationship="self_creator",
                ),
            )

        # Must block minors
        with self.assertRaises(VoiceCloningConsentError):
            cloner.clone_authorized_voice(
                adapter,
                voice_id="V01",
                display_name="Blocked Minor",
                description="Should fail",
                sample_paths=[sample_path],
                consent=ConsentAttestation(
                    explicit_authorization_confirmed=True,
                    speaker_is_adult=False,
                    authorized_by="creator",
                    speaker_relationship="other",
                ),
            )

        # By default (F-08), voice cloning is unavailable without independent verification
        with self.assertRaises(VoiceCloningConsentError):
            cloner.clone_authorized_voice(
                adapter,
                voice_id="V01",
                display_name="Blocked Without Independent Verification",
                description="Should block default production cloning",
                sample_paths=[sample_path],
                consent=ConsentAttestation(
                    explicit_authorization_confirmed=True,
                    speaker_is_adult=True,
                    authorized_by="creator_owner",
                    speaker_relationship="self_creator",
                ),
            )

        # Offline mocked staging persists strictly as self_attested_unverified + unavailable
        result = cloner.clone_authorized_voice(
            adapter,
            voice_id="V01",
            display_name="Creator Staged Voice",
            description="Staged creator voice pending independent verification.",
            sample_paths=[sample_path],
            consent=ConsentAttestation(
                explicit_authorization_confirmed=True,
                speaker_is_adult=True,
                authorized_by="creator_owner",
                speaker_relationship="self_creator",
            ),
            allow_unverified_staging=True,
        )
        self.assertIsNone(result["profile"]["provider_voice_id"])
        self.assertFalse(result["remote_submission_performed"])
        self.assertIsNone(result["provider_result"])
        self.assertEqual(result["profile"]["consent_status"], "self_attested_unverified")
        self.assertEqual(result["profile"]["availability_status"], "unavailable")

        disabled = cloner.disable_or_remove_cloned_voice(
            "V01", adapter=adapter, delete_remote=True, remove_local_profile=False
        )
        self.assertEqual(disabled["availability_status"], "disabled")
        self.assertEqual(disabled["consent_status"], "revoked")
        self.assertIsNone(disabled["remote_result"])

    # 10. Missing audio response (empty 0-byte body)
    def test_10_missing_audio_response(self) -> None:
        def mock_empty(method, url, headers, body, timeout):
            return HTTPResponseData(200, {"content-type": "audio/mpeg"}, b"")

        adapter = ElevenLabsAdapter(transport=mock_empty)
        with self.assertRaises(ProviderResponseError):
            adapter.synthesize_speech(
                SynthesisRequest(
                    text="Empty response test.",
                    provider_voice_id="el_v01",
                    output_path=self.tmp_dir / "empty.mp3",
                )
            )

    # 11. Corrupt audio response (non-audio garbage bytes rejected by FFprobe)
    def test_11_corrupt_audio_response(self) -> None:
        def mock_corrupt(method, url, headers, body, timeout):
            return HTTPResponseData(200, {"content-type": "audio/mpeg"}, b"NOT_VALID_AUDIO_BYTES_123456")

        adapter = ElevenLabsAdapter(transport=mock_corrupt)
        out_path = self.tmp_dir / "corrupt.mp3"
        adapter.synthesize_speech(
            SynthesisRequest(
                text="Corrupt audio test.",
                provider_voice_id="el_v01",
                output_path=out_path,
            )
        )
        qc = inspect_audio_file(out_path)
        self.assertFalse(qc["valid"])
        self.assertTrue(any("FFprobe failed" in e for e in qc["errors"]))

    # 12. Audio validation (valid vs silent vs missing)
    def test_12_audio_validation(self) -> None:
        valid_path = self.tmp_dir / "valid.wav"
        valid_path.write_bytes(self.valid_wav_bytes)
        qc_valid = inspect_audio_file(valid_path)
        self.assertTrue(qc_valid["valid"])
        self.assertGreater(qc_valid["duration_sec"], 1.0)
        self.assertEqual(qc_valid["sample_rate_hz"], 44100)
        self.assertFalse(qc_valid["subjective_naturalness_assessed"])

        silent_path = self.tmp_dir / "silent.wav"
        _generate_silent_wav_file(silent_path, duration_sec=1.0)
        qc_silent = inspect_audio_file(silent_path)
        self.assertFalse(qc_silent["valid"])
        self.assertTrue(qc_silent["is_effectively_silent"])

        qc_missing = inspect_audio_file(self.tmp_dir / "does_not_exist.wav")
        self.assertFalse(qc_missing["valid"])

    # 13. Retry behavior (transient 500 -> succeeds on retry)
    def test_13_retry_behavior(self) -> None:
        calls = {"count": 0}

        def mock_flaky(method, url, headers, body, timeout):
            calls["count"] += 1
            if calls["count"] == 1:
                return HTTPResponseData(503, {"content-type": "application/json"}, b'{"detail":"Temporary outage"}')
            return HTTPResponseData(200, {"content-type": "audio/wav"}, self.valid_wav_bytes)

        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
            )
        )
        registry = ProviderRegistry([ElevenLabsAdapter(transport=mock_flaky)])
        pipeline = VoiceGenerationPipeline(profile_manager=mgr, provider_registry=registry, max_retries=2)
        state = pipeline.run_script_pipeline(
            project_id="RETRY_TEST",
            project_title="Retry Test",
            script_text="Narrator: Testing automatic retry recovery.",
            output_dir=self.tmp_dir / "retry_out",
            state_path=self.tmp_dir / "retry_state.json",
            output_format="wav",
            raw_ext="wav",
        )
        self.assertEqual(calls["count"], 2)
        self.assertEqual(state["dialogue_jobs"][0]["status"], "approved")
        self.assertEqual(state["dialogue_jobs"][0]["attempts"], 2)

    # 14. Voice fallback handling (never silently substitute; accept explicit approved fallback)
    def test_14_voice_fallback_handling(self) -> None:
        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Disabled Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
                availability_status="disabled",
            )
        )
        mgr.create_profile(
            VoiceProfile(
                voice_id="V02",
                display_name="Backup Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v02",
                intended_roles=["narrator"],
                availability_status="available",
            )
        )
        segments = parse_script_dialogue("Narrator: Nobody can lie here.")
        assigner = CharacterVoiceAssigner(mgr)

        # Without explicit approval, locked V01 must block rather than silently substitute V02
        existing = {"character_voice_map": [{"character_id": "narrator", "voice_id": "V01"}]}
        char_map_blocked, blockers = assigner.assign_characters(segments, existing_state=existing)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0]["type"], "voice_unavailable")
        self.assertIn("V02", blockers[0]["suggested_fallbacks"])
        self.assertNotIn("V02", str(char_map_blocked.get("narrator", {})))

        # With explicit user-approved fallback, V02 is cleanly assigned
        char_map_ok, blockers_ok = assigner.assign_characters(
            segments,
            existing_state=existing,
            approved_fallbacks={"narrator": "V02"},
        )
        self.assertEqual(blockers_ok, [])
        self.assertEqual(char_map_ok["narrator"]["voice_id"], "V02")
        self.assertEqual(char_map_ok["narrator"]["assignment_source"], "approved_fallback")

    # 15. Multi-character dialogue generation (full pipeline -> stems + timeline WAV + SRT + QC)
    def test_15_multi_character_dialogue_generation(self) -> None:
        def mock_multi(method, url, headers, body, timeout):
            payload = self.valid_wav_bytes if "el_v01" in url else self.valid_wav_bytes_alt
            return HTTPResponseData(200, {"content-type": "audio/wav"}, payload)

        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
            )
        )
        mgr.create_profile(
            VoiceProfile(
                voice_id="V03",
                display_name="Leo",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v03",
                intended_character="leo",
            )
        )
        mgr.create_profile(
            VoiceProfile(
                voice_id="V04",
                display_name="Maya",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v04",
                intended_character="maya",
            )
        )
        registry = ProviderRegistry([ElevenLabsAdapter(transport=mock_multi)])
        pipeline = VoiceGenerationPipeline(profile_manager=mgr, provider_registry=registry)
        script = (
            "[S01]\n"
            "Narrator: In this town, nobody can lie.\n"
            "Leo: I didn't take the key.\n"
            "Maya: Then why is it in your pocket?\n"
        )
        out_dir = self.tmp_dir / "multi_out"
        state_path = out_dir / "project_voice_state.json"
        state = pipeline.run_script_pipeline(
            project_id="PROD_MULTI_01",
            project_title="Multi-Character Test",
            script_text=script,
            output_dir=out_dir,
            state_path=state_path,
            output_format="wav",
            raw_ext="wav",
        )
        self.assertEqual(state["qc_report"]["approved_lines"], 3)
        self.assertTrue(state["qc_report"]["technical_qc_passed"])
        self.assertTrue(state["qc_report"]["requires_human_listening"])
        self.assertTrue(Path(state["artifacts"]["master_dialogue_wav"]).exists())
        self.assertTrue(Path(state["artifacts"]["subtitles_srt"]).exists())

    # 16. Project-state recovery (skips already-approved lines, only retries failed lines)
    def test_16_project_state_recovery(self) -> None:
        api_calls: List[str] = []
        fail_line2 = {"active": True}

        def mock_recoverable(method, url, headers, body, timeout):
            api_calls.append(url)
            if "el_v03" in url and fail_line2["active"]:
                return HTTPResponseData(500, {"content-type": "application/json"}, b'{"detail":"Simulated crash"}')
            return HTTPResponseData(200, {"content-type": "audio/wav"}, self.valid_wav_bytes)

        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
            )
        )
        mgr.create_profile(
            VoiceProfile(
                voice_id="V03",
                display_name="Leo",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v03",
                intended_character="leo",
            )
        )
        registry = ProviderRegistry([ElevenLabsAdapter(transport=mock_recoverable)])
        pipeline = VoiceGenerationPipeline(profile_manager=mgr, provider_registry=registry, max_retries=0)
        script = "Narrator: Line one succeeds.\nLeo: Line two fails first, then recovers.\n"
        out_dir = self.tmp_dir / "recovery_out"
        state_path = out_dir / "project_voice_state.json"

        # Pass 1: Line 1 approved, Line 2 fails
        state1 = pipeline.run_script_pipeline(
            project_id="REC_01",
            project_title="Recovery Test",
            script_text=script,
            output_dir=out_dir,
            state_path=state_path,
            output_format="wav",
            raw_ext="wav",
        )
        self.assertEqual(state1["dialogue_jobs"][0]["status"], "approved")
        self.assertEqual(state1["dialogue_jobs"][1]["status"], "failed")
        self.assertEqual(len(api_calls), 2)

        # Pass 2: Provider recovers -> Line 1 MUST be skipped, only Line 2 called
        fail_line2["active"] = False
        api_calls.clear()
        state2 = pipeline.run_script_pipeline(
            project_id="REC_01",
            project_title="Recovery Test",
            script_text=script,
            output_dir=out_dir,
            state_path=state_path,
            output_format="wav",
            raw_ext="wav",
        )
        self.assertEqual(len(api_calls), 1)
        self.assertIn("el_v03", api_calls[0])
        self.assertTrue(state2["dialogue_jobs"][0]["skipped_existing_approved"])
        self.assertEqual(state2["dialogue_jobs"][1]["status"], "approved")
        self.assertTrue(state2["qc_report"]["technical_qc_passed"])


    # 17. Consent boundary: independent_identity_verified must remain False
    def test_17_consent_identity_verification_boundary(self) -> None:
        sample_path = self.tmp_dir / "adult_sample.wav"
        sample_path.write_bytes(self.valid_wav_bytes)

        def mock_clone(method, url, headers, body, timeout):
            return HTTPResponseData(
                200,
                {"content-type": "application/json"},
                json.dumps({"voice_id": "el_clone_boundary"}).encode("utf-8"),
            )

        adapter = ElevenLabsAdapter(transport=mock_clone)
        mgr = VoiceProfileManager(self.store_path)
        cloner = AuthorizedVoiceCloner(mgr, min_sample_duration_sec=0.5)

        # Attempting to assert independent_identity_verified=True without an external verifier must fail
        with self.assertRaises(VoiceCloningConsentError):
            cloner.clone_authorized_voice(
                adapter,
                voice_id="V01",
                display_name="Misrepresented Verification",
                description="Should block false independent verification claim",
                sample_paths=[sample_path],
                consent=ConsentAttestation(
                    explicit_authorization_confirmed=True,
                    speaker_is_adult=True,
                    authorized_by="creator_owner",
                    speaker_relationship="self_creator",
                    independent_identity_verified=True,
                ),
            )

        res = cloner.clone_authorized_voice(
            adapter,
            voice_id="V01",
            display_name="Attested Only",
            description="Self-attested creator voice",
            sample_paths=[sample_path],
            consent=ConsentAttestation(
                explicit_authorization_confirmed=True,
                speaker_is_adult=True,
                authorized_by="creator_owner",
                speaker_relationship="self_creator",
            ),
            allow_unverified_staging=True,
        )
        consent_rec = res["profile"]["consent_record"]
        self.assertIs(consent_rec["independent_identity_verified"], False)
        self.assertEqual(consent_rec["attestation_type"], "user_self_attestation")

    # 18. CLI entrypoint checks & secret non-exposure
    def test_18_cli_entrypoint_and_secret_safety(self) -> None:
        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="CLI Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
            )
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS_DIR)
        env["ELEVENLABS_API_KEY"] = "super_secret_do_not_print_12345"

        # profiles list succeeds
        p_ok = subprocess.run(
            [sys.executable, "-m", "voice_intelligence", "profiles", "--store", str(self.store_path)],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p_ok.returncode, 0)
        self.assertIn("CLI Narrator", p_ok.stdout)
        self.assertNotIn("super_secret_do_not_print_12345", p_ok.stdout + p_ok.stderr)

        # audio-qc on missing file exits non-zero cleanly
        p_bad_qc = subprocess.run(
            [sys.executable, "-m", "voice_intelligence", "audio-qc", "--file", str(self.tmp_dir / "missing.wav")],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(p_bad_qc.returncode, 0)

        # auth-check with unset key exits non-zero without leaking secrets
        env_nokey = dict(env)
        env_nokey.pop("ELEVENLABS_API_KEY", None)
        p_auth = subprocess.run(
            [sys.executable, "-m", "voice_intelligence", "auth-check", "--provider", "elevenlabs"],
            stdin=subprocess.DEVNULL,
            env=env_nokey,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(p_auth.returncode, 0)
        self.assertIn("ELEVENLABS_API_KEY", p_auth.stderr)

    # 19. FFmpeg video muxing with BGM, SFX, embedded subtitles & resolution/FPS preservation
    def test_19_video_mux_with_bgm_sfx_and_subtitles(self) -> None:
        src_video = self.tmp_dir / "source_720x1280_24fps.mp4"
        res = subprocess.run(
            [
                "ffmpeg",
                "-nostdin", "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=navy:s=720x1280:r=24:d=2.5",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(src_video),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0, res.stderr)

        dlg_wav = self.tmp_dir / "dialogue.wav"
        dlg_wav.write_bytes(self.valid_wav_bytes)
        bgm_wav = self.tmp_dir / "bgm.wav"
        bgm_wav.write_bytes(_generate_wav_bytes(duration_sec=2.5, freq_hz=220, volume=0.15))
        sfx_wav = self.tmp_dir / "sfx.wav"
        sfx_wav.write_bytes(_generate_wav_bytes(duration_sec=0.6, freq_hz=660, volume=0.3))
        srt_path = self.tmp_dir / "subtitles.srt"
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,200\nNarrator: Test mux.\n", encoding="utf-8")

        out_mp4 = self.tmp_dir / "muxed_output.mp4"
        report = mux_audio_and_subtitles_to_video(
            video_path=src_video,
            dialogue_audio_path=dlg_wav,
            output_video_path=out_mp4,
            bgm_path=bgm_wav,
            sfx_path=sfx_wav,
            subtitles_srt_path=srt_path,
            embed_subtitles=True,
        )
        self.assertTrue(out_mp4.exists())
        self.assertTrue(report["preserved_resolution"])
        self.assertTrue(report["preserved_fps"])
        self.assertTrue(report["subtitle_embedded"])
        self.assertTrue(report["bgm_included"])
        self.assertTrue(report["sfx_included"])
        self.assertIn("not Roblox Studio", report["render_origin_note"])
        qc = inspect_video_file(out_mp4)
        self.assertTrue(qc["valid"])
        self.assertEqual((qc["width"], qc["height"]), (720, 1280))
        self.assertAlmostEqual(qc["fps"], 24.0, places=2)
        self.assertTrue(qc["has_audio"])
        self.assertTrue(qc["has_subtitles"])

    # 20. Video muxing failure paths (missing audio, invalid video, missing SRT)
    def test_20_video_mux_failure_paths(self) -> None:
        bad_video = self.tmp_dir / "corrupt.mp4"
        bad_video.write_bytes(b"not a video")
        dlg_wav = self.tmp_dir / "dialogue.wav"
        dlg_wav.write_bytes(self.valid_wav_bytes)

        with self.assertRaises(VideoMuxError):
            mux_audio_and_subtitles_to_video(
                video_path=bad_video,
                dialogue_audio_path=dlg_wav,
                output_video_path=self.tmp_dir / "out1.mp4",
            )

        good_video = self.tmp_dir / "good.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin", "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:r=30:d=1.0",
                "-c:v",
                "libx264",
                str(good_video),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        with self.assertRaises(VideoMuxError):
            mux_audio_and_subtitles_to_video(
                video_path=good_video,
                dialogue_audio_path=self.tmp_dir / "missing_dialogue.wav",
                output_video_path=self.tmp_dir / "out2.mp4",
            )

    # 21. Source-video audio preservation (default replace vs preserve_source_audio=True on audio & silent video)
    def test_21_video_mux_preserve_source_audio(self) -> None:
        # Video WITH an existing audio stream
        vid_with_audio = self.tmp_dir / "with_audio.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x223344:s=360x640:r=24:d=2.0",
                "-f", "lavfi", "-i", "sine=frequency=520:sample_rate=48000:duration=2.0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(vid_with_audio),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        # Video WITHOUT an audio stream
        vid_silent = self.tmp_dir / "silent_video.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x111111:s=360x640:r=24:d=2.0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(vid_silent),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        dlg = self.tmp_dir / "dlg.wav"
        dlg.write_bytes(self.valid_wav_bytes)

        # Default preserve_source_audio=False replaces source audio
        out_replace = self.tmp_dir / "out_replace.mp4"
        rep_replace = mux_audio_and_subtitles_to_video(
            video_path=vid_with_audio,
            dialogue_audio_path=dlg,
            output_video_path=out_replace,
        )
        self.assertFalse(rep_replace["preserve_source_audio_requested"])
        self.assertFalse(rep_replace["source_audio_preserved"])
        self.assertTrue(inspect_video_file(out_replace)["valid"])

        # preserve_source_audio=True mixes source audio safely without clipping
        out_preserve = self.tmp_dir / "out_preserve.mp4"
        rep_preserve = mux_audio_and_subtitles_to_video(
            video_path=vid_with_audio,
            dialogue_audio_path=dlg,
            output_video_path=out_preserve,
            preserve_source_audio=True,
        )
        self.assertTrue(rep_preserve["preserve_source_audio_requested"])
        self.assertTrue(rep_preserve["source_audio_preserved"])
        self.assertTrue(rep_preserve["preserved_resolution"])
        self.assertTrue(rep_preserve["preserved_fps"])
        audio_qc = inspect_audio_file(out_preserve, check_volume=True)
        self.assertTrue(audio_qc["valid"])
        self.assertFalse(audio_qc["clipping_detected"])

        # preserve_source_audio=True on a video with NO audio stream succeeds cleanly
        out_no_src = self.tmp_dir / "out_no_src.mp4"
        rep_no_src = mux_audio_and_subtitles_to_video(
            video_path=vid_silent,
            dialogue_audio_path=dlg,
            output_video_path=out_no_src,
            preserve_source_audio=True,
        )
        self.assertTrue(rep_no_src["preserve_source_audio_requested"])
        self.assertFalse(rep_no_src["source_audio_preserved"])
        self.assertTrue(inspect_video_file(out_no_src)["valid"])

    # 22. CLI subprocess coverage for mux-video (success & failure) and run-pipeline (success & failure)
    def test_22_cli_mux_video_and_run_pipeline(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS_DIR)
        env["ELEVENLABS_API_KEY"] = "cli_secret_token_must_never_leak_999"

        # 22a. mux-video success
        src_vid = self.tmp_dir / "cli_src.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x102030:s=360x640:r=30:d=1.5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(src_vid),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        dlg = self.tmp_dir / "cli_dlg.wav"
        dlg.write_bytes(self.valid_wav_bytes)
        out_vid = self.tmp_dir / "cli_muxed.mp4"
        p_mux_ok = subprocess.run(
            [
                sys.executable, "-m", "voice_intelligence", "mux-video",
                "--video", str(src_vid),
                "--dialogue", str(dlg),
                "--output", str(out_vid),
            ],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p_mux_ok.returncode, 0, p_mux_ok.stderr)
        self.assertTrue(out_vid.exists())
        self.assertNotIn("cli_secret_token_must_never_leak_999", p_mux_ok.stdout + p_mux_ok.stderr)

        # 22b. mux-video invalid input -> non-zero exit
        p_mux_bad = subprocess.run(
            [
                sys.executable, "-m", "voice_intelligence", "mux-video",
                "--video", str(self.tmp_dir / "nonexistent.mp4"),
                "--dialogue", str(dlg),
                "--output", str(self.tmp_dir / "bad_out.mp4"),
            ],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(p_mux_bad.returncode, 0)
        self.assertNotIn("cli_secret_token_must_never_leak_999", p_mux_bad.stdout + p_mux_bad.stderr)

        # 22c. run-pipeline failure (missing script file -> non-zero exit)
        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
            )
        )
        p_run_fail = subprocess.run(
            [
                sys.executable, "-m", "voice_intelligence", "run-pipeline",
                "--store", str(self.store_path),
                "--script", str(self.tmp_dir / "missing_script.txt"),
                "--output-dir", str(self.tmp_dir / "run_fail_out"),
                "--state", str(self.tmp_dir / "run_fail_state.json"),
            ],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(p_run_fail.returncode, 0)
        self.assertNotIn("cli_secret_token_must_never_leak_999", p_run_fail.stdout + p_run_fail.stderr)

        # 22d. run-pipeline success via CLI (resuming pre-approved stem -> real FFmpeg timeline + SRT + QC, 0 live API calls)
        run_out = self.tmp_dir / "cli_run_ok"
        stems_dir = run_out / "processed_stems"
        stems_dir.mkdir(parents=True, exist_ok=True)
        stem_wav = stems_dir / "S01_S01_L01_narrator_V01.wav"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-i", str(dlg),
                "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
                str(stem_wav),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        script_file = self.tmp_dir / "cli_script.txt"
        script_file.write_text("[S01]\nNarrator: CLI recovery pipeline verification.\n", encoding="utf-8")
        state_file = run_out / "project_voice_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": "1.1.0",
                    "project_id": "CLI_OK",
                    "character_voice_map": [
                        {"character_id": "narrator", "display_name": "Narrator", "voice_id": "V01", "provider": "elevenlabs", "provider_voice_id": "el_v01"}
                    ],
                    "dialogue_jobs": [
                        {
                            "scene_id": "S01",
                            "line_id": "S01_L01",
                            "character_id": "narrator",
                            "display_name": "Narrator",
                            "voice_id": "V01",
                            "provider": "elevenlabs",
                            "provider_voice_id": "el_v01",
                            "text": "CLI recovery pipeline verification.",
                            "status": "approved",
                            "processed_stem_path": str(stem_wav),
                            "start_sec": 0.0,
                            "end_sec": 1.2,
                            "qc": {"valid": True, "duration_sec": 1.2},
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        p_run_ok = subprocess.run(
            [
                sys.executable, "-m", "voice_intelligence", "run-pipeline",
                "--store", str(self.store_path),
                "--script", str(script_file),
                "--output-dir", str(run_out),
                "--state", str(state_file),
                "--project-id", "CLI_OK",
            ],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p_run_ok.returncode, 0, p_run_ok.stderr)
        self.assertTrue((run_out / "dialogue_timeline.wav").exists())
        self.assertTrue((run_out / "subtitles.srt").exists())
        self.assertNotIn("cli_secret_token_must_never_leak_999", p_run_ok.stdout + p_run_ok.stderr)

    # 23. Regression: ElevenLabs Voice Design uses current /v1/text-to-voice/design & /v1/text-to-voice routes
    def test_23_elevenlabs_voice_design_current_routes_and_auto_generate_text(self) -> None:
        seen_urls: List[str] = []
        seen_payloads: List[Dict[str, object]] = []

        def mock_current_routes(method, url, headers, body, timeout):
            seen_urls.append(f"{method} {url}")
            seen_payloads.append(json.loads(body.decode("utf-8")) if body else {})
            if url.endswith("/v1/text-to-voice/design"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"previews": [{"generated_voice_id": "gen_v3_999"}]}).encode("utf-8"),
                )
            if url.endswith("/v1/text-to-voice"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"voice_id": "el_saved_999"}).encode("utf-8"),
                )
            return HTTPResponseData(404, {}, b'{"detail":"Deprecated or unknown route"}')

        adapter = ElevenLabsAdapter(transport=mock_current_routes)
        res = adapter.design_voice(
            {
                "display_name": "Town Narrator",
                "voice_description": "Warm, articulate young adult male storyteller with crisp pacing.",
                "sample_text": "Short sample under 100 chars triggers auto_generate_text.",
            }
        )
        self.assertEqual(res["provider_voice_id"], "el_saved_999")
        self.assertEqual(
            seen_urls,
            [
                "POST https://api.elevenlabs.io/v1/text-to-voice/design",
                "POST https://api.elevenlabs.io/v1/text-to-voice",
            ],
        )
        self.assertTrue(seen_payloads[0]["auto_generate_text"])
        self.assertNotIn("text", seen_payloads[0])

    # 24. Regression: Manifest/script IDs cannot cause path traversal in output filenames
    def test_24_filename_path_traversal_sanitization(self) -> None:
        for bad in ("../evil", "../../etc/passwd", "foo/bar", "a\\b", "..", ""):
            with self.assertRaises(ValueError):
                sanitize_filename_token(bad, "line_id")
            with self.assertRaises(ValueError):
                build_predictable_filename("S01", bad, "narrator", "V01", ext="wav")

        safe_name = build_predictable_filename("S01", "S01_L01", "Mr. Arthur", "V06", ext="wav")
        self.assertEqual(safe_name, "S01_S01_L01_Mr_Arthur_V06.wav")
        resolved = resolve_safe_child_path(self.tmp_dir, safe_name)
        self.assertEqual(resolved.parent, self.tmp_dir.resolve())
        with self.assertRaises(ValueError):
            resolve_safe_child_path(self.tmp_dir, "../escaped.wav")

    # 25. Regression: examples/ package ships no committed binary audio samples or derived stems
    def test_25_examples_package_contains_no_binary_audio_samples(self) -> None:
        examples_dir = REPO_ROOT / "examples"
        audio_exts = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}
        found = [
            str(p.relative_to(REPO_ROOT))
            for p in examples_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in audio_exts
        ]
        self.assertEqual(found, [], f"Committed binary audio files found in examples/: {found}")

    # 26. Regression: project_id path traversal rejected when muxing default output video path
    def test_26_project_id_path_traversal_rejected_in_pipeline(self) -> None:
        def mock_ok(method, url, headers, body, timeout):
            return HTTPResponseData(200, {"content-type": "audio/wav"}, self.valid_wav_bytes)

        src_vid = self.tmp_dir / "src.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x102030:s=360x640:r=24:d=1.5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(src_vid),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
        )
        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
                intended_character="narrator",
            )
        )
        pipeline = VoiceGenerationPipeline(
            profile_manager=mgr,
            provider_registry=ProviderRegistry([ElevenLabsAdapter(transport=mock_ok)]),
        )
        with self.assertRaises(ValueError):
            pipeline.run_script_pipeline(
                project_id="../../escaped_project",
                project_title="Traversal Test",
                script_text="Narrator: Testing project_id sanitization.",
                output_dir=self.tmp_dir / "pipe_out",
                state_path=self.tmp_dir / "pipe_state.json",
                source_video_path=src_vid,
                output_format="wav",
                raw_ext="wav",
            )

    # 27. Regression: VoiceDesigner allows empty sample_text (auto_generate_text=True) & filters TTS controls
    def test_27_voice_designer_empty_sample_text_and_control_filtering(self) -> None:
        captured: List[Dict[str, object]] = []

        def mock_design(method, url, headers, body, timeout):
            captured.append(json.loads(body.decode("utf-8")) if body else {})
            if url.endswith("/v1/text-to-voice/design"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"previews": [{"generated_voice_id": "gen_auto_1"}]}).encode("utf-8"),
                )
            if url.endswith("/v1/text-to-voice"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"voice_id": "el_auto_1"}).encode("utf-8"),
                )
            return HTTPResponseData(404, {}, b"{}")

        mgr = VoiceProfileManager(self.store_path)
        designer = VoiceDesigner(mgr)
        res = designer.create_designed_voice(
            ElevenLabsAdapter(transport=mock_design),
            VoiceDesignSpec(
                voice_id="V04",
                display_name="Auto Text Voice",
                voice_description="Warm adult female narrator with calm, steady documentary cadence.",
                sample_text="",
                requested_controls={"guidance_scale": 6.0, "stability": 0.7, "speed": 1.1},
            ),
        )
        self.assertEqual(res["applied_controls"], {"guidance_scale": 6.0})
        self.assertIn("stability", res["ignored_controls"])
        self.assertIn("speed", res["ignored_controls"])
        self.assertTrue(captured[0]["auto_generate_text"])
        self.assertEqual(captured[0]["guidance_scale"], 6.0)

    # 28. Regression: multipart clone upload escapes quotes/control chars in sample filenames
    def test_28_multipart_clone_filename_header_sanitization(self) -> None:
        raw_bodies: List[bytes] = []

        def mock_upload(method, url, headers, body, timeout):
            raw_bodies.append(body or b"")
            return HTTPResponseData(
                200,
                {"content-type": "application/json"},
                json.dumps({"voice_id": "el_mp_1"}).encode("utf-8"),
            )

        tricky_sample = self.tmp_dir / 'clip"quote.wav'
        tricky_sample.write_bytes(self.valid_wav_bytes)
        adapter = ElevenLabsAdapter(transport=mock_upload)
        _, body_bytes = adapter._build_clone_multipart_body(
            name="Safe Header Test",
            description="Test filename escaping",
            sample_paths=[tricky_sample],
        )
        header_text = body_bytes.decode("utf-8", errors="ignore")
        with self.assertRaises(ProviderCapabilityError):
            adapter.create_authorized_clone(
                name="Safe Header Test",
                description="Test filename escaping",
                sample_paths=[tricky_sample],
            )
        self.assertEqual(raw_bodies, [])
        self.assertIn('filename="clip_quote.wav"', header_text)
        self.assertNotIn('filename="clip"quote.wav"', header_text)

    # 29. Regression (F-01): Reject non-HTTP(S) provider URL schemes (e.g., file://, ftp://)
    def test_29_provider_rejects_non_http_url_schemes(self) -> None:
        for bad_url in ("file:///etc/passwd", "ftp://example.com/v1", "http://api.elevenlabs.io/v1", "not_a_url"):
            with self.assertRaises(ValueError):
                ElevenLabsAdapter(base_url=bad_url)
        # Explicit allow_insecure_http=True permits local http test servers, still blocks file://
        adapter_local = ElevenLabsAdapter(base_url="http://127.0.0.1:8080/v1", allow_insecure_http=True)
        self.assertEqual(adapter_local.base_url, "http://127.0.0.1:8080/v1")
        with self.assertRaises(ValueError):
            ElevenLabsAdapter(base_url="file:///etc/passwd", allow_insecure_http=True)

    # 30. Regression (F-02): Malformed JSON on HTTP 200 raises ProviderResponseError (not raw JSONDecodeError)
    def test_30_malformed_json_200_raises_provider_response_error(self) -> None:
        def mock_html_200(method, url, headers, body, timeout):
            return HTTPResponseData(200, {"content-type": "text/html"}, b"<html>Bad Gateway</html>")

        adapter = ElevenLabsAdapter(transport=mock_html_200)
        with self.assertRaises(ProviderResponseError) as ctx:
            adapter.check_authentication()
        self.assertTrue(ctx.exception.retryable)

    # 31. Regression (F-03): Missing ffprobe/ffmpeg binary returns structured invalid report (no unhandled crash)
    def test_31_missing_ffmpeg_ffprobe_handled_gracefully(self) -> None:
        from unittest.mock import patch

        valid_wav = self.tmp_dir / "probe_target.wav"
        valid_wav.write_bytes(self.valid_wav_bytes)
        with patch("voice_intelligence.audio_qc.subprocess.run", side_effect=FileNotFoundError("ffprobe")):
            rep = inspect_audio_file(valid_wav)
        self.assertFalse(rep["valid"])
        self.assertTrue(any("not found on PATH" in e for e in rep["errors"]))

    # 32. Regression (F-04): Atomic JSON persistence leaves no temp files & error bodies redact active API key
    def test_32_atomic_json_persistence_and_error_key_redaction(self) -> None:
        os.environ["ELEVENLABS_API_KEY"] = "secret_key_xyz_987654"

        def mock_echo_secret(method, url, headers, body, timeout):
            return HTTPResponseData(
                401,
                {"content-type": "application/json"},
                b'{"detail":"Rejected key secret_key_xyz_987654"}',
            )

        adapter = ElevenLabsAdapter(transport=mock_echo_secret)
        with self.assertRaises(ProviderAuthError) as ctx:
            adapter.check_authentication()
        self.assertNotIn("secret_key_xyz_987654", str(ctx.exception))
        self.assertIn("[REDACTED]", str(ctx.exception))

        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Atomic Test",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_v01",
            )
        )
        leftover_tmps = list(self.tmp_dir.glob("*.tmp"))
        self.assertEqual(leftover_tmps, [])

    # 33. Regression (F-05): mux_audio_and_subtitles_to_video rejects negative/NaN/out-of-range volumes
    def test_33_mux_rejects_invalid_volume_parameters(self) -> None:
        for bad_vol in (-0.5, float("nan"), float("inf"), 99.0):
            with self.assertRaises(VideoMuxError):
                mux_audio_and_subtitles_to_video(
                    video_path=self.tmp_dir / "v.mp4",
                    dialogue_audio_path=self.tmp_dir / "a.wav",
                    output_video_path=self.tmp_dir / "out.mp4",
                    bgm_volume=bad_vol,
                )

    # 34. Regression (F-06): Symlink inside target directory pointing outside is rejected
    def test_34_symlink_escape_rejected_by_resolve_safe_child_path(self) -> None:
        outside = self.tmp_dir / "outside.wav"
        outside.write_bytes(b"outside")
        sub = self.tmp_dir / "sandbox_sub"
        sub.mkdir()
        link = sub / "evil_link.wav"
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            resolve_safe_child_path(sub, "evil_link.wav")

    # 35. Regression (F-06): Configured but unimplemented OpenAI/Google stubs cannot be selected for TTS
    def test_35_configured_unimplemented_stubs_never_selected(self) -> None:
        old_oai = os.environ.get("OPENAI_API_KEY")
        old_gcp = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        os.environ.pop("ELEVENLABS_API_KEY", None)
        os.environ["OPENAI_API_KEY"] = "fake_openai_key_for_test"
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/tmp/fake_gcp.json"
        try:
            oai = OpenAITTSAdapter()
            gcp = GoogleCloudTTSAdapter()
            self.assertFalse(oai.capabilities().implemented)
            self.assertFalse(oai.capabilities().text_to_speech)
            self.assertFalse(gcp.capabilities().implemented)
            self.assertFalse(gcp.capabilities().text_to_speech)

            reg = ProviderRegistry([ElevenLabsAdapter(), oai, gcp, RecordedVoiceProviderAdapter()])
            with self.assertRaises(ProviderCapabilityError):
                reg.select_provider(required_capability="text_to_speech", require_configured=True)
            with self.assertRaises(ProviderCapabilityError):
                reg.select_provider(preferred_provider="openai_tts", required_capability="text_to_speech")
            with self.assertRaises(ProviderCapabilityError):
                reg.select_provider(preferred_provider="google_cloud_tts", required_capability="text_to_speech")
        finally:
            if old_oai is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_oai
            if old_gcp is None:
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            else:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = old_gcp

    # 36. Regression (F-07): _normalize_stem_to_pcm_wav handles timeout & missing ffmpeg and removes partial files
    def test_36_normalize_stem_timeout_and_missing_ffmpeg_cleans_partial(self) -> None:
        from unittest.mock import patch
        from voice_intelligence.pipeline import _normalize_stem_to_pcm_wav

        src_wav = self.tmp_dir / "in.wav"
        src_wav.write_bytes(self.valid_wav_bytes)
        dst_wav = self.tmp_dir / "partial_stem.wav"
        dst_wav.write_bytes(b"partial")

        with patch("voice_intelligence.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120.0)):
            with self.assertRaises(RuntimeError) as ctx:
                _normalize_stem_to_pcm_wav(src_wav, dst_wav)
        self.assertIn("timed out", str(ctx.exception))
        self.assertFalse(dst_wav.exists())

        dst_wav.write_bytes(b"partial2")
        with patch("voice_intelligence.pipeline.subprocess.run", side_effect=FileNotFoundError("ffmpeg")):
            with self.assertRaises(RuntimeError) as ctx2:
                _normalize_stem_to_pcm_wav(src_wav, dst_wav)
        self.assertIn("not found on PATH", str(ctx2.exception))
        self.assertFalse(dst_wav.exists())

    # 37. Regression (F-08): Profile validation forbids verified_authorized/available on self-attested clones
    def test_37_cloning_unavailable_by_default_and_never_verified_authorized(self) -> None:
        with self.assertRaises(ValueError):
            VoiceProfile(
                voice_id="V01",
                display_name="Invalid Verified Clone",
                voice_type="authorized_cloned",
                provider="elevenlabs",
                consent_status="verified_authorized",
                consent_record={"independent_identity_verified": False},
                availability_status="unavailable",
            ).validate()

        with self.assertRaises(ValueError):
            VoiceProfile(
                voice_id="V01",
                display_name="Invalid Available Clone",
                voice_type="authorized_cloned",
                provider="elevenlabs",
                consent_status="self_attested_unverified",
                consent_record={"independent_identity_verified": False},
                availability_status="available",
            ).validate()

    # 38. Regression (F-09): VoiceDesigner pre-validates duplicate IDs (0 remote calls) & rolls back on save failure
    def test_38_voice_designer_prevalidates_duplicate_and_rolls_back_on_save_failure(self) -> None:
        from unittest.mock import patch

        calls: List[str] = []

        def mock_design_and_delete(method, url, headers, body, timeout):
            calls.append(f"{method} {url}")
            if url.endswith("/v1/text-to-voice/design"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"previews": [{"generated_voice_id": "gen_rb_1"}]}).encode("utf-8"),
                )
            if url.endswith("/v1/text-to-voice"):
                return HTTPResponseData(
                    200,
                    {"content-type": "application/json"},
                    json.dumps({"voice_id": "el_rb_1"}).encode("utf-8"),
                )
            if method == "DELETE" and url.endswith("/v1/voices/el_rb_1"):
                return HTTPResponseData(200, {"content-type": "application/json"}, b'{"status":"ok"}')
            return HTTPResponseData(404, {}, b"{}")

        mgr = VoiceProfileManager(self.store_path)
        mgr.create_profile(
            VoiceProfile(
                voice_id="V02",
                display_name="Existing V02",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_existing",
            )
        )
        adapter = ElevenLabsAdapter(transport=mock_design_and_delete)
        designer = VoiceDesigner(mgr)

        # Duplicate voice_id must fail BEFORE calling provider (0 HTTP calls)
        with self.assertRaises(ValueError):
            designer.create_designed_voice(
                adapter,
                VoiceDesignSpec(
                    voice_id="V02",
                    display_name="Duplicate",
                    voice_description="Calm adult narrator voice with clear studio articulation.",
                ),
            )
        self.assertEqual(calls, [])

        # If local save fails after remote creation, remote voice is rolled back via DELETE
        with patch.object(mgr, "create_profile", side_effect=OSError("disk full")):
            with self.assertRaises(RuntimeError) as ctx:
                designer.create_designed_voice(
                    adapter,
                    VoiceDesignSpec(
                        voice_id="V06",
                        display_name="Rollback Voice",
                        voice_description="Warm elder storyteller voice with gentle pacing.",
                    ),
                )
        self.assertIn("remote_voice_deleted", str(ctx.exception))
        self.assertIn("DELETE https://api.elevenlabs.io/v1/voices/el_rb_1", calls)

    # 39. Regression (F-10): ElevenLabs IVC multipart upload uses `files[]` field name per official cURL spec
    def test_39_elevenlabs_ivc_multipart_uses_files_array_field(self) -> None:
        bodies: List[bytes] = []

        def mock_ivc(method, url, headers, body, timeout):
            bodies.append(body or b"")
            return HTTPResponseData(
                200,
                {"content-type": "application/json"},
                json.dumps({"voice_id": "el_ivc_1"}).encode("utf-8"),
            )

        sample = self.tmp_dir / "sample.wav"
        sample.write_bytes(self.valid_wav_bytes)
        ivc_adapter = ElevenLabsAdapter(transport=mock_ivc)
        _, ivc_body = ivc_adapter._build_clone_multipart_body(
            name="IVC Field Test",
            description="Check multipart field name",
            sample_paths=[sample],
        )
        decoded = ivc_body.decode("utf-8", errors="ignore")
        with self.assertRaises(ProviderCapabilityError):
            ivc_adapter.create_authorized_clone(
                name="IVC Field Test",
                description="Check multipart field name",
                sample_paths=[sample],
            )
        self.assertEqual(bodies, [])
        self.assertIn('name="files[]"', decoded)

    # 40. Regression (F-08 & F-09): Cloner staging makes ZERO provider calls and handles duplicate ID & save failure
    def test_40_cloner_never_calls_provider_and_handles_duplicate_and_save_failure(self) -> None:
        from unittest.mock import patch

        http_calls: List[str] = []

        def spy_transport(method, url, headers, body, timeout):
            http_calls.append(f"{method} {url}")
            return HTTPResponseData(500, {}, b'{"detail":"Must never be called"}')

        sample_path = self.tmp_dir / "adult_sample_f08.wav"
        sample_path.write_bytes(self.valid_wav_bytes)
        adapter = ElevenLabsAdapter(transport=spy_transport)
        mgr = VoiceProfileManager(self.store_path)
        cloner = AuthorizedVoiceCloner(mgr, min_sample_duration_sec=0.5)
        valid_consent = ConsentAttestation(
            explicit_authorization_confirmed=True,
            speaker_is_adult=True,
            authorized_by="creator_owner",
            speaker_relationship="self_creator",
        )

        # Staging succeeds locally with ZERO provider HTTP calls
        staged = cloner.clone_authorized_voice(
            adapter,
            voice_id="V01",
            display_name="Local Staged Only",
            description="Strictly local staging",
            sample_paths=[sample_path],
            consent=valid_consent,
            allow_unverified_staging=True,
        )
        self.assertEqual(http_calls, [])
        self.assertFalse(staged["remote_submission_performed"])
        self.assertIsNone(staged["profile"]["provider_voice_id"])
        self.assertEqual(staged["profile"]["consent_status"], "self_attested_unverified")
        self.assertEqual(staged["profile"]["availability_status"], "unavailable")

        # Duplicate local voice_id raises ValueError with ZERO provider calls
        with self.assertRaises(ValueError):
            cloner.clone_authorized_voice(
                adapter,
                voice_id="V01",
                display_name="Duplicate Cloner ID",
                description="Should abort cleanly",
                sample_paths=[sample_path],
                consent=valid_consent,
                allow_unverified_staging=True,
            )
        self.assertEqual(http_calls, [])

        # Local persistence failure raises RuntimeError cleanly with ZERO provider calls
        with patch.object(mgr, "create_profile", side_effect=OSError("disk full")):
            with self.assertRaises(RuntimeError) as ctx:
                cloner.clone_authorized_voice(
                    adapter,
                    voice_id="V05",
                    display_name="Save Failure Test",
                    description="Should fail cleanly",
                    sample_paths=[sample_path],
                    consent=valid_consent,
                    allow_unverified_staging=True,
                )
        self.assertIn("no remote voice was created", str(ctx.exception))
        self.assertEqual(http_calls, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
