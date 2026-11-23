# Using `roblox-town-director` with ChatGPT

- **Compatibility Model:** **Desktop Standalone Skill; Plugin Distribution for Chat/Work; Custom GPT / Project Adapter**
- **Canonical Skill Path:** `skills/roblox-town-director/`

## Client-Specific Installation Models

Availability and installation differ by ChatGPT client (desktop, web, mobile) and distribution method. Per [OpenAI Build Skills](https://developers.openai.com/codex/build-skills) and [Plugins in ChatGPT](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt):

1. **ChatGPT Desktop App (Standalone Skills):**
   - Standalone Agent Skills are supported in the ChatGPT desktop app alongside Codex CLI and IDE clients.
   - Install or symlink `skills/roblox-town-director/` into the supported local skills path (`.agents/skills/roblox-town-director/` or `~/.agents/skills/roblox-town-director/`) as documented in [OpenAI Build Skills](https://developers.openai.com/codex/build-skills).
2. **ChatGPT Chat & Work (Web, Desktop, Mobile — Plugin Distribution):**
   - Skills bundled inside a ChatGPT plugin are available across Chat and Work on web, desktop, and mobile once the plugin is installed and authorized.
   - Note: This repository currently distributes raw canonical skill files only—it does **not** ship a packaged ChatGPT plugin yet.
3. **Custom GPT or ChatGPT Project (Manual Adapter Alternative):**
   - When standalone desktop Skills or plugin distribution are not used, paste the body of `skills/roblox-town-director/SKILL.md` into Custom GPT or Project **Instructions**, and upload the files in `references/` and `templates/` as **Knowledge files**.

## Verification Status

- Canonical Agent Skills format compliance: **Verified** against [agentskills.io/specification](https://agentskills.io/specification).
- Live end-to-end run inside ChatGPT desktop, plugin distribution, or Custom GPT/Projects: **`UNVERIFIED`**.
