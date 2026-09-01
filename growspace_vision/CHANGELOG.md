# Changelog

## 1.0.0

- Package the pinned DINOv2 runtime for amd64 and aarch64.
- Generate a per-install access token and publish the endpoint to Home Assistant
  through App discovery, so no manual configuration is needed.
- Make `access_token` optional; it now overrides the generated token rather than
  being required.
- Add the internal-only authenticated Growspace Vision API wrapper.
- Include verified dependency locks, licence material, and SPDX inventories.
