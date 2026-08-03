from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from typing import Optional

from vipe_demo.dataset import PipelineError


def _version(command: str, flag: str = "--version") -> str:
    path = shutil.which(command)
    if path is None:
        return "missing"
    result = subprocess.run([path, flag], capture_output=True, text=True)
    output = result.stdout or result.stderr
    return output.splitlines()[0] if output else path


def _nvidia_query() -> Optional[dict]:
    path = shutil.which("nvidia-smi")
    if path is None:
        return None
    result = subprocess.run(
        [
            path,
            "--query-gpu=name,driver_version,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    values = [value.strip() for value in result.stdout.splitlines()[0].split(",")]
    if len(values) != 3:
        return None
    return {"name": values[0], "driver_version": values[1], "memory_total_mib": values[2]}


def _cuda_runtime_probe() -> dict:
    code = (
        "import json, torch; "
        "ok=torch.cuda.is_available(); "
        "print(json.dumps({'torch': torch.__version__, 'available': ok, "
        "'device': torch.cuda.get_device_name(0) if ok else None})); "
        "raise SystemExit(0 if ok else 2)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return {"available": False, "error": detail[-1] if detail else "CUDA probe failed"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"available": False, "error": "CUDA probe returned invalid JSON"}
    return payload if isinstance(payload, dict) else {"available": False}


def environment_report() -> dict:
    nvidia_smi = shutil.which("nvidia-smi")
    gpu = _nvidia_query() if platform.system() == "Linux" else None
    cuda_runtime = _cuda_runtime_probe() if gpu is not None else None
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "ffmpeg": _version("ffmpeg", "-version"),
        "ffprobe": _version("ffprobe", "-version"),
        "nvidia_smi": nvidia_smi or "missing",
        "gpu": gpu,
        "cuda_runtime": cuda_runtime,
        "gpu_pipeline_supported": bool(
            platform.system() == "Linux"
            and gpu is not None
            and cuda_runtime is not None
            and cuda_runtime.get("available") is True
        ),
    }


def check_environment(*, require_gpu: bool = False) -> dict:
    report = environment_report()
    missing = [name for name in ("ffmpeg", "ffprobe") if report[name] == "missing"]
    if missing:
        raise PipelineError(f"Missing local dependencies: {', '.join(missing)}")
    if require_gpu and not report["gpu_pipeline_supported"]:
        raise PipelineError(
            "ViPE and Splatfacto require a healthy Linux NVIDIA CUDA runtime. "
            f"nvidia-smi={report['gpu']!r}, torch CUDA={report['cuda_runtime']!r}."
        )
    return report


def format_report(report: dict) -> str:
    return json.dumps(report, indent=2)
