# Voice Identity Lock System (`V01`–`V06`)

Load during **Stages C, D, H, J, and L** whenever assigning, directing, generating, or auditing voices across Shorts, episodes, mini-movies, documentaries, or feature-length Roblox productions.

## 1. Permanent Internal Voice Identities

Internal voice IDs (`V01`–`V06`) are **permanent and provider-independent**. They never change when a project switches TTS/voice providers, devices, or AI agents. Canonical definitions live in [templates/voice-registry.json](../templates/voice-registry.json).

| Internal ID | Voice Name | Character Category | Core Purpose |
| :--- | :--- | :--- | :--- |
| **`V01`** | My Reference Voice | Creator Reference Narrator / Lead | Primary narrator or creator-selected lead voice anchored to private reference clips. |
| **`V02`** | Mature Adult Male | Adult Male | Fathers, leaders, mentors, authority figures, historical characters. |
| **`V03`** | Teenage Boy | Youth Male (Fictional Synthetic) | Teenage protagonists, friends, school characters, young male supporting roles. |
| **`V04`** | Mature Adult Female | Adult Female | Mothers, teachers, leaders, narrators, adult female supporting roles. |
| **`V05`** | Teenage Girl | Youth Female (Fictional Synthetic) | Teenage protagonists, friends, school characters, young female supporting roles. |
| **`V06`** | Elder Storyteller | Elder / Senior | Grandparents, village elders, historical storytellers, wise characters, flashback narration. |

## 2. Safety, Consent & Reference Privacy Rules

1. **No Cloning of Real Minors or Identifiable Third Parties:** `V03` (Teenage Boy) and `V05` (Teenage Girl) must **always** be fictional synthetic voices. Never clone real minors or imitate identifiable real people.
2. **V01 Eligibility & Rights Verification:** Before using reference-based generation or voice cloning for `V01`, verify the chosen provider's actual eligibility, consent, rights, and age policies. Never bypass provider restrictions. If reference audio comes from a finished video mix containing background music, SFX, or secondary speakers, isolate clean single-speaker speech (and verify rights/authorization) before provider upload.
3. **Private Reference Storage:** Never commit or publish private reference recordings (`.mp4`, `.wav`, `.mp3`) in a public GitHub repository unless the creator explicitly authorizes public distribution. Store only local/private path pointers in `voice-registry.json`.
4. **Never Fabricate Provider Voice IDs:** Never invent provider-specific voice IDs, numerical pitch values, or unverified accent traits. Record `"UNASSIGNED"`, `"not assessed"`, `"unknown"`, or `"provider dependent"` until verified.

## 3. Voice Assignment & Lock Rules

- **One Character, One Voice:** Every character receives exactly one locked internal `voice_id` mapped in the project manifest (`character_id -> voice_id -> provider_voice_id`) unless the script explicitly calls for an in-story voice change (e.g., disguise, age jump, supernatural mimicry—labeled explicitly in the manifest).
- **No Accidental Voice Collision:** Do not assign the protagonist's or narrator's `voice_id` to a secondary character speaking in the same scene. When a cast exceeds six speaking roles, reuse voices only across non-overlapping scenes with distinct pacing/delivery notes, or flag the need for an additional provider voice slot.
- **Reference Preservation (`V01`):** Retain the cleanest single primary reference clip plus supporting reference clips in private storage. Never silently replace `V01` references without creator approval.

## 4. Cross-Scene, Cross-Chapter & Cross-Episode Consistency

- **Cross-Scene:** Load `voice-registry.json` and the active `project-voice-manifest.json` before generating or directing any new scene.
- **Cross-Chapter / Multi-Part Mini-Movies:** Preserve `voice_id`, provider binding, and approved generation settings across all acts and chapters.
- **Cross-Episode / Sequels:** Carry forward the `character_id -> voice_id` table unchanged so returning characters sound identical across episodes.

## 5. Provider Switching, Substitution & Recovery

- **Provider Switching:** Keep `V01`–`V06` internal IDs intact. Update only `provider_binding` (`provider_name`, `provider_voice_id`, `generation_settings`) and log the migration in `verification_history`.
- **Voice Substitution Rule:** If a bound `provider_voice_id` becomes unavailable or a provider lacks a required capability (e.g., reference-based generation for `V01`), **stop and report the blocker**. Propose a candidate replacement for creator approval—never silently substitute an unrelated voice.
- **Recovery After Interruptions:** When resuming an interrupted production, reload `project-voice-manifest.json` first, verify which lines already have `approved` audio assets, and generate only missing or unapproved lines. Do not regenerate already-approved takes unnecessarily.

## 6. Voice Verification Checklist (Stage L)

Before approving voice assets for final assembly, confirm:
1. Every speaking character and narrator maps to a valid `voice_id` in `voice-registry.json`.
2. No character changes voice unintentionally across scenes or chapters.
3. Dialogue files are separated by speaker (`character_id` + line ID).
4. `V03`/`V05` are strictly fictional synthetic voices and `V01` meets provider consent/policy rules.
5. Generated outputs were actually listened to and checked (otherwise mark status `NOT RUN` or `BLOCKED`).
