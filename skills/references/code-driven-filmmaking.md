# Code-Driven Filmmaking Guide

Load during **Stages E, F, G, H, I, and L** when combining procedural/programmatic production tools with generative AI assets. Route script-writing and automation steps to a `coding`-capable model via [intelligence-router.md](intelligence-router.md).

*Note: This skill does **not** bundle a built-in rendering engine. Code-driven execution depends strictly on the runtimes and binaries actually installed and permitted in the active environment.*

## 1. Executable Code vs. Instructions vs. Conceptual Workflows

Never blur what can actually run right now with what requires external software. Label every code-driven output explicitly:

| Category | Definition | When to Use |
| :--- | :--- | :--- |
| **Executable Code** | Real scripts or commands that run directly in the active environment against verified installed binaries/libraries (e.g., `python3` + `ffmpeg` + `PIL` in a verified sandbox). | Only when the required runtime has been probed and confirmed available. Always run and verify the output file. |
| **Instructions** | Step-by-step commands or setup actions the creator executes manually in an external tool on their own machine. | When the target tool (e.g., Roblox Studio, local Blender, Termux/FFmpeg) is outside the agent's execution environment. |
| **Conceptual Workflows** | Procedural patterns, architecture outlines, or pseudocode describing how an external engine could stage a scene. | During planning or when target engine/assets are unverified; never present conceptual workflows as tested or rendered outputs. |

## 2. Hybrid Philosophy: Code for Control, Generative AI for Assets

Code does not magically create expressive animation on its own—it provides **repeatability, exact timing, deterministic layout, and verifiable exports**. Combine both strengths:
- **Use Code For:** Camera paths/framing, scene composition, character positioning, lighting parameters, procedural/keyframed animation control, timeline construction, pixel-measured subtitles, transitions, audio synchronization, batch rendering, and automated export validation (`ffprobe` / frame extraction).
- **Use Generative AI For:** Reference-locked character designs, stylized environments, custom textures, backgrounds, creative concept art, and visual assets that are slow or impractical to model procedurally.

## 3. Environment-Gated Tool Selection Matrix

Do **not** force every tool automatically. Select only tools that match actual project requirements, available hardware, OS/execution environment, and licensing:

| External Engine / Tool | Primary Code Role | Environment & Hardware Requirement | When to Select |
| :--- | :--- | :--- | :--- |
| **FFmpeg + Python (`PIL`, `numpy`, `scipy`)** | Timeline assembly, Ken Burns camera motion, transitions, pixel-wrapped subtitles, audio mixing, export validation (`ffprobe`). | Runs in lightweight Linux/macOS/Windows/VM sandboxes (no GPU required). | Programmatic editing, animatic rendering, subtitle burn-in, and export QC when installed locally. |
| **Roblox Studio + Luau** | Native Roblox environments, camera scripting, avatar positioning, lighting, weather, Moon Animator / rig playback. | Desktop OS (Windows/macOS) with Roblox Studio installed. | Authentic in-engine Roblox 3D scenes, custom props, and scripted Roblox animation. |
| **Blender + Python (`bpy`)** | 3D camera rigs, cinematic lighting, character staging, procedural animation, high-contrast 3D renders. | Desktop or cloud worker with Blender installed (GPU recommended for Cycles). | High-craft 3D cinematic lighting and custom animated sequences beyond Roblox Studio. |
| **Remotion (React / TypeScript)** | Programmatic motion graphics, kinetic captions, data-driven layouts, frame-accurate compositing. | Node.js + Chromium/FFmpeg runtime. | Stylized typography, repeatable series templates, and motion-graphic overlays. |

## 4. Mandatory Verification Gate for Executed Renders

Whenever **executable code** produces a rendered export, verify before approval:
1. **Stream & Duration Check:** Verify exact duration, resolution (`1080×1920` or `1920×1080`), frame rate, and video/audio codecs via `ffprobe` (or engine render logs).
2. **Audio Integrity Check:** Verify zero clipping, clean loudness headroom, accurate strategic silence windows, and honest reporting if spoken TTS tracks are `BLOCKED`.
3. **Visual Frame Check:** Extract and inspect key frames (opening hook, midpoint, payoff) to confirm character continuity, focal emphasis, and zero subtitle margin clipping.
4. **Failure Routing:** If a render script fails or produces visual defects, route back to the `coding` model (for layout/timing bugs) or `image_generation` / `3d_and_animation` tool (for source asset defects) per [task-decomposition.md](task-decomposition.md).
