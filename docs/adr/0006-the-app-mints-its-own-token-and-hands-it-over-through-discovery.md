# ADR 0006 — The App mints its own token and hands it over through discovery

**Status:** Accepted

Decided on 2026-09-01 in
[hub#98](https://github.com/Venosta-web/growspace_manager_workspace/issues/98). It
settles the credential lifecycle that
[hub#85](https://github.com/Venosta-web/growspace_manager_workspace/issues/85)
deliberately deferred, on the packaging mechanics established by
[hub#65](https://github.com/Venosta-web/growspace_manager_workspace/issues/65) and
recorded in
[Current Home Assistant App packaging requirements](../research/2026-09-01-home-assistant-app-packaging.md).
It implements the hand-over that
[ADR 0003](0003-growspace-vision-v1-is-a-strict-stateless-boundary.md) already
requires and changes no wire contract: the integration reads the same
`{host, port, token}` it was already built against.

The App generates its Bearer token once per install, keeps it in `/data`, and publishes
`{host, port, token}` to Supervisor App discovery on every start. `config.yaml` declares
`discovery: [growspace_manager]`, without which Supervisor answers the push `403`.
Home Assistant *pulls* that message rather than being handed it, because Core aborts a
`SOURCE_HASSIO` flow for a `single_config_entry` domain before the flow can run.

The token had to become the App's to mint, not the grower's to invent, because the App
publishes no host port. Its DNS name is `{repository}_{slug}` where the repository part
is a hash of the store URL, so on HAOS there is no endpoint a grower could read off a
screen and type in. Requiring a token they must also type would make the only usable
mode depend on a value the only usable mode never shows them.

The `access_token` option is **retained, and demoted to optional**. It is not a second
norm; it is the one case discovery cannot serve. `ports` declares `8099/tcp` unmapped,
which a grower may map themselves, and a manually configured endpoint needs a token they
can actually read. Precedence runs `GROWSPACE_VISION_TOKEN` in the environment, then the
`access_token` option, then the per-install secret — explicit first, so a token someone
chose is never shadowed by one only the App knows.

A failed publication does not stop the service. Home Assistant already names that state:
Vision reports `unavailable` with reason `not_configured`. Exiting instead would hand the
Supervisor watchdog a restart loop over a condition a restart cannot fix, and would take
down a service a manually configured endpoint could still reach.

## Consequences

- The token is written to `/data/bearer_token`, owner-readable and replaced atomically,
  and survives App restarts and updates. Deleting that file rotates the credential on the
  next start; Home Assistant picks the new one up on its next discovery pull.
- The secret is in a Supervisor backup of the App, as any `/data` content is. It is never
  logged, never passed on a command line, and never printed anywhere but the single line
  of stdout that `run.sh` reads.
- A grower who sets `access_token` after an install has already generated one silently
  supersedes it; the generated secret stays on disk and returns if the option is cleared.
- `run.sh` no longer reads options through Bashio. Token resolution and publication live
  in `growspace_vision/provision.py`, where they are unit-testable rather than only
  observable in a container.

## Considered options

- **Drop the `access_token` option entirely.** Rejected because `8099/tcp` remains
  mappable and a grower who maps it would have no way to learn the token short of a
  shell into the App.
- **Keep the mandatory `access_token` option and skip discovery.** Rejected: it is what
  ships today and it is unusable on HAOS, because the endpoint half of the pair is a
  hash the grower cannot know.
- **Derive the token from `SUPERVISOR_TOKEN`.** Rejected. That credential authenticates
  the App to Supervisor and Core; it authenticates nobody to the App, and reusing it
  would widen its blast radius for no gain.
- **Publish discovery only once the service answers `/health`.** Rejected as complexity
  without a benefit: the integration re-probes on a TTL and reports `unreachable` in the
  meantime, which is the correct description of that second. The official Matter Server
  App publishes without waiting for the same reason.
- **Fail the start when publication fails.** Rejected; see above.
