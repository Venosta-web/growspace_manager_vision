"""Executable guarantees for the Home Assistant App build inputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
PREPARE_BUILD_INPUTS = ROOT / "scripts" / "prepare-build-inputs.py"
VERIFY_BUILD_INPUTS = ROOT / "scripts" / "verify-build-inputs.py"


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


if __name__ == "__main__":
    unittest.main()
