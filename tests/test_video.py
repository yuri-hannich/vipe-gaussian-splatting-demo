from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from vipe_demo.dataset import inspect_frames
from vipe_demo.video import prepare_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoIntegrationTests(unittest.TestCase):
    def test_prepares_and_validates_deterministic_h264(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=64x48:rate=1",
                    "-frames:v",
                    "3",
                    "-q:v",
                    "2",
                    str(source / "generated-%04d.jpg"),
                ],
                check=True,
            )
            start = datetime(2025, 1, 11, 17, 11, 48)
            for offset, generated in enumerate(sorted(source.glob("generated-*.jpg"))):
                timestamp = (start + timedelta(seconds=offset)).strftime("%Y%m%d%H%M%S")
                generated.rename(source / f"dji_{timestamp}_{offset + 1:04d}_v.jpg")

            frames = inspect_frames(source, expected_count=3, hash_files=False)
            output = root / "out" / "smoke.mp4"
            manifest = root / "out" / "manifest.json"
            payload = prepare_video(
                frames,
                output,
                manifest,
                width=32,
                fps=1,
                max_frames=3,
            )
            stream = payload["probe"]["stream"]
            self.assertEqual(stream["codec_name"], "h264")
            self.assertEqual(stream["pix_fmt"], "yuv420p")
            self.assertEqual(stream["color_range"], "tv")
            self.assertEqual(stream["nb_read_frames"], "3")
            self.assertEqual((stream["width"], stream["height"]), (32, 24))


if __name__ == "__main__":
    unittest.main()
