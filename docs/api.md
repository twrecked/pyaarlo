# PyArlo Python API Reference

PyArlo v0.9 is a native `asyncio` Python library (requiring Python >= 3.10) for interacting with Arlo cameras, base stations, lights, doorbells, sensors, and locations.

---

## 1. Initialization & Lifecycle

### `PyArlo.create(**kwargs) -> PyArlo`
The asynchronous factory method for creating a `PyArlo` controller instance.

```python
import asyncio
from pyaarlo import PyArlo

async def main():
    arlo = await PyArlo.create(
        username="user@example.com",
        password="your-password",
        tfa="push",
    )

    try:
        print(f"Connected to Arlo. Cameras: {len(arlo.cameras)}")
    finally:
        # Always stop the controller to cleanly close network connections
        await arlo.stop(logout=False)

asyncio.run(main())
```

### Key Parameters for `PyArlo.create()`:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `username` | `str` | *Required* | Arlo account email address |
| `password` | `str` | *Required* | Arlo account password |
| `tfa` | `str` | `"push"` | Unified 2FA specification: `"push"`, `"email:imap"`, `"email:console"`, or `"sms"` |
| `tfa_host` | `str` | `None` | IMAP server hostname (e.g. `"imap.gmail.com"`) |
| `tfa_username` | `str` | `None` | IMAP account username |
| `tfa_password` | `str` | `None` | IMAP app-password |
| `inline_mode` | `bool` | `False` | When `True`, device actions wait inline for Arlo's response or event acknowledgment before returning. (Replaces `synchronous_mode`). |
| `start_background` | `bool` | `True` | Start the persistent event stream (MQTT/SSE) and background refresh loops. Set to `False` for fast one-shot scripts. |
| `refresh_devices` | `bool` | `True` | Query Arlo for fresh device catalogs on connect. Set to `False` to reuse cached device metadata. |
| `backend` | `str` | `"auto"` | Event stream protocol: `"auto"`, `"mqtt"`, or `"sse"`. |
| `storage_dir` | `str` | OS cache dir | Directory where persistent sessions and state files are stored. |

---

## 2. Fast One-Shot Script Mode

If your script only needs to perform an action (e.g. turn off a light, check status, or list devices) without maintaining an event stream, disable background workers for sub-second execution:

```python
arlo = await PyArlo.create(
    username="user@example.com",
    password="password",
    start_background=False,   # Skips persistent MQTT/SSE stream
    refresh_devices=False,    # Reuses saved device catalog
)
```

---

## 3. Devices & Subsystems

Once initialized, devices are available via controller properties:

```python
# Collections
arlo.cameras       # list[ArloCamera]
arlo.lights        # list[ArloLight]
arlo.doorbells     # list[ArloDoorBell]
arlo.base_stations # list[ArloBaseStation]
arlo.locations     # list[ArloLocation]
arlo.sensors       # list[ArloSensor]
```

### Common Device Properties
Every device subclass inherits from `ArloDevice` / `ArloObject`:
- `device.name`: Friendly name string.
- `device.device_id`: Arlo unique device identifier.
- `device.serial_number`: Serial number.
- `device.model_id`: Hardware model identifier.
- `device.battery_level`: Battery percentage integer (or `None`).
- `device.signal_strength`: Wireless signal strength integer.

---

## 4. Device Controls

### Smart Lights (`ArloLight`)
```python
# Turn on
await light.turn_on(brightness=150)

# Turn off
await light.turn_off()

# Set brightness (0-255)
await light.set_brightness(200)

# State inspection
print(light.is_on)      # bool
print(light.brightness) # int
```

### Locations & Modes (`ArloLocation`)
```python
loc = arlo.locations[0]
print(f"Current mode: {loc.mode}")
print(f"Available modes: {loc.available_modes}")

# Change mode
await loc.set_mode("armHome")
await loc.set_mode("standby")
```

### Cameras (`ArloCamera`)
```python
# Request fresh thumbnail/snapshot
await camera.request_snapshot()

# Get live stream URL
stream_url = await camera.get_stream()
print(f"Stream URL: {stream_url}")
```

---

## 5. Event Callbacks

PyArlo provides an event callback system for tracking real-time device updates:

```python
def on_attribute_change(device, attr, value):
    print(f"[{device.name}] {attr} changed to: {value}")

# Register for a specific event
camera.add_attr_callback("motionDetected", on_attribute_change)
doorbell.add_attr_callback("ding", on_attribute_change)

# Register for all events on a device
camera.add_attr_callback("*", on_attribute_change)
```

Common attributes:
- `motionDetected`: `True` / `False`
- `audioDetected`: `True` / `False`
- `ding`: `True` / `False` (doorbell press)
- `batteryLevel`: integer percentage
- `chargingState`: `"Charging"`, `"Discharging"`, etc.
- `lampState`: `"on"`, `"off"`
- `activeMode`: active security mode

---

## 6. Media Library (`ArloMediaLibrary`)

Access recorded videos and snapshots:

```python
# Sync recordings between dates (YYYYMMDD)
videos, snapshots, _ = await arlo.ml._sync_library("20261010", "20261017", [])

for vid in videos:
    print(f"{vid.datetime} - {vid.camera.name}: {vid.object_type} ({vid.media_duration_seconds}s)")
    
    # Download video file
    await vid.download_video(f"./media/{vid.id}.mp4")
```
