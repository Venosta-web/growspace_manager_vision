#!/usr/bin/env python3
"""Verify every prepared image input against a closed byte manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    return parser.parse_args()


def verify_artifact(root: Path, artifact: dict[str, Any]) -> Path:
    relative_path = Path(artifact["path"])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"unsafe artifact path: {relative_path}")

    path = root / relative_path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{relative_path}: artifact must be a regular file below root")
    data = path.read_bytes()
    expected_size = int(artifact["size_bytes"])
    expected_sha256 = str(artifact["sha256"])
    if len(data) != expected_size:
        raise ValueError(
            f"{relative_path}: expected {expected_size} bytes, got {len(data)}"
        )
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"{relative_path}: expected sha256 {expected_sha256}, got {actual_sha256}"
        )
    return relative_path


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported manifest schema")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("manifest must name at least one artifact")
        expected_paths: set[Path] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ValueError("artifact entries must be objects")
            expected_paths.add(verify_artifact(args.root, artifact))
        with suppress(ValueError):
            expected_paths.add(args.manifest.resolve().relative_to(args.root.resolve()))
        actual_paths = {
            path.relative_to(args.root)
            for path in args.root.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        unlisted = sorted(actual_paths - expected_paths)
        missing = sorted(expected_paths - actual_paths)
        if unlisted or missing:
            raise ValueError(
                f"input set is not closed; unlisted={unlisted}, missing={missing}"
            )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"build input verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
