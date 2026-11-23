# Editing Theory, Sound Design, and Packaging Guide

Load during **Stages I–K** (`POST`, `REVIEW`, `FULL`).

## 1. Editing Theory, Rhythm & Visual Pacing (Stage I)

- **Radio Edit First:** Assemble the voiceover and dialogue track first, trimming dead air (>0.2–0.3s unless intentional silence). Match visual cut rhythm to genre:
  - *"In This Town..." / High-Concept Shorts:* Brisk 1–2.5s visual cuts during world-building escalation, slowing slightly for the protagonist's key decision and twist.
  - *Suspense / Mystery:* Let doorway holds and reaction beats linger before cutting sharply on a discovery.
  - *Comedy:* Keep setup tight and cut cleanly right after the visual punchline lands.
  - *Emotional / Drama:* Allow 1–2 seconds of visual breathing room after key lines.
- **Cutting on Action & Eye-Trace:** Cut mid-turn or mid-step through a doorway so edits feel seamless, and keep the focal subject in a consistent screen area across rapid cuts.
- **Restraint Over Flashy Transitions:** Hard cuts should carry 90%+ of the film; reserve push-ins or fades for deliberate time jumps or twists.
- **Overlays & Sound-Off Readability:**
  - Use clean **in-editor text/shape overlays** on stationary frames for readable notes, shipping labels, or pop-up signs.
  - Burn in bold, high-contrast captions (1–3 word rhythmic pop-ups or clean upper-center lines clear of platform UI) so 100% of the story works with sound muted. Verify caption line wrapping against safe-zone margins on a test frame so long lines never clip past the frame edge.
- **Tool-Agnostic Execution:** Adapt timeline instructions to whatever editor the creator uses (mobile or desktop). Never assume a specific app is installed or regionally available; run a **10-second test export** to check audio sync, framing, and watermark rules before full render.

## 2. 4-Layer Sound Architecture & Licensing (Stage J)

Sound sells weight, space, and off-screen presence that avatars cannot animate:
1. **Dialogue / Voiceover (Primary):** Follow [voice-identity-lock.md](voice-identity-lock.md), [voice-direction.md](voice-direction.md), and [voice-provider-adapter.md](voice-provider-adapter.md) to keep `V01`–`V06` speaker-separated and continuity-locked. For human voiceover, record in a quiet, soft-furnished room (~15 cm from mic at a 45° angle). If AI TTS is used, run capability discovery and verify current official commercial, consent, and attribution terms first.
2. **Ambience (World Glue):** Subtle continuous room tone, wind, or street noise uniting separate takes.
3. **Punctuation SFX (Foley & Impact):** Footsteps, door latches, poofs, alarms, creaks, and stingers timed to exact visual frames.
4. **Music & Strategic Silence:** Duck music beneath speech. Drop **all** music and ambience for **`0.5s` of total silence** right before a twist or reveal so the payoff hits with contrast.
- **Licensing Discipline:** Use reputable royalty-free libraries (YouTube Audio Library, Pixabay, Mixkit) and verify current license terms per track. Never assume "royalty-free" means zero Content ID claims—keep the track URL and license note.

## 3. Content Packaging & Honest Analytics (Stage K)

- **Three-Angle Title Options:** Provide 3 honest titles—**(1) Curiosity Gap**, **(2) Immediate Conflict/Rule**, and **(3) High-Stakes Outcome**—and recommend the strongest.
- **First-Frame (`0:00`) & Thumbnail Composition:** Match the opening frame/thumbnail to the exact question in the title using 1 clear focal subject, strong contrast, and at most 2–4 words of text.
- **Analytics Review:** Track performance using [YouTube Studio Content Analytics](https://support.google.com/youtube/answer/12942217) (Impressions CTR, Average View Duration, Intro retention, Top Moments, Spikes, and Dips) against the channel's own baseline rather than unverified universal percentage thresholds.
