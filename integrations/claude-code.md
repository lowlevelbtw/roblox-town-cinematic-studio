# Using `roblox-town-director` with Claude Code

- **Compatibility Tier:** **A — Native Agent Skills Support**
- **Repository Storage Path:** `skills/roblox-town-director/` *(canonical source inside this repo; not automatically discovered by Claude Code on its own)*

## Supported Claude Code Discovery Locations

Claude Code discovers skills from specific `.claude/skills/` directories—not from an arbitrary `skills/` folder at a repository root. Per [Claude Code Skills documentation](https://code.claude.com/docs/en/skills), place (or symlink) the `roblox-town-director` folder into one of these supported locations:

- **Project-level (shared with a project):** `.claude/skills/roblox-town-director/SKILL.md`
- **Personal / user-level (available across all projects):** `~/.claude/skills/roblox-town-director/SKILL.md` *(Windows: `%USERPROFILE%\.claude\skills\roblox-town-director\SKILL.md`)*
- **Symlink option:** You may symlink `skills/roblox-town-director/` into `.claude/skills/roblox-town-director` or `~/.claude/skills/roblox-town-director` so edits stay tied to the canonical source.

Keep the directory name **`roblox-town-director`** unchanged so it matches the `name` field in `SKILL.md`. Do not expect automatic discovery until the folder is in a supported location.

## How It Works

Once installed in a supported discovery location, Claude Code reads the YAML frontmatter in `SKILL.md` and loads files from `references/`, `templates/`, and `examples/` progressively on demand (or when invoked directly via `/roblox-town-director`).

## Verification Status

- Canonical Agent Skills format compliance: **Verified** against [agentskills.io/specification](https://agentskills.io/specification).
- Live end-to-end run inside Claude Code: **`UNVERIFIED`** (test by installing into `.claude/skills/roblox-town-director/` or `~/.claude/skills/roblox-town-director/` and running `IDEA` or `SCRIPT` mode on a sample premise).
