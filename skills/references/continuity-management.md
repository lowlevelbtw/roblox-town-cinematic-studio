# Character, Voice, and Production Continuity Management

Load during **Stages F, G, H, J, and L** for multi-scene Shorts, episodic series, mini-movies, documentaries, and feature-length productions.

## 1. Persistent Mapping Architecture

Every production with speaking roles maintains a persistent mapping chain in [templates/project-voice-manifest.json](../templates/project-voice-manifest.json):

```text
character_id -> voice_id (V01–V06) -> provider_voice_id (when bound)
```

- **`character_id`:** Stable snake_case identifier (e.g., `narrator_main`, `protagonist_ryan`, `dad_character`, `elder_keeper`).
- **`voice_id`:** Permanent internal voice ID (`V01`–`V06`) from [templates/voice-registry.json](../templates/voice-registry.json).
- **`provider_voice_id`:** External provider identifier (or `null` / `"UNASSIGNED"` until bound to a verified provider).

## 2. Continuity Locks Across Productions

1. **No Random Voice Drift:** Once a `character_id` is mapped to a `voice_id`, it must stay locked across all scenes, chapters, episodes, and sequels unless an explicit in-story change is documented in the manifest.
2. **Protagonist & Narrator Protection:** Supporting characters must never accidentally inherit the protagonist's or narrator's `voice_id` in overlapping scenes.
3. **Speaker-Separated Dialogue Stems:** Export or track every line by `scene_id`, `line_id`, `character_id`, and `voice_id` (e.g., `S01_L03_protagonist_V03.wav`) so editors can adjust levels, pauses, and captions independently per speaker.
4. **Asset Preservation (No Unnecessary Regeneration):** Mark reviewed and accepted clips as `"approved"` with their file path or asset reference in `project-voice-manifest.json`. Never regenerate approved audio assets when revising a different scene or resuming a session.
5. **Provider Migration Continuity:** When migrating from Provider A to Provider B, preserve every `character_id -> voice_id` binding unchanged; update only `provider_name`, `provider_voice_id`, and `generation_settings`, then log the migration in `verification_history`.

## 3. Unavailable Voice & Substitution Protocol

If a bound `provider_voice_id` is deprecated, removed, or blocked by plan/policy limits:
1. Flag the affected `voice_id` and `character_id` entries as `BLOCKED` in the manifest.
2. Report the exact cause to the creator (never silently swap in an unrelated voice).
3. Propose 1–2 candidate replacement bindings that match the `voice_id` profile in `voice-registry.json`, and wait for creator approval before regenerating unapproved lines.

## 4. Interruption & Resume Workflow

When production resumes after a break, session timeout, or tool switch:
1. Reload `skills/roblox-town-director/templates/voice-registry.json` and the active `project-voice-manifest.json`.
2. Reconcile completed vs. pending lines (`approved`, `draft`, `pending`, `blocked`).
3. Verify the connected provider still exposes the expected `provider_voice_id` and capabilities via [voice-provider-adapter.md](voice-provider-adapter.md).
4. Resume strictly from the first `pending` or `draft` line while preserving all `approved` assets and existing visual/wardrobe continuity locks (see [cinematic-direction.md](cinematic-direction.md)).
