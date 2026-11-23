# Install with the Agent Skills CLI

The canonical skill lives at `skills/roblox-town-director/`. The Vercel Skills CLI can discover skills in a repository's `skills/` directory and install them into supported coding agents.

## One command for three agents

From a terminal with Node.js and npm/npx available:

```bash
npx skills add lowlevelbtw/roblox-town-cinematic-studio \
  --skill roblox-town-director \
  -a claude-code -a codex -a antigravity
```

The CLI may prompt you to choose project-level or global installation and a link/copy method. Use `-g` for user-level installation across projects. To target one agent, use one flag:

```bash
npx skills add lowlevelbtw/roblox-town-cinematic-studio --skill roblox-town-director -a claude-code
npx skills add lowlevelbtw/roblox-town-cinematic-studio --skill roblox-town-director -a codex
npx skills add lowlevelbtw/roblox-town-cinematic-studio --skill roblox-town-director -a antigravity
```

## Verify and maintain

```bash
npx skills list
npx skills check
npx skills update roblox-town-director
```

Restart the target agent if it does not discover a newly installed skill. If the CLI reports an unsupported agent or path, use that agent's native installation instructions instead.

## Platform notes

- **Claude Code:** Native Agent Skills discovery uses `.claude/skills/`.
- **Codex:** Native Agent Skills discovery uses `.agents/skills/` (project) or its user-level skills directory.
- **Antigravity:** The Skills CLI supports the `antigravity` target and installs to its supported skills location.
- **Google AI Studio:** This is not a local Agent Skills CLI target. Use [the AI Studio guide](ai-studio.md) to load the skill as system instructions and provide relevant reference/template files as context.

## What this installer does not do

It installs the skill instructions and supporting skill files. It does not install or configure Roblox Studio, Python, FFmpeg, Blender, Remotion, model-provider accounts, API keys, paid credits, browser permissions, or media-generation services. The skill must check those capabilities separately before promising a production workflow.

For exact agent support and current CLI options, consult the [Skills CLI documentation](https://github.com/vercel-labs/skills#readme) and [supported agents](https://github.com/vercel-labs/skills/blob/main/docs/agents.md).