# Using `roblox-town-director` with Google Antigravity

- **Compatibility:** Agent Skills installation through the Skills CLI is supported for the `antigravity` target.
- **Canonical source:** `skills/roblox-town-director/`

## Install

```bash
npx skills add lowlevelbtw/roblox-town-cinematic-studio --skill roblox-town-director -a antigravity
```

Use `-g` if you want a user-level installation across projects. The CLI may ask whether to symlink or copy the skill. Restart or reload Antigravity if the skill is not detected.

## Verify

Check the CLI output and confirm that Antigravity can discover `roblox-town-director`. Then ask it to read the skill and run a small IDEA or SCRIPT task before attempting a full production.

## Limits

Skill installation does not install or grant access to video-generation models, Roblox Studio, FFmpeg, Blender, local execution, browser automation, or paid services. Those must be checked independently. Live end-to-end production inside Antigravity remains **UNVERIFIED** until tested in that environment.