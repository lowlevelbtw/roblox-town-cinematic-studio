# Universal Voice Provider Adapter Contract

Load during **Stages F, H, and J** whenever checking available audio/TTS tools or binding `V01`–`V06` to a voice provider.

## 1. Provider-Independence Principle

`roblox-town-director` does **not** hardcode ElevenLabs, OpenAI, Google, local open-source TTS, or any single vendor. Different AI agents (Claude Code, Codex, Gemini CLI, ChatGPT, Claude App, Meta Muse, custom APIs, or local scripts) expose different—or zero—audio tools.

Always run **capability discovery** before promising or attempting voice generation.

## 2. Capability Discovery Matrix

For any connected provider or local tool, record only **verified** capability values (`true`, `false`, or `"unknown"`—never assume):

| Capability Key | What It Verifies | Non-Assumption Rule |
| :--- | :--- | :--- |
| `text_to_speech` | Generates speech audio from text input. | Does **not** imply voice cloning or persistent IDs. |
| `voice_reference_input` | Accepts reference audio clips to guide voice output. | Requires checking provider audio cleanliness & format rules. |
| `authorized_voice_cloning` | Supports creating a reusable voice from authorized reference clips. | Must verify provider eligibility, age, and consent policies first. |
| `custom_voice_creation` | Supports designing synthetic voices from text prompts/parameters (needed for `V02`–`V06`). | Distinct from cloning real speakers. |
| `emotion_delivery_controls` | Supports explicit style, stability, or emotion parameters. | If `false`, express delivery via punctuation and text phrasing only. |
| `pronunciation_dictionaries` | Supports custom phonetic/lexicon overrides. | If `false`, use phonetic respelling notes in the script. |
| `speech_speed_controls` | Supports rate/speed adjustments without pitch distortion. | Verify before relying on exact runtime compression. |
| `audio_file_export` | Exports downloadable audio files (`.wav`, `.mp3`, etc.). | Verify sample rate and format before editing handoff. |
| `batch_generation` | Supports generating multiple scripted lines in one run. | If `false`, generate line-by-line per speaker stem. |
| `persistent_voice_ids` | Returns a stable `provider_voice_id` reusable across sessions. | Generating audio once does **not** guarantee voice persistence. |

## 3. Standard Adapter Contract (JSON Shape)

Any local, open-source, proprietary, or MCP-connected voice adapter maps into this canonical structure:

```json
{
  "adapter_id": "provider_slug",
  "provider_name": "Human-readable provider name",
  "adapter_type": "hosted_api | local_open_source | mcp_tool | manual_export",
  "capabilities": {
    "text_to_speech": "unknown",
    "voice_reference_input": "unknown",
    "authorized_voice_cloning": "unknown",
    "custom_voice_creation": "unknown",
    "emotion_delivery_controls": "unknown",
    "pronunciation_dictionaries": "unknown",
    "speech_speed_controls": "unknown",
    "audio_file_export": "unknown",
    "batch_generation": "unknown",
    "persistent_voice_ids": "unknown"
  },
  "policy_notes": "Record verified commercial license, attribution, consent, and age requirements.",
  "verification_status": "UNVERIFIED | VERIFIED | BLOCKED"
}
```

## 4. Blocker & Fallback Handling

- **No Compatible Provider Connected:** Explicitly report that the **voice-generation execution stage is `BLOCKED`** (do not pretend audio was generated, and do not silently substitute an unrelated voice). Deliver the complete speaker-separated script, `voice_id` assignments (`V01`–`V06`), delivery cues, and manifest so the creator can run generation in their chosen external tool or record human VO.
- **Partial Capability Match (e.g., TTS works, Reference Cloning unsupported):** Allow synthetic roles (`V02`–`V06`) only where verified, retain `V01`'s profile intact, and explicitly report that `V01` reference-based generation is unsupported on the active provider.
- **Commercial & Policy Verification:** Never assume a free tier grants commercial monetization rights. Verify current official terms per provider before publishing monetized videos.

## 5. Executable Recorded Voice Backend (`scripts/voice_backend.py`)

When an external TTS provider is unavailable or the creator supplies human/recorded voice clips, use the interchangeable **`RecordedVoiceBackend`** in [scripts/voice_backend.py](../scripts/voice_backend.py) (powered by Python 3.9+ and `ffmpeg`/`ffprobe`):
- Imports WAV, MP3, and other FFmpeg-supported formats mapped to permanent `V01`–`V06` IDs via `project-voice-manifest.json`.
- Validates audio streams, duration, sample rate, channels, and missing files; trims, normalizes loudness, converts to 44.1 kHz stereo 16-bit PCM WAV, additively mixes overlapping speakers with peak-clipping prevention (`-1.0 dBFS` headroom), validates timeline/subtitle timing without silent truncation, writes synchronized `subtitles.srt`, and generates `voice_job_report.json` / `voice_job_report.md`.

