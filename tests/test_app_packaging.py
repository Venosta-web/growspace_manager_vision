"""Executable guarantees for the Home Assistant App build inputs and startup."""

from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import yaml

ROOT = Path(__file__).parents[1]
PREPARE_BUILD_INPUTS = ROOT / "scripts" / "prepare-build-inputs.py"
VERIFY_BUILD_INPUTS = ROOT / "scripts" / "verify-build-inputs.py"
APP_CONFIG = ROOT / "growspace_vision" / "config.yaml"
PROVISION = ROOT / "growspace_vision" / "provision.py"
APP_VERSION_SCRIPT = ROOT / "scripts" / "app-version.sh"
PYPROJECT = ROOT / "pyproject.toml"
DOCKERFILE = ROOT / "Dockerfile"
BUILD_IMAGES = ROOT / "scripts" / "build-app-images.sh"
SMOKE_CONTAINER = ROOT / "scripts" / "smoke-container.sh"
GENERATE_SBOM = ROOT / "scripts" / "generate-sbom.py"
MODEL_MANIFEST = ROOT / "src" / "growspace_vision" / "model_manifest.json"


def _load_provision() -> ModuleType:
    """Import the App startup helper, which ships beside `config.yaml`.

    It is loaded by path rather than imported: the App folder shares its name
    with the service package, and only one of the two belongs on `sys.path`.
    """

    spec = importlib.util.spec_from_file_location("app_provision", PROVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because `dataclasses` resolves annotations
    # through `sys.modules` while the class body is still running.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


provision = _load_provision()


def run_provision(
    *arguments: str, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the startup helper the way `run.sh` does, in a clean environment."""

    inherited = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "TMPDIR")
        if name in os.environ
    }
    return subprocess.run(
        [sys.executable, str(PROVISION), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=inherited | (environment or {}),
    )


class _DiscoveryRecorder(http.server.BaseHTTPRequestHandler):
    """A stand-in Supervisor that records one discovery push."""

    received: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).received.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body": body,
            }
        )
        payload = json.dumps({"result": "ok", "data": {"uuid": "discovery-uuid"}})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        """Stay quiet; the test asserts on what was received, not on a log."""


def _unserved_api() -> str:
    """Return a loopback URL nothing is listening on, so the push is refused."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


@contextmanager
def supervisor_stub() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Serve a Supervisor discovery endpoint on loopback for one test."""

    _DiscoveryRecorder.received = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _DiscoveryRecorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _DiscoveryRecorder.received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class BuildInputVerificationTest(unittest.TestCase):
    """The image builder accepts only the byte streams named by its manifest."""

    def test_exact_build_inputs_pass_and_tampered_bytes_fail_closed(self) -> None:
        expected = b"locked build input\n"
        with tempfile.TemporaryDirectory() as directory:
            build_root = Path(directory)
            artifact = build_root / "artifacts" / "input.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(expected)
            manifest = build_root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "artifacts": [
                            {
                                "path": "artifacts/input.bin",
                                "size_bytes": len(expected),
                                "sha256": hashlib.sha256(expected).hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            accepted = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_BUILD_INPUTS),
                    "--manifest",
                    str(manifest),
                    "--root",
                    str(build_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            artifact.write_bytes(b"tampered build input")
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_BUILD_INPUTS),
                    "--manifest",
                    str(manifest),
                    "--root",
                    str(build_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("artifacts/input.bin", rejected.stderr)

    def test_an_unlisted_build_input_fails_closed(self) -> None:
        expected = b"locked build input\n"
        with tempfile.TemporaryDirectory() as directory:
            build_root = Path(directory)
            artifact = build_root / "artifacts" / "input.bin"
            artifact.parent.mkdir()
            artifact.write_bytes(expected)
            (build_root / "artifacts" / "unlisted.bin").write_bytes(b"not locked")
            manifest = build_root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "artifacts": [
                            {
                                "path": "artifacts/input.bin",
                                "size_bytes": len(expected),
                                "sha256": hashlib.sha256(expected).hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            rejected = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY_BUILD_INPUTS),
                    "--manifest",
                    str(manifest),
                    "--root",
                    str(build_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("unlisted", rejected.stderr)

    def test_preparation_downloads_and_records_only_locked_bytes(self) -> None:
        expected = b"prepared byte stream\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.bin"
            source.write_bytes(expected)
            lock = root / "test.lock"
            lock.write_text(
                "# sha256 size_bytes destination url\n"
                f"{hashlib.sha256(expected).hexdigest()} {len(expected)} "
                f"model/input.bin {source.as_uri()}\n",
                encoding="utf-8",
            )
            output = root / "prepared"

            prepared = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE_BUILD_INPUTS),
                    "--lock",
                    str(lock),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            self.assertEqual((output / "model" / "input.bin").read_bytes(), expected)
            manifest = json.loads(
                (output / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest,
                {
                    "schema_version": 1,
                    "artifacts": [
                        {
                            "path": "model/input.bin",
                            "size_bytes": len(expected),
                            "sha256": hashlib.sha256(expected).hexdigest(),
                        }
                    ],
                },
            )


class AppManifestTest(unittest.TestCase):
    """`config.yaml` states the endpoint hand-over the integration relies on."""

    def setUp(self) -> None:
        self.config: dict[str, Any] = yaml.safe_load(
            APP_CONFIG.read_text(encoding="utf-8")
        )

    def test_the_declared_discovery_service_is_the_one_the_app_announces(self) -> None:
        """Supervisor rejects a push for a service the App did not declare."""

        self.assertEqual(self.config["discovery"], [provision.DISCOVERY_SERVICE])

    def test_the_published_port_is_declared_but_never_mapped_to_the_host(self) -> None:
        """The endpoint reaches Home Assistant only over the internal network."""

        self.assertEqual(self.config["ports"], {"8099/tcp": None})
        self.assertEqual(provision.SERVICE_PORT, 8099)

    def test_the_access_token_option_is_an_optional_override(self) -> None:
        """A per-install token is the norm, so the option must not be required."""

        self.assertEqual(self.config["schema"]["access_token"], "password?")
        self.assertNotIn("access_token", self.config["options"])


class AppVersionTest(unittest.TestCase):
    """The App version is declared once, and the model version is not it.

    Home Assistant's App store reads `version` from `config.yaml` and pulls
    exactly that image tag, so a version that is partly bumped is an install
    that fails or a `/info` that lies. It used to be spelled in seven places.
    """

    def setUp(self) -> None:
        self.declared = str(
            yaml.safe_load(APP_CONFIG.read_text(encoding="utf-8"))["version"]
        )

    def test_the_declared_version_is_what_every_consumer_resolves(self) -> None:
        printed = subprocess.run(
            [str(APP_VERSION_SCRIPT)],
            capture_output=True,
            check=True,
            text=True,
        )
        self.assertEqual(printed.stdout.strip(), self.declared)

        # Static because the build backend needs it so; checked because nothing
        # else would notice it standing still.
        pyproject = PYPROJECT.read_text(encoding="utf-8")
        self.assertIn(f'\nversion = "{self.declared}"\n', pyproject)

    def test_the_service_reports_the_version_the_store_installed(self) -> None:
        """`/info` answers a support question, so its version must be the real one."""
        from growspace_vision.settings import DEFAULT_SERVICE_VERSION, ServiceSettings

        self.assertEqual(DEFAULT_SERVICE_VERSION, self.declared)
        self.assertEqual(
            ServiceSettings(bearer_token="token").service_version, self.declared
        )
        # The image passes the declared version in explicitly; this is what a
        # run outside the image falls back to.
        self.assertIn(
            'GROWSPACE_VISION_SERVICE_VERSION="${APP_VERSION}"',
            DOCKERFILE.read_text(encoding="utf-8"),
        )

    def test_the_build_the_smoke_and_the_sbom_derive_the_version(self) -> None:
        """A bump is one edit, so none of them may carry a number of its own."""
        builder = BUILD_IMAGES.read_text(encoding="utf-8")
        smoke = SMOKE_CONTAINER.read_text(encoding="utf-8")
        sbom = GENERATE_SBOM.read_text(encoding="utf-8")

        self.assertIn("scripts/app-version.sh", builder)
        self.assertIn('--build-arg "APP_VERSION=${app_version}"', builder)
        self.assertNotIn(self.declared, builder)

        # The smoke keeps proving version agreement after the first bump, so it
        # is handed the version rather than asserting a literal.
        self.assertIn("expected_version", smoke)
        self.assertIn(".service_version == $version", smoke)

        self.assertIn("--version", sbom)
        self.assertNotIn(self.declared, sbom)

    def test_the_model_version_does_not_move_with_the_app_version(self) -> None:
        """It names the embeddings, not the release.

        Every stored Baseline Bucket and Framing Epoch in a user's evidence
        store is keyed to this number. The two are textually identical today,
        so a find-and-replace bump of the App version silently re-labels a
        comparison history nobody can rebuild — which fails no test and shows
        up as a Vision Checkup that has forgotten what the tent looked like.
        """
        from growspace_vision.analysis import UnavailableAnalyzer
        from growspace_vision.settings import ServiceSettings

        model_version = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))[
            "model_version"
        ]
        self.assertEqual(UnavailableAnalyzer.model_version, model_version)

        # The App version is settable per install; the model identity is not.
        released = ServiceSettings(bearer_token="token", service_version="9.9.9")
        self.assertEqual(released.service_version, "9.9.9")
        self.assertEqual(UnavailableAnalyzer.model_version, model_version)

        # And the two are declared apart: nothing that resolves the App version
        # reads the model manifest, and the model manifest names no service.
        for path in (APP_CONFIG, APP_VERSION_SCRIPT, PYPROJECT):
            with self.subTest(path=path.name):
                self.assertNotIn("model_version", path.read_text(encoding="utf-8"))
        self.assertNotIn("service_version", MODEL_MANIFEST.read_text(encoding="utf-8"))


class CredentialProvisioningTest(unittest.TestCase):
    """The App arrives at exactly one token, and keeps it."""

    def test_a_generated_token_is_persisted_and_reused_on_the_next_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            first = run_provision("--data-dir", str(data_dir))
            self.assertEqual(first.returncode, 0, first.stderr)
            token = first.stdout.strip()
            self.assertGreaterEqual(len(token), 32)
            self.assertIn("origin: generated", first.stderr)

            stored = data_dir / provision.TOKEN_FILE_NAME
            self.assertEqual(stored.read_text(encoding="utf-8").strip(), token)
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)

            second = run_provision("--data-dir", str(data_dir))
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(second.stdout.strip(), token)
            self.assertIn("origin: stored", second.stderr)

    def test_the_secret_never_reaches_stdout_alongside_anything_else(self) -> None:
        """`run.sh` reads stdout as the token, so stdout carries only that."""

        with tempfile.TemporaryDirectory() as directory:
            result = run_provision("--data-dir", directory)
            self.assertEqual(result.stdout.count("\n"), 1)
            self.assertNotIn(result.stdout.strip(), result.stderr)

    def test_an_environment_token_wins_and_is_never_written_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            result = run_provision(
                "--data-dir",
                str(data_dir),
                environment={"GROWSPACE_VISION_TOKEN": "supplied-by-the-container"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "supplied-by-the-container")
            self.assertIn("origin: environment", result.stderr)
            self.assertEqual(list(data_dir.iterdir()), [])

    def test_the_app_option_overrides_an_already_generated_token(self) -> None:
        """An explicit token the grower can read beats one only the App knows."""

        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            generated = run_provision("--data-dir", str(data_dir)).stdout.strip()
            options = data_dir / "options.json"
            options.write_text(
                json.dumps({"access_token": "chosen-by-the-grower"}), encoding="utf-8"
            )

            result = run_provision("--data-dir", str(data_dir))

            self.assertEqual(result.stdout.strip(), "chosen-by-the-grower")
            self.assertIn("origin: option", result.stderr)
            self.assertNotEqual(result.stdout.strip(), generated)

    def test_unreadable_options_are_reported_and_the_app_still_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            (data_dir / "options.json").write_text("{not json", encoding="utf-8")

            result = run_provision("--data-dir", str(data_dir))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip())
            self.assertIn("not readable JSON", result.stderr)


class DiscoveryPublicationTest(unittest.TestCase):
    """What the App hands Supervisor is what the integration reads back."""

    def test_the_payload_carries_the_host_the_port_and_the_token(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            supervisor_stub() as (
                api,
                received,
            ),
        ):
            result = run_provision(
                "--data-dir",
                directory,
                "--supervisor-api",
                api,
                "--host",
                "abc12345-growspace-vision",
                environment={"SUPERVISOR_TOKEN": "supervisor-secret"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(received), 1)
            push = received[0]
            self.assertEqual(push["path"], "/discovery")
            self.assertEqual(push["authorization"], "Bearer supervisor-secret")
            self.assertEqual(push["content_type"], "application/json")
            self.assertEqual(
                push["body"],
                {
                    "service": "growspace_manager",
                    "config": {
                        "host": "abc12345-growspace-vision",
                        "port": 8099,
                        "token": result.stdout.strip(),
                    },
                },
            )
            # The integration rejects a quoted port as an incomplete payload.
            self.assertIsInstance(push["body"]["config"]["port"], int)
            self.assertIn("discovery message discovery-uuid", result.stderr)

    def test_nothing_is_published_when_there_is_no_supervisor(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            supervisor_stub() as (
                api,
                received,
            ),
        ):
            result = run_provision("--data-dir", directory, "--supervisor-api", api)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(received, [])
            self.assertIn("No Supervisor to announce to", result.stderr)

    def test_a_refused_push_is_reported_and_the_service_still_starts(self) -> None:
        """Vision reports `not_configured`; a restart loop would fix nothing."""

        with tempfile.TemporaryDirectory() as directory:
            result = run_provision(
                "--data-dir",
                directory,
                "--supervisor-api",
                _unserved_api(),
                environment={"SUPERVISOR_TOKEN": "supervisor-secret"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.strip())
            self.assertIn("Could not publish the endpoint to Supervisor", result.stderr)


if __name__ == "__main__":
    unittest.main()
