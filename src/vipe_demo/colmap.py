from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable, List

from vipe_demo.dataset import PipelineError


def _data_lines(path: Path) -> List[str]:
    if not path.is_file():
        raise PipelineError(f"Missing COLMAP file: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _finite(values: Iterable[str], *, context: str) -> List[float]:
    try:
        parsed = [float(value) for value in values]
    except ValueError as error:
        raise PipelineError(f"Non-numeric value in {context}") from error
    if not all(math.isfinite(value) for value in parsed):
        raise PipelineError(f"Non-finite value in {context}")
    return parsed


def validate_colmap(root: Path, *, min_images: int) -> dict:
    """Validate the exact text layout emitted by ViPE's official converter."""
    camera_lines = _data_lines(root / "cameras.txt")
    if len(camera_lines) != 1:
        raise PipelineError(f"Expected exactly one camera, found {len(camera_lines)}")
    camera = camera_lines[0].split()
    if len(camera) != 8 or camera[1] != "PINHOLE":
        raise PipelineError("Expected one COLMAP PINHOLE camera with four intrinsics")
    width, height = int(camera[2]), int(camera[3])
    fx, fy, cx, cy = _finite(camera[4:8], context="cameras.txt")
    if width <= 0 or height <= 0 or fx <= 0 or fy <= 0:
        raise PipelineError("Invalid camera dimensions or focal length")
    if not (0 <= cx <= width and 0 <= cy <= height):
        raise PipelineError("Camera principal point lies outside the image")

    image_lines = _data_lines(root / "images.txt")
    if len(image_lines) < min_images:
        raise PipelineError(
            f"Expected at least {min_images} registered images, found {len(image_lines)}"
        )
    image_ids = set()
    image_names = set()
    translations = []
    for line in image_lines:
        fields = line.split()
        if len(fields) != 10:
            raise PipelineError("Unexpected non-empty POINTS2D data in images.txt")
        image_id = int(fields[0])
        quaternion = _finite(fields[1:5], context=f"image {image_id} quaternion")
        translation = _finite(fields[5:8], context=f"image {image_id} translation")
        if abs(math.sqrt(sum(value * value for value in quaternion)) - 1.0) > 1e-3:
            raise PipelineError(f"Image {image_id} quaternion is not normalized")
        if fields[8] != camera[0]:
            raise PipelineError(f"Image {image_id} references an unknown camera")
        image_path = root / fields[9]
        if not image_path.is_file():
            raise PipelineError(f"Registered image does not exist: {image_path}")
        if image_id in image_ids or fields[9] in image_names:
            raise PipelineError("Duplicate image ID or image path in images.txt")
        image_ids.add(image_id)
        image_names.add(fields[9])
        translations.append(translation)
    if len({tuple(round(value, 6) for value in row) for row in translations}) < 2:
        raise PipelineError("All registered camera translations are identical")

    point_lines = _data_lines(root / "points3D.txt")
    if not point_lines:
        raise PipelineError("COLMAP initialization contains no 3D points")
    point_ids = set()
    for line in point_lines:
        fields = line.split()
        if len(fields) < 8:
            raise PipelineError("Malformed point in points3D.txt")
        point_id = int(fields[0])
        _finite(fields[1:4], context=f"point {point_id} position")
        colors = [int(value) for value in fields[4:7]]
        if any(value < 0 or value > 255 for value in colors):
            raise PipelineError(f"Point {point_id} has an invalid color")
        if point_id in point_ids:
            raise PipelineError(f"Duplicate point ID: {point_id}")
        point_ids.add(point_id)

    report = {
        "schema_version": 1,
        "camera_model": "PINHOLE",
        "width": width,
        "height": height,
        "registered_images": len(image_lines),
        "points3D": len(point_lines),
        "intrinsics": {"fx": fx, "fy": fy, "cx": cx, "cy": cy},
    }
    report_path = root / "validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
