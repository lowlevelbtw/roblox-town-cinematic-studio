# Using `roblox-town-director` with the Claude App (Web / Desktop / Mobile)

- **Compatibility Model:** **Custom Skill ZIP Upload (Primary); Claude Projects (Alternative)**
- **Canonical Skill Path:** `skills/roblox-town-director/`

## Primary Setup: Direct Custom Skill ZIP Upload

Per [Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) and the [Claude Help Center](https://support.claude.com/en/articles/12512180-use-skills-in-claude), Claude supports uploading custom Agent Skills packaged as a ZIP archive:

1. Package the `skills/roblox-town-director/` directory into a `.zip` file (keeping `SKILL.md`, `references/`, `templates/`, and `examples/` inside the `roblox-town-director/` folder).
2. In Claude, open **Customize → Skills** (or **Settings → Features** depending on your current UI layout), select **+ Create skill → Upload a skill**, and upload the ZIP archive.
3. Toggle **`roblox-town-director`** on in your skills list.

**Plan & Feature Requirements:** Per [Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview), custom Skill ZIP uploads require a supported plan (Pro, Max, Ultra, Team, or Enterprise) with **code execution enabled**.

## Alternative Workflow: Claude Projects

If your plan does not have custom Skill uploads or code execution enabled:

1. Create a Claude Project named **Roblox Town Director**.
2. Paste the contents of `skills/roblox-town-director/SKILL.md` into **Project Instructions**.
3. Upload the files in `references/` and `templates/` to **Project Knowledge** so Claude can consult them on demand.

## Important Note & Verification Status

- Do not fork `SKILL.md` for Claude—always package or copy from the single canonical `skills/roblox-town-director/SKILL.md`.
- Live end-to-end ZIP upload and execution inside the Claude app: **`UNVERIFIED`**.
