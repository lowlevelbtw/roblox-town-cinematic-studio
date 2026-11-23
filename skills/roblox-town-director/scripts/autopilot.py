#!/usr/bin/env python3
"""Unified Resumable Autopilot Production Runner for Roblox Town Director v0.2.0.

Connects:
  - ProductionStateManager (atomic per-scene & voice-stage checkpoints + F-12 recovery)
  - Direct Voice-Stage Execution (F-14):
      1) Pre-generated `dialogue_audio_path` (+ optional `subtitles_srt_path`)
      2) BYO recordings via `voice_manifest_path` + `voice_backend.py`
      3) Generated TTS dialogue via `voice_profiles_path` + `script_text` + `VoiceGenerationPipeline`
  - Multi-Scene Cinematic Assembler (`video_assembler.py`: mixed clips/images, xfade, BGM ducking)
  - 16 Executable Caption Styles (`caption_styles.py`: C01-C16)
  - Audio/Video/Subtitle Muxing (`mux_audio_and_subtitles_to_video` with F-15 truncation protection)
  - Visual QC (`visual_qc.py`: black-frame detection + scene contact sheet PNG)
  - Hard Final Delivery Gate (`evaluate_final_delivery_gate` with F-13 SHA-256 caption verification)

Supports `autonomous`, `interactive`, and `user_script` operating modes.
Keeps remote voice cloning disabled and reports unavailable providers honestly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import voice_backend  # noqa: E402
from production_state import (  # noqa: E402
    ProductionStateManager,
    evaluate_final_delivery_gate,
    inspect_host_resources,
    verify_output_classification,
)
from video_assembler import (  # noqa: E402
    SceneSpec,
    assemble_scenes_with_transitions,
    mix_dialogue_and_ducked_bgm,
)
from visual_qc import generate_scene_contact_sheet  # noqa: E402
from voice_intelligence.audio_qc import inspect_audio_file  # noqa: E402
from voice_intelligence.pipeline import (  # noqa: E402
    VoiceGenerationPipeline,
    mux_audio_and_subtitles_to_video,
    resolve_safe_child_path,
    sanitize_filename_token,
)
from voice_intelligence.profile_manager import VoiceProfileManager  # noqa: E402
from voice_intelligence.providers import ProviderRegistry  # noqa: E402

DEFAULT_VOICE_REGISTRY = _SCRIPTS_DIR.parent / "templates" / "voice-registry.json"


def _resolve_voice_stage(
    spec: Dict[str, Any],
    *,
    project_id: str,
    title: str,
    out_dir: Path,
    state_mgr: ProductionStateManager,
    provider_registry: Optional[ProviderRegistry] = None,
) -> Dict[str, Any]:
    """Resolve dialogue audio & SRT via pre-generated files, BYO manifest, or VoiceGenerationPipeline."""
    cached = state_mgr.state.get("voice_stage") or {}
    if (
        cached.get("status") == "completed"
        and cached.get("dialogue_audio_path")
        and inspect_audio_file(Path(cached["dialogue_audio_path"]), check_volume=True)["valid"]
    ):
        cached_copy = dict(cached)
        cached_copy["reused_cached_voice"] = True
        return cached_copy

    # Path 1: Pre-generated dialogue audio supplied directly
    if spec.get("dialogue_audio_path"):
        dlg_p = Path(spec["dialogue_audio_path"])
        srt_p = Path(spec["subtitles_srt_path"]) if spec.get("subtitles_srt_path") else None
        result = {
            "mode": "pre_generated",
            "status": "completed",
            "reused_cached_voice": False,
            "dialogue_audio_path": str(dlg_p),
            "subtitles_srt_path": str(srt_p) if srt_p else None,
            "error": None,
        }
        state_mgr.state["voice_stage"] = result
        state_mgr.save()
        return result

    # Path 2: BYO recorded voices via voice_manifest_path + voice_backend.py
    if spec.get("voice_manifest_path"):
        manifest_p = Path(spec["voice_manifest_path"])
        registry_p = Path(spec.get("voice_registry_path") or DEFAULT_VOICE_REGISTRY)
        voice_out = out_dir / "voice_byo"
        mgr = voice_backend.SharedVoiceManager(registry_p, voice_backend.RecordedVoiceBackend())
        rep = mgr.run_project(manifest_p, voice_out)
        timeline_wav = voice_out / "dialogue_timeline.wav"
        srt_out = voice_out / "subtitles.srt"
        ok = timeline_wav.exists() and inspect_audio_file(timeline_wav, check_volume=True)["valid"]
        result = {
            "mode": "byo_recorded_manifest",
            "status": "completed" if ok else "failed",
            "reused_cached_voice": False,
            "dialogue_audio_path": str(timeline_wav) if ok else None,
            "subtitles_srt_path": str(srt_out) if srt_out.exists() else None,
            "backend_report": rep,
            "error": None if ok else "BYO voice backend produced no valid dialogue_timeline.wav.",
        }
        if "recorded_voice_backend" not in state_mgr.state["providers_used"]:
            state_mgr.state["providers_used"].append("recorded_voice_backend")
        state_mgr.state["voice_stage"] = result
        state_mgr.save()
        return result

    # Path 3: Generated TTS dialogue via voice_profiles_path + script_text + VoiceGenerationPipeline
    if spec.get("voice_profiles_path") and spec.get("script_text"):
        profiles_p = Path(spec["voice_profiles_path"])
        voice_out = out_dir / "voice_generated"
        voice_state_p = voice_out / "project_voice_state.json"
        pm = VoiceProfileManager(profiles_p)
        reg = provider_registry or ProviderRegistry()
        pipeline = VoiceGenerationPipeline(profile_manager=pm, provider_registry=reg)
        pipe_state = pipeline.run_script_pipeline(
            project_id=project_id,
            project_title=title,
            script_text=str(spec["script_text"]),
            output_dir=voice_out,
            state_path=voice_state_p,
            preferred_provider=spec.get("preferred_provider"),
            explicit_assignments=dict(spec.get("voice_assignments") or {}),
            approved_fallbacks=dict(spec.get("approved_fallbacks") or {}),
            output_format=str(spec.get("tts_output_format") or "mp3_44100_128"),
            raw_ext=str(spec.get("tts_raw_ext") or "mp3"),
        )
        artifacts = pipe_state.get("artifacts") or {}
        dlg_ref = artifacts.get("master_dialogue_wav")
        srt_ref = artifacts.get("subtitles_srt")
        qc_ok = bool((pipe_state.get("qc_report") or {}).get("technical_qc_passed"))
        ok = bool(qc_ok and dlg_ref and Path(dlg_ref).exists())
        failed_jobs = [j for j in pipe_state.get("dialogue_jobs", []) if j.get("status") != "approved"]
        err_msg = None if ok else (
            "; ".join(f"{j['line_id']}: {j.get('error')}" for j in failed_jobs)
            or "VoiceGenerationPipeline did not produce approved dialogue audio."
        )
        result = {
            "mode": "generated_tts_pipeline",
            "status": "completed" if ok else "failed",
            "reused_cached_voice": False,
            "dialogue_audio_path": dlg_ref if ok else None,
            "subtitles_srt_path": srt_ref if (srt_ref and Path(srt_ref).exists()) else None,
            "pipeline_qc_report": pipe_state.get("qc_report"),
            "error": err_msg,
        }
        state_mgr.state["voice_stage"] = result
        state_mgr.save()
        return result

    return {
        "mode": "none",
        "status": "skipped",
        "reused_cached_voice": False,
        "dialogue_audio_path": None,
        "subtitles_srt_path": str(spec["subtitles_srt_path"]) if spec.get("subtitles_srt_path") else None,
        "error": None,
    }


def run_autopilot_production(
    spec: Dict[str, Any],
    *,
    output_dir: Path,
    provider_registry: Optional[ProviderRegistry] = None,
) -> Dict[str, Any]:
    """Execute a resumable end-to-end local production from a structured production spec."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    project_id = sanitize_filename_token(str(spec.get("project_id") or "PROD_V020"), "project_id")
    title = str(spec.get("title") or project_id)
    operating_mode = str(spec.get("operating_mode") or "autonomous")
    requested_classification = str(spec.get("output_classification") or "animatic")
    production_provenance = spec.get("production_provenance")
    width = int(spec.get("width", 1080))
    height = int(spec.get("height", 1920))
    fps = int(spec.get("fps", 30))
    caption_style_id = spec.get("caption_style_id", "C16")
    caption_genre = str(spec.get("genre") or "story")
    caption_pacing = str(spec.get("pacing") or "medium")
    caption_tone = str(spec.get("tone") or "neutral")
    preserve_source_audio = bool(spec.get("preserve_source_audio", False))
    check_black_frames = bool(spec.get("check_black_frames", True))
    allow_audio_tail_sec = float(spec.get("allow_audio_tail_sec", 0.0))
    allow_audio_truncation = bool(spec.get("allow_audio_truncation", False))

    raw_scenes = spec.get("scenes") or []
    if not raw_scenes:
        raise ValueError("Production spec must include at least one scene in `scenes`.")

    scene_specs = [
        SceneSpec(
            scene_id=str(s["scene_id"]),
            source_type=str(s.get("source_type") or "image"),
            source_path=Path(s["source_path"]),
            duration_sec=float(s.get("duration_sec", 3.0)),
            motion=str(s.get("motion", "zoom_in")),
            transition=str(s.get("transition", "fade")),
            transition_duration_sec=float(s.get("transition_duration_sec", 0.4)),
        )
        for s in raw_scenes
    ]

    scene_source_types = [s.source_type for s in scene_specs]
    provenance_check = verify_output_classification(
        requested_classification,
        production_provenance=production_provenance,
        scene_source_types=scene_source_types,
    )
    output_classification = provenance_check["effective_classification"]

    state_path = out_dir / "production_state.json"
    state_mgr = ProductionStateManager(state_path)
    if not state_mgr.state:
        state_mgr.initialize(
            project_id=project_id,
            title=title,
            operating_mode=operating_mode,
            output_classification=output_classification,
            scene_ids=[s.scene_id for s in scene_specs],
            script_text=str(spec.get("script_text") or ""),
            user_script_locked=(operating_mode == "user_script" or bool(spec.get("user_script_locked", False))),
            caption_style_id=str(caption_style_id or "none"),
            voice_assignments=dict(spec.get("voice_assignments") or {}),
        )

    resources = inspect_host_resources()

    # Stage 1: Multi-scene assembly with per-scene F-12 recovery & transitions
    assembled_video_path = resolve_safe_child_path(out_dir, f"{project_id}_assembled.mp4")
    assembly_report = assemble_scenes_with_transitions(
        scene_specs,
        work_dir=out_dir / "assembly_work",
        output_video_path=assembled_video_path,
        width=width,
        height=height,
        fps=fps,
        state_manager=state_mgr,
    )

    # Stage 2 (F-14): Direct voice-stage resolution (pre-generated / BYO manifest / TTS pipeline)
    voice_stage = _resolve_voice_stage(
        spec,
        project_id=project_id,
        title=title,
        out_dir=out_dir,
        state_mgr=state_mgr,
        provider_registry=provider_registry,
    )
    dialogue_ref = voice_stage.get("dialogue_audio_path")
    srt_ref = spec.get("subtitles_srt_path") or voice_stage.get("subtitles_srt_path")
    bgm_ref = spec.get("bgm_audio_path")
    sfx_ref = spec.get("sfx_audio_path")

    ducking_report: Optional[Dict[str, Any]] = None
    final_audio_path: Optional[Path] = Path(dialogue_ref) if dialogue_ref else None
    if final_audio_path is not None and bgm_ref is not None:
        ducked_wav = resolve_safe_child_path(out_dir, f"{project_id}_master_ducked.wav")
        ducking_report = mix_dialogue_and_ducked_bgm(
            dialogue_audio_path=final_audio_path,
            bgm_audio_path=Path(bgm_ref),
            output_wav_path=ducked_wav,
            sfx_audio_path=Path(sfx_ref) if sfx_ref else None,
            target_duration_sec=assembly_report["video_qc"]["duration_sec"],
        )
        final_audio_path = ducked_wav

    # Stage 3: Final mux + styled ASS caption burn-in (with F-15 truncation guard & F-13 SHA-256 receipt)
    final_video_path = resolve_safe_child_path(out_dir, f"{project_id}_final.mp4")
    mux_report: Optional[Dict[str, Any]] = None
    caption_receipt: Optional[Dict[str, Any]] = None

    if final_audio_path is not None:
        mux_report = mux_audio_and_subtitles_to_video(
            video_path=assembled_video_path,
            dialogue_audio_path=final_audio_path,
            output_video_path=final_video_path,
            bgm_path=None if ducking_report else (Path(bgm_ref) if bgm_ref else None),
            sfx_path=None if ducking_report else (Path(sfx_ref) if sfx_ref else None),
            subtitles_srt_path=Path(srt_ref) if srt_ref else None,
            embed_subtitles=bool(spec.get("embed_subtitles", True)),
            preserve_source_audio=preserve_source_audio,
            caption_style_id=caption_style_id if srt_ref else None,
            caption_genre=caption_genre,
            caption_pacing=caption_pacing,
            caption_tone=caption_tone,
            allow_audio_tail_sec=allow_audio_tail_sec,
            allow_audio_truncation=allow_audio_truncation,
        )
        caption_receipt = mux_report.get("caption_style")
    else:
        final_video_path = assembled_video_path

    # Stage 4: Visual QC Contact Sheet (1 representative frame per scene)
    contact_sheet_path = resolve_safe_child_path(out_dir, f"{project_id}_contact_sheet.png")
    contact_sheet_report = generate_scene_contact_sheet(
        final_video_path,
        contact_sheet_path,
        scene_timestamps=assembly_report["scene_midpoints_sec"],
        scene_labels=assembly_report["scene_labels"],
    )

    # Stage 5: Hard Final Delivery Gate (with F-13 hash-verified caption receipt + black-frame QC)
    gate_result = evaluate_final_delivery_gate(
        video_path=final_video_path,
        expected_duration_sec=assembly_report["video_qc"]["duration_sec"],
        duration_tolerance_sec=float(spec.get("duration_tolerance_sec", 1.5)),
        expected_width=width,
        expected_height=height,
        expected_fps=float(fps),
        require_audio=bool(spec.get("require_audio", True)),
        require_captions=bool(spec.get("require_captions", srt_ref is not None)),
        caption_render_receipt=caption_receipt,
        check_black_frames=check_black_frames,
        output_classification=requested_classification,
        production_provenance=production_provenance,
        scene_source_types=scene_source_types,
    )
    if voice_stage.get("status") == "failed":
        gate_result["status"] = "INCOMPLETE"
        gate_result["playable_video_delivered"] = False
        gate_result["failures"].append(f"Voice stage failed: {voice_stage.get('error')}")
    state_mgr.record_final_delivery(gate_result)

    report = {
        "project_id": project_id,
        "title": title,
        "operating_mode": operating_mode,
        "requested_classification": requested_classification,
        "output_classification": gate_result["output_classification"],
        "provenance_verified": gate_result["provenance_verified"],
        "provenance_status": gate_result["provenance_status"],
        "declared_provenance": gate_result["declared_provenance"],
        "classification_downgraded": gate_result["classification_downgraded"],
        "provenance_check": provenance_check,
        "actual_production_route": "ffmpeg_multi_scene_assembler",
        "delivery_status": gate_result["status"],
        "playable_video_delivered": gate_result["playable_video_delivered"],
        "final_video_path": str(final_video_path),
        "contact_sheet_path": str(contact_sheet_path),
        "state_path": str(state_path),
        "host_resources": resources,
        "voice_stage": voice_stage,
        "assembly_report": assembly_report,
        "ducking_report": ducking_report,
        "mux_report": mux_report,
        "contact_sheet_report": contact_sheet_report,
        "delivery_gate": gate_result,
    }
    report_path = out_dir / "production_report.json"
    fd, tmp_rep = tempfile.mkstemp(prefix=".production_report_", suffix=".tmp", dir=str(out_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(report, indent=2) + "\n")
        os.replace(tmp_rep, report_path)
    except Exception:
        if os.path.exists(tmp_rep):
            os.unlink(tmp_rep)
        raise
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Roblox Town Director v0.2.0 Unified Resumable Autopilot Runner",
    )
    parser.add_argument("--spec", required=True, type=Path, help="Path to production specification JSON")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for production outputs")
    args = parser.parse_args(argv)

    try:
        if not args.spec.exists():
            raise FileNotFoundError(f"Production spec file not found: {args.spec}")
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        report = run_autopilot_production(spec, output_dir=args.output_dir)
        print(json.dumps(report, indent=2))
        return 0 if report["delivery_status"] == "COMPLETE" else 2
    except Exception as exc:
        print(json.dumps({"error": str(exc), "exit_code": 1}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
