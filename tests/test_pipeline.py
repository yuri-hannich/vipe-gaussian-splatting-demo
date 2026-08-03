from __future__ import annotations

import unittest

from vipe_demo.config import load_profile
from vipe_demo.pipeline import ROOT, build_stages, pipeline_environment


class PipelineTests(unittest.TestCase):
    def test_quality_profile_has_complete_stage_contract(self) -> None:
        profile, profiles, versions = load_profile(ROOT, "quality")
        stages = build_stages(profile, profiles)
        self.assertEqual(stages[0].name, "bootstrap")
        self.assertEqual(stages[-1].name, "report")
        self.assertEqual(len({stage.name for stage in stages}), len(stages))
        self.assertEqual(profile.train_steps, 30000)

        known = set()
        for stage in stages:
            self.assertTrue(set(stage.dependencies).issubset(known))
            known.add(stage.name)

        environment = pipeline_environment(profile, profiles, versions)
        self.assertEqual(environment["VIPE_COMMIT"], versions["VIPE_COMMIT"])
        self.assertNotIn("RUNPOD_API_KEY", environment)

    def test_smoke_profile_uses_bounded_workload(self) -> None:
        profile, profiles, _ = load_profile(ROOT, "smoke")
        stages = build_stages(profile, profiles)
        prepare = next(stage for stage in stages if stage.name == "prepare")
        inspect = next(stage for stage in stages if stage.name == "inspect")
        self.assertIn("--max-frames", prepare.command)
        self.assertIn("--minimum-count", inspect.command)
        self.assertEqual(profile.frames, 24)
        self.assertEqual(profile.train_steps, 2000)


if __name__ == "__main__":
    unittest.main()
