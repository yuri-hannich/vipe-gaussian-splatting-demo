from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

from vipe_demo.dataset import PipelineError


def _version(command: str, flag: str = "--version") -> str:
    path = shutil.which(command)
    if path is None:
        return "missing"
    result = subprocess.run([path, flag], capture_output=True, text=True)
    output = result.stdout or result.stderr
    return output.splitlines()[0] if output else path


def environment_report() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "ffmpeg": _version("ffmpeg", "-version"),
        "ffprobe": _version("ffprobe", "-version"),
        "nvidia_smi": nvidia_smi or "missing",
        "gpu_pipeline_supported": platform.system() == "Linux" and nvidia_smi is not None,
    }


def check_environment(*, require_gpu: bool = False) -> dict:
    report = environment_report()
    missing = [name for name in ("ffmpeg", "ffprobe") if report[name] == "missing"]
    if missing:
        raise PipelineError(f"Missing local dependencies: {', '.join(missing)}")
    if require_gpu and not report["gpu_pipeline_supported"]:
        raise PipelineError(
            "ViPE and Splatfacto require a Linux host with an NVIDIA CUDA GPU. "
            "This machine can run dataset preparation and artifact validation only."
        )
    return report


def format_report(report: dict) -> str:
    return json.dumps(report, indent=2)
