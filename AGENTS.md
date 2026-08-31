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
- Preserve the strict ownership boundary: Vision analyzes one image without history;
  Home Assistant owns scheduling, baselines, comparison, interpretation, and alerts.

## Validation

Run the dependency-free contract suite after contract or fixture changes:

```bash
python3 -m unittest discover -s tests -v
```

Follow the workspace hub's cross-repo guidance when a change also affects the Home
Assistant integration or Lovelace card.
