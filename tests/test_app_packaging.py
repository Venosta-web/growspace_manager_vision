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
