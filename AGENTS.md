# AGENTS.md — Growspace Vision

This repository owns the Growspace Vision service, its HTTP contract, domain
language, architecture decisions, and supporting experiments. The sibling
`growspace_manager_workspace` repository remains the cross-repo runtime hub, roadmap,
and issue tracker; keep coordination artifacts there and service-owned artifacts here.

## Sources of truth

- Read `CONTEXT.md` before naming or changing Vision concepts.
- Treat `contracts/growspace-vision/v1/openapi.json` as the normative V1 wire
  contract. Keep its fixtures and `tests/test_growspace_vision_contract.py` in sync.
- Record durable service decisions in `docs/adr/`. Keep measurements and exploratory
  code in `docs/research/` and `scratchpad/`; neither is production implementation.
- Never commit an image derived from the private corpus — no frame, crop, thumbnail,
  contact sheet or rendered perturbation. Research documents cite aggregate results and
  point at local artifacts instead. `.gitignore` carries the rule; see
  [ADR 0008](docs/adr/0008-corpus-derived-imagery-stays-out-of-this-repository.md).
- Preserve the strict ownership boundary: Vision analyzes one image without history;
  Home Assistant owns scheduling, baselines, comparison, interpretation, and alerts.

## Validation

Run the dependency-free contract suite after contract or fixture changes:

```bash
python3 -m unittest discover -s tests -v
```

Run the downstream vendoring gate after changing anything under
`contracts/growspace-vision/v1/fixtures/`. It is the only automatic check that Home
Assistant's vendored copy still matches the contract this repository owns:

```bash
./scripts/check-backend-vendoring.sh
```

Follow the workspace hub's cross-repo guidance when a change also affects the Home
Assistant integration or Lovelace card.

## Dependency updates

Dependabot checks GitHub Actions, the digest-pinned Docker base image, the
`test` optional dependencies, and the pinned build backend each Monday. Its
version-update PRs target `main` and use the `chore(deps)` commit prefix.

Runtime dependencies are deliberately ignored. Their pins in `pyproject.toml`
are repeated in `packaging/requirements-runtime.txt` and the per-architecture
hash locks under `packaging/locks/`; changing only the Python manifest would
leave the offline image inputs inconsistent. Update those together through the
coordinated runtime-dependency update. Dependabot also does not change the App version in
`growspace_vision/config.yaml` or the model version in
`src/growspace_vision/model_manifest.json`; both require release decisions.

The Quality workflow builds and smokes both App architectures on every PR,
including Dependabot PRs. A new base image must still install the locked Debian
packages; that build and smoke check is the compatibility gate for image bumps.
