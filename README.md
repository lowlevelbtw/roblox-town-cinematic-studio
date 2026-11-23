Roblox Town Cinematic Studio

<p align="center">
  <strong>One prompt. One directed production. One finished video.</strong>
</p><p align="center">
  An open-source, model-independent production skill for creating cinematic Roblox town, roleplay, and animated stories.
</p><p align="center">
  <img src="https://img.shields.io/badge/version-0.2.0--consolidated-blue" alt="Version 0.2.0"/>
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"/>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+"/>
  <img src="https://img.shields.io/badge/status-active%20development-orange" alt="Active development"/>
</p>---

What is Roblox Town Cinematic Studio?

Roblox Town Cinematic Studio is an AI-assisted production system built around one canonical skill: "roblox-town-director".

It coordinates specialized AI models and creative tools across storytelling, voice production, code-driven filmmaking, editing, quality control, and video packaging.

The goal is straightforward: make a complete Roblox story-production workflow possible without depending on one AI provider, one model, or one expensive editing application.

The project is hardware-independent by design. Actual execution still depends on the tools, permissions, and capabilities available in the active environment.

Showcase

A look at the visual direction and Roblox environments the project is designed to support.

Cinematic scene| Character storytelling
"Roblox cinematic scene" (assets/showcase/dumpster-scene.jpg)| "Roblox character scene" (assets/showcase/street-camp-scene.jpg)
"Roblox town environment" (assets/showcase/town-environment.jpg)| "Roblox action scene" (assets/showcase/action-scene.jpg)

These images demonstrate visual direction, not proof of automated in-game capture or completed video rendering.

Core capabilities

1. Intelligence routing

Routes production tasks to suitable models based on their capabilities rather than relying on a single provider.

- 11 routing capabilities, including storytelling, research, coding, image generation, video generation, audio processing, and quality assessment.
- Four routing modes: "AUTOMATIC", "MANUAL", "BUDGET", and "RESOURCE_EFFICIENT".
- A six-step model-substitution recovery loop.

See ""references/intelligence-router.md"" (skills/roblox-town-director/references/intelligence-router.md).

2. Adaptive production planning

Breaks a production into a structured hierarchy:

"Film → Acts → Chapters → Sequences → Scenes → Shots → Assets"

Three execution profiles are available:

- "FRONTIER"
- "BALANCED"
- "RESOURCE_EFFICIENT"

The workflow also includes context slicing for smaller models and a five-step Scene QC Loop.

3. Code-driven filmmaking

Coordinates procedural production tools with generative AI assets.

Supported production paths include:

- FFmpeg and Python
- Roblox Studio and Luau
- Blender and Python
- Remotion

Export verification is part of the production workflow. Tool availability and actual execution must be verified by the active environment.

4. Voice intelligence

The voice system lives in "scripts/voice_intelligence/".

It includes:

- Voice Profile Manager and Voice Design
- Persistent character-to-voice assignment
- Provider-independent adapter architecture
- Resumable dialogue production
- Audio quality checks
- Consent-gated authorized voice-cloning interfaces

Important limitations: Remote voice cloning is disabled. Independent identity verification is not implemented ("independent_identity_verified: false"). Some provider adapters are contract-only or mock-tested; live provider API verification has not been completed.

5. Captioning and video assembly

The production scripts include caption generation, video assembly, visual quality control, and audio/video processing.

The automated production tests cover all 15 caption presets ("C01–C15") and "C16 Auto Adaptive", as well as multi-scene assembly, audio ducking, black-frame detection, contact sheets, and verification receipts.

6. Storytelling and cinematic continuity

Production guidance covers:

- The "In This Town..." Shorts format
- Shot-scale variation and active blocking
- Prop-state visual consistency
- Flashback differentiation
- 180-degree continuity
- Caption safe margins
- Cinematic direction and scene continuity

Six-voice identity system

The internal voice IDs remain consistent when changing AI agents or TTS providers.

ID| Identity| Intended use
V01| My Reference Voice| Creator-selected primary narrator
V02| Mature Adult Male| Fathers, leaders, mentors
V03| Teenage Boy| Teen protagonists and friends
V04| Mature Adult Female| Mothers, teachers, narrators
V05| Teenage Girl| Teen protagonists and friends
V06| Elder Storyteller| Grandparents and elder narration

