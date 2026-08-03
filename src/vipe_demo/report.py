from __future__ import annotations

import json
import math
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from typing import Mapping

from vipe_demo.config import load_profile
from vipe_demo.dataset import PipelineError, sha256_file
from vipe_demo.environment import environment_report
from vipe_demo.pipeline import ROOT, pipeline_environment
from vipe_demo.video import probe_video


PLY_PROPERTIES = (
    "x",
    "y",
    "z",
    "nx",
    "ny",
    "nz",
    "f_dc_0",
    "f_dc_1",
    "f_dc_2",
    *(f"f_rest_{index}" for index in range(45)),
    "opacity",
    "scale_0",
    "scale_1",
    "scale_2",
    "rot_0",
    "rot_1",
    "rot_2",
    "rot_3",
)
PRE_REPORT_STAGES = (
    "bootstrap",
    "preflight",
    "download",
    "inspect",
    "prepare",
    "setup_vipe",
    "vipe_infer",
    "export_colmap",
    "validate_colmap",
    "setup_splatfacto",
    "train_splatfacto",
    "evaluate",
    "export_splat",
    "render",
)
REQUIRED_METRICS = ("psnr", "ssim", "lpips", "num_rays_per_sec", "fps")


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "unavailable"


def _ply_metadata(path: Path) -> dict:
    if not path.is_file():
        raise PipelineError(f"Missing Gaussian Splat PLY: {path}")
    vertex_count = None
    properties = []
    vertex_element = False
    binary_little_endian = False
    header_bytes = 0
    with path.open("rb") as stream:
        if stream.readline() != b"ply\n":
            raise PipelineError(f"Not a PLY file: {path}")
        for _ in range(512):
            line = stream.readline()
            if not line:
                break
            try:
                text = line.decode("ascii").strip()
            except UnicodeDecodeError as error:
                raise PipelineError(f"Non-ASCII PLY header: {path}") from error
            if text == "format binary_little_endian 1.0":
                binary_little_endian = True
            elif text.startswith("element "):
                parts = text.split()
                if len(parts) != 3:
                    raise PipelineError(f"Malformed PLY element header: {path}")
                if parts[1] != "vertex":
                    raise PipelineError(f"Unexpected PLY element {parts[1]!r}: {path}")
                try:
                    vertex_count = int(parts[2])
                except ValueError as error:
                    raise PipelineError(f"Malformed PLY vertex header: {path}") from error
                if vertex_count <= 0:
                    raise PipelineError("Gaussian Splat export contains no vertices")
                vertex_element = True
            elif text.startswith("property ") and vertex_element:
                parts = text.split()
                if len(parts) != 3 or parts[1] != "float":
                    raise PipelineError(f"Unexpected PLY vertex property: {text}")
                properties.append(parts[2])
            elif text == "end_header":
                header_bytes = stream.tell()
                break
    if not binary_little_endian:
        raise PipelineError(f"Expected binary_little_endian PLY: {path}")
    if vertex_count is None or header_bytes == 0:
        raise PipelineError(f"Incomplete PLY header: {path}")
    if tuple(properties) != PLY_PROPERTIES:
        raise PipelineError(f"Unexpected Gaussian Splat PLY property schema: {path}")
    expected_bytes = header_bytes + vertex_count * len(PLY_PROPERTIES) * 4
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise PipelineError(
            f"PLY payload length mismatch: expected {expected_bytes}, found {actual_bytes}: {path}"
        )
    return {
        "vertices": vertex_count,
        "properties": len(properties),
        "format": "binary_little_endian",
        "header_bytes": header_bytes,
        "expected_bytes": expected_bytes,
    }


def _ply_vertices(path: Path) -> int:
    return int(_ply_metadata(path)["vertices"])


