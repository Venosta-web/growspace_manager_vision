# Growspace Vision

Growspace Vision is the local analysis service used by the Growspace Manager
integration. It evaluates one camera snapshot at a time and returns a frame-quality
result and, for usable frames, a model-versioned visual embedding. It retains no image
history and makes no cloud or internet request at runtime.

## Configuration

There is nothing to configure. On its first start the App generates its own access token,
keeps it in its private `/data` storage, and announces its address and that token to Home
Assistant through App discovery. Install Growspace Vision, start it, and Growspace Manager
finds it.

The service is available only on Home Assistant's internal App network at port `8099`; it
deliberately publishes no host port and requests no Home Assistant, Supervisor, device, or
filesystem privileges.

### `access_token` (optional)

Leave it empty unless you have mapped port `8099` to your host yourself and want to
configure Growspace Manager with a manual endpoint. In that case set `access_token` to a
secret of your own and enter the same value in Growspace Manager; it overrides the
generated one. Clearing it again returns the App to its generated token.

To rotate the generated token, delete `/data/bearer_token` from the App's storage and
restart the App. Growspace Manager picks up the new one by itself.

The App ships the model and complete runtime. It never downloads a model or Python
package after installation. A missing or altered model leaves the service unready.

Physical aarch64 latency and memory have not been measured; the aarch64 image is covered
by an emulated startup and contract smoke check only.
