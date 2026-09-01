# Current Home Assistant App packaging requirements

Research for [Package the multi-architecture Home Assistant App](https://github.com/Venosta-web/growspace_manager_workspace/issues/85),
under [Deliver Growspace Vision V1 end to end](https://github.com/Venosta-web/growspace_manager_workspace/issues/79).

Date: 2026-09-01. External claims below use current Home Assistant developer
documentation and first-party Home Assistant repositories. This note covers the App
wrapper only; the stronger model, dependency, hermetic-build, notice, and no-runtime-
download decisions remain in
[the production supply-chain research](2026-08-31-production-model-runtime-supply-chain.md).

## Implementation resolution

| Concern | Constraint for Growspace Vision |
|---|---|
| Build metadata | Do **not** add `build.yaml`. Since the 2026 BuildKit migration it is legacy; put the pinned multi-platform `FROM`, custom `ARG`s, and labels in `Dockerfile`. |
| Architectures | Declare exactly `amd64` and `aarch64` in `config.yaml`; Docker platform names are `linux/amd64` and `linux/arm64`. |
| Published image | Publish a generic multi-arch manifest and set `image: ghcr.io/venosta-web/growspace-manager-vision`; `version` must equal the selected image tag. |
| Runtime | This is a long-running dependency of Home Assistant: use `startup: services`, `boot: auto`, the Home Assistant base image's s6 init (`init: false`), and one foreground process. |
| Network | Keep `host_network: false`, bind the service to container port 8099, and either omit `ports` or declare `8099/tcp: null`. Both retain internal App-network access without publishing a host port. |
| Ingress | Do not enable it. Ingress is for a human-facing web UI, while Growspace Vision is a machine API authenticated by its own bearer token. |
| Privilege | Request no host mounts, devices, privileged capabilities, Supervisor API role, Home Assistant API access, Docker API, or host namespaces. Leave protection and AppArmor enabled. |
| Options/token | `SUPERVISOR_TOKEN` is for App-to-Supervisor/Core calls; it is not the Vision API credential. Collect a required `access_token` with schema type `password`, read it from `/data/options.json` through Bashio, export it as `GROWSPACE_VISION_TOKEN`, never print it, and `exec` the service. |
| Health | Configure `watchdog: http://[HOST]:[PORT:8099]/health`. Keep `/health` unauthenticated, as the service already does, so Supervisor can probe it. |
| Shutdown | The wrapper must end in `exec growspace-vision`; do not background it. The daemon must terminate within `timeout` (10 seconds by default, configurable up to 300) or Docker will kill it. |

These values follow the current
[App configuration reference](https://developers.home-assistant.io/docs/apps/configuration/),
whose required keys are `name`, `version`, `slug`, `description`, and `arch`, and whose
current Supervisor schema accepts only the supported App architectures while warning
on the retired ones. The schema also establishes the defaults used above (`startup:
application`, `boot: auto`, `init: true`, protection/AppArmor enabled) and the valid
watchdog/port/timeout shapes
([Supervisor `apps/validate.py`](https://github.com/home-assistant/supervisor/blob/main/supervisor/apps/validate.py)).

## Repository and App files

A distributable App repository has `repository.yaml` at its Git root with at least a
`name`; `url` and `maintainer` are optional. The documented conventional layout keeps
each App in its own folder containing `config.yaml`, `Dockerfile`, runtime script or
`rootfs`, `README.md`, `DOCS.md`, `CHANGELOG.md`, translations, logo/icon, and optional
AppArmor profile
([repository documentation](https://developers.home-assistant.io/docs/apps/repository/),
[configuration file layout](https://developers.home-assistant.io/docs/apps/configuration/)).

Supervisor actually discovers `**/config.{yaml,yml,json}`, excludes hidden paths and
`rootfs`, and treats the configuration's parent as the App build location. Therefore a
root-level `config.yaml` is technically supported for this single-product repository
and keeps the existing root Docker build context intact, although a named subdirectory
is the documented multi-App convention. Whichever layout is chosen, do not add another
unrelated `config.yaml`: discovery is recursive
([Supervisor store loader](https://github.com/home-assistant/supervisor/blob/main/supervisor/store/data.py)).

At minimum, the store-facing files should be:

- `repository.yaml` with the repository identity;
- `config.yaml` with App identity, architectures, runtime/security settings, options,
  watchdog, and generic image name;
- `README.md`, `DOCS.md`, and `CHANGELOG.md`; and
- PNG `icon.png` and `logo.png` when store presentation is in scope.

Home Assistant describes `DOCS.md` as the user manual, including configuration,
support, and licensing information. Its current presentation guidance also defines the
icon/logo names and PNG format
([presenting an App](https://developers.home-assistant.io/docs/apps/presentation/)).

## `build.yaml` is obsolete; Dockerfile and BuildKit own the build

The legacy builder previously read `build_from`, `args`, and `labels` from
`build.yaml`. Home Assistant retired that builder in April 2026. Current guidance is to
move `build_from` to an explicit `FROM`, build arguments to Dockerfile `ARG`s, and
labels to Dockerfile/workflow labels; a present `build.yaml` is read only for backward
compatibility, emits warnings, and is intended to disappear
([BuildKit migration](https://developers.home-assistant.io/blog/2026/04/02/builder-migration/),
[current configuration note](https://developers.home-assistant.io/docs/apps/configuration/)).

Only `BUILD_VERSION` and `BUILD_ARCH` are Home Assistant-provided build arguments.
`BUILD_FROM` is no longer supplied by default as of Supervisor 2026.04.0. The current
Dockerfile's explicit, dated Debian Trixie multi-arch digest is therefore the correct
base-selection shape; it does not need an architecture-specific base mapping. Home
Assistant's base repository confirms that `base-debian` is the glibc alternative and
that current base images publish one multi-arch reference covering amd64 and arm64
([docker-base README](https://github.com/home-assistant/docker-base)).

For publication, Home Assistant recommends its versioned builder composite actions.
The official example reads `arch` and `image` from `config.yaml`, builds amd64 on an
x86 runner and aarch64 on an ARM runner, publishes the per-architecture images, and
then creates a generic manifest
([example workflow](https://github.com/home-assistant/apps-example/blob/main/.github/workflows/build-app.yaml)).
The `build-image` action injects `BUILD_ARCH`/`BUILD_VERSION`, adds
`io.hass.arch`/`io.hass.version` and OCI source/version labels, and signs pushed images
with Cosign by default
([builder action source](https://github.com/home-assistant/builder/blob/master/actions/build-image/action.yml)).
The generic image name is now preferred in `config.yaml`; `{arch}` remains only a
compatibility fallback
([publishing documentation](https://developers.home-assistant.io/docs/apps/publishing/)).

The stock workflow proves that both images build; it does not prove the issue's native
amd64 contract checks, aarch64 execution smoke, offline analysis, or SBOM attachment.
Those remain explicit additional CI gates. Home Assistant's local-testing guide maps
HA `aarch64` to Docker `linux/arm64` and documents `--platform` for cross-architecture
builds
([local App testing](https://developers.home-assistant.io/docs/apps/testing/)).

## Ports, discovery, Ingress, and tokens

Apps and Home Assistant Core share Supervisor's internal network. App DNS names are
derived from `{REPO}_{SLUG}` and underscores become hyphens. A Git repository's
`{REPO}` component is a hash of its URL, so downstream code should not hard-code the
full hostname
([App communication](https://developers.home-assistant.io/docs/apps/communication/)).

The explicit internal-only pattern in the official Matter Server App is useful here:
it declares its API port as `null`, binds on the App network, and sends Home Assistant
a discovery payload containing `hostname` and the internal port
([Matter Server config](https://github.com/home-assistant/addons/blob/master/matter_server/config.yaml),
[Matter discovery script](https://github.com/home-assistant/addons/blob/master/matter_server/rootfs/etc/s6-overlay/scripts/matter-server-discovery)).
Growspace Vision should likewise avoid a default host-port mapping. The later backend
integration can either discover `{host, port, token}` through Supervisor App discovery
or obtain equivalent explicit configuration; discovery invokes the integration's
reserved `async_step_hassio`
([Home Assistant config-flow documentation](https://developers.home-assistant.io/docs/core/integration/config_flow/)).

Ingress is not a generic service tunnel. It authenticates a Home Assistant user and
proxies a web UI, normally on 8099; an Ingress-only server is expected to accept only
connections from `172.30.32.2`
([Ingress requirements](https://developers.home-assistant.io/docs/apps/presentation/#ingress)).
Enabling it would neither replace the Vision bearer-token contract nor help the
integration's direct API calls, so omit `ingress`, `ingress_port`, `webui`, and panel
settings.

Likewise, do not set `homeassistant_api` or `hassio_api` merely to obtain a credential.
Those flags authorize the App to call Core or Supervisor through `http://supervisor`
using `SUPERVISOR_TOKEN`; they do not authenticate callers to the App. The default
Supervisor API still permits an App's self-info and discovery calls, so later discovery
does not require broadening the role
([communication/API permissions](https://developers.home-assistant.io/docs/apps/communication/),
[App security](https://developers.home-assistant.io/docs/apps/security/)).

For issue 85's standalone wrapper, the least assumptive token surface is a mandatory
option:

```yaml
options: {}
schema:
  access_token: password
```

An option with no default and a non-optional schema must be supplied before the App can
start; `password` is a supported schema type. Runtime options are available in
`/data/options.json`, and Home Assistant's base images include Bashio to read them
([options/schema and App script](https://developers.home-assistant.io/docs/apps/configuration/)).
The wrapper must keep expansion quoted, avoid command tracing, and never log the value.
If the backend ticket adopts Supervisor discovery, it may instead generate a long
random token once under persistent `/data` and convey it only in the protected
discovery payload; that is a later cross-repository credential-lifecycle decision, not
a reason to misuse `SUPERVISOR_TOKEN` now.

## Foreground process and shutdown

For one daemon, the documented thin pattern is a Bash/Bashio startup script copied by
the Dockerfile and used as `CMD`. It reads options and ends with `exec` so the service,
not a lingering shell, is the foreground child of the base image's s6 init
([App script and Dockerfile example](https://developers.home-assistant.io/docs/apps/configuration/)).
Because the Home Assistant base already includes s6-overlay, `config.yaml` must set
`init: false`; the configuration reference explicitly requires this for s6-overlay v3.

The official App template's supervised-service variant applies the same rule: its
`run` script reads Bashio options and `exec`s the program, while its `finish` script
records a non-zero exit code and halts the s6 tree; ordinary exits are restarted
([template `run`](https://github.com/home-assistant/apps-example/blob/main/example/rootfs/etc/services.d/example/run),
[template `finish`](https://github.com/home-assistant/apps-example/blob/main/example/rootfs/etc/services.d/example/finish)).
Growspace Vision should choose one model, not layer a CMD wrapper and an additional s6
longrun around the same process. The direct CMD wrapper is sufficient for one Uvicorn
process and naturally makes unexpected daemon exit terminate the container.

## Security, reproducibility, and licensing boundaries

Home Assistant's security guidance is to avoid host networking, use AppArmor, map only
necessary folders read-only, grant only necessary APIs, and sign published images.
Growspace Vision needs none of the privileged options or mounts, so the secure default
is also the simplest configuration
([App security](https://developers.home-assistant.io/docs/apps/security/)).
`host_network: false` is isolation from the host network, **not an outbound-egress
deny rule**. The current Supervisor App schema has no egress-deny key, so the issue's
"no outbound network connection" acceptance must be proved externally (for example,
successful startup and analysis in a no-egress network namespace plus a runtime
connection audit); it cannot be asserted by `config.yaml`.

Home Assistant recommends a pinned base for build stability, OCI license/source labels,
signed images, user documentation that states the license, and pre-built images rather
than mutable local builds. It does not make byte-reproducible layers, SBOMs, complete
dependency notices, or offline builds App-schema requirements. Issue 80 deliberately
adds those stronger gates. Consequently the final image/release still must contain the
service MIT license, DINOv2 Apache-2.0 attribution and artifact identity, ONNX Runtime
MIT license and version-matched third-party notices, the complete dependency notice
bundle, per-architecture SBOMs, and the pinned model bytes. The OCI license label and
`DOCS.md` should describe the combined distribution accurately rather than imply that
the service's MIT license relicenses the model.
