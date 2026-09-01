# Growspace Vision

Growspace Vision is the local analysis service used by the Growspace Manager
integration. It evaluates one camera snapshot at a time and returns a frame-quality
result and, for usable frames, a model-versioned visual embedding. It retains no image
history and makes no cloud or internet request at runtime.

## Configuration

Set `access_token` to a generated secret and enter the same value when configuring Growspace
Vision in Growspace Manager. The service is available only on Home Assistant's internal
App network at port `8099`; it deliberately publishes no host port and requests no Home
Assistant, Supervisor, device, or filesystem privileges.

The App ships the model and complete runtime. It never downloads a model or Python
package after installation. A missing or altered model leaves the service unready.

Physical aarch64 latency and memory have not been measured; the aarch64 image is covered
by an emulated startup and contract smoke check only.
