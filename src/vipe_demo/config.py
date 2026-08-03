from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from vipe_demo.dataset import PipelineError


def load_env_file(path: Path) -> Dict[str, str]:
    """Load the intentionally simple KEY=VALUE project configuration format."""
    values: Dict[str, str] = {}
    if not path.is_file():
        raise PipelineError(f"Configuration file does not exist: {path}")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise PipelineError(f"Invalid configuration at {path}:{line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise PipelineError(f"Invalid configuration at {path}:{line_number}")
        values[key] = value
    return values


def required(values: Dict[str, str], key: str) -> str:
    try:
        return values[key]
    except KeyError as error:
        raise PipelineError(f"Missing required configuration value: {key}") from error


def positive_int(values: Dict[str, str], key: str) -> int:
    raw_value = required(values, key)
    try:
        value = int(raw_value)
    except ValueError as error:
        raise PipelineError(f"{key} must be an integer, got: {raw_value}") from error
    if value <= 0:
        raise PipelineError(f"{key} must be positive, got: {value}")
    return value


@dataclass(frozen=True)
class Profile:
    name: str
    frames: int
    width: int
    slam_buffer: int
    train_steps: int
    eval_interval: int


def load_profile(root: Path, name: str) -> tuple[Profile, Dict[str, str], Dict[str, str]]:
    profiles = load_env_file(root / "configs" / "profiles.env")
    versions = load_env_file(root / "configs" / "versions.env")
    prefix = name.upper()
    if name not in {"smoke", "quality"}:
        raise PipelineError(f"Unknown profile '{name}'; expected smoke or quality")
    profile = Profile(
        name=name,
        frames=positive_int(profiles, f"{prefix}_FRAMES"),
        width=positive_int(profiles, f"{prefix}_WIDTH"),
        slam_buffer=positive_int(profiles, f"{prefix}_SLAM_BUFFER"),
        train_steps=positive_int(profiles, f"{prefix}_TRAIN_STEPS"),
        eval_interval=positive_int(profiles, f"{prefix}_EVAL_INTERVAL"),
    )
    return profile, profiles, versions
