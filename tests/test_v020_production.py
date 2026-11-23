#!/usr/bin/env python3
"""Automated executable tests for Roblox Town Director v0.2.0 capabilities.

Verifies:
  - Real FFmpeg ASS burn-in rendering & decoding of ALL 15 caption presets (C01-C15)
  - C16 Auto Adaptive selector across genres, pacing, speaker count, and tone
  - Dynamic 9:16 (1080x1920) & 16:9 (1920x1080) scaling + Unicode/ASS escaping
  - Integrated mux_audio_and_subtitles_to_video(..., caption_style_id=...) & CLI list-caption-styles
  - Per-scene persistent ProductionStateManager, single-scene failure recovery, and user-script lock
  - Hard Final Delivery Gate (COMPLETE vs INCOMPLETE vs FAILED)
  - Honest host resource inspection
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "roblox-town-director" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import caption_styles  # noqa: E402
from production_state import (  # noqa: E402
    ProductionStateManager,
    evaluate_final_delivery_gate,
    inspect_host_resources,
)
from voice_intelligence import (  # noqa: E402
    inspect_video_file,
    mux_audio_and_subtitles_to_video,
)


class TestV020ProductionCapabilities(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._shared_tmp = tempfile.TemporaryDirectory()
        cls.shared_dir = Path(cls._shared_tmp.name)
        cls.base_video = cls.shared_dir / "base_360x640_24fps.mp4"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x162447:s=180x320:r=12:d=1.5",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                str(cls.base_video),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
            timeout=30.0,
        )
        cls.base_audio = cls.shared_dir / "voice.wav"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-y", "-v", "error",
                "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=1.5",
                "-af", "volume=0.25",
                str(cls.base_audio),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
            timeout=30.0,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._shared_tmp.cleanup()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # 1. Real FFmpeg rendering & decoding of ALL 15 caption presets (C01-C15)
    def test_01_all_15_caption_presets_render_and_decode_via_ffmpeg(self) -> None:
        presets = caption_styles.load_caption_presets()
        self.assertEqual(len(presets), 16)
        cues = [
            caption_styles.CaptionCue(0.0, 0.75, "Wait—that was the last bus!", speaker="Toby"),
            caption_styles.CaptionCue(0.75, 1.45, "Come inside before you freeze.", speaker="Mr. Arthur"),
        ]
        seen_styles = set()
        for idx in range(1, 16):
            pid = f"C{idx:02d}"
            doc = caption_styles.generate_ass_document(cues, style_id=pid, width=360, height=640)
            self.assertEqual(doc["preset_id"], pid)
            self.assertEqual(doc["source_cue_count"], 2)
            self.assertGreaterEqual(doc["cue_count"], 2)
            seen_styles.add(doc["ass_content"].split("[Events]")[0])

            ass_file = self.tmp_dir / f"{pid}.ass"
            ass_file.write_text(doc["ass_content"], encoding="utf-8")
            out_mp4 = self.tmp_dir / f"render_{pid}.mp4"
            res = caption_styles.render_ass_captions_onto_video(
                video_path=self.base_video,
                ass_path=ass_file,
                output_video_path=out_mp4,
            )
            self.assertGreater(res["bytes_written"], 1000)
            qc = inspect_video_file(out_mp4)
            self.assertTrue(qc["valid"], f"Preset {pid} produced invalid MP4: {qc['errors']}")
            self.assertEqual((qc["width"], qc["height"]), (180, 320))

        # Confirm presets are genuinely distinct in ASS style definitions
        self.assertEqual(len(seen_styles), 15)

    # 2. C16 Auto Adaptive selection across genres, pacing, speakers, and tone
    def test_02_c16_auto_adaptive_selects_expected_presets(self) -> None:
        self.assertEqual(caption_styles.select_caption_style(genre="comedy", pacing="fast"), "C05")
        self.assertEqual(caption_styles.select_caption_style(genre="gaming"), "C09")
        self.assertEqual(caption_styles.select_caption_style(genre="documentary"), "C10")
        self.assertEqual(caption_styles.select_caption_style(genre="suspense", visual_complexity="high"), "C11")
        self.assertEqual(caption_styles.select_caption_style(genre="emotional", speaker_count=2), "C12")
        self.assertEqual(caption_styles.select_caption_style(genre="story", speaker_count=3), "C08")
        self.assertEqual(caption_styles.select_caption_style(genre="story", pacing="fast", tone="energetic"), "C02")

        resolved = caption_styles.resolve_preset("C16", genre="gaming")
        self.assertEqual(resolved["id"], "C09")
        self.assertEqual(resolved["selected_via"], "C16")

    # 3. Dynamic 9:16 & 16:9 scaling + Unicode & ASS control escaping
    def test_03_caption_dynamic_scaling_9x16_and_16x9_plus_unicode_escaping(self) -> None:
        cues = [
            caption_styles.CaptionCue(0.0, 2.0, "Look {here} \\ now — café 100%!", speaker="Toby"),
        ]
        v_doc = caption_styles.generate_ass_document(cues, style_id="C02", width=1080, height=1920)
        h_doc = caption_styles.generate_ass_document(cues, style_id="C02", width=1920, height=1080)
        self.assertIn("PlayResX: 1080", v_doc["ass_content"])
        self.assertIn("PlayResY: 1920", v_doc["ass_content"])
        self.assertIn("PlayResX: 1920", h_doc["ass_content"])
        self.assertIn("PlayResY: 1080", h_doc["ass_content"])
        self.assertIn(r"\{here\}", v_doc["ass_content"])
        self.assertIn(r"\kf", v_doc["ass_content"])
        self.assertIn("café", v_doc["ass_content"])

    # 4. Integrated mux_audio_and_subtitles_to_video(..., caption_style_id=...) & CLI list-caption-styles
    def test_04_mux_with_caption_style_and_cli_list_caption_styles(self) -> None:
        srt_file = self.tmp_dir / "dialogue.srt"
        srt_file.write_text(
            "1\n00:00:00,000 --> 00:00:01,400\nToby: Testing karaoke burn-in with audio mux.\n",
            encoding="utf-8",
        )
        out_mp4 = self.tmp_dir / "captioned_mux.mp4"
        report = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=self.base_audio,
            output_video_path=out_mp4,
            subtitles_srt_path=srt_file,
            embed_subtitles=True,
            caption_style_id="C02",
        )
        self.assertEqual(report["caption_style"]["preset_id"], "C02")
        self.assertTrue(report["caption_style"]["burned_in"])
        self.assertTrue(report["output_video_qc"]["has_audio"])
        self.assertTrue(report["output_video_qc"]["has_subtitles"])

        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS_DIR)
        p = subprocess.run(
            [sys.executable, "-m", "voice_intelligence", "list-caption-styles"],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30.0,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["count"], 16)

    # 5. Per-scene state persistence, single-scene failure recovery & user-script preservation lock
    def test_05_per_scene_state_persistence_and_failure_recovery(self) -> None:
        state_file = self.tmp_dir / "production_state.json"
        mgr = ProductionStateManager(state_file)
        mgr.initialize(
            project_id="LAST_BUS_V2",
            title="The Last Bus",
            operating_mode="user_script",
            output_classification="animatic",
            scene_ids=["S01", "S02", "S03"],
            script_text="Toby: Original user script line.",
            user_script_locked=True,
            caption_style_id="C12",
            voice_assignments={"toby": "V03"},
        )
        # User-supplied script must not be silently rewritten
        with self.assertRaises(PermissionError):
            mgr.update_script("Toby: Silently changed line.")
        mgr.update_script("Toby: Authorized edit.", user_authorized_rewrite=True)

        import shutil
        s1_asset = self.tmp_dir / "S01.mp4"
        s2_asset = self.tmp_dir / "S02.mp4"
        shutil.copy2(self.base_video, s1_asset)
        shutil.copy2(self.base_video, s2_asset)
        mgr.mark_scene_completed("S01", s1_asset, provider="ffmpeg")
        mgr.mark_scene_completed("S02", s2_asset, provider="ffmpeg")
        mgr.mark_scene_failed("S03", "Transient render timeout")

        # Reload from disk (simulated restart) -> only S03 needs retry; S01 & S02 stay completed
        mgr2 = ProductionStateManager(state_file)
        self.assertEqual(mgr2.get_pending_or_failed_scenes(), ["S03"])
        self.assertEqual(mgr2.state["scenes"]["S01"]["status"], "completed")
        self.assertEqual(mgr2.state["scenes"]["S03"]["status"], "failed")

    # 6. Hard Final Delivery Gate (COMPLETE vs INCOMPLETE vs FAILED)
    def test_06_final_delivery_gate_complete_incomplete_and_failed(self) -> None:
        # Missing file -> FAILED
        g_fail = evaluate_final_delivery_gate(video_path=self.tmp_dir / "missing.mp4")
        self.assertEqual(g_fail["status"], "FAILED")
        self.assertFalse(g_fail["playable_video_delivered"])

        # Silent video when audio is required -> INCOMPLETE
        g_inc = evaluate_final_delivery_gate(
            video_path=self.base_video,
            expected_duration_sec=1.5,
            require_audio=True,
        )
        self.assertEqual(g_inc["status"], "INCOMPLETE")
        self.assertFalse(g_inc["playable_video_delivered"])

        # Complete muxed video with audio + captions -> COMPLETE
        srt_file = self.tmp_dir / "gate.srt"
        srt_file.write_text("1\n00:00:00,000 --> 00:00:01,400\nToby: Ready.\n", encoding="utf-8")
        final_mp4 = self.tmp_dir / "final_complete.mp4"
        mux_rep = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=self.base_audio,
            output_video_path=final_mp4,
            subtitles_srt_path=srt_file,
            embed_subtitles=True,
            caption_style_id="C01",
        )
        g_ok = evaluate_final_delivery_gate(
            video_path=final_mp4,
            expected_duration_sec=1.5,
            expected_width=180,
            expected_height=320,
            expected_fps=12.0,
            require_audio=True,
            require_captions=True,
            caption_render_receipt=mux_rep["caption_style"],
            output_classification="animatic",
        )
        self.assertEqual(g_ok["status"], "COMPLETE")
        self.assertTrue(g_ok["playable_video_delivered"])
        self.assertTrue(g_ok["full_decode_passed"])

    # 7. Honest host resource inspection
    def test_07_host_resource_inspection_honest(self) -> None:
        info = inspect_host_resources()
        self.assertIn("available", info)
        if info["available"]:
            self.assertGreater(info["mem_total_mb"], 0)
            self.assertGreater(info["mem_available_mb"], 0)


    # 8. Regression (F-12): Invalid, 0-byte, corrupt, and missing scene files are NEVER skipped on recovery
    def test_08_f12_invalid_empty_and_missing_scene_assets_never_skipped(self) -> None:
        import shutil
        state_file = self.tmp_dir / "f12_state.json"
        mgr = ProductionStateManager(state_file)
        mgr.initialize(
            project_id="F12_CHECK",
            title="F12 Recovery Integrity",
            scene_ids=["S01_valid", "S02_empty", "S03_corrupt", "S04_missing"],
            script_text="Toby: Testing asset validation.",
        )
        valid_clip = self.tmp_dir / "valid.mp4"
        shutil.copy2(self.base_video, valid_clip)
        empty_clip = self.tmp_dir / "empty.mp4"
        empty_clip.write_bytes(b"")
        corrupt_clip = self.tmp_dir / "corrupt.mp4"
        corrupt_clip.write_bytes(b"NOT_A_VALID_MP4_STREAM")
        missing_clip = self.tmp_dir / "does_not_exist.mp4"

        mgr.mark_scene_completed("S01_valid", valid_clip)
        mgr.mark_scene_completed("S02_empty", empty_clip)
        mgr.mark_scene_completed("S03_corrupt", corrupt_clip)
        mgr.mark_scene_completed("S04_missing", missing_clip)

        reloaded = ProductionStateManager(state_file)
        self.assertEqual(
            reloaded.get_pending_or_failed_scenes(),
            ["S02_empty", "S03_corrupt", "S04_missing"],
        )

    # 9. Regression (F-13): Unverified captions_burned_in=True boolean is rejected; SHA-256 receipt passes
    def test_09_f13_unverified_captions_burned_in_boolean_rejected(self) -> None:
        # Video with audio but NO embedded subtitles and NO burned-in captions
        no_cap_mp4 = self.tmp_dir / "no_captions.mp4"
        mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=self.base_audio,
            output_video_path=no_cap_mp4,
            subtitles_srt_path=None,
            embed_subtitles=False,
        )
        # Merely setting captions_burned_in=True MUST FAIL the delivery gate
        g_spoofed = evaluate_final_delivery_gate(
            video_path=no_cap_mp4,
            require_audio=True,
            require_captions=True,
            captions_burned_in=True,
        )
        self.assertEqual(g_spoofed["status"], "INCOMPLETE")
        self.assertFalse(g_spoofed["captions_verified"])
        self.assertTrue(any("Unverified captions_burned_in=True claim rejected" in f for f in g_spoofed["failures"]))

        # Genuine burned-in captions (embed_subtitles=False) with SHA-256 verified receipt MUST PASS
        srt_file = self.tmp_dir / "burned_only.srt"
        srt_file.write_text("1\n00:00:00,000 --> 00:00:01,400\nToby: Verified burned-in.\n", encoding="utf-8")
        burned_only_mp4 = self.tmp_dir / "burned_only.mp4"
        mux_rep = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=self.base_audio,
            output_video_path=burned_only_mp4,
            subtitles_srt_path=srt_file,
            embed_subtitles=False,
            caption_style_id="C01",
        )
        g_verified = evaluate_final_delivery_gate(
            video_path=burned_only_mp4,
            require_audio=True,
            require_captions=True,
            caption_render_receipt=mux_rep["caption_style"],
        )
        self.assertEqual(g_verified["status"], "COMPLETE")
        self.assertTrue(g_verified["captions_verified"])
        self.assertEqual(g_verified["caption_verification_method"], "sha256_render_receipt")

        # Tampering with receipt SHA-256 MUST FAIL
        bad_receipt = dict(mux_rep["caption_style"])
        bad_receipt["output_sha256"] = "0" * 64
        g_tampered = evaluate_final_delivery_gate(
            video_path=burned_only_mp4,
            require_audio=True,
            require_captions=True,
            caption_render_receipt=bad_receipt,
        )
        self.assertEqual(g_tampered["status"], "INCOMPLETE")
        self.assertFalse(g_tampered["captions_verified"])

    # 10. Multi-Scene Assembler: mixed image + video clips, xfade transition, and interrupted recovery
    def test_10_video_assembler_mixed_inputs_xfade_and_interrupted_recovery(self) -> None:
        from PIL import Image
        from video_assembler import SceneSpec, VideoAssemblyError, assemble_scenes_with_transitions

        img_path = self.tmp_dir / "scene1_keyframe.jpg"
        Image.new("RGB", (180, 320), (35, 90, 150)).save(img_path)

        state_file = self.tmp_dir / "asm_state.json"
        mgr = ProductionStateManager(state_file)
        mgr.initialize(
            project_id="ASM_REC",
            title="Assembly Recovery Test",
            scene_ids=["S01", "S02"],
            script_text="Toby: Testing recovery.",
        )

        # Pass 1: S01 succeeds, S02 fails because of missing input
        bad_scenes = [
            SceneSpec("S01", "image", img_path, duration_sec=1.5, motion="zoom_in", transition="fade", transition_duration_sec=0.3),
            SceneSpec("S02", "video", self.tmp_dir / "missing_scene2.mp4", duration_sec=1.5, transition="none"),
        ]
        with self.assertRaises(VideoAssemblyError):
            assemble_scenes_with_transitions(
                bad_scenes,
                work_dir=self.tmp_dir / "asm_work",
                output_video_path=self.tmp_dir / "assembled.mp4",
                width=360,
                height=640,
                fps=24,
                state_manager=mgr,
            )
        self.assertEqual(mgr.state["scenes"]["S01"]["status"], "completed")
        self.assertEqual(mgr.state["scenes"]["S02"]["status"], "failed")

        # Pass 2: Fix S02 input and resume -> S01 MUST be skipped (cached), S02 rendered, xfade assembled
        good_scenes = [
            SceneSpec("S01", "image", img_path, duration_sec=1.5, motion="zoom_in", transition="fade", transition_duration_sec=0.3),
            SceneSpec("S02", "video", self.base_video, duration_sec=1.5, transition="none"),
        ]
        mgr_resume = ProductionStateManager(state_file)
        rep = assemble_scenes_with_transitions(
            good_scenes,
            work_dir=self.tmp_dir / "asm_work",
            output_video_path=self.tmp_dir / "assembled.mp4",
            width=360,
            height=640,
            fps=24,
            state_manager=mgr_resume,
        )
        self.assertEqual(rep["skipped_cached_scenes"], ["S01"])
        self.assertEqual(rep["rendered_scenes"], ["S02"])
        self.assertTrue(rep["video_qc"]["valid"])
        self.assertEqual((rep["video_qc"]["width"], rep["video_qc"]["height"]), (360, 640))
        self.assertAlmostEqual(rep["video_qc"]["duration_sec"], 2.7, delta=0.25)

    # 11. Dialogue-aware BGM ducking via FFmpeg sidechaincompress
    def test_11_dialogue_aware_bgm_ducking(self) -> None:
        from video_assembler import mix_dialogue_and_ducked_bgm

        bgm = self.tmp_dir / "bgm.wav"
        sfx = self.tmp_dir / "sfx.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=200:sample_rate=48000:duration=2.0", "-af", "volume=0.3", str(bgm)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=0.4", "-af", "volume=0.2", str(sfx)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        out_wav = self.tmp_dir / "ducked_master.wav"
        rep = mix_dialogue_and_ducked_bgm(
            dialogue_audio_path=self.base_audio,
            bgm_audio_path=bgm,
            sfx_audio_path=sfx,
            output_wav_path=out_wav,
        )
        self.assertTrue(rep["bgm_ducking_applied"])
        self.assertTrue(rep["sfx_included"])
        self.assertTrue(rep["audio_qc"]["valid"])
        self.assertEqual(rep["audio_qc"]["sample_rate_hz"], 48000)
        self.assertEqual(rep["audio_qc"]["channels"], 2)
        self.assertFalse(rep["audio_qc"]["clipping_detected"])

    # 12. Visual QC: black-frame detection & PIL scene contact sheet
    def test_12_visual_qc_black_frame_detection_and_contact_sheet(self) -> None:
        from visual_qc import detect_black_segments, generate_scene_contact_sheet

        # Normal colored video -> 0 unexpected blank segments
        qc_clean = detect_black_segments(self.base_video)
        self.assertTrue(qc_clean["valid"])
        self.assertFalse(qc_clean["has_unexpected_blank_segments"])

        # Pure black 1.2s video -> blackdetect MUST flag it
        black_mp4 = self.tmp_dir / "black_1s.mp4"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=180x320:r=12:d=1.2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(black_mp4)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        qc_black = detect_black_segments(black_mp4, min_duration_sec=0.4)
        self.assertTrue(qc_black["valid"])
        self.assertTrue(qc_black["has_unexpected_blank_segments"])
        self.assertGreaterEqual(qc_black["total_black_duration_sec"], 1.0)

        # Contact sheet PNG generation
        sheet_png = self.tmp_dir / "contact_sheet.png"
        sheet_rep = generate_scene_contact_sheet(
            self.base_video,
            sheet_png,
            scene_timestamps=[0.3, 0.9],
            scene_labels=["S01", "S02"],
        )
        self.assertTrue(sheet_png.exists())
        self.assertEqual(sheet_rep["frame_count"], 2)
        self.assertTrue(sheet_rep["requires_human_or_multimodal_inspection"])

    # 13. Unified Autopilot Runner end-to-end (Python API + CLI subprocess)
    def test_13_unified_autopilot_runner_end_to_end_and_cli(self) -> None:
        from PIL import Image
        from autopilot import run_autopilot_production

        img1 = self.tmp_dir / "ap_s1.jpg"
        Image.new("RGB", (180, 320), (40, 110, 170)).save(img1)
        bgm = self.tmp_dir / "ap_bgm.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=196:sample_rate=48000:duration=2.5", "-af", "volume=0.25", str(bgm)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        srt = self.tmp_dir / "ap_subs.srt"
        srt.write_text(
            "1\n00:00:00,100 --> 00:00:01,200\nToby: One prompt to one finished video.\n"
            "2\n00:00:01,300 --> 00:00:02,400\nMr. Arthur: Verified by the delivery gate.\n",
            encoding="utf-8",
        )
        spec = {
            "project_id": "AUTOPILOT_E2E",
            "title": "Autopilot End-to-End Test",
            "operating_mode": "autonomous",
            "output_classification": "animatic",
            "width": 180,
            "height": 320,
            "fps": 12,
            "genre": "emotional",
            "caption_style_id": "C16",
            "script_text": "Toby: One prompt to one finished video.",
            "dialogue_audio_path": str(self.base_audio),
            "bgm_audio_path": str(bgm),
            "subtitles_srt_path": str(srt),
            "scenes": [
                {"scene_id": "S01", "source_type": "image", "source_path": str(img1), "duration_sec": 1.5, "motion": "zoom_in", "transition": "fade", "transition_duration_sec": 0.3},
                {"scene_id": "S02", "source_type": "video", "source_path": str(self.base_video), "duration_sec": 1.5, "transition": "none"},
            ],
        }
        spec_file = self.tmp_dir / "spec.json"
        spec_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        out_dir = self.tmp_dir / "ap_out"

        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS_DIR)
        p = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "autopilot.py"), "--spec", str(spec_file), "--output-dir", str(out_dir)],
            stdin=subprocess.DEVNULL,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120.0,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        report = json.loads(p.stdout)
        self.assertEqual(report["delivery_status"], "COMPLETE")
        self.assertTrue(report["playable_video_delivered"])
        self.assertTrue(Path(report["final_video_path"]).exists())
        self.assertTrue(Path(report["contact_sheet_path"]).exists())
        self.assertEqual(report["mux_report"]["caption_style"]["preset_id"], "C12")
        self.assertTrue(report["delivery_gate"]["captions_verified"])
        self.assertFalse(report["delivery_gate"]["black_frame_qc"]["has_unexpected_blank_segments"])

    # 14. Regression (F-15): Dialogue duration & truncation protection (matching, video>audio, audio>video, intentional tail)
    def test_14_f15_dialogue_duration_and_truncation_protection(self) -> None:
        from voice_intelligence import VideoMuxError

        short_audio = self.tmp_dir / "short_1.0s.wav"
        long_audio = self.tmp_dir / "long_2.6s.wav"
        tail_audio = self.tmp_dir / "tail_1.9s.wav"
        for p, dur in ((short_audio, 1.0), (long_audio, 2.6), (tail_audio, 1.9)):
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=320:sample_rate=48000:duration={dur}", "-af", "volume=0.25", str(p)],
                stdin=subprocess.DEVNULL, check=True, timeout=30.0,
            )

        # a) Matching durations (1.5s video, 1.5s audio) -> PASS
        rep_match = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=self.base_audio,
            output_video_path=self.tmp_dir / "match.mp4",
        )
        self.assertTrue(rep_match["output_video_qc"]["valid"])

        # b) Video longer than audio (1.5s video, 1.0s audio) -> PASS
        rep_short = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=short_audio,
            output_video_path=self.tmp_dir / "short.mp4",
        )
        self.assertTrue(rep_short["output_video_qc"]["valid"])

        # c) Audio longer than video (2.6s audio on 1.5s video) -> MUST FAIL (no silent truncation)
        with self.assertRaises(VideoMuxError) as ctx:
            mux_audio_and_subtitles_to_video(
                video_path=self.base_video,
                dialogue_audio_path=long_audio,
                output_video_path=self.tmp_dir / "truncated_blocked.mp4",
            )
        self.assertIn("Silent dialogue truncation is prohibited", str(ctx.exception))

        # d) Intentional audio tail explicitly allowed (1.9s audio on 1.5s video with allow_audio_tail_sec=0.5) -> PASS
        rep_tail = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=tail_audio,
            output_video_path=self.tmp_dir / "tail_ok.mp4",
            allow_audio_tail_sec=0.5,
        )
        self.assertTrue(rep_tail["output_video_qc"]["valid"])
        self.assertGreater(rep_tail["audio_overrun_sec"], 0.0)

    # 15. F-14: Autopilot direct BYO recorded voice execution via voice_manifest_path + interrupted recovery
    def test_15_f14_autopilot_byo_recorded_voice_manifest_and_recovery(self) -> None:
        from PIL import Image
        from autopilot import run_autopilot_production

        proj_dir = self.tmp_dir / "byo_proj"
        proj_dir.mkdir()
        rec_wav = proj_dir / "narrator_line1.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100:duration=1.1", "-af", "volume=0.3", str(rec_wav)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        manifest = {
            "project_id": "BYO_AUTO",
            "project_title": "BYO Autopilot Test",
            "character_voice_map": [
                {"character_id": "narrator", "display_name": "Narrator", "voice_id": "V01"}
            ],
            "dialogue_assets": [
                {
                    "scene_id": "S01",
                    "line_id": "S01_L01",
                    "character_id": "narrator",
                    "voice_id": "V01",
                    "text": "Recorded BYO line.",
                    "start_sec": 0.1,
                    "end_sec": 1.2,
                    "recording_path": "narrator_line1.wav",
                }
            ],
        }
        manifest_path = proj_dir / "project-voice-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        img1 = proj_dir / "s1.jpg"
        Image.new("RGB", (180, 320), (30, 80, 140)).save(img1)
        out_dir = self.tmp_dir / "byo_out"
        spec = {
            "project_id": "BYO_E2E",
            "title": "BYO Autopilot E2E",
            "operating_mode": "user_script",
            "output_classification": "animatic",
            "width": 180,
            "height": 320,
            "fps": 12,
            "caption_style_id": "C01",
            "voice_manifest_path": str(manifest_path),
            "scenes": [
                {"scene_id": "S01", "source_type": "image", "source_path": str(img1), "duration_sec": 2.0, "motion": "static", "transition": "none"}
            ],
        }
        rep1 = run_autopilot_production(spec, output_dir=out_dir)
        self.assertEqual(rep1["delivery_status"], "COMPLETE")
        self.assertEqual(rep1["voice_stage"]["mode"], "byo_recorded_manifest")
        self.assertFalse(rep1["voice_stage"]["reused_cached_voice"])
        self.assertTrue(Path(rep1["final_video_path"]).exists())

        # Pass 2 (recovery/resume): voice_stage and S01 must both be reused without regeneration
        rep2 = run_autopilot_production(spec, output_dir=out_dir)
        self.assertEqual(rep2["delivery_status"], "COMPLETE")
        self.assertTrue(rep2["voice_stage"]["reused_cached_voice"])
        self.assertEqual(rep2["assembly_report"]["skipped_cached_scenes"], ["S01"])

    # 16. F-14: Autopilot direct VoiceGenerationPipeline execution (mocked provider + unconfigured provider honesty)
    def test_16_f14_autopilot_generated_dialogue_pipeline_and_unavailable_provider(self) -> None:
        from PIL import Image
        from autopilot import run_autopilot_production
        from voice_intelligence import (
            ElevenLabsAdapter,
            HTTPResponseData,
            ProviderRegistry,
            VoiceProfile,
            VoiceProfileManager,
        )

        wav_bytes = self.base_audio.read_bytes()
        calls = {"n": 0}

        def mock_tts(method, url, headers, body, timeout):
            calls["n"] += 1
            return HTTPResponseData(200, {"content-type": "audio/wav"}, wav_bytes)

        profiles_path = self.tmp_dir / "profiles.json"
        pm = VoiceProfileManager(profiles_path)
        pm.create_profile(
            VoiceProfile(
                voice_id="V03",
                display_name="Toby",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_toby_mock",
                intended_character="toby",
            )
        )
        img1 = self.tmp_dir / "gen_s1.jpg"
        Image.new("RGB", (180, 320), (45, 95, 160)).save(img1)

        old_key = os.environ.get("ELEVENLABS_API_KEY")
        os.environ["ELEVENLABS_API_KEY"] = "mock_key_never_sent"
        try:
            spec = {
                "project_id": "TTS_AUTO",
                "title": "TTS Autopilot E2E",
                "operating_mode": "autonomous",
                "output_classification": "animatic",
                "width": 180,
                "height": 320,
                "fps": 12,
                "caption_style_id": "C02",
                "voice_profiles_path": str(profiles_path),
                "voice_assignments": {"toby": "V03"},
                "script_text": "[S01]\nToby: Direct voice pipeline test.\n",
                "tts_output_format": "wav",
                "tts_raw_ext": "wav",
                "scenes": [
                    {"scene_id": "S01", "source_type": "image", "source_path": str(img1), "duration_sec": 2.2, "motion": "static", "transition": "none"}
                ],
            }
            out_dir = self.tmp_dir / "tts_out"
            reg = ProviderRegistry([ElevenLabsAdapter(transport=mock_tts)])
            rep1 = run_autopilot_production(spec, output_dir=out_dir, provider_registry=reg)
            self.assertEqual(rep1["delivery_status"], "COMPLETE")
            self.assertEqual(rep1["voice_stage"]["mode"], "generated_tts_pipeline")
            self.assertEqual(calls["n"], 1)

            # Resumed run skips voice generation (0 additional provider calls)
            rep2 = run_autopilot_production(spec, output_dir=out_dir, provider_registry=reg)
            self.assertTrue(rep2["voice_stage"]["reused_cached_voice"])
            self.assertEqual(calls["n"], 1)

            # Unconfigured provider (no key) reports failure honestly & returns INCOMPLETE
            os.environ.pop("ELEVENLABS_API_KEY", None)
            out_unconf = self.tmp_dir / "tts_unconf"
            rep_fail = run_autopilot_production(spec, output_dir=out_unconf, provider_registry=ProviderRegistry())
            self.assertEqual(rep_fail["voice_stage"]["status"], "failed")
            self.assertEqual(rep_fail["delivery_status"], "INCOMPLETE")
            self.assertFalse(rep_fail["playable_video_delivered"])
        finally:
            if old_key is None:
                os.environ.pop("ELEVENLABS_API_KEY", None)
            else:
                os.environ["ELEVENLABS_API_KEY"] = old_key

    # 17. Regression (F-16): Long BGM track ducked to video duration does not trigger false dialogue truncation
    def test_17_f16_long_bgm_does_not_trigger_false_dialogue_truncation(self) -> None:
        from PIL import Image
        from autopilot import run_autopilot_production

        img1 = self.tmp_dir / "f16_s1.jpg"
        Image.new("RGB", (180, 320), (35, 95, 145)).save(img1)
        long_bgm = self.tmp_dir / "long_bgm_6s.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=180:sample_rate=48000:duration=6.0", "-af", "volume=0.25", str(long_bgm)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        srt = self.tmp_dir / "f16.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,400\nToby: Short dialogue over long BGM.\n", encoding="utf-8")
        spec = {
            "project_id": "F16_BGM",
            "title": "F16 Long BGM Test",
            "operating_mode": "autonomous",
            "output_classification": "animatic",
            "width": 180,
            "height": 320,
            "fps": 12,
            "caption_style_id": "C01",
            "dialogue_audio_path": str(self.base_audio),
            "bgm_audio_path": str(long_bgm),
            "subtitles_srt_path": str(srt),
            "scenes": [
                {"scene_id": "S01", "source_type": "image", "source_path": str(img1), "duration_sec": 2.0, "motion": "static", "transition": "none"}
            ],
        }
        rep = run_autopilot_production(spec, output_dir=self.tmp_dir / "f16_out")
        self.assertEqual(rep["delivery_status"], "COMPLETE")
        self.assertLessEqual(rep["ducking_report"]["audio_qc"]["duration_sec"], 2.15)

    # 18. Regression (F-17): Temporary .ass and _cap.mp4 files are cleaned up even when muxing fails
    def test_18_f17_temp_caption_files_cleaned_up_on_mux_failure(self) -> None:
        from unittest.mock import patch
        from voice_intelligence import VideoMuxError

        srt = self.tmp_dir / "f17.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,200\nToby: Cleanup test.\n", encoding="utf-8")
        out_dir = self.tmp_dir / "f17_dir"
        out_dir.mkdir()
        out_mp4 = out_dir / "fail_mux.mp4"

        with patch("voice_intelligence.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300.0)):
            with self.assertRaises(VideoMuxError):
                mux_audio_and_subtitles_to_video(
                    video_path=self.base_video,
                    dialogue_audio_path=self.base_audio,
                    output_video_path=out_mp4,
                    subtitles_srt_path=srt,
                    caption_style_id="C01",
                )
        leftover = list(out_dir.glob(".*"))
        self.assertEqual(leftover, [], f"Leaked temp files on mux failure: {leftover}")

    # 19. Regression (F-20): video_assembler rejects invalid dimensions, FPS, and negative/NaN volumes
    def test_19_f20_video_assembler_rejects_invalid_dimensions_and_volumes(self) -> None:
        from PIL import Image
        from video_assembler import SceneSpec, VideoAssemblyError, mix_dialogue_and_ducked_bgm, normalize_scene_clip

        img1 = self.tmp_dir / "f20.jpg"
        Image.new("RGB", (180, 320), (20, 40, 80)).save(img1)
        spec = SceneSpec("S01", "image", img1, duration_sec=1.0, motion="static", transition="none")
        with self.assertRaises(VideoAssemblyError):
            normalize_scene_clip(spec, self.tmp_dir / "bad_dim.mp4", width=0, height=640, fps=24)
        with self.assertRaises(VideoAssemblyError):
            normalize_scene_clip(spec, self.tmp_dir / "bad_fps.mp4", width=180, height=320, fps=-1)
        with self.assertRaises(VideoAssemblyError):
            mix_dialogue_and_ducked_bgm(
                dialogue_audio_path=self.base_audio,
                bgm_audio_path=self.base_audio,
                output_wav_path=self.tmp_dir / "bad_vol.wav",
                bgm_base_volume=float("nan"),
            )

    # 20. Regression (F-21): max_audio_overrun_sec and allow_audio_tail_sec reject NaN, +/-inf, and negative values
    def test_20_f21_max_audio_overrun_sec_rejects_nan_inf_and_negative(self) -> None:
        from voice_intelligence import VideoMuxError

        # Create dialogue longer than base_video (~1.8s) to ensure NaN/inf cannot bypass overrun guard
        long_dlg = self.tmp_dir / "f21_long_dlg.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3.2", str(long_dlg)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        out_mp4 = self.tmp_dir / "f21_out.mp4"

        for bad_val in (float("nan"), float("inf"), float("-inf"), -0.1, -5.0, "not_a_number"):
            with self.assertRaises(VideoMuxError, msg=f"max_audio_overrun_sec={bad_val!r} must raise"):
                mux_audio_and_subtitles_to_video(
                    video_path=self.base_video,
                    dialogue_audio_path=long_dlg,
                    output_video_path=out_mp4,
                    max_audio_overrun_sec=bad_val,  # type: ignore[arg-type]
                )
            with self.assertRaises(VideoMuxError, msg=f"allow_audio_tail_sec={bad_val!r} must raise"):
                mux_audio_and_subtitles_to_video(
                    video_path=self.base_video,
                    dialogue_audio_path=long_dlg,
                    output_video_path=out_mp4,
                    allow_audio_tail_sec=bad_val,  # type: ignore[arg-type]
                )

        # Valid overrun rejection with default finite tolerance
        with self.assertRaises(VideoMuxError):
            mux_audio_and_subtitles_to_video(
                video_path=self.base_video,
                dialogue_audio_path=long_dlg,
                output_video_path=out_mp4,
            )

        # Explicit finite allow_audio_tail_sec permits intentional tail
        res_tail = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=long_dlg,
            output_video_path=self.tmp_dir / "f21_tail_ok.mp4",
            allow_audio_tail_sec=2.0,
        )
        self.assertTrue(Path(res_tail["output_video_path"]).exists())

        # Explicit allow_audio_truncation permits intentional truncation
        res_trunc = mux_audio_and_subtitles_to_video(
            video_path=self.base_video,
            dialogue_audio_path=long_dlg,
            output_video_path=self.tmp_dir / "f21_trunc_ok.mp4",
            allow_audio_truncation=True,
        )
        self.assertTrue(Path(res_trunc["output_video_path"]).exists())

    # 21. Regression (F-22): Temp .ass and _cap.mp4 files cleaned up on caption-render failure, mux failure, and timeout
    def test_21_f22_temp_caption_files_cleaned_on_render_mux_and_timeout_failures(self) -> None:
        from unittest.mock import patch
        from voice_intelligence import VideoMuxError
        import caption_styles

        srt = self.tmp_dir / "f22.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,200\nToby: Full cleanup coverage.\n", encoding="utf-8")

        # Case A: caption_styles.render_ass_captions_onto_video fails after writing .ass (and even if partial _cap.mp4 exists)
        dir_a = self.tmp_dir / "f22_render_fail"
        dir_a.mkdir()
        def _fail_caption_render(*, video_path, ass_path, output_video_path, **kwargs):
            Path(output_video_path).write_bytes(b"partial_cap")
            raise caption_styles.CaptionRenderError("Simulated ASS burn-in failure")

        with patch("caption_styles.render_ass_captions_onto_video", side_effect=_fail_caption_render):
            with self.assertRaises(caption_styles.CaptionRenderError):
                mux_audio_and_subtitles_to_video(
                    video_path=self.base_video,
                    dialogue_audio_path=self.base_audio,
                    output_video_path=dir_a / "out_a.mp4",
                    subtitles_srt_path=srt,
                    caption_style_id="C01",
                )
        self.assertEqual(list(dir_a.glob(".*")), [], f"Leaked temp files on caption-render failure: {list(dir_a.glob('.*'))}")

        # Case B: FFmpeg mux returns non-zero exit code after caption render succeeds
        dir_b = self.tmp_dir / "f22_mux_nonzero"
        dir_b.mkdir()
        fake_fail = subprocess.CompletedProcess(args=["ffmpeg"], returncode=1, stdout="", stderr="simulated mux error")
        with patch("voice_intelligence.pipeline.subprocess.run", return_value=fake_fail):
            with self.assertRaises(VideoMuxError):
                mux_audio_and_subtitles_to_video(
                    video_path=self.base_video,
                    dialogue_audio_path=self.base_audio,
                    output_video_path=dir_b / "out_b.mp4",
                    subtitles_srt_path=srt,
                    caption_style_id="C01",
                )
        self.assertEqual(list(dir_b.glob(".*")), [], f"Leaked temp files on mux non-zero failure: {list(dir_b.glob('.*'))}")

        # Case C: FFmpeg mux times out after caption render succeeds
        dir_c = self.tmp_dir / "f22_mux_timeout"
        dir_c.mkdir()
        with patch("voice_intelligence.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300.0)):
            with self.assertRaises(VideoMuxError):
                mux_audio_and_subtitles_to_video(
                    video_path=self.base_video,
                    dialogue_audio_path=self.base_audio,
                    output_video_path=dir_c / "out_c.mp4",
                    subtitles_srt_path=srt,
                    caption_style_id="C01",
                )
        self.assertEqual(list(dir_c.glob(".*")), [], f"Leaked temp files on mux timeout: {list(dir_c.glob('.*'))}")

    # 22. Regression (F-23 & F-25): Local FFmpeg pipeline never falsely verifies external Roblox/Blender/AI origin
    def test_22_f23_f25_output_classification_rejects_fabricated_and_unverifiable_origin(self) -> None:
        from PIL import Image
        import production_state
        from autopilot import run_autopilot_production
        from production_state import evaluate_final_delivery_gate, verify_output_classification

        # 0. Ensure no public attestation helper exists that can stamp arbitrary MP4s as verified external origin
        self.assertFalse(hasattr(production_state, "issue_trusted_producer_attestation"))
        self.assertFalse(hasattr(production_state, "ProducerProvenanceReceipt"))

        # 1. Single static PNG + FFmpeg claiming real_roblox_production -> downgrades to animatic
        png_path = self.tmp_dir / "f23_single.png"
        Image.new("RGB", (180, 320), (40, 100, 170)).save(png_path)
        srt = self.tmp_dir / "f23.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,200\nToby: Provenance verification test.\n", encoding="utf-8")

        spec_false_claim = {
            "project_id": "F23_FALSE_CLAIM",
            "title": "Single PNG False Claim",
            "operating_mode": "autonomous",
            "output_classification": "real_roblox_production",
            "production_provenance": {"route": "real_roblox_production", "roblox_capture_source": "fake_capture.mp4"},
            "width": 180,
            "height": 320,
            "fps": 12,
            "caption_style_id": "C01",
            "dialogue_audio_path": str(self.base_audio),
            "subtitles_srt_path": str(srt),
            "scenes": [
                {"scene_id": "S01", "source_type": "image", "source_path": str(png_path), "duration_sec": 2.0, "motion": "static", "transition": "none"}
            ],
        }
        rep = run_autopilot_production(spec_false_claim, output_dir=self.tmp_dir / "f23_out")
        self.assertEqual(rep["delivery_status"], "COMPLETE")
        self.assertEqual(rep["requested_classification"], "real_roblox_production")
        self.assertEqual(rep["output_classification"], "animatic")
        self.assertFalse(rep["provenance_verified"])
        self.assertEqual(rep["provenance_status"], "unverifiable_external_origin")
        self.assertTrue(rep["classification_downgraded"])
        self.assertEqual(rep["actual_production_route"], "ffmpeg_multi_scene_assembler")

        # 2. F-25: Fabricated AND existing-file claims across all three external classifications MUST downgrade
        test_cases = [
            ("real_roblox_production", {"route": "real_roblox_production", "roblox_capture_source": "fake_capture.mp4"}),
            ("real_roblox_production", {"route": "real_roblox_production", "roblox_capture_source": str(self.base_video)}),
            ("code_driven_roblox_style_animation", {"route": "code_driven_roblox_style_animation", "renderer_tool": "blender", "render_script_or_project": "fake.blend"}),
            ("ai_generated_video", {"route": "ai_generated_video", "video_provider": "made-up-provider", "generation_job_id": "fake-job-123"}),
        ]
        for cls_name, decl in test_cases:
            res = verify_output_classification(
                cls_name,
                production_provenance=decl,
                scene_source_types=["video"],
            )
            self.assertEqual(res["effective_classification"], "animatic", f"{cls_name} must downgrade")
            self.assertFalse(res["provenance_verified"], f"{cls_name} must not verify")
            self.assertEqual(res["provenance_status"], "unverifiable_external_origin")
            self.assertTrue(res["classification_downgraded"])
            self.assertEqual(res["declared_provenance"], decl)
            self.assertEqual(res["actual_production_route"], "ffmpeg_multi_scene_assembler")

        # 3. Direct gate call with real FFmpeg video claiming real_roblox_production still downgrades honestly
        gate_unverified = evaluate_final_delivery_gate(
            video_path=Path(rep["final_video_path"]),
            require_audio=True,
            require_captions=False,
            output_classification="real_roblox_production",
            production_provenance={"route": "real_roblox_production", "roblox_capture_source": str(self.base_video)},
            scene_source_types=["video"],
        )
        self.assertEqual(gate_unverified["output_classification"], "animatic")
        self.assertFalse(gate_unverified["provenance_verified"])
        self.assertEqual(gate_unverified["provenance_status"], "unverifiable_external_origin")
        self.assertTrue(gate_unverified["classification_downgraded"])

        # 4. Honest animatic classification is accepted cleanly
        ok_animatic = verify_output_classification("animatic", scene_source_types=["image"])
        self.assertEqual(ok_animatic["effective_classification"], "animatic")
        self.assertTrue(ok_animatic["provenance_verified"])
        self.assertEqual(ok_animatic["provenance_status"], "animatic_verified_local_assembly")
        self.assertFalse(ok_animatic["classification_downgraded"])

    # 23. Regression (F-24): Sum of two individually finite tolerances overflowing to +inf must raise VideoMuxError
    def test_23_f24_tolerance_sum_overflow_rejected(self) -> None:
        from voice_intelligence import VideoMuxError

        long_dlg = self.tmp_dir / "f24_long_dlg.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3.2", str(long_dlg)],
            stdin=subprocess.DEVNULL, check=True, timeout=30.0,
        )
        out_mp4 = self.tmp_dir / "f24_overflow.mp4"

        # Exact reproduction of RC3 audit finding F-24: 1e308 + 1e308 == float("inf")
        with self.assertRaises(VideoMuxError):
            mux_audio_and_subtitles_to_video(
                video_path=self.base_video,
                dialogue_audio_path=long_dlg,
                output_video_path=out_mp4,
                max_audio_overrun_sec=1e308,
                allow_audio_tail_sec=1e308,
            )
        self.assertFalse(out_mp4.exists(), "Overflowing tolerance must not produce a silently truncated video")

        # Boolean tolerances also rejected
        with self.assertRaises(VideoMuxError):
            mux_audio_and_subtitles_to_video(
                video_path=self.base_video,
                dialogue_audio_path=long_dlg,
                output_video_path=out_mp4,
                max_audio_overrun_sec=True,  # type: ignore[arg-type]
            )

    # 24. Regression (D-MT04-01): Provider migration validates mappings, preserves dialogue assignments, and rolls back on failure
    def test_24_d_mt04_01_provider_migration_validation_preservation_and_rollback(self) -> None:
        from unittest.mock import patch
        from voice_intelligence import VoiceProfile, VoiceProfileManager, load_project_voice_state

        store = self.tmp_dir / "mig_profiles.json"
        state_p = self.tmp_dir / "mig_project_state.json"
        pm = VoiceProfileManager(store)
        pm.create_profile(VoiceProfile(voice_id="V01", display_name="Narrator", voice_type="original_synthetic", provider="elevenlabs", provider_voice_id="el_v01", intended_character="narrator"))
        pm.create_profile(VoiceProfile(voice_id="V03", display_name="Toby", voice_type="original_synthetic", provider="elevenlabs", provider_voice_id="el_v03", intended_character="toby"))

        initial_state = {
            "schema_version": "1.1.0",
            "project_id": "MIG_TEST",
            "character_voice_map": [
                {"character_id": "narrator", "display_name": "Narrator", "voice_id": "V01", "provider": "elevenlabs", "provider_voice_id": "el_v01", "lock_scope": "project_wide"},
                {"character_id": "toby", "display_name": "Toby", "voice_id": "V03", "provider": "elevenlabs", "provider_voice_id": "el_v03", "lock_scope": "project_wide"},
            ],
            "dialogue_jobs": [
                {"line_id": "S01_L01", "character_id": "narrator", "voice_id": "V01", "status": "approved", "text": "Preserved line."}
            ],
        }
        state_p.write_text(json.dumps(initial_state, indent=2), encoding="utf-8")

        # Missing mapping must fail pre-flight without mutating store or state
        with self.assertRaises(ValueError):
            pm.migrate_provider(
                from_provider="elevenlabs",
                to_provider="openai_tts",
                voice_id_mapping={"V01": "alloy"},  # V03 missing
                project_state_path=state_p,
            )
        self.assertEqual(pm.require_profile("V01").provider, "elevenlabs")

        # Rollback on project-state write failure must restore BOTH store and in-memory profiles
        with patch("os.replace", side_effect=[os.replace, OSError("simulated disk full on state write")]):
            # Actually patch tempfile.mkstemp for the second write (state file)
            pass
        orig_mkstemp = __import__("tempfile").mkstemp
        call_n = {"n": 0}
        def fail_on_state_write(*args, **kwargs):
            call_n["n"] += 1
            if call_n["n"] == 2:
                raise OSError("simulated state write failure")
            return orig_mkstemp(*args, **kwargs)
        with patch("voice_intelligence.profile_manager.tempfile.mkstemp", side_effect=fail_on_state_write):
            with self.assertRaises(OSError):
                pm.migrate_provider(
                    from_provider="elevenlabs",
                    to_provider="openai_tts",
                    voice_id_mapping={"V01": "alloy", "V03": "echo"},
                    project_state_path=state_p,
                )
        # Verify full rollback (in-memory + on-disk)
        self.assertEqual(pm.require_profile("V01").provider, "elevenlabs")
        reloaded = VoiceProfileManager(store)
        self.assertEqual(reloaded.require_profile("V01").provider, "elevenlabs")
        self.assertEqual(reloaded.require_profile("V03").provider_voice_id, "el_v03")

        # Successful migration updates provider bindings while preserving internal voice_ids & approved dialogue_jobs
        res = pm.migrate_provider(
            from_provider="elevenlabs",
            to_provider="openai_tts",
            voice_id_mapping={"V01": "alloy", "V03": "echo"},
            project_state_path=state_p,
        )
        self.assertEqual(res["migrated_count"], 2)
        self.assertTrue(res["project_state_updated"])
        self.assertEqual(pm.require_profile("V01").provider, "openai_tts")
        self.assertEqual(pm.require_profile("V01").provider_voice_id, "alloy")
        st_after = load_project_voice_state(state_p)
        cmap = {e["character_id"]: e for e in st_after["character_voice_map"]}
        self.assertEqual(cmap["narrator"]["voice_id"], "V01")
        self.assertEqual(cmap["narrator"]["provider"], "openai_tts")
        self.assertEqual(cmap["toby"]["provider_voice_id"], "echo")
        self.assertEqual(st_after["dialogue_jobs"][0]["status"], "approved")

    # 25. Regression (D-MT04-02): Secure connector credentials work without exposing API keys in env, logs, or reports
    def test_25_d_mt04_02_secure_connector_credentials_without_env_or_leakage(self) -> None:
        from voice_intelligence import ElevenLabsAdapter, HTTPResponseData, ProviderRegistry, SynthesisRequest

        old_env = os.environ.pop("ELEVENLABS_API_KEY", None)
        try:
            secret_token = "sk_secret_vault_token_999999"
            seen_headers = []

            # Case A: connector_authenticated=True transport (no raw key in Python or env at all)
            def connector_transport(method, url, headers, body, timeout):
                seen_headers.append(dict(headers))
                return HTTPResponseData(200, {"content-type": "audio/wav"}, self.base_audio.read_bytes())

            conn_adapter = ElevenLabsAdapter(connector_authenticated=True, transport=connector_transport)
            self.assertTrue(conn_adapter.is_configured())
            self.assertEqual(conn_adapter.credential_source(), "connector_transport")
            out_wav = self.tmp_dir / "conn_tts.wav"
            conn_adapter.synthesize_speech(SynthesisRequest(text="Connector test", provider_voice_id="el_1", output_path=out_wav, output_format="wav"))
            self.assertNotIn("xi-api-key", seen_headers[0])
            self.assertNotIn("ELEVENLABS_API_KEY", os.environ)

            # Case B: in-memory credential_provider callback (never touches os.environ; redacted on error & repr)
            def fail_echo_transport(method, url, headers, body, timeout):
                return HTTPResponseData(401, {}, f"Invalid key {secret_token}".encode("utf-8"))

            cb_adapter = ElevenLabsAdapter(credential_provider=lambda: secret_token, transport=fail_echo_transport)
            self.assertTrue(cb_adapter.is_configured())
            self.assertEqual(cb_adapter.credential_source(), "credential_provider")
            self.assertNotIn(secret_token, repr(cb_adapter))
            reg_dump = json.dumps(ProviderRegistry([cb_adapter]).list_providers())
            self.assertNotIn(secret_token, reg_dump)
            with self.assertRaises(Exception) as ctx:
                cb_adapter.check_authentication()
            self.assertNotIn(secret_token, str(ctx.exception))
            self.assertIn("[REDACTED]", str(ctx.exception))
        finally:
            if old_env is not None:
                os.environ["ELEVENLABS_API_KEY"] = old_env

    # 26. Regression (O-S12L-02): QC reporting clearly distinguishes intentionally blocked lines from production failures
    def test_26_o_s12l_02_qc_distinguishes_blocked_lines_from_mechanism_failures(self) -> None:
        from voice_intelligence import run_project_audio_qc

        # Intentionally blocked line (voice unavailable) with zero mechanism failures
        qc_blocked = run_project_audio_qc(
            dialogue_jobs=[
                {"line_id": "S01_L01", "character_id": "narrator", "voice_id": "V01", "status": "approved", "start_sec": 0.0, "end_sec": 1.5, "qc": {"duration_sec": 1.4}},
                {"line_id": "S01_L02", "character_id": "mayor", "voice_id": None, "status": "blocked_voice_unavailable", "error": "Locked voice V02 disabled; awaiting fallback approval."},
            ],
            character_voice_map={"narrator": {"voice_id": "V01"}},
        )
        self.assertFalse(qc_blocked["technical_qc_passed"])
        self.assertEqual(qc_blocked["qc_outcome_category"], "blocked_by_policy_or_assignment")
        self.assertEqual(qc_blocked["blocked_dialogue_lines"], ["S01_L02"])
        self.assertEqual(qc_blocked["production_mechanism_failures"], [])
        self.assertEqual(qc_blocked["character_mapping_errors"], [])

        # Production mechanism failure (TTS/FFmpeg error) is clearly categorized separately
        qc_failed = run_project_audio_qc(
            dialogue_jobs=[
                {"line_id": "S01_L01", "character_id": "narrator", "voice_id": "V01", "status": "failed", "error": "HTTP 500"},
            ],
            character_voice_map={"narrator": {"voice_id": "V01"}},
        )
        self.assertEqual(qc_failed["qc_outcome_category"], "failed_production_mechanism")
        self.assertEqual(qc_failed["blocked_dialogue_lines"], [])
        self.assertEqual(qc_failed["production_mechanism_failures"], ["S01_L01"])

    # 27. Regression (D-RC6-01): Provider adapter unconditionally blocks cloning across ALL transports while preserving TTS
    def test_27_provider_adapter_boundary_blocks_prohibited_and_live_remote_cloning(self) -> None:
        from voice_intelligence import ElevenLabsAdapter, HTTPResponseData, ProhibitedVoiceCloningError, SynthesisRequest

        sample = self.tmp_dir / "clone_guard.wav"
        sample.write_bytes(self.base_audio.read_bytes())
        clone_calls = {"n": 0}
        tts_calls = {"n": 0}

        def spy_connector_transport(method, url, headers, body, timeout):
            if "/voices/add" in url:
                clone_calls["n"] += 1
                return HTTPResponseData(200, {}, b'{"voice_id":"must_never_run"}')
            tts_calls["n"] += 1
            return HTTPResponseData(200, {"content-type": "audio/wav"}, self.base_audio.read_bytes())

        # 1. allow_remote_cloning flag is rejected (removed in v0.2.0)
        with self.assertRaises(TypeError):
            ElevenLabsAdapter(connector_authenticated=True, transport=spy_connector_transport, allow_remote_cloning=True)  # type: ignore[call-arg]

        adapter = ElevenLabsAdapter(connector_authenticated=True, transport=spy_connector_transport)
        self.assertFalse(adapter.capabilities().authorized_voice_cloning)

        # 2. Prohibited minor / child / unauthorized / impersonation requests blocked with ZERO transport calls
        for name, desc, labels in (
            ("Teen Boy Voice", "Clone of a 14-year-old minor", None),
            ("Celebrity Impersonation", "Unauthorized clone without consent", None),
            ("Custom Voice", "Normal description", {"age": "15"}),
            ("Custom Voice", "Normal description", {"consent_verified": "false"}),
        ):
            with self.assertRaises(ProhibitedVoiceCloningError):
                adapter.create_authorized_clone(name=name, description=desc, sample_paths=[sample], labels=labels)

        # 3. D-RC6-01: Non-prohibited cloning request through custom connector transport MUST ALSO raise with ZERO transport calls
        with self.assertRaises(ProhibitedVoiceCloningError):
            adapter.create_authorized_clone(
                name="Authorized Adult Creator",
                description="Clean adult voice sample with verified consent",
                sample_paths=[sample],
                labels={"age": "30", "consent_verified": "true"},
            )
        self.assertEqual(clone_calls["n"], 0)

        # 4. Default live-network adapter also unconditionally blocks cloning
        live_adapter = ElevenLabsAdapter(credential_provider=lambda: "sk_dummy_never_sent")
        with self.assertRaises(ProhibitedVoiceCloningError):
            live_adapter.create_authorized_clone(name="Adult Self", description="Authorized adult creator", sample_paths=[sample])

        # 5. Normal ElevenLabs TTS through connector transport and credential_provider remains fully operational
        tts_out = self.tmp_dir / "connector_tts_ok.wav"
        res = adapter.synthesize_speech(
            SynthesisRequest(text="Connector TTS still works.", provider_voice_id="el_v01", output_path=tts_out, output_format="wav")
        )
        self.assertEqual(tts_calls["n"], 1)
        self.assertTrue(res.output_path.exists())

        cb_out = self.tmp_dir / "cb_tts_ok.wav"
        cb_adapter = ElevenLabsAdapter(credential_provider=lambda: "sk_mem_only_token", transport=spy_connector_transport)
        cb_res = cb_adapter.synthesize_speech(
            SynthesisRequest(text="Callback TTS still works.", provider_voice_id="el_v01", output_path=cb_out, output_format="wav")
        )
        self.assertEqual(tts_calls["n"], 2)
        self.assertTrue(cb_res.output_path.exists())

    # 28. Regression (D-MT03-01 & D-MT03-03): Example shot plan aligns exact timestamps and marks untested game behaviour UNVERIFIED
    def test_28_d_mt03_01_and_03_example_shot_alignment_and_unverified_markers(self) -> None:
        ex_text = (REPO_ROOT / "skills/roblox-town-director/examples/solo-short-example.md").read_text(encoding="utf-8")
        # Aligned door-open cue at 0:15.5 in both script and shot plan (no contradictory "15s")
        self.assertIn("0:15.5", ex_text)
        self.assertNotIn("tap door open at `15s`", ex_text)
        # No unsupported "works in any Roblox town house" claim; untested game mechanics marked UNVERIFIED
        self.assertNotIn("works in any Roblox town house", ex_text)
        self.assertGreaterEqual(ex_text.count("UNVERIFIED"), 6)

    # 29. Regression (D-MT05-02): Pixel-width caption wrapping prevents 50-71 char tail overflow across 9:16, 16:9, long words, Unicode & all 16 styles
    def test_29_d_mt05_02_caption_wrapping_enforces_pixel_width_and_safe_margins(self) -> None:
        long_sentence = (
            "In this quiet Roblox town, nobody ever opens the red cellar door after midnight "
            "because the streetlights flicker out and the footsteps always stop right behind you!"
        )
        long_word_sentence = "Check supercalifragilisticexpialidocious_unbreakable_token_1234567890 right now."
        unicode_sentence = "Café — résumé — 日本語テスト — ¿Dónde está la llave del reloj antiguo en el pueblo?"

        # 1. Direct _wrap_lines never joins overflowing text into an unbounded tail
        fallback_lines = caption_styles._wrap_lines(long_sentence, max_chars=22, max_lines=2)
        self.assertGreater(len(fallback_lines), 2)
        for ln in fallback_lines:
            self.assertLessEqual(len(ln), 22, f"Fallback line overflowed max_chars: {ln!r}")

        # 2. Both 9:16 (1080x1920) and 16:9 (1920x1080) stay strictly within safe_text_width_px across all 16 styles
        for width, height in ((1080, 1920), (1920, 1080)):
            cues = [
                caption_styles.CaptionCue(0.0, 4.0, long_sentence, speaker="Narrator"),
                caption_styles.CaptionCue(4.0, 6.5, long_word_sentence, speaker="Toby"),
                caption_styles.CaptionCue(6.5, 9.0, unicode_sentence, speaker="Grandpa"),
            ]
            for idx in range(1, 17):
                pid = f"C{idx:02d}"
                doc = caption_styles.generate_ass_document(cues, style_id=pid, width=width, height=height)
                self.assertGreaterEqual(doc["margin_lr"], int(round(width * 0.06)))
                self.assertLessEqual(
                    doc["max_rendered_line_px"],
                    doc["safe_text_width_px"] + 1.0,
                    f"{pid} at {width}x{height} exceeded safe width: {doc['max_rendered_line_px']} > {doc['safe_text_width_px']}",
                )
                self.assertIn("WrapStyle: 0", doc["ass_content"])
                # Long sentence should paginate cleanly into >= 2 dialogue events rather than cramming 70 chars on line 2
                self.assertGreater(doc["cue_count"], len(cues))

    # 30. Regression (D-MT05-02): Real FFmpeg-rendered frames at 9:16 and 16:9 keep ALL caption pixels inside safe horizontal margins
    def test_30_d_mt05_02_rendered_caption_frames_stay_inside_horizontal_margins(self) -> None:
        from PIL import Image

        long_line = (
            "Nobody in Brookhaven-style Midnight Town ever ignores the warning bell when the clock "
            "strikes twelve because the shadows remember every single secret you whisper!"
        )
        for label, w, h, style_id in (
            ("9x16_C01", 540, 960, "C01"),
            ("16x9_C07", 960, 540, "C07"),
        ):
            bg_mp4 = self.tmp_dir / f"bg_{label}.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"color=c=0x101828:s={w}x{h}:r=12:d=1.2",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(bg_mp4),
                ],
                stdin=subprocess.DEVNULL,
                check=True,
                timeout=30.0,
            )
            doc = caption_styles.generate_ass_document(
                [caption_styles.CaptionCue(0.0, 1.2, long_line, speaker="Narrator")],
                style_id=style_id,
                width=w,
                height=h,
            )
            ass_p = self.tmp_dir / f"{label}.ass"
            ass_p.write_text(doc["ass_content"], encoding="utf-8")
            out_mp4 = self.tmp_dir / f"cap_{label}.mp4"
            caption_styles.render_ass_captions_onto_video(
                video_path=bg_mp4,
                ass_path=ass_p,
                output_video_path=out_mp4,
            )
            frame_png = self.tmp_dir / f"frame_{label}.png"
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "0.25", "-i", str(out_mp4), "-frames:v", "1", str(frame_png)],
                stdin=subprocess.DEVNULL,
                check=True,
                timeout=30.0,
            )
            img = Image.open(frame_png).convert("RGB")
            px = img.load()
            # Background is solid dark navy (16, 24, 40). Any bright caption pixel must stay inside [margin_check, w - margin_check].
            edge_guard = max(12, int(w * 0.03))
            bright_xs = []
            for y in range(h):
                for x in range(w):
                    r, g, b = px[x, y]
                    if (r + g + b) > 180:
                        bright_xs.append(x)
            self.assertTrue(bright_xs, f"No caption pixels rendered in {label}")
            self.assertGreaterEqual(min(bright_xs), edge_guard, f"Caption clipped left edge in {label}: min_x={min(bright_xs)} < {edge_guard}")
            self.assertLessEqual(max(bright_xs), w - 1 - edge_guard, f"Caption clipped right edge in {label}: max_x={max(bright_xs)} > {w - 1 - edge_guard}")

    # 31. Regression (D-RC8-01): Zero-duration ASS events are impossible across 0.05s, 0.10s, 0.20s, 0.50s, and normal cues
    def test_31_d_rc8_01_no_zero_duration_events_and_minimum_page_duration_enforced(self) -> None:
        import re

        time_re = re.compile(r"^Dialogue: 0,(\d+):(\d{2}):(\d{2})\.(\d{2}),(\d+):(\d{2}):(\d{2})\.(\d{2}),")

        def _parse_event_spans_cs(ass_content: str):
            spans = []
            for ln in ass_content.splitlines():
                m = time_re.match(ln)
                if m:
                    h1, m1, s1, c1, h2, m2, s2, c2 = (int(x) for x in m.groups())
                    st = ((h1 * 3600 + m1 * 60 + s1) * 100) + c1
                    en = ((h2 * 3600 + m2 * 60 + s2) * 100) + c2
                    spans.append((st, en))
            return spans

        # 19-page wall of text (exact D-RC8-01 reproduction)
        huge_wall = " ".join(
            [f"WordBlock{i:02d} mysterious midnight hallway echo" for i in range(1, 35)]
        )

        # For 0.05s, 0.10s, 0.20s, 0.50s with an impossible 19-page wall -> must raise clear CaptionRenderError (zero silent truncation, zero 0-duration events)
        for short_dur in (0.05, 0.10, 0.20, 0.50):
            with self.assertRaises(caption_styles.CaptionRenderError, msg=f"19-page cue in {short_dur}s must raise"):
                caption_styles.generate_ass_document(
                    [caption_styles.CaptionCue(0.0, short_dur, huge_wall, speaker="Narrator")],
                    style_id="C01",
                    width=1080,
                    height=1920,
                )

        # D-RC9-01: Standalone single-page cues below 0.25s (0.05s, 0.10s, 0.20s) MUST raise CaptionRenderError
        for too_short in (0.05, 0.10, 0.20):
            with self.assertRaises(caption_styles.CaptionRenderError, msg=f"Standalone {too_short}s cue must be rejected"):
                caption_styles.generate_ass_document(
                    [caption_styles.CaptionCue(1.0, 1.0 + too_short, "Wait!", speaker="Toby")],
                    style_id="C01",
                    width=1080,
                    height=1920,
                )

        # D-RC9-01: Adjacent same-speaker short cue merges cleanly without extending timeline; different speaker rejects
        merged_doc = caption_styles.generate_ass_document(
            [
                caption_styles.CaptionCue(0.00, 0.15, "Wait!", speaker="Toby"),
                caption_styles.CaptionCue(0.15, 0.80, "Don't open that door.", speaker="Toby"),
            ],
            style_id="C01",
            width=1080,
            height=1920,
        )
        m_spans = _parse_event_spans_cs(merged_doc["ass_content"])
        self.assertEqual(m_spans[0][0], 0)
        self.assertEqual(m_spans[-1][1], 80)
        for st, en in m_spans:
            self.assertGreaterEqual(en - st, caption_styles.MIN_PAGE_DURATION_CS)

        with self.assertRaises(caption_styles.CaptionRenderError):
            caption_styles.generate_ass_document(
                [
                    caption_styles.CaptionCue(0.00, 0.15, "Wait!", speaker="Toby"),
                    caption_styles.CaptionCue(0.15, 0.80, "Stay back.", speaker="Narrator"),
                ],
                style_id="C01",
                width=1080,
                height=1920,
            )

        # Positive tests: 0.25s and 0.50s single-page cues pass cleanly with exact centisecond timing
        for valid_dur in (0.25, 0.50):
            doc = caption_styles.generate_ass_document(
                [caption_styles.CaptionCue(1.0, 1.0 + valid_dur, "Wait!", speaker="Toby")],
                style_id="C01",
                width=1080,
                height=1920,
            )
            spans = _parse_event_spans_cs(doc["ass_content"])
            self.assertEqual(len(spans), 1)
            st, en = spans[0]
            self.assertEqual(st, 100)
            self.assertEqual(en, 100 + int(round(valid_dur * 100)))
            self.assertGreaterEqual(en - st, caption_styles.MIN_PAGE_DURATION_CS)

        # Normal-duration long multi-page cue across all 16 styles & both 9:16 and 16:9:
        # every page has >= MIN_PAGE_DURATION_CS (25cs), exact contiguous bounds, zero invented duration
        long_dialogue = (
            "In this quiet Roblox town, nobody ever opens the red cellar door after midnight "
            "because the streetlights flicker out and footsteps always stop right behind you!"
        )
        for w, h in ((1080, 1920), (1920, 1080)):
            for idx in range(1, 17):
                pid = f"C{idx:02d}"
                doc = caption_styles.generate_ass_document(
                    [caption_styles.CaptionCue(0.50, 4.50, long_dialogue, speaker="Narrator")],
                    style_id=pid,
                    width=w,
                    height=h,
                )
                spans = _parse_event_spans_cs(doc["ass_content"])
                self.assertGreaterEqual(len(spans), 1)
                self.assertEqual(spans[0][0], 50)
                self.assertEqual(spans[-1][1], 450)
                for i, (st, en) in enumerate(spans):
                    self.assertGreater(en, st, f"Zero-duration event in {pid} {w}x{h}")
                    if len(spans) > 1:
                        self.assertGreaterEqual(en - st, caption_styles.MIN_PAGE_DURATION_CS, f"Unreadable <0.25s page in {pid}")
                    if i > 0:
                        self.assertEqual(st, spans[i - 1][1], "Non-contiguous page timestamps")

    # 32. Regression (D-RC8-01): Grapheme-safe splitting preserves Unicode combining characters and ZWJ/skin-tone emojis
    def test_32_d_rc8_01_grapheme_boundary_safe_splitting_combining_and_emoji(self) -> None:
        # Combining acute accent (e + U+0301) and ZWJ family emoji + skin-tone emoji
        combining_word = ("cafe\u0301" * 12)
        zwj_emoji_seq = ("👨\u200d👩\u200d👧\u200d👦👍🏽" * 10)
        mixed_text = f"{combining_word} {zwj_emoji_seq}"

        clusters_c = caption_styles._split_grapheme_clusters(combining_word)
        self.assertIn("e\u0301", clusters_c)
        clusters_e = caption_styles._split_grapheme_clusters(zwj_emoji_seq)
        self.assertIn("👨\u200d👩\u200d👧\u200d👦", clusters_e)
        self.assertIn("👍🏽", clusters_e)

        # Ensure splitting into narrow width NEVER orphans a combining mark or ZWJ at the start/end of a line
        doc = caption_styles.generate_ass_document(
            [caption_styles.CaptionCue(0.0, 5.0, mixed_text, speaker="Toby")],
            style_id="C01",
            width=1080,
            height=1920,
        )
        for ln in doc["ass_content"].splitlines():
            if ln.startswith("Dialogue:"):
                payload = ln.split(",,", 1)[1]
                for subline in payload.split(r"\N"):
                    if subline:
                        self.assertFalse(subline.startswith("\u0301"), f"Orphaned combining mark: {subline!r}")
                        self.assertFalse(subline.startswith("\u200d"), f"Orphaned ZWJ: {subline!r}")
                        self.assertFalse(subline.endswith("\u200d"), f"Trailing ZWJ: {subline!r}")

    # 33. Regression (CR-01): visual_qc.generate_scene_contact_sheet handles out-of-range / near-EOF timestamps safely
    def test_33_cr01_contact_sheet_clamps_out_of_range_and_eof_timestamps_safely(self) -> None:
        from visual_qc import generate_scene_contact_sheet

        out_png = self.tmp_dir / "cr01_contact_sheet.png"
        rep = generate_scene_contact_sheet(
            self.base_video,
            out_png,
            scene_timestamps=[0.2, 1.49, 99.0],
            scene_labels=["S01", "NearEOF", "PastEOF"],
        )
        self.assertTrue(out_png.exists())
        self.assertEqual(rep["frame_count"], 3)

    # 34. Regression (CR-02 & CR-03): AST-verified stdin/-nostdin hygiene + atomic report failure-path rollback
    def test_34_cr02_cr03_atomic_reports_and_ffmpeg_nostdin_hygiene(self) -> None:
        import ast
        from unittest.mock import patch
        from PIL import Image
        import autopilot as autopilot_mod
        from voice_intelligence import (
            ProviderRegistry,
            VoiceGenerationPipeline,
            VoiceProfile,
            VoiceProfileManager,
        )
        import voice_intelligence.pipeline as vi_pipeline_mod

        # 34a. AST audit across ALL production scripts and test modules:
        #      - Every subprocess.run() call must pass stdin=subprocess.DEVNULL
        #      - Every FFmpeg command list (outside CompletedProcess mocks) must include "-nostdin"
        py_files = sorted(
            list((REPO_ROOT / "skills/roblox-town-director/scripts").rglob("*.py"))
            + list((REPO_ROOT / "tests").rglob("*.py"))
        )
        self.assertGreaterEqual(len(py_files), 10)

        missing_stdin = []
        missing_nostdin = []
        for py_file in py_files:
            rel = str(py_file.relative_to(REPO_ROOT))
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=rel)
            parents = {}
            for parent in ast.walk(tree):
                for child in ast.iter_child_nodes(parent):
                    parents[child] = parent

            for node in ast.walk(tree):
                # Check every subprocess.run(...) call for stdin=subprocess.DEVNULL
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                    and node.func.attr == "run"
                ):
                    stdin_kw = next((kw for kw in node.keywords if kw.arg == "stdin"), None)
                    is_devnull = (
                        stdin_kw is not None
                        and isinstance(stdin_kw.value, ast.Attribute)
                        and isinstance(stdin_kw.value.value, ast.Name)
                        and stdin_kw.value.value.id == "subprocess"
                        and stdin_kw.value.attr == "DEVNULL"
                    )
                    if not is_devnull:
                        missing_stdin.append(f"{rel}:{node.lineno}")

                # Check every FFmpeg command list literal for "-nostdin"
                if isinstance(node, ast.List) and node.elts:
                    first = node.elts[0]
                    is_ffmpeg = (
                        (isinstance(first, ast.Constant) and first.value == "ffmpeg")
                        or (isinstance(first, ast.Attribute) and "ffmpeg" in first.attr.lower())
                        or (isinstance(first, ast.Name) and "ffmpeg" in first.id.lower())
                    )
                    if is_ffmpeg:
                        # Skip mock subprocess.CompletedProcess(args=["ffmpeg"], ...) objects
                        parent = parents.get(node)
                        grandparent = parents.get(parent) if parent is not None else None
                        if (
                            isinstance(parent, ast.keyword)
                            and parent.arg == "args"
                            and isinstance(grandparent, ast.Call)
                            and isinstance(grandparent.func, ast.Attribute)
                            and grandparent.func.attr == "CompletedProcess"
                        ):
                            continue
                        has_nostdin = any(
                            isinstance(e, ast.Constant) and e.value == "-nostdin"
                            for e in node.elts
                        )
                        if not has_nostdin:
                            missing_nostdin.append(f"{rel}:{node.lineno}")

        self.assertEqual(missing_stdin, [], f"subprocess.run calls missing stdin=subprocess.DEVNULL: {missing_stdin}")
        self.assertEqual(missing_nostdin, [], f"FFmpeg command lists missing -nostdin: {missing_nostdin}")

        # 34b. Failure-path rollback & temp cleanup for autopilot.py production_report.json (CR-02)
        ap_out = self.tmp_dir / "cr02_autopilot_fail"
        ap_out.mkdir()
        existing_ap_report = ap_out / "production_report.json"
        ap_sentinel = '{"sentinel": "preserve_existing_production_report"}\n'
        existing_ap_report.write_text(ap_sentinel, encoding="utf-8")

        img = self.tmp_dir / "cr02_scene.jpg"
        Image.new("RGB", (180, 320), (30, 60, 120)).save(img)
        spec = {
            "project_id": "CR02_AP_FAIL",
            "title": "CR02 Autopilot Atomic Fail",
            "operating_mode": "autonomous",
            "output_classification": "animatic",
            "width": 180,
            "height": 320,
            "fps": 12,
            "dialogue_audio_path": str(self.base_audio),
            "scenes": [
                {"scene_id": "S01", "source_path": str(img), "duration_sec": 1.5}
            ],
        }
        real_ap_replace = os.replace

        def fail_only_ap_report_replace(src, dst):
            if Path(dst).name == "production_report.json":
                raise OSError("simulated production_report replace failure")
            return real_ap_replace(src, dst)

        with patch.object(autopilot_mod.os, "replace", side_effect=fail_only_ap_report_replace):
            with self.assertRaises(OSError):
                autopilot_mod.run_autopilot_production(spec, output_dir=ap_out)
        self.assertEqual(existing_ap_report.read_text(encoding="utf-8"), ap_sentinel)
        self.assertEqual(list(ap_out.glob(".production_report_*.tmp")), [])

        # 34c. Failure-path rollback & temp cleanup for voice_intelligence/pipeline.py audio_qc_report.json (CR-02)
        vi_out = self.tmp_dir / "cr02_pipeline_fail"
        vi_out.mkdir()
        existing_qc_report = vi_out / "audio_qc_report.json"
        qc_sentinel = '{"sentinel": "preserve_existing_audio_qc_report"}\n'
        existing_qc_report.write_text(qc_sentinel, encoding="utf-8")

        profiles_path = self.tmp_dir / "cr02_profiles.json"
        pm = VoiceProfileManager(profiles_path)
        pm.create_profile(
            VoiceProfile(
                voice_id="V01",
                display_name="Narrator",
                voice_type="original_synthetic",
                provider="elevenlabs",
                provider_voice_id="el_narrator_cr02",
                intended_character="narrator",
            )
        )
        registry = ProviderRegistry()
        pipeline = VoiceGenerationPipeline(profile_manager=pm, provider_registry=registry)

        real_replace = os.replace

        def fail_only_qc_replace(src, dst):
            if Path(dst).name == "audio_qc_report.json":
                raise OSError("simulated audio_qc_report replace failure")
            return real_replace(src, dst)

        with patch.object(vi_pipeline_mod.os, "replace", side_effect=fail_only_qc_replace):
            with self.assertRaises(OSError):
                pipeline.run_script_pipeline(
                    project_id="CR02_VI_FAIL",
                    project_title="CR02 Pipeline Atomic Fail",
                    script_text="[Scene 1]\nNarrator: Testing atomic rollback.",
                    output_dir=vi_out,
                    state_path=vi_out / "project_voice_state.json",
                )
        self.assertEqual(existing_qc_report.read_text(encoding="utf-8"), qc_sentinel)
        self.assertEqual(list(vi_out.glob(".audio_qc_report_*.tmp")), [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
