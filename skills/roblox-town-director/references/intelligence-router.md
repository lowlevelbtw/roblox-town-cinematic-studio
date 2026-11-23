# Intelligence Router & Task-Based Model Selection

Load at session start and during **Stages A, F, G, H, I, J, and L** alongside [adaptive-intelligence.md](adaptive-intelligence.md), [task-decomposition.md](task-decomposition.md), and [templates/model-capability-registry.json](../templates/model-capability-registry.json).

## 1. Core Routing Principle & Capability Distinctions

Never force a single AI model to perform every filmmaking job when specialized models or tools are available. Route each production task by **actual runtime availability and verified capability**—never by brand reputation, parameter count, or mere presence in a registry file.

Always distinguish these four states explicitly:
1. **Discovered models:** Models actively detected at runtime via the current agent's API, CLI, or orchestration environment.
2. **Configured models:** Models manually entered by the user in `templates/model-capability-registry.json` (not guaranteed reachable until checked).
3. **Available tools:** Concrete tools, binaries, or integrations actually declared and callable in the current session (e.g., image generator, shell/`ffmpeg`, file I/O, connected MCP/TTS provider).
4. **Experimentally verified capabilities:** Capabilities proven by actual execution and inspected outputs (not merely claimed in docs or registry templates).

**Registry Non-Selection Rule:** Never select a model or provider merely because it appears in `model-capability-registry.json`. Confirm runtime availability and required permissions before routing any task to it.

### 11 Defined Routing Capabilities
1. `creative_reasoning` — Premise stress-testing, subtext, Dual-Gate A/B critique, dramatic structure.
2. `storytelling` — Narrative architecture, character arcs, dialogue, *"In This Town..."* pacing.
3. `research` — Verifying Roblox experience features, platform docs, audio licensing, factual accuracy.
4. `coding` — Python/Blender scripts, Roblox Studio Luau scripts, FFmpeg/Remotion editing automation, JSON validation.
5. `image_generation` — Reference-locked character sheets, keyframes, stylized backgrounds, thumbnails.
6. `video_generation` — AI video synthesis and motion clips where supported.
7. `3d_and_animation` — 3D scene layout, rigging, keyframed animation, procedural camera/lighting control.
8. `text_to_speech` — Spoken dialogue/narration bound to `V01`–`V06` via [voice-provider-adapter.md](voice-provider-adapter.md).
9. `audio_processing` — Stem mixing, loudness normalization, SFX synthesis, noise/music isolation checks.
10. `video_editing` — Timeline assembly, cutting on action, transitions, burned-in captions, rendering.
11. `quality_assessment` — Multimodal visual/audio inspection, continuity verification, export validation.

## 2. Task-to-Capability Routing Matrix

| Production Task | Primary Required Capability | Secondary / Support |
| :--- | :--- | :--- |
| Concept, story & script | `storytelling` + `creative_reasoning` | `research` |
| Production planning & task graph | `creative_reasoning` | `coding` (JSON validation) |
| Blender Python / Roblox Luau / FFmpeg / Remotion scripts | `coding` | `3d_and_animation` |
| Character designs, keyframes & thumbnails | `image_generation` | `quality_assessment` |
| Character/scene animation & video clips | `3d_and_animation` or `video_generation` | `coding` |
| Spoken dialogue & narration (`V01`–`V06`) | `text_to_speech` | `audio_processing` |
| Timeline assembly, captions & export | `coding` + `video_editing` | `audio_processing` |
| Frame-by-frame & audio QC review | `quality_assessment` (multimodal) | `creative_reasoning` |

Multiple models and tools may collaborate on one production while sharing the same locked `project-voice-manifest.json` and `task-graph-template.json`.

## 3. Four Adaptive Model Modes & Runtime Discovery

Configure the active routing mode in `templates/model-capability-registry.json`:

- **`AUTOMATIC` (Default):** Discovers capabilities directly from the current agent's actual available tools and integrations:
  1. Inspect the active session's declared tools and connected integrations (e.g., image generation, multimodal file viewing, shell/code execution, connected TTS/MCP tools).
  2. Where shell access is permitted, probe installed local runtimes/binaries (e.g., `ffmpeg`, `ffprobe`, `python3`, `blender`, `node`) without assuming they exist.
  3. Check active network/API permissions and any user-configured entries in `model-capability-registry.json`.
  4. **If runtime discovery is unavailable** (e.g., a chat-only client with no tool introspection), require honest **manual configuration** and mark all unchecked capabilities **`UNVERIFIED`** rather than guessing.
- **`MANUAL`:** Respects explicit user model assignments per task category (`manual_overrides`), warning if a pinned model lacks a required capability or is unreachable.
- **`BUDGET`:** Prioritizes free, local, and low-cost models/tools while explicitly stating any quality or capability tradeoffs up front—never hiding limitations.
- **`RESOURCE_EFFICIENT`:** Breaks large assignments into atomic tasks via [task-decomposition.md](task-decomposition.md) with minimal context slicing so smaller or local models preserve character identity, `V01`–`V06` bindings, and story continuity.

## 4. Failure Recovery & Model Substitution (6-Step Protocol)

If the selected model or tool cannot complete a task or fails validation:
1. **Identify the missing capability** (e.g., no multimodal inspection, no TTS provider, Python syntax drift, or visual continuity break).
2. **Search available alternatives** among actually discovered models and available tools (not unverified registry entries).
3. **Select another suitable model or tool** that genuinely supports the required capability.
4. **Preserve existing project state** (keep all `approved` assets, locked `character_id -> voice_id` bindings, and completed task nodes intact).
5. **Retry within bounded limits** (respect `retry_policy.max_retries` in `task-graph-template.json`).
6. **Record the substitution** in the task's `failure_log` (or mark the stage `BLOCKED` / `ESCALATED` if no alternative exists).

**Non-Negotiable Rule:** Never silently downgrade output quality or fabricate completed outputs when a capability is unavailable.
