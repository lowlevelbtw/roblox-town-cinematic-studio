# Using `roblox-town-director` with Gemini CLI

- **Compatibility Model:** **Native Agent Skills Support (`.gemini/skills/` or `.agents/skills/`)**
- **Repository Storage Path:** `skills/roblox-town-director/` *(canonical source inside this repo; not automatically discovered on its own)*

## Supported Gemini CLI Discovery Locations & Commands

Per [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/skills/) and [Managing Agent Skills](https://geminicli.com/docs/cli/using-agent-skills/), install, link, or copy `skills/roblox-town-director/` into one of these supported locations:

- **Workspace-level:** `.gemini/skills/roblox-town-director/` or `.agents/skills/roblox-town-director/`
- **User-level (all workspaces):** `~/.gemini/skills/roblox-town-director/` or `~/.agents/skills/roblox-town-director/`
- **CLI Management Commands:**
  - Install from a Git repository URL or local path: `gemini skills install <url-or-path>`
  - Link a local skill folder during development: `gemini skills link skills/roblox-town-director`
  - Verify discovery inside a session: `/skills list`

Keep the directory name **`roblox-town-director`** matching the `name` field in `SKILL.md`.

## How It Works

Once installed or linked into a supported discovery location, Gemini CLI reads `SKILL.md` natively via the open Agent Skills specification and loads supporting files from `references/`, `templates/`, and `examples/` on demand.

## Verification Status

- Canonical Agent Skills format compliance: **Verified** against [agentskills.io/specification](https://agentskills.io/specification).
- Live end-to-end run inside Gemini CLI: **`UNVERIFIED`**.
