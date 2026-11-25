# PyArlo v0.9.0-beta.6 — Release Notes

## SIP/WebRTC capability detection

PyArlo now checks its built-in SIP model list when Arlo's capability document omits `Streaming.SIPStreaming`. An explicit `true` or `false` still takes precedence. Models not on the list aren't enabled by a missing flag alone, and SIP push-to-talk by itself does not imply support for SIP live view.

This lets Home Assistant select WebRTC for supported doorbells such as the AVD2001A and AVD4001A instead of defaulting to HLS when the flag is absent. This fixes stream selection; whether WebRTC resolves the reporter's pixelation in [hass-aarlo #1156](https://github.com/twrecked/hass-aarlo/issues/1156) still needs a live test.

Use `pyaarlo capabilities --built-in AVD4001A i016` to compare the calculated SIP streaming decision with the built-in fallback.
