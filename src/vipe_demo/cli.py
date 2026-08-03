from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from vipe_demo.dataset import PipelineError, inspect_frames, write_dataset_manifest
from vipe_demo.colmap import validate_colmap
from vipe_demo.environment import check_environment, format_report
from vipe_demo.pipeline import run_pipeline
from vipe_demo.report import create_report
from vipe_demo.video import prepare_video


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vipe-demo", description="ViPE Gaussian Splatting pipeline utilities"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Check local dependencies")
    check.add_argument("--require-gpu", action="store_true")

    inspect = commands.add_parser("inspect", help="Validate the source image sequence")
    inspect.add_argument("--input", type=Path, required=True)
    inspect.add_argument("--manifest", type=Path, required=True)
    count = inspect.add_mutually_exclusive_group()
    count.add_argument("--expected-count", type=int)
    count.add_argument("--minimum-count", type=int)
    inspect.add_argument("--skip-hash", action="store_true")

    prepare = commands.add_parser("prepare", help="Create and validate a ViPE MP4")
    prepare.add_argument("--input", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--width", type=int, default=1280)
    prepare.add_argument("--fps", type=int, default=1)
    prepare.add_argument("--max-frames", type=int)
    prepare.add_argument("--start-offset", type=int, default=0)
    prepare.add_argument("--skip-hash", action="store_true")

    colmap = commands.add_parser("validate-colmap", help="Validate ViPE's COLMAP export")
    colmap.add_argument("--input", type=Path, required=True)
    colmap.add_argument("--min-images", type=int, required=True)

    pipeline = commands.add_parser("pipeline", help="Run the resumable end-to-end pipeline")
    pipeline.add_argument("--profile", choices=("smoke", "quality"), default="quality")
    pipeline.add_argument("--dry-run", action="store_true")
    pipeline.add_argument("--force", action="store_true")

    report = commands.add_parser("report", help="Validate deliverables and write a run report")
    report.add_argument("--profile", choices=("smoke", "quality"), required=True)
    return parser


def _run(args: argparse.Namespace) -> None:
    if args.command == "pipeline":
        run_pipeline(profile_name=args.profile, dry_run=args.dry_run, force=args.force)
        return

    if args.command == "validate-colmap":
        report = validate_colmap(args.input, min_images=args.min_images)
        print(
            f"Validated {report['registered_images']} cameras and "
            f"{report['points3D']} initialization points: {args.input}"
        )
        return

    if args.command == "report":
        report = create_report(args.profile)
        print(
            f"Validated {report['artifacts']['splat']['gaussians']} Gaussians and "
            f"{report['artifacts']['demo']['decoded_frames']} demo frames"
        )
        return

    if args.command == "check":
        print(format_report(check_environment(require_gpu=args.require_gpu)))
        return

    frames = inspect_frames(args.input, hash_files=not args.skip_hash)
    if args.command == "inspect":
        if args.expected_count is not None and len(frames) != args.expected_count:
            raise PipelineError(
                f"Expected {args.expected_count} frames, found {len(frames)}"
            )
        if args.minimum_count is not None and len(frames) < args.minimum_count:
            raise PipelineError(
                f"Expected at least {args.minimum_count} frames, found {len(frames)}"
            )
        manifest = write_dataset_manifest(frames, args.input, args.manifest)
        print(
            f"Validated {manifest['frame_count']} frames at "
            f"{manifest['width']}x{manifest['height']}; manifest: {args.manifest}"
        )
        return

    payload = prepare_video(
        frames,
        args.output,
        args.manifest,
        width=args.width,
        fps=args.fps,
        max_frames=args.max_frames,
        start_offset=args.start_offset,
    )
    probe = payload["probe"]["stream"]
    print(
        f"Prepared {payload['selected_frame_count']} frames as "
        f"{probe['width']}x{probe['height']} at {payload['fps']} FPS: {args.output}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        _run(_parser().parse_args(argv))
    except (PipelineError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
