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
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
VENDORING_WORKFLOW = ROOT / ".github" / "workflows" / "backend-vendoring.yml"
VENDORING_SCRIPT = ROOT / "scripts" / "check-backend-vendoring.sh"
APP_CONFIG = ROOT / "growspace_vision" / "config.yaml"
ARCHITECTURES_SCRIPT = ROOT / "scripts" / "app-architectures.sh"
RETRY_SCRIPT = ROOT / "scripts" / "retry-registry.sh"
TAG_STATE_SCRIPT = ROOT / "scripts" / "registry-tag-state.sh"


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


class VisionReleaseWorkflowTest(unittest.TestCase):
    """The App is only installable if `main` publishes what `config.yaml` names.

    Home Assistant's App store reads `version` off the default branch and pulls
    exactly that image tag. For the whole of V1 that tag was never pushed: CI
    built both architectures on every pull request and threw them away, so the
    store offered an App nobody could install and nothing said so. These
    assertions are about the published contract — which branch publishes, what
    the version comes from, which architectures reach the registry, and that a
    published version is never replaced — not about the shape of the YAML.
    """

    def setUp(self) -> None:
        self.document = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
        self.jobs = self.document["jobs"]

    def _declared_architectures(self) -> list[str]:
        """Ask the mapping the release itself uses, not a copy of it."""
        listed = subprocess.run(
            [str(ARCHITECTURES_SCRIPT)],
            capture_output=True,
            check=True,
            cwd=ROOT,
            text=True,
        )
        return listed.stdout.split()

    def test_a_main_push_publishes_and_can_be_retried_by_hand(self) -> None:
        self.assertEqual(self.document["on"]["push"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", self.document["on"])
        # Two pushes must not race to publish the same tag.
        self.assertEqual(
            self.document["concurrency"],
            {"group": "app-publish", "cancel-in-progress": False},
        )

    def test_every_job_fails_fast_instead_of_inheriting_the_six_hour_default(
        self,
    ) -> None:
        """A hung publish costs minutes, the same bound `quality.yml` carries."""
        for name, job in self.jobs.items():
            with self.subTest(job=name):
                self.assertIn("timeout-minutes", job)
                self.assertLessEqual(job["timeout-minutes"], 60)

    def test_the_release_publishes_exactly_the_architectures_the_app_declares(
        self,
    ) -> None:
        """Adding an arch to `config.yaml` must not leave the release behind.

        Supervisor picks its own architecture out of the published manifest
        list, so an arch the store offers and the release never pushed is an
        install that fails on the user's hardware and nowhere else.
        """
        declared = self._declared_architectures()
        built = [
            entry["architecture"]
            for entry in self.jobs["app-images"]["strategy"]["matrix"]["include"]
        ]
        release = next(
            step
            for step in self.jobs["publish"]["steps"]
            if step.get("name") == "Create Release"
        )
        attached = [
            name.removeprefix("sbom-").removesuffix(".spdx.json")
            for name in release["with"]["files"].split()
            if name.startswith("sbom-")
        ]

        self.assertCountEqual(built, declared)
        self.assertCountEqual(attached, declared)

    def test_the_images_are_built_on_native_runners_by_the_gate_s_own_builder(
        self,
    ) -> None:
        """What a user pulls is what CI proved, built the way CI builds it."""
        job = self.jobs["app-images"]
        commands = "\n".join(step.get("run", "") for step in job["steps"])
        actions = {step.get("uses", "") for step in job["steps"]}

        self.assertEqual(
            job["strategy"]["matrix"]["include"],
            [
                {"architecture": "amd64", "runner": "ubuntu-24.04"},
                {"architecture": "arm64", "runner": "ubuntu-24.04-arm"},
            ],
        )
        self.assertIn(
            "./scripts/build-app-images.sh ${{ matrix.architecture }}", commands
        )
        self.assertFalse(
            any(action.startswith("docker/setup-qemu-action@") for action in actions)
        )

    def test_a_published_version_is_never_republished(self) -> None:
        """A version is immutable, and a docs-only merge needs no bump."""
        published = self._guard_step()

        self.assertIn("exists=true", published["run"])
        self.assertEqual(
            self.jobs["app-images"]["if"], "needs.version.outputs.exists != 'true'"
        )
        # `publish` needs `app-images`, which is skipped, so it is skipped too.
        self.assertIn("app-images", self.jobs["publish"]["needs"])

    def test_the_guard_reads_what_the_registry_said_not_whether_it_exited(
        self,
    ) -> None:
        """`exists=false` must mean an absence, not an unanswered question.

        The step used to run `imagetools inspect` with both streams thrown away
        and treat any non-zero exit as "not published", which makes a 404 and a
        500 the same answer. `PublishedTagGuardTest` proves the classifier tells
        them apart; this is the wiring that puts it in the release's path.
        """
        published = self._guard_step()

        self.assertIn("./scripts/registry-tag-state.sh", published["run"])
        self.assertIn("published", published["run"])
        # Nothing in the step may rescue a non-zero classifier into an answer:
        # GitHub runs `run:` under `bash -e`, so an indeterminate probe fails
        # the job only for as long as its status is left alone.
        self.assertNotIn("|| true", published["run"])
        self.assertNotIn("continue-on-error", published)

    def _guard_step(self) -> dict[str, object]:
        return next(
            step
            for step in self.jobs["version"]["steps"]
            if step.get("id") == "published"
        )

    def test_the_version_comes_from_the_file_the_app_store_reads(self) -> None:
        declared = next(
            step
            for step in self.jobs["version"]["steps"]
            if step.get("id") == "declared"
        )

        self.assertIn("./scripts/app-version.sh", declared["run"])

    def test_the_generic_tag_config_yaml_names_is_the_one_composed(self) -> None:
        """`image:` carries no architecture suffix, so the manifest must not."""
        config = yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))
        manifest = next(
            step
            for step in self.jobs["publish"]["steps"]
            if step.get("id") == "manifest"
        )

        self.assertEqual(config["image"], self.document["env"]["IMAGE"])
        self.assertIn('--tag "${IMAGE}:${VERSION}"', manifest["run"])
        self.assertIn("./scripts/app-architectures.sh", manifest["run"])
        # An installed image is traceable to a release without querying GHCR.
        self.assertIn("digest=$digest", manifest["run"])

    def test_the_release_carries_the_supply_chain_material_and_the_digest(
        self,
    ) -> None:
        release = next(
            step
            for step in self.jobs["publish"]["steps"]
            if step.get("name") == "Create Release"
        )

        self.assertEqual(release["with"]["target_commitish"], "${{ github.sha }}")
        self.assertIs(release["with"]["generate_release_notes"], True)
        self.assertIs(release["with"]["fail_on_unmatched_files"], True)
        self.assertIn(
            "packaging/THIRD_PARTY_NOTICES.md", release["with"]["files"].split()
        )
        self.assertIn("steps.manifest.outputs.digest", release["with"]["body"])

    def test_the_created_tag_is_verified_against_the_commit_that_was_built(
        self,
    ) -> None:
        verification = next(
            step
            for step in self.jobs["publish"]["steps"]
            if step.get("name") == "Verify release tag"
        )

        self.assertIn("git/ref/tags", verification["run"])
        self.assertIn("TARGET_SHA", verification["run"])

    def test_a_publish_job_can_do_no_more_than_publish(self) -> None:
        """Only the job that cuts the release may write to this repository."""
        self.assertNotIn("permissions", self.document)

        self.assertEqual(
            self.jobs["version"]["permissions"],
            {"contents": "read", "packages": "read"},
        )
        self.assertEqual(
            self.jobs["app-images"]["permissions"],
            {"contents": "read", "packages": "write"},
        )
        self.assertEqual(
            self.jobs["publish"]["permissions"],
            {"contents": "write", "packages": "write"},
        )

    def test_the_pull_request_gate_still_only_reads(self) -> None:
        """Publishing is a new workflow, not a new power for `quality.yml`."""
        gate = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

        self.assertEqual(gate["permissions"], {"contents": "read", "packages": "read"})

    def test_every_registry_call_is_retried_rather_than_run_once(self) -> None:
        """One 500 on a manifest PUT threw a whole release away.

        Run 33997608337 pushed every arm64 layer and then lost the release to a
        single transient registry error, because `publish` needs `app-images`
        and a hiccup on one architecture skips the release outright. Every
        registry call in this workflow is load-bearing and ran exactly once, so
        this asks the whole set rather than the one call the incident happened
        to land on.
        """
        for name, job in self.jobs.items():
            for step in job["steps"]:
                for command in self._commands(step.get("run", "")):
                    if "docker push" not in command and "imagetools" not in command:
                        continue
                    with self.subTest(job=name, command=command):
                        self.assertIn("./scripts/retry-registry.sh", command)

    @staticmethod
    def _commands(script: str) -> list[str]:
        """Rejoin the continuations these commands are wrapped across.

        A registry call and the helper in front of it routinely land on
        different physical lines, so reading the script line by line would
        report a wrapped call as unwrapped.
        """
        return " ".join(
            line.strip().removesuffix("\\") + ("\n" if not line.endswith("\\") else "")
            for line in script.splitlines()
        ).split("\n")

    def test_exhausting_the_retries_cannot_outlast_a_job_s_timeout(self) -> None:
        """Attempts are bounded, and the helper says what its bound costs.

        The point of retrying is that a job survives a hiccup, which it does not
        do if the backoff can push it past the bound
        `test_every_job_fails_fast_...` asserts. The helper is asked for its own
        worst case rather than the number being copied here.
        """
        budget = int(self._retry_budget_seconds())

        for name, job in self.jobs.items():
            calls = sum(
                step.get("run", "").count("./scripts/retry-registry.sh")
                # The immutability guard retries through the same helper, one
                # budget deep, so a job that calls it spends the same worst case
                # as one that wraps a registry command itself.
                + step.get("run", "").count("./scripts/registry-tag-state.sh")
                for step in job["steps"]
            )
            with self.subTest(job=name, calls=calls):
                self.assertLess(budget * calls, job["timeout-minutes"] * 60)

    def _retry_budget_seconds(self) -> str:
        asked = subprocess.run(
            [str(RETRY_SCRIPT), "--budget"],
            capture_output=True,
            check=True,
            cwd=ROOT,
            text=True,
        )
        return asked.stdout.strip()

    def test_the_repository_carries_no_build_yaml(self) -> None:
        """The pinned base image, ARGs and labels live in the Dockerfile.

        `build.yaml` is legacy since the April 2026 BuildKit migration, and the
        stock Home Assistant App example workflow still uses it — so the way
        this comes back is a contributor copying that example.
        """
        self.assertFalse((ROOT / "growspace_vision" / "build.yaml").exists())
        self.assertFalse((ROOT / "build.yaml").exists())


