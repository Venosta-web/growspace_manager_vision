#!/usr/bin/env python3
"""Materialize one architecture's hash-locked, offline image context."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class LockedArtifact:
    sha256: str
    size_bytes: int
    destination: Path
    url: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def parse_lock(path: Path) -> list[LockedArtifact]:
    artifacts: list[LockedArtifact] = []
    destinations: set[Path] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=3)
        if len(fields) != 4:
            raise ValueError(f"{path}:{line_number}: expected four fields")
        sha256, size_text, destination_text, url = fields
        if len(sha256) != 64 or any(
            value not in "0123456789abcdef" for value in sha256
        ):
            raise ValueError(f"{path}:{line_number}: invalid sha256")
        size_bytes = int(size_text)
        if size_bytes < 0:
            raise ValueError(f"{path}:{line_number}: negative size")
        destination = Path(destination_text)
        if destination.is_absolute() or ".." in destination.parts:
            raise ValueError(f"{path}:{line_number}: unsafe destination")
        if destination in destinations:
            raise ValueError(f"{path}:{line_number}: duplicate destination")
        if urlparse(url).scheme not in {"file", "http", "https"}:
            raise ValueError(f"{path}:{line_number}: unsupported URL scheme")
        destinations.add(destination)
        artifacts.append(LockedArtifact(sha256, size_bytes, destination, url))
    if not artifacts:
        raise ValueError(f"{path}: lock is empty")
    return artifacts


def verify(path: Path, artifact: LockedArtifact) -> bool:
    if not path.is_file() or path.stat().st_size != artifact.size_bytes:
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256


def materialize(output: Path, artifact: LockedArtifact) -> None:
    destination = output / artifact.destination
    if verify(destination, artifact):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
    request = urllib.request.Request(
        artifact.url, headers={"User-Agent": "growspace-vision-build-preparer/1"}
    )
    try:
        with urllib.request.urlopen(request) as response, partial.open("wb") as target:
            while block := response.read(1024 * 1024):
                target.write(block)
        if not verify(partial, artifact):
            raise ValueError(
                f"{artifact.destination}: downloaded bytes do not match lock"
            )
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    try:
        artifacts = parse_lock(args.lock)
        args.output.mkdir(parents=True, exist_ok=True)
        for artifact in artifacts:
            materialize(args.output, artifact)
        manifest = {
            "schema_version": 1,
            "artifacts": [
                {
                    "path": artifact.destination.as_posix(),
                    "size_bytes": artifact.size_bytes,
                    "sha256": artifact.sha256,
                }
                for artifact in artifacts
            ],
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        expected_paths = {artifact.destination for artifact in artifacts}
        expected_paths.add(Path("manifest.json"))
        actual_paths = {
            path.relative_to(args.output)
            for path in args.output.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        unlisted = sorted(actual_paths - expected_paths)
        missing = sorted(expected_paths - actual_paths)
        if unlisted or missing:
            raise ValueError(
                f"output set is not closed; unlisted={unlisted}, missing={missing}"
            )
    except (OSError, ValueError) as error:
        print(f"build input preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
