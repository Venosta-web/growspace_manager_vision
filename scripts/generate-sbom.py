#!/usr/bin/env python3
"""Generate a deterministic SPDX inventory of one image's locked inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    # The App version, handed down from growspace_vision/config.yaml through the
    # image build. Never a literal here: an SBOM naming a version the image is
    # not is worse than no SBOM, and this file has no way to notice.
    parser.add_argument("--version", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    files = []
    relationships = []
    for index, artifact in enumerate(manifest["artifacts"], start=1):
        spdx_id = f"SPDXRef-BuildInput-{index}"
        files.append(
            {
                "fileName": artifact["path"],
                "SPDXID": spdx_id,
                "checksums": [
                    {
                        "algorithm": "SHA256",
                        "checksumValue": artifact["sha256"],
                    }
                ],
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-Growspace-Vision",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": spdx_id,
            }
        )

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"growspace-vision-{args.version}-linux-{args.arch}",
        "documentNamespace": (
            "https://github.com/Venosta-web/growspace_manager_vision/"
            f"sbom/{args.version}/linux-{args.arch}"
        ),
        "creationInfo": {
            "created": "2026-08-31T00:00:00Z",
            "creators": ["Tool: growspace-vision-generate-sbom-1"],
        },
        "documentDescribes": ["SPDXRef-Package-Growspace-Vision"],
        "packages": [
            {
                "name": "growspace-manager-vision",
                "SPDXID": "SPDXRef-Package-Growspace-Vision",
                "versionInfo": args.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "MIT AND Apache-2.0",
                "copyrightText": "NOASSERTION",
            }
        ],
        "files": files,
        "relationships": relationships,
    }
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
