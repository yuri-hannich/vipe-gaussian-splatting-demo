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
        metrics = artifacts / "metrics.json"
        demo = artifacts / "demo.mp4"
        splat.parent.mkdir(parents=True)
        header = ["ply", "format binary_little_endian 1.0", "element vertex 42"]
        header.extend(f"property float {name}" for name in report_module.PLY_PROPERTIES)
        header.append("end_header")
        splat.write_bytes(
            ("\n".join(header) + "\n").encode()
            + bytes(42 * len(report_module.PLY_PROPERTIES) * 4)
        )
        evaluation = {
            "experiment_name": "zavod70",
            "method_name": "splatfacto",
            "checkpoint": "/workspace/step-000029999.ckpt",
            "results": {
                "psnr": 16.8,
                "ssim": 0.39,
                "lpips": 0.42,
                "num_rays_per_sec": 1_600_000.0,
                "fps": 0.85,
            },
        }
        metrics.write_text(json.dumps(evaluation))
        demo.write_bytes(b"synthetic-video")

        def entry(path: Path) -> dict:
            return {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        payload = {
            "schema_version": 2,
            "profile": "quality",
            "repository_revision": "abc123",
            "evaluation": evaluation,
            "stages": {
                name: {"status": "complete"} for name in report_module.PRE_REPORT_STAGES
            },
            "artifacts": {
                "splat": {
                    **entry(splat),
                    "gaussians": 42,
                    "properties": len(report_module.PLY_PROPERTIES),
                    "format": "binary_little_endian",
                },
                "metrics": entry(metrics),
                "demo": {
                    **entry(demo),
                    "codec": "h264",
                    "width": 1600,
                    "height": 1200,
                    "pixel_format": "yuv420p",
                    "color_range": "tv",
                    "fps": 24.0,
                    "decoded_frames": 218,
                    "duration_seconds": 218 / 24,
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
                    "pix_fmt": "yuv420p",
                    "color_range": "tv",
                    "avg_frame_rate": "24/1",
                    "nb_read_frames": "218",
                },
                "format": {"duration": str(218 / 24)},
            }
            with patch.object(report_module, "ROOT", root), patch.object(
                pipeline_module, "ROOT", root
            ), patch.object(report_module, "probe_video", return_value=probe):
                result = report_module.verify_artifacts("quality")
            self.assertEqual(result["gaussians"], 42)
            self.assertEqual(result["demo_frames"], 218)

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

    def test_rejects_truncated_ply_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            splat = root / "artifacts" / "quality" / "splat" / "splat.ply"
            splat.write_bytes(splat.read_bytes()[:-4])
            with self.assertRaisesRegex(PipelineError, "payload length mismatch"):
                report_module._ply_metadata(splat)

    def test_rejects_non_finite_metrics(self) -> None:
        metrics = {
            "experiment_name": "zavod70",
            "method_name": "splatfacto",
            "checkpoint": "step.ckpt",
            "results": {
                "psnr": float("nan"),
                "ssim": 0.4,
                "lpips": 0.4,
                "num_rays_per_sec": 1.0,
                "fps": 1.0,
            },
        }
        with self.assertRaisesRegex(PipelineError, "not finite"):
            report_module._validate_metrics(metrics)

    def test_rejects_incomplete_stage_provenance(self) -> None:
        records = {
            name: {"status": "complete"} for name in report_module.PRE_REPORT_STAGES
        }
        records.pop("render")
        with self.assertRaisesRegex(PipelineError, "Missing pre-report stage records"):
            report_module._validate_stage_records(records)


if __name__ == "__main__":
    unittest.main()
