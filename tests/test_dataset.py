from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from vipe_demo.dataset import PipelineError, inspect_frames, jpeg_dimensions


def minimal_jpeg(width: int, height: int) -> bytes:
    components = b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    sof_payload = b"\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big")
    sof_payload += b"\x03" + components
    segment = b"\xff\xc0" + (len(sof_payload) + 2).to_bytes(2, "big") + sof_payload
    return b"\xff\xd8" + segment + b"\xff\xd9"


class DatasetTests(unittest.TestCase):
    def test_reads_jpeg_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "frame.jpg"
            path.write_bytes(minimal_jpeg(4000, 3000))
            self.assertEqual(jpeg_dimensions(path), (4000, 3000))

    def test_inspects_contiguous_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            start = datetime(2025, 1, 11, 17, 11, 48)
            for offset in range(3):
                timestamp = (start + timedelta(seconds=offset)).strftime("%Y%m%d%H%M%S")
                name = f"dji_{timestamp}_{offset + 1:04d}_v.jpg"
                (root / name).write_bytes(minimal_jpeg(4000, 3000))
            frames = inspect_frames(root, expected_count=3, hash_files=False)
            self.assertEqual([frame.index for frame in frames], [1, 2, 3])

    def test_rejects_missing_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "dji_20250111171148_0001_v.jpg").write_bytes(minimal_jpeg(4, 2))
            (root / "dji_20250111171150_0003_v.jpg").write_bytes(minimal_jpeg(4, 2))
            with self.assertRaisesRegex(PipelineError, "not contiguous"):
                inspect_frames(root, hash_files=False)


if __name__ == "__main__":
    unittest.main()
