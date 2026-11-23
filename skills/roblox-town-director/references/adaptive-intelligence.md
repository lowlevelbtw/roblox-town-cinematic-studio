# Adaptive Intelligence & Model-Tier Execution Profiles

Load during **Stages A, F, G, and L** (or at session start) to adapt workflow depth, prompt density, context slicing, and verification rigor to the active AI model and connected tools—from frontier models to small local or free models.

## 1. Capability-First Discovery (Never Assume by Model Name Alone)

Model parameter count or brand name does **not** guarantee reliable tool use, long-context recall, or multimodal understanding. Before selecting an execution profile, assess five observable runtime dimensions:

| Dimension | What to Check | Adaptation Rule |
| :--- | :--- | :--- |
| **Context Window** | Effective usable context before instruction drift or truncation. | If tight, load only the active task slice + locked character/voice entries rather than all references at once. |
| **Tool Availability** | Which file, image, video, audio/TTS, and editing tools actually exist and have permission to run. | Execute only verified tools; route unavailable stages to manual/external handoff without pretending execution succeeded. |
| **Multimodal Support** | Whether the agent can inspect generated images, video frames, or audio files directly. | If visual/audio inspection is unavailable, rely on explicit structural checks (`ffprobe`, JSON validation, caption-width math) and flag visual QC as requiring human review. |
| **Reasoning & Instruction Adherence** | Reliability across multi-step constraints (continuity, timing math, JSON formatting). | If multi-constraint drift occurs, decompose into smaller single-purpose tasks via [task-decomposition.md](task-decomposition.md). |
| **Output Constraints** | Token limits, truncation risk, or structured-output reliability. | Emit one scene, shot, or file per step on constrained models rather than dumping an entire multi-scene packet in one turn. |

## 2. Three Execution Profiles

### `FRONTIER`
- **Best For:** Complex reasoning, original creative direction, multi-act narrative architecture, subtle subtext, deep Dual-Gate critique, and cross-scene cinematic/continuity auditing.
- **Workflow Behavior:** Can synthesize multi-scene plans, cross-reference multiple guides (`storytelling.md`, `cinematic-direction.md`, `voice-identity-lock.md`) simultaneously, and perform nuanced root-cause diagnosis during QC failures.

### `BALANCED`
- **Best For:** Structured creative development, scene-by-scene planning, asset management, manifest updates, and step-by-step production execution.
- **Workflow Behavior:** Works cleanly one sequence or scene at a time using explicit templates (`short-production-packet.md`, `task-graph-template.json`, `project-voice-manifest.json`) with clear stage gates before moving forward.

### `RESOURCE_EFFICIENT`
- **Best For:** Smaller, free, local, or open-source models that perform best with short instructions, narrow scope, structured schemas, and deterministic workflows.
- **Workflow Behavior:**
  - **Minimal Context Slicing:** Supply **only** the current task node from `task-graph-template.json`, the relevant locked entries from `project-voice-manifest.json`, and the single reference section needed for that step.
  - **One Atomic Deliverable per Step:** Produce one beat, one shot prompt, one subtitle block, or one manifest update per turn.
  - **Deterministic Validation:** Rely on explicit checklists, JSON schema fields, and concrete numeric bounds (e.g., shot count, word-count range, safe-zone wrap width) rather than open-ended abstract critique.
  - **Continuity Protection:** Never let a smaller model re-invent character outfits, locations, or `character_id -> voice_id` bindings—always inject the locked fields verbatim into the task input.

## 3. Profile Switching & Hybrid Pipelines

A single production may combine profiles across stages—for example:
- **`FRONTIER`** for Stage A–D concept, narrative architecture, and script lock.
- **`BALANCED`** for Stage E–G shot planning, visual prompt generation, and manifest tracking.
- **`RESOURCE_EFFICIENT`** for deterministic Stage I–J subtitle formatting, file naming, or per-shot checklist verification.

Regardless of profile, **character identity, locked `V01`–`V06` voice IDs, and Stage L QC standards remain identical**.
