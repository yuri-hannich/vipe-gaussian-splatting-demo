from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Union

from vipe_demo.config import Profile, load_profile, positive_int, required
from vipe_demo.dataset import PipelineError, sha256_file


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Stage:
    name: str
    command: Sequence[str]
    dependencies: Sequence[str]
    inputs: Sequence[Path]
    outputs: Sequence[Path]


def _path_signature(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "kind": "missing"}
    if path.is_file():
        return {
            "path": str(path),
            "kind": "file",
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    entries = []
    for item in sorted(path.rglob("*")):
        if item.is_file():
            stat = item.stat()
            entries.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "path": str(path),
        "kind": "directory",
        "files": len(entries),
        "tree_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _fingerprint(
    stage: Stage,
    dependency_fingerprints: Mapping[str, str],
    stage_environment: Mapping[str, str],
) -> str:
    payload = {
        "schema_version": 1,
        "name": stage.name,
        "command": list(stage.command),
        "dependencies": {
            name: dependency_fingerprints[name] for name in stage.dependencies
        },
        "environment": dict(sorted(stage_environment.items())),
        "inputs": [_path_signature(path) for path in stage.inputs],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_record(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _outputs_match(stage: Stage, record: dict) -> bool:
    expected = record.get("outputs")
    if not isinstance(expected, list) or len(expected) != len(stage.outputs):
        return False
    return expected == [_path_signature(path) for path in stage.outputs]


def _write_record(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _relative_command(command: Sequence[str]) -> str:
    rendered = []
    for part in command:
        try:
            rendered.append(str(Path(part).relative_to(ROOT)))
        except (ValueError, OSError):
            rendered.append(part)
    return " ".join(rendered)


def _profile_paths(
    profile: Profile, values: Mapping[str, str]
) -> Dict[str, Union[Path, str]]:
    dataset_name = required(dict(values), "DATASET_NAME")
    dataset_dir = Path(os.environ.get("DATASET_DIR", ROOT / "data" / "raw" / dataset_name))
    variant = "smoke" if profile.name == "smoke" else "full"
    sequence = f"{dataset_name}-smoke" if profile.name == "smoke" else dataset_name
    run_root = ROOT / "runs" / profile.name
    colmap_root = run_root / "colmap" / sequence
    ns_root = run_root / "nerfstudio"
    ns_config = ns_root / sequence / "splatfacto" / profile.name / "config.yml"
    artifacts = ROOT / "artifacts" / profile.name
    return {
        "dataset": dataset_dir,
        "source_manifest": ROOT / "data" / "manifests" / "source.json",
        "video": ROOT / "data" / "interim" / variant / f"{sequence}.mp4",
        "video_manifest": ROOT / "data" / "manifests" / f"{variant}-video.json",
        "run_root": run_root,
        "sequence": sequence,
        "vipe_output": run_root / "vipe",
        "colmap_root": colmap_root,
        "ns_root": ns_root,
        "ns_config": ns_config,
        "ns_models": ns_config.parent / "nerfstudio_models",
        "metrics": artifacts / "metrics.json",
        "eval_renders": artifacts / "evaluation",
        "splat": artifacts / "splat" / "splat.ply",
        "demo": artifacts / "demo.mp4",
        "report": artifacts / "run-report.json",
    }


def pipeline_environment(
    profile: Profile, profiles: Mapping[str, str], versions: Mapping[str, str]
) -> Dict[str, str]:
    paths = _profile_paths(profile, profiles)
    environment = {
        **versions,
        "PROJECT_ROOT": str(ROOT),
        "PROFILE": profile.name,
        "FRAME_COUNT": str(profile.frames),
        "VIDEO_WIDTH": str(profile.width),
        "CAPTURE_FPS": required(dict(profiles), "CAPTURE_FPS"),
        "SLAM_BUFFER": str(profile.slam_buffer),
        "TRAIN_STEPS": str(profile.train_steps),
        "EVAL_INTERVAL": str(profile.eval_interval),
        "DATASET_FOLDER_URL": required(dict(profiles), "DATASET_FOLDER_URL"),
        "DATASET_NAME": required(dict(profiles), "DATASET_NAME"),
        "EXPECTED_FRAMES": required(dict(profiles), "EXPECTED_FRAMES"),
        "RENDER_INTERPOLATION_STEPS": required(
            dict(profiles), "RENDER_INTERPOLATION_STEPS"
        ),
        "RENDER_FPS": required(dict(profiles), "RENDER_FPS"),
        "DATASET_DIR": str(paths["dataset"]),
        "DATASET_ARCHIVE": os.environ.get("DATASET_ARCHIVE", ""),
        "SOURCE_MANIFEST": str(paths["source_manifest"]),
        "VIDEO_PATH": str(paths["video"]),
        "VIDEO_MANIFEST": str(paths["video_manifest"]),
        "RUN_ROOT": str(paths["run_root"]),
        "SEQUENCE_NAME": str(paths["sequence"]),
        "VIPE_OUTPUT_DIR": str(paths["vipe_output"]),
        "COLMAP_ROOT": str(paths["colmap_root"]),
        "NS_OUTPUT_ROOT": str(paths["ns_root"]),
        "NS_CONFIG": str(paths["ns_config"]),
        "NS_MODELS": str(paths["ns_models"]),
        "METRICS_PATH": str(paths["metrics"]),
        "EVAL_RENDER_DIR": str(paths["eval_renders"]),
        "SPLAT_PATH": str(paths["splat"]),
        "DEMO_PATH": str(paths["demo"]),
        "REPORT_PATH": str(paths["report"]),
        "VIPE_DIR": str(ROOT / ".cache" / "deps" / "vipe"),
        "VIPE_CONDA_PREFIX": str(ROOT / ".cache" / "envs" / "vipe"),
        "NERFSTUDIO_DIR": str(ROOT / ".cache" / "deps" / "nerfstudio"),
        "SPLAT_CONDA_PREFIX": str(ROOT / ".cache" / "envs" / "splatfacto"),
    }
    return environment


def build_stages(profile: Profile, profiles: Mapping[str, str]) -> List[Stage]:
    paths = _profile_paths(profile, profiles)
    python = sys.executable
    scripts = ROOT / "scripts"
    min_images = max(8, int(profile.frames * 0.75))
    download_inputs = [
        scripts / "download_dataset.sh",
        ROOT / "configs" / "versions.env",
        ROOT / "configs" / "dataset-files.tsv",
    ]
    if os.environ.get("DATASET_ARCHIVE"):
        download_inputs.append(Path(os.environ["DATASET_ARCHIVE"]))
    prepare_command = [
        python,
        "-m",
        "vipe_demo",
        "prepare",
        "--input",
        str(paths["dataset"]),
        "--output",
        str(paths["video"]),
        "--manifest",
        str(paths["video_manifest"]),
        "--width",
        str(profile.width),
        "--fps",
        required(dict(profiles), "CAPTURE_FPS"),
    ]
    if profile.name == "smoke":
        prepare_command.extend(["--max-frames", str(profile.frames)])

    return [
        Stage(
            "bootstrap",
            ["bash", str(scripts / "bootstrap_host.sh")],
            [],
            [
                scripts / "bootstrap_host.sh",
                scripts / "lib" / "common.sh",
                ROOT / "configs" / "versions.env",
            ],
            [
                ROOT / ".cache" / "tools" / "conda-path",
                ROOT / ".cache" / "tools" / "uv-path",
            ],
        ),
        Stage(
            "preflight",
            [python, "-m", "vipe_demo", "check", "--require-gpu"],
            ["bootstrap"],
            [ROOT / "src" / "vipe_demo" / "environment.py"],
            [],
        ),
        Stage(
            "download",
            ["bash", str(scripts / "download_dataset.sh")],
            ["preflight"],
            download_inputs,
            [paths["dataset"]],  # type: ignore[list-item]
        ),
        Stage(
            "inspect",
            [
                python,
                "-m",
                "vipe_demo",
                "inspect",
                "--input",
                str(paths["dataset"]),
                "--manifest",
                str(paths["source_manifest"]),
                "--minimum-count" if profile.name == "smoke" else "--expected-count",
                str(profile.frames),
            ],
            ["download"],
            [paths["dataset"], ROOT / "src" / "vipe_demo" / "dataset.py"],  # type: ignore[list-item]
            [paths["source_manifest"]],  # type: ignore[list-item]
        ),
        Stage(
            "prepare",
            prepare_command,
            ["inspect"],
            [
                paths["source_manifest"],  # type: ignore[list-item]
                ROOT / "src" / "vipe_demo" / "video.py",
            ],
            [paths["video"], paths["video_manifest"]],  # type: ignore[list-item]
        ),
        Stage(
            "setup_vipe",
            ["bash", str(scripts / "setup_vipe.sh")],
            ["preflight", "bootstrap"],
            [scripts / "setup_vipe.sh", scripts / "lib" / "common.sh", ROOT / "configs" / "versions.env"],
            [
                ROOT / ".cache" / "deps" / "vipe" / "run.py",
                ROOT / ".cache" / "deps" / "vipe" / ".venv" / "bin" / "python",
            ],
        ),
        Stage(
            "vipe_infer",
            ["bash", str(scripts / "run_vipe.sh")],
            ["prepare", "setup_vipe"],
            [paths["video_manifest"], scripts / "run_vipe.sh"],  # type: ignore[list-item]
            [paths["vipe_output"]],  # type: ignore[list-item]
        ),
        Stage(
            "export_colmap",
            ["bash", str(scripts / "export_colmap.sh")],
            ["vipe_infer"],
            [scripts / "export_colmap.sh"],
            [
                paths["colmap_root"] / "cameras.txt",  # type: ignore[operator]
                paths["colmap_root"] / "images.txt",  # type: ignore[operator]
                paths["colmap_root"] / "points3D.txt",  # type: ignore[operator]
                paths["colmap_root"] / "images",  # type: ignore[operator]
            ],
        ),
        Stage(
            "validate_colmap",
            [
                python,
                "-m",
                "vipe_demo",
                "validate-colmap",
                "--input",
                str(paths["colmap_root"]),
                "--min-images",
                str(min_images),
            ],
            ["export_colmap"],
            [ROOT / "src" / "vipe_demo" / "colmap.py"],
            [paths["colmap_root"] / "validation.json"],  # type: ignore[operator]
        ),
        Stage(
            "setup_splatfacto",
            ["bash", str(scripts / "setup_splatfacto.sh")],
            ["preflight", "bootstrap"],
            [scripts / "setup_splatfacto.sh", scripts / "lib" / "common.sh", ROOT / "configs" / "versions.env"],
            [
                ROOT / ".cache" / "deps" / "nerfstudio" / "pyproject.toml",
                ROOT / ".cache" / "envs" / "splatfacto" / "bin" / "ns-train",
            ],
        ),
        Stage(
            "train_splatfacto",
            ["bash", str(scripts / "run_splatfacto.sh"), "train"],
            ["validate_colmap", "setup_splatfacto"],
            [paths["colmap_root"] / "validation.json", scripts / "run_splatfacto.sh"],  # type: ignore[operator]
            [paths["ns_config"], paths["ns_models"]],  # type: ignore[list-item]
        ),
        Stage(
            "evaluate",
            ["bash", str(scripts / "run_splatfacto.sh"), "evaluate"],
            ["train_splatfacto"],
            [paths["ns_config"]],  # type: ignore[list-item]
            [paths["metrics"]],  # type: ignore[list-item]
        ),
        Stage(
            "export_splat",
            ["bash", str(scripts / "run_splatfacto.sh"), "export"],
            ["train_splatfacto"],
            [paths["ns_config"]],  # type: ignore[list-item]
            [paths["splat"]],  # type: ignore[list-item]
        ),
        Stage(
            "render",
            ["bash", str(scripts / "run_splatfacto.sh"), "render"],
            ["train_splatfacto"],
            [paths["ns_config"]],  # type: ignore[list-item]
            [paths["demo"]],  # type: ignore[list-item]
        ),
        Stage(
            "report",
            [python, "-m", "vipe_demo", "report", "--profile", profile.name],
            ["evaluate", "export_splat", "render"],
            [
                paths["metrics"],  # type: ignore[list-item]
                paths["splat"],  # type: ignore[list-item]
                paths["demo"],  # type: ignore[list-item]
                ROOT / "configs" / "versions.env",
                ROOT / "configs" / "profiles.env",
            ],
            [paths["report"]],  # type: ignore[list-item]
        ),
    ]


def run_pipeline(*, profile_name: str, dry_run: bool = False, force: bool = False) -> None:
    profile, profiles, versions = load_profile(ROOT, profile_name)
    stage_environment = pipeline_environment(profile, profiles, versions)
    stages = build_stages(profile, profiles)
    run_root = Path(stage_environment["RUN_ROOT"])
    record_root = run_root / ".pipeline" / "stages"
    fingerprints: Dict[str, str] = {}
    print(f"Pipeline profile: {profile.name}")
    print(f"Frames: {profile.frames}, width: {profile.width}, train steps: {profile.train_steps}")

    for stage in stages:
        fingerprint = _fingerprint(stage, fingerprints, stage_environment)
        fingerprints[stage.name] = fingerprint
        record_path = record_root / f"{stage.name}.json"
        record = _read_record(record_path)
        resumable = (
            not force
            and record is not None
            and record.get("fingerprint") == fingerprint
            and record.get("status") == "complete"
            and _outputs_match(stage, record)
        )
        status = "RESUME" if resumable else "RUN"
        print(f"[{status:6}] {stage.name:20} {_relative_command(stage.command)}")
        if dry_run or resumable:
            continue

        started = time.time()
        env = os.environ.copy()
        env.update(stage_environment)
        env["PYTHONPATH"] = str(ROOT / "src")
        run_root.mkdir(parents=True, exist_ok=True)
        log_root = run_root / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        log_path = log_root / f"{stage.name}.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {stage.name} ===\n")
            log.flush()
            process = subprocess.Popen(
                stage.command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="")
                log.write(line)
            return_code = process.wait()
        if return_code != 0:
            raise PipelineError(
                f"Stage '{stage.name}' failed with exit code {return_code}; log: {log_path}"
            )
        missing = [path for path in stage.outputs if not path.exists()]
        if missing:
            raise PipelineError(
                f"Stage '{stage.name}' did not create required outputs: "
                + ", ".join(str(path) for path in missing)
            )
        completed = time.time()
        _write_record(
            record_path,
            {
                "schema_version": 1,
                "stage": stage.name,
                "status": "complete",
                "fingerprint": fingerprint,
                "started_at_epoch": started,
                "completed_at_epoch": completed,
                "duration_seconds": round(completed - started, 3),
                "command": list(stage.command),
                "outputs": [_path_signature(path) for path in stage.outputs],
                "log": str(log_path),
            },
        )

    if dry_run:
        print("Dry run complete; no commands were executed.")
    else:
        print(f"Pipeline complete: {stage_environment['REPORT_PATH']}")
