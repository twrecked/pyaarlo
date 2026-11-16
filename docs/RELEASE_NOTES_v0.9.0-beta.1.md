# 🚀 PyArlo v0.9.0-beta.1 — Release Notes

> Version `0.9.0-beta.1` marks the first official beta release of the modernized **PyArlo v0.9 architecture**. This milestone introduces a non-blocking, async-first engine, first-class siren and light entities, dynamic cloud capability resolution, native WebRTC SIP streaming protocol support, and advanced 2FA handling.

---

## ⚠️ Breaking Changes & Migration from v0.8.x

If you are upgrading from PyArlo `v0.8.x`, please note the following architectural shifts:

### 1. Native Async-First Architecture (`asyncio`)
* **All I/O is Async:** Network requests, event stream dispatching, media streaming, and device actions now operate strictly as native `asyncio` coroutines (`await arlo.async_init()`, `await camera.get_stream()`, `await light.turn_on()`, etc.).
* **Zero Legacy Shims:** Synchronous blocking calls, busy-wait sleep loops (`time.sleep()`), and legacy compatibility wrappers have been removed to guarantee clean event loop performance.
* **Target Runtime:** Python $\ge 3.12$ is recommended (minimum $\ge 3.10$).

### 2. First-Class Sirens (`pyaarlo.siren`)
* **Dedicated Siren Objects:** Sirens are no longer treated as secondary attributes or switch toggles on base stations or cameras. They are now discrete `ArloSiren` objects accessible via `arlo.sirens` and `arlo.lookup_siren_by_id()`.
* **Standardized Controls:** Siren methods provide native `siren_on(duration=..., volume=...)` and `siren_off()` operations.

### 3. Unified Camera Lights (`pyaarlo.light`)
* **First-Class Device Representation:** Cameras with built-in spotlights or floodlights automatically instantiate first-class `ArloLight` objects available in `arlo.lights` and `arlo.all_devices`.
* **Consistent Control API:** Spotlight and floodlight devices support `turn_on(brightness=...)` and `turn_off()` natively, with transparent delegation on parent camera objects.

---

## 🌟 What's New in v0.9.0-beta.1

### 1. Dynamic Cloud Capability Resolution (`pyaarlo.capabilities`)
Eliminates static model tuple checks by dynamically inspecting Arlo cloud capability documents (`/resources/capabilities/<model>/...`):
* **Feature Detection:** Evaluates motion detection (PIR and video analytics), audio detection, sirens, spotlights, floodlights, ambient sensors (temperature, humidity, air quality), and power source types (battery vs AC-only).
* **Startup Priming & Caching:** Capability documents are eagerly primed during initial discovery for instantaneous synchronous capability queries.
* **Robust Static Fallbacks:** Seamlessly falls back to built-in rules if offline, on cache miss, or on legacy hardware.

### 2. Native WebRTC SIP Streaming Protocol (`pyaarlo.sip`)
* **Sub-Second Streaming:** Implements full client-side WebRTC signaling via Arlo's SIP protocol for cameras declaring SIP capability.
* **Trickle ICE & Signaling:** Debounced trickle-ICE candidate buffering, reverse SDP candidate splicing, and automated STUN/TURN server retrieval from Arlo Cloud.
* Media flows directly peer-to-peer between client and camera without transcode overhead.

### 3. Advanced Multi-Factor Authentication (2FA)
* **Step-by-Step Login (`ArloLogin`):** Non-blocking interactive and resumable authentication flow designed for modern UI and headless setups.
* **Push Approval Polling:** Real-time push notification factor polling with automatic factor selection (`tfa_factor_id`).
* **Factor Discovery:** Query available 2FA factors via `PyArlo.tfa_factors()` or the CLI.

### 4. Modern Diagnostic & Control CLI (`pyaarlo`)
* **`pyaarlo capabilities`:** Inspect calculated hardware features across cameras, doorbells, lights, sensors, and base stations, with `--built-in`/`--static` fallback diffing.
* **`pyaarlo siren`:** Dedicated siren CLI group (`on`, `off`, `turn-on`, `turn-off`) supporting individual devices or `all`.
* **`pyaarlo light`:** Control standalone lights, spotlights, and floodlights by friendly name or device ID.
* **`--hass` Flag:** Directly extracts credentials and active session cache from Home Assistant's configuration directory.

---

## 📦 Installation & Upgrading

Install the beta release via pip:

```bash
pip install pyaarlo==0.9.0-beta.1
```

Or install directly from GitHub tag:

```bash
pip install git+https://github.com/twrecked/pyaarlo.git@v0.9.0-beta.1#pyaarlo==0.9.0-beta.1
```
