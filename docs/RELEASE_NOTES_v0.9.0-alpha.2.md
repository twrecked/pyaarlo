# 🚀 PyArlo v0.9.0-alpha.2 — Release Notes

> ### ⚠️ Alpha Pre-Release & Community Testing Notice
> This is the second alpha pre-release for the **v0.9 native `asyncio` rewrite**.
> 
> Version `0.9.0-alpha.2` focuses on **session stability**, **robust token renewal**, **request synchronization**, **V3 mode alignment**, and **device API normalization**.
> 
> Feedback from users with diverse Arlo hardware (SmartHubs, wired/wireless doorbells, floodlights, chime units) remains vital! Please report any regressions or unhandled events on [GitHub Issues](https://github.com/twrecked/pyaarlo/issues) with diagnostic logs generated via `--debug-report`.

---

## 🌟 What's New in v0.9.0-alpha.2

### 1. Graceful Token Renewal & In-Flight Request Draining
In high-concurrency environments (like Home Assistant or multi-camera setups), rotating expired tokens can trigger race conditions if requests are dispatched mid-rotation. Alpha 2 makes session rotation rock-solid:
- **Serialized Authentication:** All login and token refresh sequences are strictly serialized behind `_login_lock` with a 10-second debounce check, eliminating double-login churn.
- **In-Flight HTTP Request Draining:** Added `session.drain_in_flight(timeout=2.0)` to allow outgoing HTTP requests to finish before old tokens are invalidated.
- **Stream Transaction Draining:** Added `backend._drain_transactions(timeout=5.0)` to wait for pending transaction confirmations over MQTT before restarting the event stream.
- **Request Pausing:** Non-auth API requests arriving while renewal is actively taking place now pause on `_login_lock` and dispatch cleanly with the fresh token once renewal finishes, completely eliminating transient `401 Unauthorized` errors.
- **Forced Fresh Tokens:** Scheduled renewal now forces a re-authentication handshake rather than reusing an expiring cached token.

### 2. V3 Mode Synchronization & Propagation (Issue #1162)
For users on Arlo's modern V3 experience (Location / Experience-based arming):
- **Base Station Propagation:** Mode changes received via user commands, stream events, or location updates now immediately propagate to all associated base stations.
- **Desync Bypass (`force=True`):** Base stations pass `force=True` when requesting mode updates, ensuring desynced base stations are never blocked by `"no mode change needed"` guards.
- **Stream Reconnect Sync:** Base station refresh sequences now actively synchronize mode state with `location.update_mode()`.

### 3. Device API & Property Normalization
Standardized and normalized getter, setter, and action method naming across all device classes (`ArloDevice`, `ArloCamera`, `ArloDoorBell`, `ArloBaseStation`, `ArloLight`):
- **Lighting Controls:**
  - Standardized spotlight actions: `await camera.spotlight_on()`, `await camera.spotlight_off()`, `await camera.set_spotlight(...)`.
  - Added cached properties: `spotlight_is_on`, `spotlight_state`, and `spotlight_brightness`.
  - Normalized floodlights: `floodlight_is_on`, `floodlight_brightness`, and `await light.set_floodlight(...)`.
  - Normalized nightlights: `nightlight_is_on`, `nightlight_brightness`, and `@property.setter` support.
- **Power & Siren Symmetry:**
  - Added `await set_is_on()` coroutines paired with `@is_on.setter` across Devices, Cameras, and Lights.
  - Added `await set_siren_state()` coroutines paired with `@siren_state.setter` across Cameras, Doorbells, and Base Stations.
  - Added `await set_is_silenced()` paired with `@is_silenced.setter` on Doorbells.
- **Audio Control:** Added speaker volume property and async setter on `ArloCamera`.

### 4. False-Trigger Filtering & Callback Deduplication
- **`recentActivity` Fix:** Fixed a bug where periodic camera status packets containing `"motionDetected": false` or `"audioDetected": false` inadvertently triggered `recentActivity=True`. Strict truthiness is now enforced.
- **Callback Deduplication:** Successive triggers occurring while already active extend the activity timer without re-firing redundant state callbacks.

### 5. Tuned Defaults & Cleaner Logs
- **Reduced Timeouts:** Lowered default `request_timeout` from **60s** to **15s** for faster failure recovery.
- **Tuned Recent Activity:** Lowered default `recent_time` from **600s** (10m) to **120s** (2m).
- **Removed Obsolete `reconnect_every`:** Removed legacy reconnect loops in favor of pure dynamic token renewal.
- **Quieter Debug Logs:** Periodic base station capability checks (`pingCapability`, `sirenState`) moved from `debug` to verbose packet debug (`vdebug`), removing ~50 lines/minute of repetitive log noise.

### 6. Configuration & CLI Improvements
- **Strict Type Coercion:** Enforced strict runtime type coercion for numeric and boolean settings in `ArloCfg` and `ArloTaskManager` to prevent string/type collisions in `asyncio.sleep()`.
- **CLI Configuration Forwarding:** CLI tools now forward all config file parameters (including `recent_time`) to `PyArlo.create()`.
- **Documentation Cleanup:** Moved legacy documentation, guides, and release notes into the `docs/` directory.

---

## 📋 Upgrading

To test this pre-release directly in your environment:

```bash
pip install git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.2
```

*(Or point your Home Assistant custom component `manifest.json` to the release tag).*
