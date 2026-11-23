#!/usr/bin/env python3
"""
Automated regression and hardening test suite for Roblox Town Director Recorded Voice Backend.
Run from repository root:
  python3 -m unittest discover -s tests -v
"""

import array
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "roblox-town-director" / "scripts"
REGISTRY_PATH = REPO_ROOT / "skills" / "roblox-town-director" / "templates" / "voice-registry.json"
sys.path.insert(0, str(SCRIPTS_DIR))

from voice_backend import (  # noqa: E402
    ExternalTTSBackend,
    RecordedVoiceBackend,
    SharedVoiceManager,
)


def make_sine_wav(path: Path, freq: float, dur: float, sr: int = 44100, amp: float = 0.4) -> None:
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-f", "lavfi",
            "-i", f"aevalsrc={amp}*sin(2*PI*{freq}*t):d={dur}:s={sr}",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_mp3(path: Path, freq: float, dur: float, amp: float = 0.3) -> None:
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-y", "-f", "lavfi",
            "-i", f"aevalsrc=0:d=0.3:s=44100[s1];sine=f={freq}:d={dur}:r=44100,volume={amp}[t];aevalsrc=0:d=0.3:s=44100[s2];[s1][t][s2]concat=n=3:v=0:a=1",
            "-c:a", "libmp3lame", "-b:a", "128k",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class TestVoiceBackendHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rtd_voice_test_"))
        self.audio_dir = self.tmp / "audio"
        self.out_dir = self.tmp / "out"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_manifest(self, char_map, dialogue_assets) -> Path:
        mf = {
            "schema_version": "1.0.0",
            "project_id": "unit_test_project",
            "project_title": "Unit Test",
            "format": "short",
            "registry_source": str(REGISTRY_PATH),
            "active_provider": {},
            "character_voice_map": char_map,
            "dialogue_assets": dialogue_assets,
            "resume_checkpoint": {},
        }
        p = self.tmp / "project-voice-manifest.json"
        p.write_text(json.dumps(mf, indent=2), encoding="utf-8")
        return p

    def test_01_wav_mp3_corrupt_missing_and_voice_mapping(self) -> None:
        wav1 = self.audio_dir / "line1.wav"
        mp3_2 = self.audio_dir / "line2.mp3"
        corrupt3 = self.audio_dir / "corrupt.wav"
        make_sine_wav(wav1, 220.0, 1.2, sr=48000)
        make_mp3(mp3_2, 330.0, 1.5)
        corrupt3.write_bytes(b"NOT_AUDIO_BYTES")

        mf_path = self._write_manifest(
            [
                {"character_id": "narrator", "display_name": "Narrator", "voice_id": "V01"},
                {"character_id": "leo", "display_name": "Leo", "voice_id": "V03"},
                {"character_id": "maya", "display_name": "Maya", "voice_id": "V05"},
            ],
            [
                {"line_id": "L1", "character_id": "narrator", "voice_id": "V01", "start_sec": 0.0, "end_sec": 1.5, "text": "One", "recording_path": "audio/line1.wav"},
                {"line_id": "L2", "character_id": "leo", "voice_id": "V03", "start_sec": 2.0, "end_sec": 4.0, "text": "Two", "recording_path": "audio/line2.mp3", "trim_start_sec": 0.1, "trim_end_sec": 1.8},
                {"line_id": "L3", "character_id": "maya", "voice_id": "V05", "start_sec": 4.5, "end_sec": 6.0, "text": "Three", "recording_path": "audio/corrupt.wav"},
                {"line_id": "L4", "character_id": "narrator", "voice_id": "V01", "start_sec": 6.5, "end_sec": 8.0, "text": "Four", "recording_path": "audio/missing.wav"},
            ],
        )
        mgr = SharedVoiceManager(REGISTRY_PATH, RecordedVoiceBackend())
        report = mgr.run_project(mf_path, self.out_dir, total_duration_sec=8.5)
        self.assertEqual(report["summary"]["successful"], 2)
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(report["summary"]["missing"], 1)
        self.assertTrue((self.out_dir / "subtitles.srt").exists())

    def test_02_external_tts_remains_blocked(self) -> None:
        mf_path = self._write_manifest(
            [{"character_id": "narrator", "display_name": "Narrator", "voice_id": "V01"}],
            [{"line_id": "L1", "character_id": "narrator", "voice_id": "V01", "start_sec": 0.0, "end_sec": 2.0, "text": "Hello"}],
        )
        mgr = SharedVoiceManager(REGISTRY_PATH, ExternalTTSBackend())
        report = mgr.run_project(mf_path, self.out_dir, total_duration_sec=2.0)
        self.assertFalse(mgr.backend.discover_capabilities()["text_to_speech"])
        self.assertEqual(report["summary"]["blocked"], 1)
        self.assertEqual(report["summary"]["successful"], 0)

    def test_03_simultaneous_overlapping_dialogue_additive_mix_and_clipping_prevention(self) -> None:
        # Two loud clips at 220Hz and 550Hz overlapping from 1.0s to 2.0s
        c1 = self.audio_dir / "c1.wav"
        c2 = self.audio_dir / "c2.wav"
        make_sine_wav(c1, 220.0, 2.0, amp=0.9)
        make_sine_wav(c2, 550.0, 2.0, amp=0.9)

        mf_path = self._write_manifest(
            [
                {"character_id": "leo", "display_name": "Leo", "voice_id": "V03"},
                {"character_id": "maya", "display_name": "Maya", "voice_id": "V05"},
            ],
            [
                {"line_id": "L1", "character_id": "leo", "voice_id": "V03", "start_sec": 0.0, "end_sec": 2.0, "text": "Leo speaks", "recording_path": "audio/c1.wav", "normalize": False, "trim_silence": False},
                {"line_id": "L2", "character_id": "maya", "voice_id": "V05", "start_sec": 1.0, "end_sec": 3.0, "text": "Maya overlaps", "recording_path": "audio/c2.wav", "normalize": False, "trim_silence": False},
            ],
        )
        mgr = SharedVoiceManager(REGISTRY_PATH, RecordedVoiceBackend())
        report = mgr.run_project(mf_path, self.out_dir, total_duration_sec=3.2)

        self.assertEqual(report["summary"]["overlaps_detected"], 1)
        self.assertTrue(report["mix_stats"]["clipping_prevented"])
        self.assertLessEqual(report["mix_stats"]["final_peak_int16"], 32767)

        # Verify overlap window (1.1s-1.9s) has higher peak than solo window (0.1s-0.9s), proving additive mix (not overwrite)
        with wave.open(report["timeline_wav"], "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        samples = array.array("h")
        samples.frombytes(raw)
        sr_ch = 44100 * 2
        solo_peak = max(abs(x) for x in samples[int(0.1 * sr_ch):int(0.9 * sr_ch)])
        overlap_peak = max(abs(x) for x in samples[int(1.1 * sr_ch):int(1.9 * sr_ch)])
        self.assertGreater(overlap_peak, solo_peak * 1.4)

    def test_04_out_of_range_and_contradictory_subtitle_validation_never_truncates(self) -> None:
        c1 = self.audio_dir / "long.wav"
        make_sine_wav(c1, 260.0, 2.5)
        mf_path = self._write_manifest(
            [{"character_id": "narrator", "display_name": "Narrator", "voice_id": "V01"}],
            [
                {"line_id": "L_BAD", "character_id": "narrator", "voice_id": "V01", "start_sec": 2.0, "end_sec": 1.0, "text": "Contradictory", "recording_path": "audio/long.wav", "trim_silence": False},
            ],
        )
        mgr = SharedVoiceManager(REGISTRY_PATH, RecordedVoiceBackend())
        report = mgr.run_project(mf_path, self.out_dir, total_duration_sec=3.0)
        err_types = {e["type"] for e in report["timeline_validation"]["errors"]}
        self.assertIn("contradictory_subtitle_timing", err_types)
        self.assertIn("out_of_range_timeline_event", err_types)
        # Never silently truncated: timeline expanded to >= 4.5s
        self.assertGreaterEqual(report["timeline_meta"]["duration_sec"], 4.4)

    def test_05_invalid_voice_assignment_and_mismatch(self) -> None:
        c1 = self.audio_dir / "ok.wav"
        make_sine_wav(c1, 220.0, 1.0)
        mf_path = self._write_manifest(
            [{"character_id": "leo", "display_name": "Leo", "voice_id": "V03"}],
            [
                {"line_id": "L_MISMATCH", "character_id": "leo", "voice_id": "V02", "start_sec": 0.0, "end_sec": 1.2, "text": "Wrong voice", "recording_path": "audio/ok.wav"},
                {"line_id": "L_INVALID", "character_id": "leo", "voice_id": "V99", "start_sec": 1.5, "end_sec": 2.5, "text": "Bad ID", "recording_path": "audio/ok.wav"},
            ],
        )
        mgr = SharedVoiceManager(REGISTRY_PATH, RecordedVoiceBackend())
        report = mgr.run_project(mf_path, self.out_dir, total_duration_sec=3.0)
        self.assertEqual(report["summary"]["failed"], 2)
        self.assertEqual(report["summary"]["successful"], 0)


    def test_06_manifest_id_path_traversal_rejected(self) -> None:
        """Regression: malicious manifest line_id or character_id must never write outside output_dir."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_dir = base / "stems"
            out_dir.mkdir(parents=True, exist_ok=True)
            wav_src = base / "valid.wav"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100:duration=0.6",
                    str(wav_src),
                ],
                stdin=subprocess.DEVNULL,
                check=True,
            )
            backend = RecordedVoiceBackend()
            res = backend.process_line(
                {
                    "line_id": "../../escaped_line",
                    "character_id": "narrator",
                    "voice_id": "V01",
                    "recording_path": str(wav_src),
                },
                out_dir,
                base,
            )
            self.assertEqual(res["status"], "failed")
            self.assertIn("Unsafe path characters", res["reason"])
            self.assertIsNone(res["processed_path"])
            self.assertEqual(list(out_dir.iterdir()), [])

    def test_07_relative_recording_path_traversal_rejected(self) -> None:
        """Regression: relative recording_path escaping base_dir must be rejected."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proj_dir = root / "project"
            out_dir = proj_dir / "stems"
            out_dir.mkdir(parents=True, exist_ok=True)
            outside_wav = root / "outside_secret.wav"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100:duration=0.6",
                    str(outside_wav),
                ],
                stdin=subprocess.DEVNULL,
                check=True,
            )
            backend = RecordedVoiceBackend()
            res = backend.process_line(
                {
                    "line_id": "S01_L01",
                    "character_id": "narrator",
                    "voice_id": "V01",
                    "recording_path": "../outside_secret.wav",
                },
                out_dir,
                proj_dir,
            )
            self.assertEqual(res["status"], "failed")
            self.assertIn("escapes project base_dir", res["reason"])
            self.assertIsNone(res["processed_path"])

    def test_08_probe_and_process_line_timeout_and_missing_binary(self) -> None:
        """Regression (F-07): ffprobe/ffmpeg timeouts and missing binaries fail cleanly with no partial output."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            out_dir = base / "stems"
            out_dir.mkdir(parents=True, exist_ok=True)
            wav_src = base / "valid.wav"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100:duration=0.6",
                    str(wav_src),
                ],
                stdin=subprocess.DEVNULL,
                check=True,
                timeout=30.0,
            )
            backend = RecordedVoiceBackend()
            with patch("voice_backend.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=60.0)):
                ok, meta, err = backend.probe_audio(wav_src)
            self.assertFalse(ok)
            self.assertIn("timed out", err)

            with patch.object(backend, "probe_audio", return_value=(True, {"duration_sec": 0.6, "sample_rate": 44100, "channels": 1}, None)):
                with patch("voice_backend.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120.0)):
                    res = backend.process_line(
                        {"line_id": "S01_L01", "character_id": "narrator", "voice_id": "V01", "recording_path": str(wav_src)},
                        out_dir,
                        base,
                    )
            self.assertEqual(res["status"], "failed")
            self.assertIn("timed out", res["reason"])
            self.assertEqual(list(out_dir.iterdir()), [])

if __name__ == "__main__":
    unittest.main()
