from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import vipe_demo.report as report_module
import vipe_demo.pipeline as pipeline_module
from vipe_demo.dataset import PipelineError


class ReportVerificationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        shutil.copytree(Path(__file__).resolve().parents[1] / "configs", root / "configs")
        artifacts = root / "artifacts" / "quality"
        splat = artifacts / "splat" / "splat.ply"
        demo = artifacts / "demo.mp4"
        splat.parent.mkdir(parents=True)
        splat.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 42\nend_header\n")
        demo.write_bytes(b"synthetic-video")

        def entry(path: Path) -> dict:
            return {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        payload = {
            "profile": "quality",
            "repository_revision": "abc123",
            "artifacts": {
                "splat": {**entry(splat), "gaussians": 42},
                "demo": {
                    **entry(demo),
                    "codec": "h264",
                    "width": 1600,
                    "height": 1200,
                    "decoded_frames": 12,
                },
            },
        }
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "run-report.json").write_text(json.dumps(payload))

    def test_verifies_copied_artifact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            probe = {
                "stream": {
                    "codec_name": "h264",
                    "width": 1600,
                    "height": 1200,
                    "nb_read_frames": "12",
                }
            }
            with patch.object(report_module, "ROOT", root), patch.object(
                pipeline_module, "ROOT", root
            ), patch.object(report_module, "probe_video", return_value=probe):
                result = report_module.verify_artifacts("quality")
            self.assertEqual(result["gaussians"], 42)
            self.assertEqual(result["demo_frames"], 12)

    def test_rejects_tampered_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            (root / "artifacts" / "quality" / "demo.mp4").write_bytes(b"tampered")
            with patch.object(report_module, "ROOT", root), patch.object(
                pipeline_module, "ROOT", root
            ):
                with self.assertRaises(PipelineError):
                    report_module.verify_artifacts("quality")


if __name__ == "__main__":
    unittest.main()
