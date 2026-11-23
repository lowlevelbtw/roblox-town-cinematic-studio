# Using `roblox-town-director` with Google AI Studio

- **Compatibility Tier:** **C — Manual System Instructions / API Integration**
- **Canonical Skill Path:** `skills/roblox-town-director/`

## Setup

Google AI Studio does **not** natively install Agent Skills folders from disk. Load the canonical files using one of two methods:

1. **AI Studio Prompt UI:**
   - Paste `skills/roblox-town-director/SKILL.md` into **System Instructions**.
   - Attach the relevant file(s) from `skills/roblox-town-director/references/` and `templates/` into the prompt context for the mode you are running.
2. **Gemini API / Application Integration:**
   - Load `SKILL.md` as `system_instruction` in your application code, and dynamically inject the matching file from `references/` based on the active workflow stage (`Stages A–D`, `E–G`, `F–H`, or `I–K`).

## Limitation

Because AI Studio has no local filesystem skill loader, relative links inside `SKILL.md` must be supplied via prompt attachments or your application's context loader.
