# Voice Direction and Performance Guide

Load during **Stages C, D, and J** (`SCRIPT`, `POST`, `FULL`, `REVIEW`) alongside [voice-identity-lock.md](voice-identity-lock.md).

## 1. Core Voice Direction by Identity (`V01`–`V06`)

| ID | Identity | Delivery Target | What to Avoid |
| :--- | :--- | :--- | :--- |
| **`V01`** | My Reference Voice | Preserve natural pronunciation, speaking rhythm, and emotional range observed in the creator's reference clips. | Over-smoothed robotic cadence or altering natural phrasing rhythm. |
| **`V02`** | Mature Adult Male | Mature, composed, natural, distinctive, confident; grounded authority for fathers, mentors, leaders, and historical roles. | Exaggerated "movie-trailer" bass growling or melodramatic booming. |
| **`V03`** | Teenage Boy | Youthful, natural, conversational, emotionally expressive (fictional synthetic). | Sounding like an adult exaggerating slang or pretending to be a teenager. |
| **`V04`** | Mature Adult Female | Mature, warm, confident, natural, emotionally controlled for mothers, teachers, leaders, and narrators. | Flat corporate-tutorial monotone or overly theatrical shouting. |
| **`V05`** | Teenage Girl | Youthful, natural, conversational, expressive (fictional synthetic). | Exaggerated, shrill, or stereotypical cartoon delivery. |
| **`V06`** | Elder Storyteller | Older-sounding, thoughtful, slightly textured, calm, distinctive for grandparents, elders, and flashback narration. | Caricatured shaky-elderly comedy voices or artificially slow mumbling. |

## 2. Dialogue Delivery vs. Narration

- **Narration:** Anchor the story with one consistent narrator voice (`V01` by default, or `V04`/`V06` when the story calls for a warm or flashback narrator). Keep narrator tone steady across acts so shifts in intensity come from pacing and word choice, not random voice drift.
- **In-Scene Dialogue:** Write short, speakable clauses (6–14 words per beat in Shorts; natural conversational turns in mini-movies). Prefer subtext and interrupted rhythms over stiff exposition blocks.
- **Narrator-to-Dialogue Separation:** Never blur narrator lines and character dialogue into one undifferentiated audio block. Separate narrator tracks and each character's lines into distinct stems or clips.

## 3. Emotional Direction, Pacing & Pauses

- **Emotion via Beat Cues:** Tag emotional shifts per line using playable intent (e.g., `[guarded]`, `[urgent, hushed]`, `[relieved exhale]`, `[quiet dread]`) rather than vague labels like "act better." Only apply provider-specific emotion sliders if capability discovery confirms the provider supports them.
- **Pacing by Format:**
  - *Shorts / "In This Town...":* Crisp setup cadence, slight slowdown before a twist or realization, clean punch on the button line.
  - *Mini-Movies / Documentaries:* Allow breathing room between emotional beats (`0.4–1.0s` beats) so reactions land visually before the next line begins.
- **Intentional Pauses:** Mark beats explicitly (`[0.3s beat]`, `[0.5s pre-twist silence]`). Trim accidental dead air during radio-edit assembly, but protect scripted silence gaps.

## 4. Pronunciation & Character Voice Differentiation

- **Pronunciation Discipline:** Record unusual character names, town names, or Roblox terms in a pronunciation note (or provider pronunciation dictionary if supported) so every character pronounces proper nouns identically across episodes.
- **Speaker Differentiation:** Differentiate speakers using **three layers**, not pitch alone: (1) distinct locked `voice_id`, (2) distinct sentence length/cadence (e.g., clipped authoritative lines for `V02` vs. quick reactive turns for `V03`/`V05`), and (3) clean audio separation per speaker in the edit timeline.
