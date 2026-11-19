# PyArlo v0.9.0-beta.4 — Release Notes

## Cloud recording

- Fix `startRecord` requests rejected because Arlo did not provide a camera or base station time zone. PyArlo now checks the camera, its base station, and its matched V3 location, in that order, before using a caller-provided fallback.
- Only mark a recording active and schedule its stop after Arlo accepts the start request. The stop operation also reports whether Arlo accepted it.

## CLI

Use `camera record` to create a timed recording in the Arlo cloud library. FFmpeg must be on `PATH`; it keeps the stream open without writing a local file.

```bash
pyaarlo camera record "Test 03" --duration 30
pyaarlo media list -c "Test 03" --days 1 --compact
```

If Arlo doesn't provide a time zone, pass `--timezone` with an IANA zone such as `America/New_York`. In `--hass` mode, the CLI can also use Home Assistant's saved time zone.

Start and stop acknowledgments do not confirm upload. Use `media list` to verify the clip and `media download` to save it locally.
