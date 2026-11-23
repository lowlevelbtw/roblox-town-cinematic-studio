# Recorded Voice Test Project (Synthetic Local Example)

This example demonstrates `skills/roblox-town-director/scripts/voice_backend.py` without committing binary audio samples or derived stems to the repository.

## Run Locally

From the repository root:

```bash
# 1. Generate synthetic WAV/MP3 tone fixtures and a corrupt-file fixture locally
python3 examples/recorded-voice-test-project/generate_synthetic_fixtures.py

# 2. Run the Recorded Voice Backend against the example manifest
python3 skills/roblox-town-director/scripts/voice_backend.py \
  --manifest examples/recorded-voice-test-project/project-voice-manifest.json \
  --registry skills/roblox-town-director/templates/voice-registry.json \
  --output-dir examples/recorded-voice-test-project/output
```

Expected local result: `2` approved lines (`V01`, `V03`), `1` corrupt recording rejected (`corrupt_maya_line3.wav`), `1` missing recording reported honestly (`0` fabricated audio jobs).
