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

### 7. First-Class Siren Device & CLI (`ArloSiren`, `pyaarlo siren`)
Sirens are now first-class devices in PyAarlo rather than secondary methods on other objects:
* **`ArloSiren` Class (`pyaarlo.siren`)**:
  - `siren.is_on`, `siren.siren_state`
  - `await siren.turn_on(duration=..., volume=...)`
  - `await siren.turn_off()`
* **Collections & Lookups**:
  - `arlo.sirens`: list of discovered sirens (integrated camera/doorbell/hub sirens and standalone sirens)
  - `arlo.lookup_siren_by_id(...)`, `arlo.lookup_siren_by_name(...)`
* **CLI Siren Group (`pyaarlo siren`)**:
  ```bash
  # Control individual siren by device or parent name:
  pyaarlo siren on "Front" -d 60 -v 8
  pyaarlo siren off "Front"

  # Control all sirens simultaneously:
  pyaarlo siren on all
  pyaarlo siren off all

  # List sirens:
  pyaarlo list sirens
  ```

### 8. Unified Camera Spotlights & Floodlights (`ArloLight`, `pyaarlo light`)
Following the pattern established for sirens, camera spotlights and floodlights are now instantiated as first-class `ArloLight` devices:
* **Unified Light Management**: Camera spotlights and floodlights appear directly in `arlo.lights` and `arlo.all_devices`.
* **Standard Light Controls**: `light.turn_on()`, `light.turn_off()`, `light.set_brightness()`, `light.is_on`, and `light.brightness` work uniformly across standalone smart lights and camera lights.
* **Camera Method Delegation**: `camera.spotlight_on()`, `camera.spotlight_off()`, `camera.set_spotlight_brightness()`, `camera.floodlight_on()`, `camera.floodlight_off()`, and `camera.set_floodlight_brightness()` transparently delegate to the camera's child light while retaining backwards compatibility.
* **CLI Light Group (`pyaarlo light`)**:
  ```bash
  # Control camera spotlight or floodlight by camera name:
  pyaarlo light on "Driveway" -b 200
  pyaarlo light off "Driveway"
  pyaarlo light brightness 128 "Front"

  # Control all lights simultaneously:
  pyaarlo light on all
  pyaarlo light off all
  ```

### 9. Dynamic 2FA Factor Selection & Resumable Login (PR #225)
*Contributed by [Edwin ANNE](https://github.com/edwin-anne) (@edwin-anne).*
* **Exact Factor Selection (`tfa_factor_id`)**: Supports selecting an exact 2FA factor ID ahead of nickname/type guessing—essential for accounts with multiple phones or email addresses.
* **Resumable Step-by-Step Login (`ArloLogin`, `LoginStep`)**: Adds a state-machine login workflow designed for UI setup wizards. Suspends at the factor selection step so UIs can display the real account factors, then handles push polling or code submission.
* **Reliable Push Approval**: Polls according to `tfa_push_timeout` and `tfa_push_poll` (default 300s, matching the official Arlo web client) and terminates immediately on denied requests (error 9239).
* **Factor Listing**: Added `PyArlo.tfa_factors()` and CLI command `pyaarlo tfa-factors`.
* **Persistent User-Agent Pairing**: Preserves paired browser user agents across logins to maintain Arlo cloud trust.

---

## 👥 Contributors
Special thanks to **[Edwin ANNE](https://github.com/edwin-anne)** (@edwin-anne) for contributing PR [#225](https://github.com/twrecked/pyaarlo/pull/225) (Dynamic 2FA factor selection and step-by-step login).
