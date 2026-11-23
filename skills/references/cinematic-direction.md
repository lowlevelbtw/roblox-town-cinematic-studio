# Cinematic Direction and Visual Continuity Guide

Load during **Stages E–G** (`SHOOT`, `REVIEW`, `FULL`, and visual planning in `SCRIPT`). Apply these rules across **Live Gameplay Staging**, **Custom Roblox Animation**, and **Hybrid / External Production** without forcing expensive or unavailable tools.

## 1. Visual Language, Shot Variation & Camera Motivation (Stage E)

Every camera placement must serve tension, spatial geography, point of view, or emotional distance—never repeat the same flat medium framing across consecutive beats:
- **Shot Scale & Variation Rule:** Alternate shot scales across consecutive beats (e.g., *Wide Establishing → Medium Two-Shot → Tight Over-the-Shoulder → Low-Angle Confrontation → Wide Payoff*). Avoid repeating identical camera distance and angle back-to-back unless holding a deliberate stillness beat.
  - *Wide / Establishing:* Grounds spatial geography, environmental clues, and character isolation.
  - *Medium / Two-Shot:* Reads posture, wardrobe contrast, prop interactions, and interpersonal distance.
  - *Tight / Over-the-Shoulder:* Focuses visual emphasis on a doorway, clue, prop, or reaction. For standard live-gameplay avatars lacking facial micro-expressions, use over-the-shoulder POV, head turns, and spatial distance instead of extreme face close-ups. (Expressive 2D/3D faces require **Custom Roblox Animation** or **Hybrid Production**.)
- **Power Angles:** *Low angles* (camera low, tilted up) make doors, houses, or authority figures feel imposing; *high angles* (camera high, tilted down) make a character look cornered, small, or watched.
- **Camera Movement:** Match movement to dramatic intent—slow push-in for rising tension, pull-back for comedic or shock reveals, lateral pan to connect a character to a hidden clue, and locked-off static frames for abrupt freezes. Always provide a **stationary camera fallback** when smooth panning is unavailable or jittery.
- **Depth, Composition & Visual Emphasis:** Frame through doorways, railings, windows, or foreground props to build foreground/midground/background depth. Give every shot **one clear focal point** so the viewer's eye lands immediately on the story beat (never scatter competing focal elements across a busy background).

## 2. Character Blocking, Animation & Environmental Storytelling

- **Active Character Blocking (Avoid Static Mannequin Stills):** Give characters purposeful physical staging—entering across a threshold, stepping back in surprise, turning toward a sound, hiding a prop behind their back, or shifting distance from another character.
- **Facial & Body Animation (Where Supported):** When using Custom Roblox Animation or supported AI/video tools, specify clear, readable posture and facial beats (raised hands, clenched posture, sweat/shock beat, relieved grin). When limited to Live Gameplay Staging or animatics, convey the same beat via blocking, camera push-in, and cut timing.
- **Environmental Movement & Storytelling:** Use the environment to tell the story without extra dialogue—cracked glass, spilled props, swaying foliage, glowing signs, passing background townspeople, or doorway shadows. Keep background motion subtle enough not to steal focus from the lead action.

## 3. Lighting & Weather Direction

- **Lighting Contrast:** Avoid pitch-black rooms that turn into blocky compression artifacts on social feeds. Build mood with **key-vs-spill contrast**—a lit hallway spilling into a dim room, golden afternoon light against long shadows, or warm streetlights against a cool night street.
- **Weather & Atmosphere:** Use weather (rain, fog, dusk glow, wind) only when it reinforces mood and is genuinely supported by the chosen production method; never prescribe unverified in-game weather scripts as ordinary live gameplay.

## 4. Shot Transitions, Sound & Subtitle Synchronization

- **Purposeful Transitions:** Use **hard cuts on action** for momentum, **L-cuts / J-cuts** (audio leading or trailing the picture cut by `0.2–0.5s`) to smooth scene shifts, **match cuts** on visual motifs (e.g., red smoke to red warning light), and brief **blackout or `0.5–0.7s` silence drops** before major twists. Avoid random flashy transitions that break spatial immersion.
- **Coherent Subtitle & Sound Sync:** Group burned-in captions into **complete, natural semantic clauses** (never disconnected 1–2 word orphan fragments that break sentence meaning). Align caption entry/exit with speaker changes and beat cuts, and verify line wrapping against `9:16` / `16:9` safe-zone margins on a test frame.

## 5. 4-Part Continuity System (Stage G)

1. **180-Degree Screen Direction:** Keep left-to-right spatial geography consistent across reverse-angle cuts so viewers never lose track of where characters stand relative to doorways or each other.
2. **Character & Wardrobe Lock:** Lock outfits, accessories, and held items before Take 1 (and pass approved reference frames forward when generating consecutive AI visuals).
3. **Location, Lighting & Floor Marks:** Lock in-game time-of-day and lighting mood before shooting/generating a scene. Use fixed landmarks (rug corners, doorframes, tile lines, curb edges) as repeatable actor marks across takes.
4. **Editing Handles (Trim Buffers):** Record enough additional footage to allow clean editing. Recommend 2–3 seconds of handles where practical, but adapt to the shot and recording method.

## 6. Evidence-Based Visual QC Rules (From Real AI Video Runs)

- **Prop-State Visual Truth:** When narration or dialogue highlights a physical detail or contrast (e.g., a torn/broken prop vs. a brand-new replacement, or a readable note), show it visually via distinct prop geometry or a dedicated close-up insert—never reuse the identical intact prop model across both states.
- **Flashback & Time-Jump Differentiation:** Separate past flashbacks from present scenes using at least two clear cues (lighting/color-grade shift, ambient sound shift such as rain or room tone, and a purposeful transition) so viewers never confuse timelines.
- **Distinct Character Silhouettes & Faces:** Differentiate characters speaking or standing in the same frame with distinct hairstyles, accessories, or facial features—never clone the identical face/head mesh and recolor only the shirt.
