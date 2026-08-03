from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vipe_demo.colmap import validate_colmap
from vipe_demo.dataset import PipelineError


class ColmapTests(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        (root / "images").mkdir()
        (root / "images" / "frame_000000.jpg").write_bytes(b"frame")
        (root / "images" / "frame_000001.jpg").write_bytes(b"frame")
        (root / "cameras.txt").write_text("1 PINHOLE 1280 960 800 800 640 480\n")
        (root / "images.txt").write_text(
            "1 1 0 0 0 0 0 0 1 images/frame_000000.jpg\n\n"
            "2 1 0 0 0 1 0 0 1 images/frame_000001.jpg\n\n"
        )
        (root / "points3D.txt").write_text("1 0 0 1 255 128 0 0\n")

    def test_validates_vipe_text_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            report = validate_colmap(root, min_images=2)
            self.assertEqual(report["registered_images"], 2)
            self.assertEqual(report["points3D"], 1)
            self.assertTrue((root / "validation.json").is_file())

    def test_rejects_identical_camera_translations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            images = (root / "images.txt").read_text().replace(
                "2 1 0 0 0 1 0 0", "2 1 0 0 0 0 0 0"
            )
            (root / "images.txt").write_text(images)
            with self.assertRaisesRegex(PipelineError, "translations are identical"):
                validate_colmap(root, min_images=2)


if __name__ == "__main__":
    unittest.main()