Voice safety rules are part of the design. Teenage character voices must be fictional synthetic voices, never cloned from real minors. Private reference recordings and API credentials must never be committed to a public repository.

To configure a provider, review "templates/voice-registry.json", "templates/project-voice-manifest.json", and the provider adapter documentation before changing provider bindings.

Six operating modes

Mode| Purpose
"IDEA"| Develop and evaluate a story concept
"SCRIPT"| Build the script and production plan
"SHOOT"| Coordinate scene and shot production
"POST"| Handle editing and packaging
"REVIEW"| Evaluate production quality
"FULL"| Coordinate the complete workflow

Platform integrations

There is one canonical skill, located at:

"skills/roblox-town-director/SKILL.md"

Platform-specific installation and discovery mechanisms differ. Cloning this repository does not automatically install the skill into every AI application.

Platform| Installation approach| Guide
Claude Code| Native filesystem skill| "Guide" (integrations/claude-code.md)
Claude App| Custom Skill ZIP or Projects alternative| "Guide" (integrations/claude-app.md)
OpenAI Codex| Native ".agents/skills/"| "Guide" (integrations/codex.md)
ChatGPT| Desktop skill, Project/GPT adapter, or plugin distribution| "Guide" (integrations/chatgpt.md)
Gemini CLI| Native skill directories| "Guide" (integrations/gemini-cli.md)
Google AI Studio| Manual system-instruction/API adapter| "Guide" (integrations/ai-studio.md)
Other agents| Markdown fallback; compatibility unverified| Load "SKILL.md" and required references

Optional: recorded voice backend

The local recorded-voice backend can import, validate, normalize, and assemble creator-supplied voice recordings without requiring an external TTS API.

Requirements

- Python 3.9+
- FFmpeg and FFprobe installed and available on "PATH"

Install FFmpeg

# Debian / Ubuntu
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows
winget install Gyan.FFmpeg

# Android Termux
pkg install python ffmpeg

Run the backend

python skills/roblox-town-director/scripts/voice_backend.py

Run the regression tests

python3 -m unittest discover -s tests -v

The recorded-voice example project is in ""examples/recorded-voice-test-project/"" (examples/recorded-voice-test-project/).

It includes synthetic fixture generation, a project voice manifest, and examples covering audio import, trimming, normalization, invalid-file rejection, missing-file handling, and timeline/SRT assembly.

External TTS execution is not implemented in this local backend.

Project structure

roblox-town-cinematic-studio/
├── .github/
│   └── workflows/
│       └── ci.yml
├── examples/
│   └── recorded-voice-test-project/
├── integrations/
├── skills/
│   └── roblox-town-director/
│       ├── references/
│       ├── templates/
│       ├── scripts/
│       │   └── voice_intelligence/
│       ├── examples/
│       └── evaluations/
├── tests/
├── evaluations/
│   └── caption-samples-rc10/
├── assets/
│   └── showcase/
├── CHANGELOG.md
├── LICENSE
└── README.md

Verification status

Version "0.2.0-consolidated" is built on the frozen "v0.1.1 RC6" baseline.

The project defines 82 automated tests:

- 8 tests in "test_voice_backend.py"
- 40 tests in "test_voice_intelligence.py"
- 34 tests in "test_v020_production.py"

The test suite includes FFmpeg rendering and production-pipeline checks. These are defined test results in the project documentation; remote GitHub Actions execution has not yet been verified.

The following remain pending:

- Full evaluation-suite execution
- Model-tier and capability benchmarks
- Live TTS provider verification
- Physical Roblox filming validation
- Remote CI execution

Do not interpret the presence of a workflow, adapter, or test as proof that its corresponding live service has been verified.

Known limitations

- Physical Roblox gameplay capture and device control are not assumed.
- Media rendering requires available tools and permissions.
- TTS providers are not interchangeable without checking their actual capabilities.
- No model benchmark scores or live provider results are fabricated.
- Unverified Roblox props, emotes, and camera controls must be checked in-game before being treated as supported.

When a production stage is unavailable, the system should complete the stages it can support and report the blocked stages with practical alternatives.

License

Released under the "MIT License" (LICENSE).
