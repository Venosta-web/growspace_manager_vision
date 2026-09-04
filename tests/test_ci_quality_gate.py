"""The Vision V1 owner boundaries must be executable in repository CI."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"


class VisionQualityWorkflowTest(unittest.TestCase):
    """Keep CI wired to the same public checks documented for contributors."""

    def setUp(self) -> None:
        self.document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_unit_job_runs_every_repository_quality_boundary(self) -> None:
        steps = self.document["jobs"]["unit"]["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)

        self.assertIn("ruff check", commands)
        self.assertIn("ruff format --check", commands)
        self.assertIn("mypy", commands)
        self.assertIn("unittest discover", commands)

    def test_image_jobs_run_both_architectures_on_native_runners(self) -> None:
        job = self.document["jobs"]["app-images"]
        steps = job["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)
        actions = {step.get("uses", "") for step in steps}
        matrix = job["strategy"]["matrix"]["include"]

        self.assertEqual(
            matrix,
            [
                {"architecture": "amd64", "runner": "ubuntu-24.04"},
                {"architecture": "arm64", "runner": "ubuntu-24.04-arm"},
            ],
        )
        self.assertIn(
            "./scripts/build-app-images.sh ${{ matrix.architecture }}", commands
        )
        self.assertTrue(
            any(action.startswith("docker/setup-buildx-action@") for action in actions)
        )
        self.assertFalse(
            any(action.startswith("docker/setup-qemu-action@") for action in actions)
        )

    def test_build_and_runtime_smoke_both_disable_outbound_networking(self) -> None:
        builder = (ROOT / "scripts" / "build-app-images.sh").read_text(encoding="utf-8")
        smoke = (ROOT / "scripts" / "smoke-container.sh").read_text(encoding="utf-8")

        self.assertIn("--network none", builder)
        self.assertGreaterEqual(smoke.count("--network none"), 2)


if __name__ == "__main__":
    unittest.main()
