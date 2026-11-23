#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Generate synthetic tone fixtures locally for examples/recorded-voice-test-project/.

Keeps the repository free of committed audio binaries and derived stems.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    audio_dir = root / "test_audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=260:sample_rate=44100:duration=1.6",
            "-af", "volume=0.3",
            str(audio_dir / "v01_narrator_line1.wav"),
        ],
        check=True,
        timeout=60.0,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "sine=frequency=340:sample_rate=44100:duration=1.8",
            "-af", "volume=0.3",
            str(audio_dir / "v03_leo_line2.mp3"),
        ],
        check=True,
        timeout=60.0,
    )
    (audio_dir / "corrupt_maya_line3.wav").write_bytes(b"RIFF_CORRUPT_TEST_PAYLOAD_FOR_REJECTION_VALIDATION")
    print(f"Generated synthetic fixtures in {audio_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