class RegistryRetryHelperTest(unittest.TestCase):
    """Drive the helper the release runs, against a command that is not a registry.

    Asserting that the workflow *mentions* a retry would pass just as happily
    against a helper that swallowed a real failure or looped forever. So these
    run `scripts/retry-registry.sh` itself and count what a stub was asked to
    do, the way the architecture assertions ask `app-architectures.sh` instead
    of keeping a copy of the mapping.
    """

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.attempts = Path(self.directory.name) / "attempts"
        self.attempts.write_text("0", encoding="utf-8")

    def _stub(self, *, succeeds_on: int, failure_status: int = 1) -> Path:
        """A command that fails until its `succeeds_on`th call, counting calls.

        `succeeds_on` of 0 never succeeds, which is how the exhausting case
        proves the helper stops rather than that it stopped this time.
        """
        stub = Path(self.directory.name) / "registry-command"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'attempt=$(( $(cat "{self.attempts}") + 1 ))\n'
            f'echo "$attempt" > "{self.attempts}"\n'
            f"if (( attempt == {succeeds_on} )); then\n"
            '  echo "sha256:0123456789abcdef"\n'
            "  exit 0\n"
            "fi\n"
            f"exit {failure_status}\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub

    def _run(
        self, stub: Path, attempts: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        # The real backoff is the helper's default; waiting it out here would
        # only measure `sleep`. The attempt count is left at its default unless
        # a test is about the bound itself.
        environment = {**os.environ, "VISION_REGISTRY_DELAY_SECONDS": "0"}
        if attempts is not None:
            environment["VISION_REGISTRY_ATTEMPTS"] = attempts

        return subprocess.run(
            [str(RETRY_SCRIPT), str(stub)],
            capture_output=True,
            check=False,
            cwd=ROOT,
            env=environment,
            text=True,
        )

    def _calls(self) -> int:
        return int(self.attempts.read_text(encoding="utf-8").strip())

    def test_a_transient_failure_is_retried_and_the_log_says_what_it_cost(
        self,
    ) -> None:
        finished = self._run(self._stub(succeeds_on=2))

        self.assertEqual(finished.returncode, 0)
        self.assertEqual(self._calls(), 2)
        self.assertIn("succeeded on attempt 2", finished.stderr)

    def test_the_wrapped_command_s_output_is_the_helper_s_output(self) -> None:
        """`publish` reads the release digest through this helper."""
        finished = self._run(self._stub(succeeds_on=2))

        self.assertEqual(finished.stdout, "sha256:0123456789abcdef\n")

    def test_a_command_that_never_succeeds_still_fails_the_job(self) -> None:
        """A masked registry error would cut a release for an image nobody has.

        The default attempt count is read back off the run rather than written
        down here, so this stays an assertion that the helper retried and then
        gave up — not a second copy of a number the helper already owns.
        """
        finished = self._run(self._stub(succeeds_on=0, failure_status=7))

        self.assertEqual(finished.returncode, 7)
        self.assertGreater(self._calls(), 1)
        self.assertIn(f"failed on all {self._calls()} attempts", finished.stderr)

    def test_the_attempts_stop_at_the_bound_they_are_given(self) -> None:
        finished = self._run(self._stub(succeeds_on=0), attempts="4")

        self.assertNotEqual(finished.returncode, 0)
        self.assertEqual(self._calls(), 4)


class PublishedTagGuardTest(unittest.TestCase):
    """Drive the immutability guard against a registry that answers on cue.

    `test_a_published_version_is_never_republished` asserts that `exists=true`
    skips the image jobs. What was missing is that the value being wired is
    trustworthy: the probe threw both streams away and read every non-zero exit
    as an absence, so a 404 and the `500 Internal Server Error` this registry
    is known to return were the same answer. A docs-only merge landing during a
    GHCR wobble would have rebuilt a published version from a different commit
    and pushed over bytes users already had, and the run would have looked
    ordinary.

    So these run `scripts/registry-tag-state.sh` itself against a stub, the way
    `RegistryRetryHelperTest` runs the retry helper. The messages the stub
    answers with are the ones a real `docker buildx imagetools inspect` gives.
    """

    ABSENT = "ERROR: ghcr.io/venosta-web/growspace-manager-vision:9.9.9: not found"
    PRESENT = (
        "Name:      ghcr.io/venosta-web/growspace-manager-vision:1.0.1\n"
        "MediaType: application/vnd.docker.distribution.manifest.list.v2+json\n"
        "Digest:    sha256:0123456789abcdef"
    )
    SERVER_ERROR = (
        "ERROR: failed to copy: failed to do request: "
        "received unexpected HTTP status: 500 Internal Server Error"
    )
    UNAUTHORIZED = (
        "ERROR: failed to authorize: failed to fetch oauth token: "
        "unexpected status from GET request to https://ghcr.io/token"
        "?scope=repository%3Avenosta-web%2Fgrowspace-manager-vision%3Apull"
        "&service=ghcr.io: 401 Unauthorized"
    )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.answers = Path(self.directory.name)
        self.calls = self.answers / "calls"
        self.calls.write_text("0", encoding="utf-8")

    def _registry(self, *answers: tuple[int, str]) -> Path:
        """A stubbed registry giving `answers` in order, repeating the last.

        Repeating rather than running out is what makes the exhausting case
        prove the guard stops, instead of proving the stub did.
        """
        for index, (status, message) in enumerate(answers, start=1):
            (self.answers / f"answer-{index}").write_text(
                f"{status}\n{message}\n", encoding="utf-8"
            )

        stub = self.answers / "imagetools-inspect"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'call=$(( $(cat "{self.calls}") + 1 ))\n'
            f'echo "$call" > "{self.calls}"\n'
            f'answer="{self.answers}/answer-$call"\n'
            f'[[ -f "$answer" ]] || answer="{self.answers}/answer-{len(answers)}"\n'
            'status="$(head -1 "$answer")"\n'
            # A success prints a manifest on stdout; a failure explains itself
            # on stderr, which is where the classification has to be read from.
            "if (( status == 0 )); then\n"
            '  tail -n +2 "$answer"\n'
            "else\n"
            '  tail -n +2 "$answer" >&2\n'
            "fi\n"
            'exit "$status"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub

    def _ask(self, *answers: tuple[int, str]) -> subprocess.CompletedProcess[str]:
        stub = self._registry(*answers)
        return subprocess.run(
            [
                str(TAG_STATE_SCRIPT),
                "ghcr.io/venosta-web/growspace-manager-vision:1.0.1",
            ],
            capture_output=True,
            check=False,
            cwd=ROOT,
            env={
                **os.environ,
                "VISION_REGISTRY_INSPECT": str(stub),
                # The retry is the helper's, and it is asserted elsewhere;
                # waiting out its backoff here would only measure `sleep`.
                "VISION_REGISTRY_DELAY_SECONDS": "0",
            },
            text=True,
        )

    def _calls(self) -> int:
        return int(self.calls.read_text(encoding="utf-8").strip())

    def test_a_version_genuinely_absent_is_reported_absent_at_once(self) -> None:
        """The case that must still build — and it costs no backoff to reach.

        A version being released for the first time is absent on purpose, so
        the answer is definitive and asking again would only delay every
        release by the full retry budget.
        """
        asked = self._ask((1, self.ABSENT))

        self.assertEqual(asked.returncode, 0)
        self.assertEqual(asked.stdout, "absent\n")
        self.assertEqual(self._calls(), 1)

    def test_a_published_version_is_reported_published(self) -> None:
        """The no-op case: a docs-only merge to `main` publishes nothing."""
        asked = self._ask((0, self.PRESENT))

        self.assertEqual(asked.returncode, 0)
        self.assertEqual(asked.stdout, "published\n")

    def test_a_registry_error_fails_rather_than_claiming_an_absence(self) -> None:
        """The bug: a 500 read as `exists=false` republishes a live version."""
        asked = self._ask((1, self.SERVER_ERROR))

        self.assertNotEqual(asked.returncode, 0)
        self.assertNotIn("absent", asked.stdout)
        self.assertIn("cannot tell", asked.stderr)
        # The log has to name what it saw, or a red release says nothing about
        # why it could not be evaluated.
        self.assertIn("500 Internal Server Error", asked.stderr)

    def test_a_credential_problem_fails_rather_than_claiming_an_absence(
        self,
    ) -> None:
        """A token that cannot read the package has not proven anything absent."""
        asked = self._ask((1, self.UNAUTHORIZED))

        self.assertNotEqual(asked.returncode, 0)
        self.assertNotIn("absent", asked.stdout)
        self.assertIn("401 Unauthorized", asked.stderr)

    def test_an_indeterminate_answer_is_retried_before_the_guard_gives_up(
        self,
    ) -> None:
        """Failing closed must not turn one blip into a failed release either.

        The same transient error that must never be read as an absence is also
        the one the retry helper exists for, so the guard asks again before it
        concludes it cannot tell.
        """
        asked = self._ask((1, self.SERVER_ERROR), (1, self.ABSENT))

        self.assertEqual(asked.returncode, 0)
        self.assertEqual(asked.stdout, "absent\n")
        self.assertEqual(self._calls(), 2)

    def test_a_registry_that_never_answers_fails_the_version_job(self) -> None:
        """Bounded: it retries, gives up, and fails rather than guessing."""
        asked = self._ask((1, self.SERVER_ERROR))

        self.assertNotEqual(asked.returncode, 0)
        self.assertGreater(self._calls(), 1)
        self.assertIn(f"failed on all {self._calls()} attempts", asked.stderr)


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
