# Using `roblox-town-director` with OpenAI Codex

- **Compatibility Model:** **Native Agent Skills Support (`.agents/skills/`)**
- **Repository Storage Path:** `skills/roblox-town-director/` *(canonical source inside this repo; not automatically discovered on its own)*

## Supported Codex Discovery Locations

Codex discovers Agent Skills from `.agents/skills/` locations rather than an arbitrary repository root `skills/` folder. Per [OpenAI Codex Build Skills documentation](https://developers.openai.com/codex/build-skills), place or symlink the `roblox-town-director` folder into one of these supported paths:

- **Repository-level:** `.agents/skills/roblox-town-director/SKILL.md`
- **User-level (all repositories):** `~/.agents/skills/roblox-town-director/SKILL.md`
- **Symlink option:** Codex supports symlinked skill folders, so you can symlink `skills/roblox-town-director/` into `.agents/skills/roblox-town-director` or `~/.agents/skills/roblox-town-director` to stay tied to the canonical source.

Keep the folder name **`roblox-town-director`** identical to the `name` field in `SKILL.md`. Do not expect automatic discovery until the skill is placed or symlinked into a supported `.agents/skills/` path.

## How It Works

Once installed in a supported discovery location, Codex reads the YAML frontmatter in `SKILL.md` natively and resolves relative links (`references/*.md`, `templates/*.md`) on demand across `IDEA`, `SCRIPT`, `SHOOT`, `POST`, `REVIEW`, and `FULL` modes.

## Verification Status

- Canonical Agent Skills format compliance: **Verified** against [agentskills.io/specification](https://agentskills.io/specification).
- Live end-to-end run inside Codex: **`UNVERIFIED`**.
