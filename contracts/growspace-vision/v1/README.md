# Growspace Vision HTTP contract V1

[`openapi.json`](openapi.json) is the normative OpenAPI 3.1 contract. Fixtures under
[`fixtures/`](fixtures/) are portable inputs for the future Python client and strict
Zod schemas.

## Protocol summary

- `POST /analyze` accepts one JPEG or PNG in a two-part multipart request: `metadata`
  (`application/json`) and `image` (`image/jpeg` or `image/png`). There is no batch or
  service-side scoring operation.
- `/info` is the permanently frozen V1 negotiation bootstrap. The integration chooses
  the highest value it also supports from `supported_schema_versions`.
- `GET /models?schema_version=1` describes models usable with the selected analysis
  schema. The request metadata must copy an exact loaded `model_id` and
  `model_version` pair.
- `/health` is unauthenticated for the Supervisor watchdog and exposes readiness only.
  Every other endpoint requires the per-install Bearer token supplied through
  Supervisor discovery. A manually configured endpoint requires its own user-supplied
  Bearer token; unauthenticated manual endpoints are invalid configurations.
- `/health` remains ready while the one inference slot is occupied; `busy` is normal
  load, not a condition for Supervisor to restart the App.
- Every object is closed. Unknown keys fail validation, even when they would otherwise
  be harmless additions.

## Ownership and failure semantics

An `analyzed` response says only that the App produced an embedding. It does not say
that the scene is normal, anomalous, healthy, or unhealthy. A `rejected` response is a
successful, first-class unusable-frame result and contains no embedding.

After `analyzed`, Home Assistant may compare the embedding with its matching Baseline
Bucket and record `anomaly_score` and `trend` on a Visual Comparison Result.
`change_score` is not a second score in V1; the canonical temporal measure is
`anomaly_score`. None of those fields is valid in an App response.

Any non-2xx response or client timeout means the service failed. Home Assistant must
not add the frame to a baseline, create a Visual Comparison Result, or substitute an
empty, normal, or healthy result. It does not retry automatically.

| HTTP | error code                   | meaning                                         |
| ---: | ---------------------------- | ----------------------------------------------- |
|  401 | `unauthorized`               | token missing or invalid                        |
|  413 | `image_too_large`            | encoded or decoded size limit exceeded          |
|  415 | `unsupported_image_format`   | image is not JPEG or PNG                        |
|  422 | `invalid_request`            | closed metadata or image decoding failed        |
|  422 | `unsupported_schema_version` | requested analysis schema is unsupported        |
|  422 | `invalid_request`            | requested model identity/version is unknown     |
|  429 | `busy`                       | the sole inference slot is occupied             |
|  500 | `internal_failure`           | inference deadline or internal operation failed |
|  503 | `model_not_loaded`           | configured or requested model is unavailable    |

Errors never use an `analyzed` or `rejected` body. An unknown model is an invalid
request; a known model whose `state` is `unavailable` is `model_not_loaded`.

## Version negotiation

`/info` is the bootstrap and therefore remains parseable as V1 even when the App no
longer supports V1 analysis. Its `supported_schema_versions` values select the schemas
usable with `/models` and `/analyze`; the integration chooses the highest exact
intersection with its own versions. `/models` receives that choice as the required
`schema_version` query parameter, and `/analyze` receives it in metadata.

An App advertising V1 must return the V1 shape when V1 is selected. Additions are not
tolerated: a field addition, removal, type change, or semantic change creates another
integer version. A service release or model artifact update changes `service_version`
or `model_version`, not `schema_version`.

## Operational contract

| limit                | owner       |   V1 value |
| -------------------- | ----------- | ---------: |
| encoded image body   | App         |     10 MiB |
| decoded image pixels | App         | 24,000,000 |
| active inference     | App         |          1 |
| server-side queue    | App         |          0 |
| inference deadline   | App         | 10 seconds |
| total HTTP timeout   | integration | 15 seconds |

The App returns `429 busy` rather than queueing a concurrent request. An App-side
deadline is `500 internal_failure`; an integration-side timeout has no response but the
same no-write semantics.

## Fixture manifest

[`fixtures/manifest.json`](fixtures/manifest.json) maps every fixture to its component
schema and expected validity. The negative response fixtures make the #68 constraint
executable: `symptoms`, `chlorosis`, and `drooping` are each rejected, as are temporal
scores and environmental request data.
