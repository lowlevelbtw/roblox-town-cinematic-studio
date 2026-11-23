# Model-Tier & Capability Benchmark Suite (`roblox-town-director` v0.1.1)

*Status: **`[NOT RUN]`** across all profiles and capability tests. Do not record or fabricate scores until each test is actually executed on real outputs.*

## 1. Purpose
Evaluate actual model outputs across **storytelling**, **coding**, **visual reasoning**, and **instruction adherence**—comparing `FRONTIER`, `BALANCED`, and `RESOURCE_EFFICIENT` profiles using [references/intelligence-router.md](../references/intelligence-router.md), [references/adaptive-intelligence.md](../references/adaptive-intelligence.md), and [references/task-decomposition.md](../references/task-decomposition.md).

## 2. Core Cross-Tier Production Benchmark (Identical Assignment Across All 3 Profiles)

> **Prompt:** "Produce a 45-second vertical `9:16` Roblox Short titled *'In This Town, Every Secret Glows'*. Include: (1) a 0–3s visual town-rule hook, (2) two recurring characters (`protagonist_kai` using `V03` and `elder_mira` using `V06`) plus narrator (`narrator_main` using `V01`), (3) a 4-scene shot breakdown with varied camera angles, blocking, environmental clues, and transitions, (4) a valid `project-voice-manifest.json` with speaker-separated lines, and (5) a Stage L QC check reporting any blocked tools honestly."

### Execution Rules
- **`FRONTIER`:** May run with full canonical skill + references in a single coordinated workflow.
- **`BALANCED`:** Runs stage-by-stage using `templates/task-graph-template.json` and `templates/project-voice-manifest.json`.
- **`RESOURCE_EFFICIENT`:** Runs decomposed atomic tasks (`S01`–`S04`, one task per turn) with minimal context slicing (locked wardrobe + `character_id -> voice_id` + active scene spec only).

## 3. Capability-Specific Repeatable Tests (For Intelligence Router Calibration)

| Test ID | Target Capability | Repeatable Test Prompt / Task | Pass Criteria | Result |
| :--- | :--- | :--- | :--- | :--- |
| **B1** | `storytelling` | Pitch & script a 45s *"In This Town..."* Short with a visual rule twist and zero exposition dumps. | Strong 0–3s hook, clear goal/obstacle/payoff, zero script contradictions. | `[NOT RUN]` |
| **B2** | `coding` | Write a self-contained Python + FFmpeg script that renders a 15s `1080×1920` clip with pixel-wrapped subtitles and `ffprobe` validation. | Runs cleanly without syntax errors; verified 15.0s output with zero clipped captions. | `[NOT RUN]` |
| **B3** | `quality_assessment` (visual reasoning) | Inspect 3 frames from an AI-generated Short containing a prop continuity error and clipped captions. | Identifies actual visual defects accurately without hallucinating unseen details. | `[NOT RUN]` |
| **B4** | Instruction Adherence & Routing | Run a production request in an environment with no TTS provider and a `MANUAL` or `BUDGET` routing constraint. | Produces valid JSON manifests, zero fabricated provider voice IDs, honest `BLOCKED` reporting, and records any model substitution. | `[NOT RUN]` |

## 4. Cross-Tier Measurement Rubric & Results Table

Record **actual observed measurements only** (`PASS` / `PARTIAL` / `FAIL`, real timestamps, real counts, real cost where measurable, or `NOT RUN` / `N/A`):

| Metric | How to Measure | `FRONTIER` | `BALANCED` | `RESOURCE_EFFICIENT` |
| :--- | :--- | :--- | :--- | :--- |
| **Model & Client Tested** | Exact model name + client/runtime | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Story Coherence** | Clear goal, escalating conflict, rule-based payoff (`1–5` rubric) | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Character Consistency** | Wardrobe, traits, and `character_id -> voice_id` preserved across all 4 scenes | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Visual Consistency** | Location, lighting, props, and 180° geography stay locked | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Cinematic Quality** | Varied shot scales/angles, active blocking, environmental storytelling, transitions, coherent captions | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Instruction Adherence** | Valid JSON, zero fabricated provider voice IDs, honest `BLOCKED` reporting, no unverified claims | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Production Time** | Wall-clock time from prompt start to verified completion | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Tool Usage** | Tools discovered vs. invoked vs. honestly reported blocked | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Failure Rate** | Number of QC retries / escalations divided by total tasks | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
| **Cost (Where Measurable)** | Observed API/token/tool cost (or `$0` for free/local runs; `N/A` if unmetered) | `[NOT RUN]` | `[NOT RUN]` | `[NOT RUN]` |
