# Changelog

## 1.0.1

- No change to the analysis service, the model, or what the image contains.
  The model version stays `1.0.0`, so stored comparison history keeps its
  meaning across this update.
- Publishing now retries the registry calls a transient GHCR failure
  interrupts. The 1.0.0 release was lost to one such failure after every layer
  had already been pushed, and recovering it took a hand-dispatched re-run;
  this is the first release published through the retried path.

## 1.0.0

- Package the pinned DINOv2 runtime for amd64 and aarch64.
- Generate a per-install access token and publish the endpoint to Home Assistant
  through App discovery, so no manual configuration is needed.
- Make `access_token` optional; it now overrides the generated token rather than
  being required.
- Add the internal-only authenticated Growspace Vision API wrapper.
- Include verified dependency locks, licence material, and SPDX inventories.