## 6. Modular Voice Intelligence & Authorized Cloning Module (`scripts/voice_intelligence/`)

For provider-backed voice profiles, voice design, consent-gated voice cloning, automatic character assignment, and resumable TTS generation, use the modular package under `scripts/voice_intelligence/`:

- **`profile_manager.py` (`VoiceProfileManager`):** Persists permanent voice profiles (`V01`–`V06` and custom IDs) with `voice_type` (`original_synthetic`, `authorized_cloned`, `recorded_human`), provider bindings, consent records, availability status, and disable/revoke/remove operations.
- **`providers.py` (`ProviderRegistry`, `ElevenLabsAdapter`, `OpenAITTSAdapter`, `GoogleCloudTTSAdapter`, `RecordedVoiceProviderAdapter`):** Modular provider interface with capability detection. `ElevenLabsAdapter` uses stdlib `urllib.request` and reads `ELEVENLABS_API_KEY` from the environment only (never hardcoded, logged, or stored in manifests). `OpenAITTSAdapter` and `GoogleCloudTTSAdapter` provide interchangeable capability-declared contracts (live API execution not yet implemented).
- **`voice_design.py` (`VoiceDesigner`):** Creates original synthetic voices from descriptive specs while mapping only controls supported by the active provider.
- **`voice_cloning.py` (`AuthorizedVoiceCloner`):** Strictly consent-gated workflow—requires explicit adult authorization (`ConsentAttestation`), blocks minors and unauthorized impersonation, validates imported samples locally via FFprobe/FFmpeg while keeping **remote voice cloning submission unconditionally disabled in `v0.2.0` at both `AuthorizedVoiceCloner` and `ElevenLabsAdapter.create_authorized_clone()`** (zero audio uploaded, zero remote voice resources created). Default calls raise `VoiceCloningConsentError`; local-only staging (`allow_unverified_staging=True`) persists `provider_voice_id=None`, `consent_status="self_attested_unverified"`, and `availability_status="unavailable"` (never `verified_authorized` or `available`), and supports local revoking/removal.
  - **Consent vs. Identity Verification Boundary:** `ConsentAttestation` records user-provided self-attestation only and explicitly persists `"independent_identity_verified": false` (`"attestation_type": "user_self_attestation"`). A user consent declaration or checkbox must never be treated as independent verification of speaker identity, legal age, or commercial rights; attempting to assert `independent_identity_verified=True` without an integrated external verification system is rejected.
- **`character_assignment.py` (`CharacterVoiceAssigner`):** Parses scripts, assigns persistent character-to-voice mappings across scenes, and blocks rather than silently substituting when a locked voice becomes unavailable (requiring explicit user-approved fallback).
- **`pipeline.py` (`VoiceGenerationPipeline`) & `audio_qc.py`:** Runs the resumable 11-stage generation pipeline with predictable filenames, skips already-approved lines on recovery, retries transient failures, reuses `voice_backend.py` for additive mixing and SRT export, and runs FFprobe/FFmpeg technical QC while explicitly marking subjective speech naturalness as `requires_human_listening: true`.

- **`__main__.py` (CLI Entrypoint) & `mux_audio_and_subtitles_to_video`:** Run `python3 -m voice_intelligence <auth-check|list-voices|profiles|run-pipeline|audio-qc|mux-video>` (never prints API keys). `mux_audio_and_subtitles_to_video` preserves source video resolution/FPS via `-c:v copy` and supports `preserve_source_audio: bool = False` (replaces source audio by default; mixes attenuated source audio through `alimiter` when `True`, handling silent source videos gracefully). Note: `run_script_pipeline` schedules script lines sequentially; overlapping timestamps are supported via `voice_backend.py` manifests.
- **Acceptance Criteria:** See [evaluations/voice-intelligence-acceptance.md](../evaluations/voice-intelligence-acceptance.md).

> **Verification Boundary:** All **82 automated tests** (`8/8` in `tests/test_voice_backend.py` + `40/40` in `tests/test_voice_intelligence.py` + `34/34` in `tests/test_v020_production.py`) pass locally with real FFmpeg/FFprobe media validation and mocked provider/connector HTTP responses. Live ElevenLabs API calls remain `BLOCKED`/unverified in offline environments or whenever no connector credential or `ELEVENLABS_API_KEY` is configured.
