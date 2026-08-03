from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Optional, Sequence

from vipe_demo.dataset import Frame, PipelineError, sha256_file


def require_command(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise PipelineError(f"Required command is not installed: {name}")
    return command


def probe_video(path: Path) -> dict:
    ffprobe = require_command("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,pix_fmt,r_frame_rate,avg_frame_rate,nb_read_frames",
        "-show_entries",
        "format=duration,size",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    if len(streams) != 1:
        raise PipelineError(f"Expected one video stream in {path}, found {len(streams)}")
    return {"stream": streams[0], "format": payload.get("format", {})}


def validate_video(path: Path, *, expected_frames: int, expected_fps: int) -> dict:
    if not path.is_file():
        raise PipelineError(f"Video does not exist: {path}")
    probe = probe_video(path)
    stream = probe["stream"]
    frame_count = int(stream.get("nb_read_frames", 0))
    fps = Fraction(stream.get("avg_frame_rate", "0/1"))
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))
    pix_fmt = stream.get("pix_fmt")

    if frame_count != expected_frames:
        raise PipelineError(
            f"Expected {expected_frames} decoded frames, found {frame_count}: {path}"
        )
    if fps != expected_fps:
        raise PipelineError(f"Expected {expected_fps} FPS, found {fps}: {path}")
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise PipelineError(f"Video dimensions must be positive and even: {width}x{height}")
    if pix_fmt != "yuv420p":
        raise PipelineError(f"Expected yuv420p, found {pix_fmt}: {path}")
    return probe


def prepare_video(
    frames: Sequence[Frame],
    output_path: Path,
    manifest_path: Path,
    *,
    width: int,
    fps: int,
    max_frames: Optional[int] = None,
    start_offset: int = 0,
) -> dict:
    if fps <= 0:
        raise PipelineError("FPS must be positive")
    if width <= 0 or width % 2:
        raise PipelineError("Output width must be a positive even number")
    if start_offset < 0 or start_offset >= len(frames):
        raise PipelineError(f"Invalid start offset: {start_offset}")

    selected = list(frames[start_offset:])
    if max_frames is not None:
        if max_frames <= 0:
            raise PipelineError("max-frames must be positive")
        if len(selected) < max_frames:
            raise PipelineError(
                f"Requested {max_frames} frames, but only {len(selected)} are available"
            )
        selected = selected[:max_frames]
    if not selected:
        raise PipelineError("No frames selected for video preparation")

    ffmpeg = require_command("ffmpeg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(f".{output_path.stem}.tmp.mp4")

    with tempfile.TemporaryDirectory(prefix="vipe-frames-", dir=output_path.parent) as temp:
        staging = Path(temp)
        for sequence_index, frame in enumerate(selected, start=1):
            target = staging / f"frame_{sequence_index:04d}.jpg"
            os.symlink(frame.path.resolve(), target)

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(fps),
            "-start_number",
            "1",
            "-i",
            str(staging / "frame_%04d.jpg"),
            "-vf",
            f"scale={width}:-2:flags=lanczos:in_range=full:out_range=tv,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-fps_mode",
            "cfr",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ]
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as error:
            raise PipelineError(f"FFmpeg failed with exit code {error.returncode}") from error

    probe = validate_video(
        temporary_output, expected_frames=len(selected), expected_fps=fps
    )
    temporary_output.replace(output_path)
    payload = {
        "schema_version": 1,
        "profile": "smoke" if max_frames is not None else "full",
        "source_frame_count": len(frames),
        "selected_frame_count": len(selected),
        "first_source_frame": selected[0].name,
        "last_source_frame": selected[-1].name,
        "source_indices": [frame.index for frame in selected],
        "fps": fps,
        "video": output_path.name,
        "video_sha256": sha256_file(output_path),
        "probe": probe,
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
