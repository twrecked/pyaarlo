# PyArlo v0.9.0-beta.5 — Release Notes

## Media player detection

- Fix startup `4000: Resource not found` responses on video doorbells such as the `AVD2001A`. PyArlo no longer treats `Melody` alone as evidence that a doorbell supports the `audioPlayback` endpoint (#231).
- Devices that explicitly advertise `AudioPlayback` and the existing Arlo Baby playback behavior are unchanged.
