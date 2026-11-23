# Task Decomposition Engine & Scene Quality-Control Loop

Load during **Stages F, G, H, I, and L**—especially for multi-scene Shorts, episodic series, mini-movies, or whenever running under `BALANCED` or `RESOURCE_EFFICIENT` execution profiles ([adaptive-intelligence.md](adaptive-intelligence.md)).

## 1. Hierarchical Production Decomposition

Break large creative assignments into verifiable, dependency-ordered tasks so any model tier can execute reliably without losing continuity:

```text
Full Film / Project
  └── Acts (for mini-movies / features)
        └── Chapters / Episodes
              └── Sequences
                    └── Scenes
                          └── Shots
                                └── Individual Production Assets (keyframes, clips, voice stems, SFX, subtitles)
```

- **Shorts (15–60s):** Typically decompose directly as `Project -> Scenes -> Shots -> Assets`.
- **Mini-Movies & Episodic Series (3–10+ min):** Use the full hierarchy so each scene or shot can be generated, verified, and resumed independently.

## 2. Mandatory Task Contract

Represent active production graphs using [templates/task-graph-template.json](../templates/task-graph-template.json). Every task node must define:

| Field | Requirement |
| :--- | :--- |
| **`task_id`** | Unique, stable identifier (e.g., `S02_SH01_KEYFRAME`, `S02_L02_VO_V05`). |
| **`parent_id`** | Upstream container ID (`PROJECT`, `ACT_01`, `S02`, etc.) for traceability. |
| **`recommended_profile`** | `FRONTIER`, `BALANCED`, or `RESOURCE_EFFICIENT`. |
| **`required_inputs`** | Exact minimal inputs needed (locked character wardrobe, `character_id -> voice_id`, prior reference frame, beat text)—never dump the entire repo into a small model's context. |
| **`expected_output`** | Concrete deliverable path, schema, or asset specification. |
| **`dependencies`** | List of upstream `task_id`s that must be `approved` before this task starts. |
| **`validation_criteria`** | Objective pass/fail checks (continuity, framing variation, safe-zone captions, duration, codec/integrity). |
| **`retry_policy`** | Maximum retries (`max_retries`) and exact constraint-tightening rule on retry. |
| **`status`** | `pending` \| `in_progress` \| `needs_retry` \| `approved` \| `blocked` \| `escalated`. |

## 3. Minimal Context Slicing (For Smaller & Local Models)

When executing a task under `RESOURCE_EFFICIENT` (or tight context windows), pass **only**:
1. The active task node (`task_id`, `required_inputs`, `expected_output`, `validation_criteria`).
2. Locked character visual descriptors and `character_id -> voice_id` mappings for speakers appearing in that specific scene.
3. The immediately preceding approved shot/reference image (when generating consecutive shots in the same location).

Do not feed unrelated chapters, unused voice profiles, or uninvolved integration guides into a single shot task.

## 4. Scene Quality-Control & Failure-Escalation Loop

Evaluate **every scene and asset before marking it `approved`**. Never silently accept poor framing, broken continuity, clipped captions, or missing audio just to finish the run.

When a scene or asset fails `validation_criteria`:
1. **Identify the Actual Failure:** State the exact observable defect (e.g., *"Shot 3 repeats Shot 2's medium framing with static character posture"*, *"Subtitle line overflows right margin at 0:24"*, or *"Principal's badge disappeared in Scene 4"*).
2. **Classify the Root Cause:**
   - `instruction_gap`: Ambiguous prompt, missing wardrobe lock, or missing shot-variation rule.
   - `model_capability`: Active model dropped multi-step constraints or drifted over long context.
   - `tool_limitation`: Connected tool lacks required capability (e.g., no TTS provider, no animation control, or resolution/duration cap).
   - `generated_media_defect`: Visual artifact, character drift, audio clipping, or sync error in the produced asset.
3. **Retry with a More Constrained Task (Up to `max_retries`):** Tighten the prompt, lock a reference frame, split the task into smaller atomic steps, or tighten deterministic bounds (e.g., pixel-measured caption wrapping).
4. **Switch to an Alternative Tool (If Available):** Route the failed step to an alternate permitted generator, editor, or Live Gameplay / animatic fallback.
5. **Escalate Unresolved Problems:** If retries and alternatives still fail (or a required tool is missing), set task status to **`blocked`** or **`escalated`**, record the exact cause in the task graph, and report the blocker clearly to the creator with concrete next options.
