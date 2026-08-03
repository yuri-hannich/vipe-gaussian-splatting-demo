from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Mapping, Optional

from vipe_demo.config import load_profile
from vipe_demo.dataset import PipelineError, sha256_file
from vipe_demo.environment import environment_report
from vipe_demo.pipeline import ROOT, pipeline_environment
from vipe_demo.video import probe_video


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _nvidia_smi() -> Optional[Mapping[str, str]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    name, driver, memory = [value.strip() for value in result.stdout.splitlines()[0].split(",")]
    return {"name": name, "driver_version": driver, "memory_total_mib": memory}


def _ply_vertices(path: Path) -> int:
    if not path.is_file():
        raise PipelineError(f"Missing Gaussian Splat PLY: {path}")
    with path.open("rb") as stream:
        if stream.readline() != b"ply\n":
            raise PipelineError(f"Not a PLY file: {path}")
        for _ in range(256):
            line = stream.readline()
            if not line:
                break
            if line.startswith(b"element vertex "):
                try:
                    count = int(line.split()[2])
                except (IndexError, ValueError) as error:
                    raise PipelineError(f"Malformed PLY vertex header: {path}") from error
                if count <= 0:
                    raise PipelineError("Gaussian Splat export contains no vertices")
                return count
            if line == b"end_header\n":
                break
    raise PipelineError(f"PLY vertex count was not found: {path}")


def _stage_records(run_root: Path) -> dict:
    records = {}
    for path in sorted((run_root / ".pipeline" / "stages").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise PipelineError(f"Invalid pipeline stage record: {path}") from error
        records[path.stem] = {
            "duration_seconds": payload.get("duration_seconds"),
            "fingerprint": payload.get("fingerprint"),
            "status": payload.get("status"),
        }
    return records


def create_report(profile_name: str) -> dict:
    profile, profiles, versions = load_profile(ROOT, profile_name)
    environment = pipeline_environment(profile, profiles, versions)
    metrics_path = Path(environment["METRICS_PATH"])
    splat_path = Path(environment["SPLAT_PATH"])
    demo_path = Path(environment["DEMO_PATH"])
    report_path = Path(environment["REPORT_PATH"])
    colmap_validation_path = Path(environment["COLMAP_ROOT"]) / "validation.json"

    for path in (metrics_path, splat_path, demo_path, colmap_validation_path):
        if not path.is_file():
            raise PipelineError(f"Missing final pipeline input: {path}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    colmap = json.loads(colmap_validation_path.read_text(encoding="utf-8"))
    video_probe = probe_video(demo_path)
    stream = video_probe["stream"]
    decoded_frames = int(stream.get("nb_read_frames", 0))
    if decoded_frames <= 0 or stream.get("codec_name") not in {"h264", "hevc"}:
        raise PipelineError("Rendered demo is empty or uses an unexpected codec")

    payload = {
        "schema_version": 1,
        "created_at_epoch": time.time(),
        "profile": profile.name,
        "repository_revision": _git_revision(),
        "upstream": {
            "vipe": {
                "tag": versions["VIPE_TAG"],
                "commit": versions["VIPE_COMMIT"],
            },
            "nerfstudio": {
                "tag": versions["NERFSTUDIO_TAG"],
                "commit": versions["NERFSTUDIO_COMMIT"],
            },
            "torch": versions["SPLAT_TORCH_VERSION"],
            "cuda_splatfacto": versions["SPLAT_CUDA_VERSION"],
        },
        "configuration": {
            "frames": profile.frames,
            "video_width": profile.width,
            "capture_fps": int(profiles["CAPTURE_FPS"]),
            "slam_buffer": profile.slam_buffer,
            "training_steps": profile.train_steps,
            "evaluation_interval": profile.eval_interval,
        },
        "host": {**environment_report(), "gpu": _nvidia_smi()},
        "geometry": colmap,
        "evaluation": metrics,
        "artifacts": {
            "splat": {
                "path": str(splat_path.relative_to(ROOT)),
                "bytes": splat_path.stat().st_size,
                "sha256": sha256_file(splat_path),
                "gaussians": _ply_vertices(splat_path),
            },
            "demo": {
                "path": str(demo_path.relative_to(ROOT)),
                "bytes": demo_path.stat().st_size,
                "sha256": sha256_file(demo_path),
                "codec": stream.get("codec_name"),
                "width": int(stream.get("width", 0)),
                "height": int(stream.get("height", 0)),
                "decoded_frames": decoded_frames,
                "duration_seconds": float(video_probe["format"].get("duration", 0)),
            },
        },
        "stages": _stage_records(Path(environment["RUN_ROOT"])),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
