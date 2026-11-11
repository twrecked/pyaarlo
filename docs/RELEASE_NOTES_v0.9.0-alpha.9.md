# 🚀 PyArlo v0.9.0-alpha.9 — Release Notes

> Version `0.9.0-alpha.9` introduces **dynamic cloud capability resolution** for Arlo devices, eliminating static model hardcoding for motion detection, audio detection, sirens, spotlights, and power sources while providing full backward compatibility through static fallback rules and expanded CLI diagnostics.

---

## 🌟 What's New in v0.9.0-alpha.9

### 1. Dynamic Cloud Capability Evaluation (`pyaarlo.capabilities`)
Previously, device capabilities (such as motion detection, audio detection, built-in siren, battery, and spotlight) were evaluated using static tuples of model prefixes. PyArlo now dynamically evaluates cloud capability documents (`/resources/capabilities/<model>/<model>_<version>.json`):
* **Motion Detection**: Detects triggers from `Automation3.0` (`motionStart`), `Automation` (`PIRMotionDetectionTrigger`, `IVMotionDetectionTrigger`), `AutomationSettings`, `MotionDetectionTest`, and activity/PIR zones.
* **Audio Detection**: Detects `audioStart` and `AudioDetectionTrigger` events.
* **Siren**: Inspects `ResourceTypes: ["Siren"]` and automation siren actions.
* **Battery**: Inspects `PowerSource.Battery` (properly identifying AC-only indoor cameras as non-battery devices dynamically).
* **Spotlight & Floodlight**: Inspects `Spotlight` and `Light` hardware declarations.
* **Ambient Sensors**: Detects temperature, humidity, and air quality sensors for environmental models.

### 2. Robust Static Fallbacks
If a capability document is not cached (e.g. offline boot, cache miss, or unsupported legacy hardware), PyArlo transparently falls back to the built-in static model rules.

### 3. Startup Capability Cache Priming
During initial discovery (`_refresh_capabilities()`), PyArlo automatically primes the capabilities cache for all detected device models so downstream entities can query capabilities synchronously without network delay.

### 4. Expanded Capabilities CLI (`pyaarlo capabilities`)
* Displays all calculated device capabilities (Motion Detection, Audio Detection, Siren, Spotlight, Floodlight, Battery, SIP Streaming, SIP Push-To-Talk, Full Duplex Talk, and ambient sensors).
* Added `--built-in` / `--static` option to display the legacy static fallback value alongside the calculated value (e.g. `SIP Streaming: True [built-in: False]`).
* Resolves targets across all device classes (`all_devices`), allowing cameras, doorbells, lights, sensors, and base stations to be inspected by friendly name.

### 5. Home Assistant Integration Support (`--hass`)
For environments where Home Assistant is installed alongside `hass-aarlo`, the CLI now supports an explicit `--hass` flag:
```bash
# In standard Home Assistant container/OS environments (defaults to /config):
pyaarlo --hass light "Porch" on

# Or with an explicit Home Assistant configuration directory path:
pyaarlo --hass /home/homeassistant/.homeassistant camera "Driveway" snapshot
```
* **Direct Config Extraction**: Reads `username`, `password`, and 2FA parameters directly from Home Assistant's `.storage/core.config.entries` JSON.
* **Shared Session & Capabilities Cache**: Points `storage_dir` and `cache_dir` directly to `<hass_dir>/.aarlo`, sharing the active login tokens, cookies, and cached capability documents without requiring a new 2FA login challenge.

### 6. Resource Role Evaluation & Types Consolidation (`is_resource`)
Device role classification previously maintained in `pyaarlo.types` has been consolidated into `pyaarlo.capabilities`:
* **`is_resource(res_type)`**: Evaluates device roles (`"camera"`, `"gateway"`, `"doorbell"`, `"light"`, `"siren"`, `"chime"`) directly against Arlo's `ResourceTypes` array in cloud capability documents.
* **`device.is_resource(...)`**: Added convenient role checks directly on `ArloDevice`.
* **Deprecation Shim**: `pyaarlo.types` is now a thin backwards-compatible shim re-exporting `ArloTypes` and `is_resource`.
