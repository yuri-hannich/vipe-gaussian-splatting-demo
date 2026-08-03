from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vipe_demo.config import load_env_file
from vipe_demo.dataset import PipelineError


class ConfigTests(unittest.TestCase):
    def test_dataset_inventory_is_complete_and_ordered(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rows = [
            line.split("\t")
            for line in (root / "configs" / "dataset-files.tsv").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(len(rows), 126)
        self.assertEqual(len({row[0] for row in rows}), 126)
        self.assertEqual(rows[0][1], "dji_20250111171148_0001_v.jpg")
        self.assertEqual(rows[-1][1], "dji_20250111171353_0126_v.jpg")
        self.assertEqual(sum(int(row[2]) for row in rows), 1_074_302_976)

    def test_loads_comments_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.env"
            path.write_text("# comment\nONE=1\nURL=https://example.com/a?b=c\n")
            self.assertEqual(
                load_env_file(path), {"ONE": "1", "URL": "https://example.com/a?b=c"}
            )

    def test_rejects_invalid_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.env"
            path.write_text("NOT_AN_ASSIGNMENT\n")
            with self.assertRaises(PipelineError):
                load_env_file(path)


if __name__ == "__main__":
    unittest.main()