def _finite_metric(results: Mapping[str, object], key: str) -> float:
    value = results.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PipelineError(f"Evaluation metric {key!r} is missing or not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise PipelineError(f"Evaluation metric {key!r} is not finite")
    return number


def _validate_metrics(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise PipelineError("Metrics root must be a JSON object")
    for key in ("experiment_name", "method_name", "checkpoint"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise PipelineError(f"Metrics field {key!r} is missing or empty")
    results = payload.get("results")
    if not isinstance(results, dict):
        raise PipelineError("Metrics results must be a JSON object")
    values = {key: _finite_metric(results, key) for key in REQUIRED_METRICS}
    if not 0 <= values["ssim"] <= 1:
        raise PipelineError("SSIM must be between 0 and 1")
    if values["lpips"] < 0:
        raise PipelineError("LPIPS must be non-negative")
    if values["num_rays_per_sec"] <= 0 or values["fps"] <= 0:
        raise PipelineError("Evaluation throughput metrics must be positive")
    for key, value in results.items():
        if key.endswith("_std"):
            if _finite_metric(results, key) < 0:
                raise PipelineError(f"Evaluation metric {key!r} must be non-negative")
    return payload


def _expected_render_frames(frame_count: int, eval_interval: int, steps: int) -> int:
    eval_frames = ((frame_count - 1) // eval_interval) + 1
    train_frames = frame_count - eval_frames
    if train_frames < 2:
        raise PipelineError("Profile has too few training cameras for interpolation")
    return (train_frames - 1) * steps


def _validate_demo(probe: Mapping[str, object], profile, profiles: Mapping[str, str]) -> dict:
    stream = probe.get("stream")
    video_format = probe.get("format")
    if not isinstance(stream, dict) or not isinstance(video_format, dict):
        raise PipelineError("Rendered demo probe is incomplete")
    decoded_frames = int(stream.get("nb_read_frames", 0))
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))
    render_fps = int(profiles["RENDER_FPS"])
    interpolation_steps = int(profiles["RENDER_INTERPOLATION_STEPS"])
    expected_frames = _expected_render_frames(
        profile.frames, profile.eval_interval, interpolation_steps
    )
    fps = Fraction(stream.get("avg_frame_rate", "0/1"))
    duration = float(video_format.get("duration", 0))
    expected_height = profile.width * 3 // 4
    if stream.get("codec_name") != "h264":
        raise PipelineError("Rendered demo must use H.264")
    if (width, height) != (profile.width, expected_height):
        raise PipelineError(
            f"Rendered demo must be {profile.width}x{expected_height}, found {width}x{height}"
        )
    if stream.get("pix_fmt") != "yuv420p":
        raise PipelineError("Rendered demo must use yuv420p")
    if stream.get("color_range") not in {None, "unknown", "tv"}:
        raise PipelineError(f"Unexpected rendered demo color range: {stream.get('color_range')}")
    if decoded_frames != expected_frames:
        raise PipelineError(
            f"Expected {expected_frames} rendered frames, found {decoded_frames}"
        )
    if fps <= 0 or abs(float(fps) - render_fps) > render_fps * 0.02:
        raise PipelineError(f"Rendered demo frame rate is inconsistent: {fps}")
    expected_duration = decoded_frames / render_fps
    if duration <= 0 or abs(duration - expected_duration) > 2.1 / render_fps:
        raise PipelineError(
            f"Rendered demo duration is inconsistent: expected near {expected_duration:.6f}s, found {duration:.6f}s"
        )
    return {
        "codec": stream.get("codec_name"),
        "width": width,
        "height": height,
        "pixel_format": stream.get("pix_fmt"),
        "color_range": stream.get("color_range", "unknown"),
        "fps": float(fps),
        "decoded_frames": decoded_frames,
        "duration_seconds": duration,
    }


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


def _validate_stage_records(records: Mapping[str, object]) -> None:
    missing = [name for name in PRE_REPORT_STAGES if name not in records]
    if missing:
        raise PipelineError(f"Missing pre-report stage records: {', '.join(missing)}")
    incomplete = [
        name
        for name in PRE_REPORT_STAGES
        if not isinstance(records[name], dict) or records[name].get("status") != "complete"
    ]
    if incomplete:
        raise PipelineError(f"Incomplete pre-report stages: {', '.join(incomplete)}")


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
    try:
        metrics = _validate_metrics(json.loads(metrics_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise PipelineError(f"Invalid metrics JSON: {metrics_path}") from error
    colmap = json.loads(colmap_validation_path.read_text(encoding="utf-8"))
    video_probe = probe_video(demo_path)
    demo_metadata = _validate_demo(video_probe, profile, profiles)
    ply_metadata = _ply_metadata(splat_path)
    stage_records = _stage_records(Path(environment["RUN_ROOT"]))
    _validate_stage_records(stage_records)

    payload = {
        "schema_version": 2,
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
        "host": environment_report(),
        "geometry": colmap,
        "evaluation": metrics,
        "artifacts": {
            "splat": {
                "path": str(splat_path.relative_to(ROOT)),
                "bytes": splat_path.stat().st_size,
                "sha256": sha256_file(splat_path),
                "gaussians": ply_metadata["vertices"],
                "properties": ply_metadata["properties"],
                "format": ply_metadata["format"],
            },
            "metrics": {
                "path": str(metrics_path.relative_to(ROOT)),
                "bytes": metrics_path.stat().st_size,
                "sha256": sha256_file(metrics_path),
            },
            "demo": {
                "path": str(demo_path.relative_to(ROOT)),
                "bytes": demo_path.stat().st_size,
                "sha256": sha256_file(demo_path),
                **demo_metadata,
            },
        },
        "stages": stage_records,
        "stage_record_scope": "all successful stages preceding report; the report stage records itself after this snapshot",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _reported_artifact(root: Path, entry: Mapping[str, object], label: str) -> Path:
    relative = entry.get("path")
    if not isinstance(relative, str):
        raise PipelineError(f"Run report has no path for {label}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise PipelineError(f"Run report path escapes the repository: {relative}") from error
    if not path.is_file():
        raise PipelineError(f"Missing reported {label}: {path}")
    return path


def verify_artifacts(profile_name: str) -> dict:
    """Verify copied deliverables against the report produced on the GPU host."""
    profile, profiles, versions = load_profile(ROOT, profile_name)
    environment = pipeline_environment(profile, profiles, versions)
    report_path = Path(environment["REPORT_PATH"])
    if not report_path.is_file():
        raise PipelineError(f"Missing run report: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PipelineError(f"Invalid run report: {report_path}") from error
    if payload.get("profile") != profile.name:
        raise PipelineError(
            f"Expected {profile.name} report, found {payload.get('profile')!r}"
        )
    if payload.get("schema_version") != 2:
        raise PipelineError(f"Expected run report schema 2, found {payload.get('schema_version')!r}")
    stages = payload.get("stages")
    if not isinstance(stages, dict):
        raise PipelineError("Run report has no stage provenance")
    _validate_stage_records(stages)

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise PipelineError("Run report has no artifacts object")
    splat_entry = artifacts.get("splat")
    metrics_entry = artifacts.get("metrics")
    demo_entry = artifacts.get("demo")
    if not all(isinstance(entry, dict) for entry in (splat_entry, metrics_entry, demo_entry)):
        raise PipelineError("Run report is missing splat, metrics, or demo metadata")

    splat_path = _reported_artifact(ROOT, splat_entry, "Gaussian splat")
    metrics_path = _reported_artifact(ROOT, metrics_entry, "evaluation metrics")
    demo_path = _reported_artifact(ROOT, demo_entry, "demo video")
    for path, entry, label in (
        (splat_path, splat_entry, "Gaussian splat"),
        (metrics_path, metrics_entry, "evaluation metrics"),
        (demo_path, demo_entry, "demo video"),
    ):
        if path.stat().st_size != entry.get("bytes"):
            raise PipelineError(f"Reported byte size does not match {label}: {path}")
        if sha256_file(path) != entry.get("sha256"):
            raise PipelineError(f"Reported SHA-256 does not match {label}: {path}")

    try:
        metrics = _validate_metrics(json.loads(metrics_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as error:
        raise PipelineError(f"Invalid copied metrics JSON: {metrics_path}") from error
    if metrics != payload.get("evaluation"):
        raise PipelineError("Reported evaluation does not match metrics.json")
    ply_metadata = _ply_metadata(splat_path)
    gaussians = ply_metadata["vertices"]
    if gaussians != splat_entry.get("gaussians"):
        raise PipelineError("Reported Gaussian count does not match the PLY header")
    if splat_entry.get("properties") != ply_metadata["properties"]:
        raise PipelineError("Reported PLY property count does not match the artifact")
    if splat_entry.get("format") != ply_metadata["format"]:
        raise PipelineError("Reported PLY format does not match the artifact")
    probe = probe_video(demo_path)
    expected_video = _validate_demo(probe, profile, profiles)
    for key, actual in expected_video.items():
        if demo_entry.get(key) != actual:
            raise PipelineError(f"Reported demo {key} does not match the copied video")
    return {
        "profile": profile.name,
        "repository_revision": payload.get("repository_revision"),
        "gaussians": gaussians,
        "demo_frames": expected_video["decoded_frames"],
    }
