from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


FRAME_PATTERN = re.compile(
    r"^(?P<prefix>.+?)_(?P<timestamp>\d{14})_(?P<index>\d{4})_v\.(?:jpg|jpeg)$",
    re.IGNORECASE,
)
SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class PipelineError(RuntimeError):
    """Raised when an input or generated artifact fails validation."""


@dataclass(frozen=True)
class Frame:
    path: Path
    name: str
    index: int
    timestamp: datetime
    width: int
    height: int
    size_bytes: int
    sha256: Optional[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jpeg_dimensions(path: Path) -> Tuple[int, int]:
    """Read JPEG dimensions without an image-library dependency."""
    with path.open("rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise PipelineError(f"Not a JPEG file: {path}")

        while True:
            prefix = stream.read(1)
            if not prefix:
                break
            if prefix != b"\xff":
                continue

            marker_byte = stream.read(1)
            while marker_byte == b"\xff":
                marker_byte = stream.read(1)
            if not marker_byte:
                break
            marker = marker_byte[0]

            if marker in {0x01, *range(0xD0, 0xD9)}:
                continue

            length_bytes = stream.read(2)
            if len(length_bytes) != 2:
                break
            segment_length = int.from_bytes(length_bytes, "big")
            if segment_length < 2:
                raise PipelineError(f"Invalid JPEG segment in: {path}")

            if marker in SOF_MARKERS:
                payload = stream.read(5)
                if len(payload) != 5:
                    break
                height = int.from_bytes(payload[1:3], "big")
                width = int.from_bytes(payload[3:5], "big")
                if width <= 0 or height <= 0:
                    raise PipelineError(f"Invalid JPEG dimensions in: {path}")
                return width, height

            stream.seek(segment_length - 2, 1)

    raise PipelineError(f"Could not find JPEG dimensions in: {path}")


def _candidate_paths(input_dir: Path) -> Iterable[Path]:
    for path in input_dir.iterdir():
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}:
            yield path


def inspect_frames(
    input_dir: Path,
    *,
    expected_count: Optional[int] = None,
    hash_files: bool = True,
) -> Sequence[Frame]:
    if not input_dir.is_dir():
        raise PipelineError(f"Input directory does not exist: {input_dir}")

    parsed = []
    unexpected = []
    for path in _candidate_paths(input_dir):
        match = FRAME_PATTERN.match(path.name)
        if not match:
            unexpected.append(path.name)
            continue
        parsed.append(
            (
                int(match.group("index")),
                datetime.strptime(match.group("timestamp"), "%Y%m%d%H%M%S"),
                path,
            )
        )

    if unexpected:
        preview = ", ".join(sorted(unexpected)[:5])
        raise PipelineError(f"Unexpected JPEG filenames: {preview}")
    if not parsed:
        raise PipelineError(f"No matching JPEG frames found in: {input_dir}")

    parsed.sort(key=lambda item: item[0])
    indices = [item[0] for item in parsed]
    if len(indices) != len(set(indices)):
        raise PipelineError("Duplicate frame indices found")
    expected_indices = list(range(indices[0], indices[-1] + 1))
    if indices != expected_indices:
        missing = sorted(set(expected_indices) - set(indices))
        raise PipelineError(f"Frame indices are not contiguous; missing: {missing}")
    if expected_count is not None and len(parsed) != expected_count:
        raise PipelineError(
            f"Expected {expected_count} frames, found {len(parsed)} in {input_dir}"
        )

    timestamps = [item[1] for item in parsed]
    deltas = [
        int((current - previous).total_seconds())
        for previous, current in zip(timestamps, timestamps[1:])
    ]
    if any(delta != 1 for delta in deltas):
        raise PipelineError(
            "Filename timestamps must advance by exactly one second; "
            f"observed intervals: {sorted(set(deltas))}"
        )

    frames = []
    for index, timestamp, path in parsed:
        width, height = jpeg_dimensions(path)
        frames.append(
            Frame(
                path=path,
                name=path.name,
                index=index,
                timestamp=timestamp,
                width=width,
                height=height,
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path) if hash_files else None,
            )
        )

    dimensions = {(frame.width, frame.height) for frame in frames}
    if len(dimensions) != 1:
        raise PipelineError(f"Frames have inconsistent dimensions: {sorted(dimensions)}")
    return frames


def write_dataset_manifest(
    frames: Sequence[Frame], input_dir: Path, output_path: Path
) -> dict:
    width, height = frames[0].width, frames[0].height
    payload = {
        "schema_version": 1,
        "dataset": input_dir.name,
        "frame_count": len(frames),
        "first_index": frames[0].index,
        "last_index": frames[-1].index,
        "first_timestamp": frames[0].timestamp.isoformat(),
        "last_timestamp": frames[-1].timestamp.isoformat(),
        "capture_fps": 1,
        "width": width,
        "height": height,
        "total_bytes": sum(frame.size_bytes for frame in frames),
        "frames": [
            {
                **asdict(frame),
                "path": frame.name,
                "timestamp": frame.timestamp.isoformat(),
            }
            for frame in frames
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
