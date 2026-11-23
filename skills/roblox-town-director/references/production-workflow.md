# Production Workflow and Method Classification Guide

Load during **Stages F–H** (`SHOOT`, `REVIEW`, `FULL`).

## 1. Mandatory Production-Method Classification

Every production plan must explicitly classify which production method the story requires—and never pretend a custom-animated scene can be reproduced via ordinary live gameplay:

| Production Method | What It Covers | Typical Capabilities |
| :--- | :--- | :--- |
| **1. Live Gameplay Staging** | Recording actions performed inside an existing Roblox experience (Brookhaven, Berry Avenue, Livetopia, Bloxburg, etc.). | Walking, turning, sitting, tapping doors, standard avatar outfits, basic in-game props/vehicles (`UNVERIFIED` until checked). |
| **2. Custom Roblox Animation** | Custom rigs, keyframed animations, Roblox Studio environments, scripted VFX/lighting, Moon Animator. | Expressive 2D/3D facial swaps, giant custom creatures (e.g., horse-sized mice), custom weather/lava floors, precise camera paths. |
| **3. Hybrid / External Production** | Roblox assets or footage combined with Blender, 2D animation, compositing, or external AI-assisted animation/video tools. | High-contrast cinematic lighting, custom 2D face overlays, motion graphics, stylized thumbnails, and composite effects. |

**Resource-Aware Alternatives:** Whenever a concept naturally leans toward **Custom Roblox Animation** or **Hybrid Production** (such as *"In This Town..."* stories with swarms of mice or stretching smiles), explicitly identify the **exact capabilities required** (e.g., custom rigging, Studio VFX, or 2D/3D compositing)—and if the creator only has **Live Gameplay Staging**, provide a practical rewrite using doorways, static editor overlays, sound cues, and reaction cuts.

## 2. Experience-Agnostic Verification (`UNVERIFIED` Rule)

- Never assume an experience has a specific prop, vehicle, emote, door lock, or private server price.
- Mark uncertain game features **`UNVERIFIED`**, pair them with a **1-Minute In-Game Check**, and include a fallback that requires zero special props.

## 3. Cast Blocking & Coordination

- **Solo (1 Person, 1 Device):** Use 1st-person POV, narrator voiceover, doorway/mirror framing, or shoot-and-swap reverse angles on fixed floor marks.
- **1 Helper (2 Devices):** Separate **`[Camera Operator Avatar]`** (hidden off-screen or behind cover) from **`[Actor Avatar]`**. For 2-character beats on 2 devices, alternate between hidden-camera solo shots and actor-POV/reverse-angle cuts.
- **Multi-Actor Cast (3+ Players):** Assign one dedicated `[Camera Operator Avatar]`, coordinate cues via voice call or timer, and shoot out of story order grouped by location to prevent public-server build resets.

## 4. Environment-Adaptive Capture Notes (Apply Only When Relevant)

- **Roblox Built-in Captures:** Per [Roblox Support](https://en.help.roblox.com/hc/en-us/articles/203314190-How-do-I-take-a-video-in-an-experience), Captures records up to **30 seconds** and hides in-game UI, **but does not record in-experience audio**. Use for silent B-roll where VO and SFX are added in post.
- **Mobile Environments (Android / iOS):**
  - *Orientation & Crop Math:* For `9:16` vertical videos, test **portrait capture** first. If portrait UI blocks the view and you record in `16:9` landscape to crop to `9:16`, only **~31.6% of the original width** stays visible (`(9/16) / (16/9) = 81/256`). Keep subjects centered and preview the crop on a **10s Technical Test Clip**.
  - *Device Stability:* Screen-recorder internal audio, FPS, storage, and thermal limits vary by device and OS version—never guarantee fixed specs. Recommend testing Manual Graphics ([Google Play Roblox Guide](https://play.google.com/store/apps/editorial?id=mc_games_editorialevergreen_postinstall_best_roblox_settings_for_gameplay_now_fcp&hl=en_AU)), closing background apps, and filming in modular blocks.
- **Desktop Environments (PC / Mac):** Creators on desktop may use screen capture (e.g., OBS), Roblox Studio, or developer Freecam (`Shift+P`, available to experience owners/editors per [Roblox Creator Hub](https://create.roblox.com/docs/workspace/camera/free-camera)). When a requested effect depends on desktop-only tools (such as Roblox Studio or Blender), state the exact tool/capability required and offer a lower-resource staging workaround rather than relying on a blunt rejection.
