# Growspace Vision

Growspace Vision is the local, stateless image-analysis service for Growspace
Manager. It analyzes one camera snapshot at a time and returns a model-versioned
visual embedding or a first-class frame-quality rejection. Home Assistant owns
scheduling, history, baseline comparison, interpretation, and alerting.

This repository is the source of truth for the service boundary and its supporting
research:

- [`CONTEXT.md`](CONTEXT.md) defines the shared domain language.
- [`contracts/growspace-vision/v1/`](contracts/growspace-vision/v1/) contains the
  normative OpenAPI 3.1 contract and executable fixtures.
- [`docs/adr/`](docs/adr/) records the accepted boundary and baseline decisions.
- [`docs/research/`](docs/research/) and [`scratchpad/`](scratchpad/) preserve the
  experiments behind those decisions.

The cross-repository roadmap and issue tracker remain in
[`growspace_manager_workspace`](https://github.com/Venosta-web/growspace_manager_workspace).

## Verify the V1 contract

The contract checks use only the Python standard library:

```bash
python3 -m unittest discover -s tests -v
```
