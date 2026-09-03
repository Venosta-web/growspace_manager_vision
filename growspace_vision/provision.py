#!/usr/bin/env python3
"""Establish the App's Bearer credential and hand it to Home Assistant.

Growspace Vision publishes no host port, so there is no endpoint a grower could
read off a screen and type in: the App's DNS name is ``{repository}_{slug}``
with the repository part a hash of the store URL. The endpoint and the
credential that opens it therefore travel together, once per start, through
Supervisor App discovery. Supervisor accepts that push only because
``config.yaml`` declares ``discovery: [growspace_manager]``; without it the API
answers 403. The integration then *pulls* the message rather than waiting to be
told, because Core aborts a ``SOURCE_HASSIO`` flow for a single-entry domain
before the flow could run.

Three ways to arrive at the token, in this order:

``GROWSPACE_VISION_TOKEN``
    The plain-container override. Used by the packaging smoke check and by any
    deployment that runs the image directly rather than as an App.
``access_token``
    The grower's explicit override, read from the App options. Retained for the
    one case discovery cannot serve: a grower who maps ``8099/tcp`` themselves
    and configures Growspace Manager as a manual endpoint, where they have to
    be able to know the token.
a per-install secret under ``/data``
    The norm. Generated once, readable only by the App, and shown to nobody --
    it reaches Home Assistant through the discovery payload alone.

The token is written to stdout and nothing else is, because ``run.sh`` reads it
by command substitution. Diagnostics go to stderr and never name the value.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import tempfile
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DISCOVERY_SERVICE = "growspace_manager"
"""The integration domain the App announces to, as declared in ``config.yaml``."""

SERVICE_PORT = 8099
"""The internal App-network port, published in the payload rather than to the host."""

SUPERVISOR_API = "http://supervisor"
TOKEN_FILE_NAME = "bearer_token"
TOKEN_BYTES = 32
PUBLISH_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class Credential:
    """One resolved Bearer token and where it came from.

    ``origin`` exists so that a start can be explained in the App log without
    the log ever carrying the secret.
    """

    token: str = field(repr=False)
    origin: str


def resolve_credential(
    *,
    environ: Mapping[str, str],
    options_path: Path,
    data_dir: Path,
) -> Credential:
    """Return the token this start must serve, generating one if it must.

    Generation is the last resort rather than the first, so an explicitly
    supplied token is never shadowed by a secret the grower cannot see.
    """
    supplied = environ.get("GROWSPACE_VISION_TOKEN", "").strip()
    if supplied:
        return Credential(token=supplied, origin="environment")

    configured = _configured_token(options_path)
    if configured:
        return Credential(token=configured, origin="option")

    return _stored_or_generated(data_dir / TOKEN_FILE_NAME)


def publish_discovery(
    *,
    api: str,
    supervisor_token: str,
    service: str,
    host: str,
    port: int,
    token: str,
    timeout: float = PUBLISH_TIMEOUT_SECONDS,
) -> str:
    """Push ``{host, port, token}`` to Supervisor and return the message UUID.

    ``port`` is a JSON number, not a string: the integration rejects an
    incomplete payload, and a quoted port is an incomplete payload.
    """
    payload = json.dumps(
        {
            "service": service,
            "config": {"host": host, "port": port, "token": token},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api}/discovery",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: Any = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("Supervisor returned an unreadable discovery response")
    data = body.get("data")
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if not isinstance(uuid, str) or not uuid:
        raise ValueError("Supervisor accepted the message but named no UUID")
    return uuid


def _configured_token(options_path: Path) -> str:
    """Read the optional ``access_token`` App option.

    An unreadable options file is reported and then treated as unset. Refusing
    to start would take the service down over a file the grower did not write,
    and there is no risk of serving the wrong token: a file that cannot be
    parsed states no token at all.
    """
    try:
        raw = options_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as err:
        _log(f"Could not read the App options at {options_path}: {err}")
        return ""

    try:
        options: Any = json.loads(raw)
    except json.JSONDecodeError as err:
        _log(f"The App options at {options_path} are not readable JSON: {err}")
        return ""
    if not isinstance(options, dict):
        return ""
    return str(options.get("access_token") or "").strip()


def _stored_or_generated(path: Path) -> Credential:
    """Reuse the per-install secret, or mint it the first time.

    Reuse matters beyond tidiness: a token that changed on every start would
    invalidate whatever Home Assistant last discovered until the next pull.
    """
    try:
        stored = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        stored = ""
    if stored:
        return Credential(token=stored, origin="stored")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    _write_secret(path, token)
    return Credential(token=token, origin="generated")


def _write_secret(path: Path, token: str) -> None:
    """Write the secret owner-readable, atomically, or not at all.

    A half-written token file would be read as a valid but wrong secret on the
    next start, so the file appears only once it is complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".bearer_token-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(f"{token}\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _log(message: str) -> None:
    """Report to stderr, because stdout carries the token and nothing else."""
    print(f"[growspace-vision] {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve the credential, announce the endpoint, and print the token."""
    parser = argparse.ArgumentParser(description="Provision the Growspace Vision App.")
    parser.add_argument("--data-dir", type=Path, default=Path("/data"))
    parser.add_argument("--options", type=Path, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=SERVICE_PORT)
    parser.add_argument("--service", default=DISCOVERY_SERVICE)
    parser.add_argument("--supervisor-api", default=SUPERVISOR_API)
    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir
    options_path: Path = args.options or data_dir / "options.json"

    credential = resolve_credential(
        environ=os.environ, options_path=options_path, data_dir=data_dir
    )
    print(credential.token, flush=True)
    _log(f"Bearer token origin: {credential.origin}")

    supervisor_token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not supervisor_token:
        _log("No Supervisor to announce to; serving the endpoint directly")
        return 0

    # A failed announcement must not take the service down. Home Assistant
    # already has a name for this state -- Vision reports `not_configured` --
    # and exiting instead would hand the watchdog a restart loop that cannot
    # fix a Supervisor that is not answering.
    try:
        uuid = publish_discovery(
            api=args.supervisor_api,
            supervisor_token=supervisor_token,
            service=args.service,
            host=args.host or socket.gethostname(),
            port=args.port,
            token=credential.token,
        )
    except (OSError, ValueError) as err:
        _log(f"Could not publish the endpoint to Supervisor: {err}")
        _log("Growspace Manager will report Vision as not configured until it can")
        return 0

    _log(f"Published the endpoint to Home Assistant as discovery message {uuid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
