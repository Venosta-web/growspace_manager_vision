# ADR 0003 — Growspace Vision V1 is a strict stateless boundary

**Status:** Accepted

Decided on 2026-08-31 in
[hub#67](https://github.com/Venosta-web/growspace_manager_workspace/issues/67),
after the encoder, embedding-distance, packaging, and symptom-output work in issues
#61, #62, #65, and #68. The normative wire contract is
[`contracts/growspace-vision/v1/openapi.json`](../../contracts/growspace-vision/v1/openapi.json).

Growspace Vision accepts exactly one image and a closed metadata object, performs one
stateless analysis, and returns either a model-versioned embedding or a first-class
quality rejection. It never receives environmental observations and never returns
symptoms, a health judgment, an anomaly score, a change score, or a trend. Home
Assistant owns Baseline Buckets and turns accepted embeddings into Visual Comparison
Results.

This boundary is deliberately stricter than the card's tolerant inbound schemas.
Every V1 object rejects unknown keys and every wire change, including an additive
field, requires a new integer schema version. That makes environmental-data leakage
and symptom-shaped output structural contract violations rather than conventions a
future contributor can quietly bypass. The integration negotiates the highest exact
analysis schema version shared with `/info`; no common version makes Vision
unavailable, never healthy or empty.

The service combines image validation and embedding retrieval in `POST /analyze`.
Batching was rejected because the existing workflow's multiple cameras have
independent quality and failure outcomes, while a batch would add partial-success
semantics to a service that gains nothing from owning them. Separate scoring was
rejected because centroid-cosine comparison, rolling baselines, anomaly scores, and
trends all require history that belongs to Home Assistant.

Multipart keeps the image as bytes and the metadata independently schema-validatable,
avoiding base64 expansion and header-encoded domain data. The only permitted metadata
is identity, capture time, light state, and exact schema/model selection. Raw image
quality measurements remain in the service response because they describe one frame;
history-relative gates and escalation remain in Home Assistant.

The App publishes no host port. It generates a per-install Bearer token and passes it
to the integration through Supervisor discovery; `/info`, `/models`, and `/analyze`
require it. `/health` is the sole unauthenticated exception because Supervisor's HTTP
watchdog cannot attach headers. It reveals readiness only and remains reachable solely
on the internal App network. A normally occupied inference slot does not make the
watchdog unhealthy; concurrent analysis is rejected separately as `429 busy`.

## Consequences

- A newer App must continue serving a response for an older schema it advertises; an
  App that drops V1 remains discoverable through the frozen `/info` bootstrap but is
  unavailable to a V1-only integration.
- A model-version change does not change the HTTP schema, but Home Assistant must start
  a new Baseline Bucket; embeddings from different model versions are never compared.
- Quality rejection is HTTP 200 and is stored as unusable, not scored. Transport,
  authentication, model, timeout, and internal failures use typed non-2xx errors and
  produce no baseline member, Visual Comparison Result, or healthy result.
- The App runs one inference at a time with no queue. Home Assistant owns camera-level
  scheduling and receives `429 busy` when it violates that limit.

## Considered options

- **Batch analysis.** Rejected because partial success belongs with the HA workflow and
  because the chosen CPU runtime has a concurrency limit of one.
- **Base64 JSON or a raw body with metadata headers.** Rejected because base64 inflates
  captures and headers cannot express or validate the closed metadata object cleanly.
- **A separate embedding endpoint and scoring endpoint.** Rejected because service-side
  scoring would give the stateless service hidden temporal ownership.
- **Tolerant additive response evolution.** Rejected because accepting unknown output
  would allow symptom or proxy fields to re-enter V1 without a negotiated contract.
