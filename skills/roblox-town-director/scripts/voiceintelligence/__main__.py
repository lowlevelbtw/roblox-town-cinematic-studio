#!/usr/bin/env python3
"""Command-line entrypoint for the Roblox Town Director Voice Intelligence module.

Provides safe, non-secret-printing commands for:
  - auth-check   : Verify provider configuration/authentication
  - list-voices  : Discover available provider voices
  - profiles     : List or inspect local VoiceProfileManager records
  - run-pipeline : Run script dialogue generation (+ optional FFmpeg video mux)
  - audio-qc     : Inspect an audio or video file via FFprobe/FFmpeg

Never prints or logs API keys or credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audio_qc import inspect_audio_file, inspect_video_file
from .pipeline import VoiceGenerationPipeline, mux_audio_and_subtitles_to_video
from .profile_manager import VoiceProfileManager
from .providers import ProviderRegistry, VoiceProviderError
import caption_styles


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice_intelligence",
        description="Roblox Town Director Voice Intelligence & Cloning CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # 1. auth-check
    p_auth = sub.add_parser("auth-check", help="Check provider configuration and authentication")
    p_auth.add_argument("--provider", default="elevenlabs", help="Provider ID (default: elevenlabs)")

    # 2. list-voices
    p_lv = sub.add_parser("list-voices", help="Discover voices from a configured provider")
    p_lv.add_argument("--provider", default="elevenlabs", help="Provider ID (default: elevenlabs)")

    # 3. profiles
    p_prof = sub.add_parser("profiles", help="Inspect local voice profiles")
    p_prof.add_argument("--store", required=True, type=Path, help="Path to voice_profiles.json")
    p_prof.add_argument("--voice-id", default=None, help="Inspect a single voice_id")
    p_prof.add_argument("--only-available", action="store_true", help="Filter to available profiles")

    # 4. run-pipeline
    p_run = sub.add_parser("run-pipeline", help="Run dialogue pipeline (+ optional video mux)")
    p_run.add_argument("--store", required=True, type=Path, help="Path to voice_profiles.json")
    p_run.add_argument("--script", required=True, type=Path, help="Path to script file")
    p_run.add_argument("--output-dir", required=True, type=Path, help="Output directory")
    p_run.add_argument("--state", required=True, type=Path, help="Path to project_voice_state.json")
    p_run.add_argument("--project-id", default="PROD_001", help="Project ID")
    p_run.add_argument("--project-title", default="Untitled Production", help="Project title")
    p_run.add_argument("--provider", default=None, help="Preferred provider ID")
    p_run.add_argument("--video", type=Path, default=None, help="Optional source video for muxing")
    p_run.add_argument("--bgm", type=Path, default=None, help="Optional background music file")
    p_run.add_argument("--sfx", type=Path, default=None, help="Optional sound effects file")
    p_run.add_argument("--no-embed-subtitles", action="store_true", help="Keep SRT sidecar only")
    p_run.add_argument("--preserve-source-audio", action="store_true", help="Mix existing source video audio instead of replacing it")

    # 5. audio-qc / mux-check
    p_qc = sub.add_parser("audio-qc", help="Run FFprobe/FFmpeg technical QC on audio or video")
    p_qc.add_argument("--file", required=True, type=Path, help="Audio or video file to inspect")
    p_qc.add_argument("--video", action="store_true", help="Inspect as video container")

    # 6. mux-video
    p_mux = sub.add_parser("mux-video", help="Mux dialogue audio (+ optional BGM/SFX/SRT) onto video")
    p_mux.add_argument("--video", required=True, type=Path, help="Source video path")
    p_mux.add_argument("--dialogue", required=True, type=Path, help="Master dialogue audio path")
    p_mux.add_argument("--output", required=True, type=Path, help="Output MP4 path")
    p_mux.add_argument("--bgm", type=Path, default=None, help="Optional BGM audio path")
    p_mux.add_argument("--sfx", type=Path, default=None, help="Optional SFX audio path")
    p_mux.add_argument("--srt", type=Path, default=None, help="Optional SRT subtitle path")
    p_mux.add_argument("--no-embed-subtitles", action="store_true", help="Keep SRT sidecar only")
    p_mux.add_argument("--preserve-source-audio", action="store_true", help="Mix existing source video audio instead of replacing it")
    p_mux.add_argument("--caption-style", default=None, help="Optional caption preset ID (C01-C16)")

    # 7. list-caption-styles
    sub.add_parser("list-caption-styles", help="List all 16 caption presets (C01-C16)")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    registry = ProviderRegistry()

    try:
        if args.command == "auth-check":
            adapter = registry.get(args.provider)
            result = adapter.check_authentication()
            _print_json(result)
            return 0

        if args.command == "list-voices":
            adapter = registry.get(args.provider)
            voices = adapter.list_voices()
            _print_json({"provider": args.provider, "count": len(voices), "voices": voices})
            return 0

        if args.command == "profiles":
            mgr = VoiceProfileManager(args.store)
            if args.voice_id:
                prof = mgr.require_profile(args.voice_id)
                _print_json(prof.to_dict())
            else:
                items = [p.to_dict() for p in mgr.list_profiles(only_available=args.only_available)]
                _print_json({"count": len(items), "profiles": items})
            return 0

        if args.command == "audio-qc":
            if args.video:
                report = inspect_video_file(args.file)
            else:
                report = inspect_audio_file(args.file, check_volume=True)
            _print_json(report)
            return 0 if report.get("valid") else 2

        if args.command == "list-caption-styles":
            presets = caption_styles.load_caption_presets()
            _print_json({"count": len(presets), "presets": list(presets.values())})
            return 0

        if args.command == "mux-video":
            report = mux_audio_and_subtitles_to_video(
                video_path=args.video,
                dialogue_audio_path=args.dialogue,
                output_video_path=args.output,
                bgm_path=args.bgm,
                sfx_path=args.sfx,
                subtitles_srt_path=args.srt,
                embed_subtitles=not args.no_embed_subtitles,
                preserve_source_audio=args.preserve_source_audio,
                caption_style_id=args.caption_style,
            )
            _print_json(report)
            return 0

        if args.command == "run-pipeline":
            if not args.script.exists():
                raise FileNotFoundError(f"Script file not found: {args.script}")
            mgr = VoiceProfileManager(args.store)
            pipeline = VoiceGenerationPipeline(profile_manager=mgr, provider_registry=registry)
            state = pipeline.run_script_pipeline(
                project_id=args.project_id,
                project_title=args.project_title,
                script_text=args.script.read_text(encoding="utf-8"),
                output_dir=args.output_dir,
                state_path=args.state,
                preferred_provider=args.provider,
                source_video_path=args.video,
                bgm_path=args.bgm,
                sfx_path=args.sfx,
                embed_subtitles=not args.no_embed_subtitles,
                preserve_source_audio=args.preserve_source_audio,
            )
            _print_json(state)
            qc = state.get("qc_report") or {}
            return 0 if qc.get("technical_qc_passed") else 2

        parser.print_help()
        return 2
    except (VoiceProviderError, KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc), "exit_code": 1}), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"error": f"Unexpected failure: {exc}", "exit_code": 1}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
