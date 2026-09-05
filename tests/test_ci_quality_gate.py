"""The Vision V1 owner boundaries must be executable in repository CI."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "quality.yml"
VENDORING_WORKFLOW = ROOT / ".github" / "workflows" / "backend-vendoring.yml"
VENDORING_SCRIPT = ROOT / "scripts" / "check-backend-vendoring.sh"


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

    def test_every_job_fails_fast_instead_of_inheriting_the_six_hour_default(
        self,
    ) -> None:
        """A hung job must cost minutes of a private repository, not GitHub's default.

        `app-images` has been bounded since it was written; `unit` was not, so when
        the analysis deadline deadlocked one request the job that noticed it ran for
        the whole 360-minute default instead, twice, and `main` carried no completed
        unit gate at all. The bound is asserted for every job because the one that
        went unbounded was the one nobody thought could hang.
        """

        for name, job in self.document["jobs"].items():
            with self.subTest(job=name):
                self.assertIn("timeout-minutes", job)
                self.assertLessEqual(job["timeout-minutes"], 60)

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


class BackendVendoringWorkflowTest(unittest.TestCase):
    """The vendoring gate is documented as CI, so CI has to be where it runs.

    `docs/CONTRACT.md` in the hub claimed for months that Growspace Manager
    checked its vendored fixtures against this repository. Nothing did: the
    backend is public and this repository is private, so the comparison cannot
    run there without a credential, and it ran only from a workspace command
    that needs both checkouts on one disk.
    """

    def setUp(self) -> None:
        self.document = yaml.safe_load(VENDORING_WORKFLOW.read_text(encoding="utf-8"))

    def test_drift_is_noticed_from_either_side_of_the_boundary(self) -> None:
        """A change here trips it; the weekly run is what catches a backend edit."""
        triggers = self.document["on"]

        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIn("pull_request", triggers)
        self.assertIn("schedule", triggers)
        self.assertIn("workflow_dispatch", triggers)

    def test_the_job_runs_the_comparison_and_fails_fast(self) -> None:
        job = self.document["jobs"]["vendored-fixtures"]
        commands = "\n".join(step.get("run", "") for step in job["steps"])

        self.assertIn("./scripts/check-backend-vendoring.sh", commands)
        self.assertIn("timeout-minutes", job)
        self.assertLessEqual(job["timeout-minutes"], 60)

    def test_reading_the_public_backend_needs_no_credential(self) -> None:
        """The gate must not acquire a secret it would then have to be trusted with."""
        self.assertNotIn("secrets.", VENDORING_WORKFLOW.read_text(encoding="utf-8"))

    def test_the_check_reports_the_comparison_rather_than_its_own_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            backend = Path(directory) / "backend"
            helper = backend / "tests" / "utils" / "vision_contract_fixtures.py"
            helper.parent.mkdir(parents=True)

            helper.write_text("raise SystemExit(0)\n", encoding="utf-8")
            self.assertEqual(self._run(backend).returncode, 0)

            helper.write_text("raise SystemExit(1)\n", encoding="utf-8")
            self.assertEqual(self._run(backend).returncode, 1)

            helper.unlink()
            missing = self._run(backend)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("vision_contract_fixtures.py is missing", missing.stderr)

    def _run(self, backend: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(VENDORING_SCRIPT)],
            capture_output=True,
            check=False,
            cwd=ROOT,
            env={**os.environ, "GROWSPACE_BACKEND_ROOT": str(backend)},
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
