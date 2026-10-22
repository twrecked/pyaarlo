# 🚀 PyArlo v0.9.0-alpha.1 — Native Asyncio Rewrite

> ### ⚠️ Alpha Release & Community Testing Notice
> **PyArlo v0.9 is a major rewrite transitioning the entire codebase from legacy synchronous threads and locks to native Python `asyncio`.**
>
> This is an active alpha pre-release. While the core architecture is significantly faster and non-blocking, Arlo has dozens of camera models, SmartHubs, doorbells, and floodlights with varying firmware versions.
>
> **Community feedback and testing are vital!** If you encounter bugs, unhandled events, or regressions, please [open a GitHub issue](https://github.com/twrecked/pyaarlo/issues) with your hardware models and diagnostic logs generated via `--debug-report`.
>
> *(Legacy synchronous v0.8 documentation is archived in [README_v8.md](README_v8.md)).*

---

## 🌟 Highlights

### 1. Native `asyncio` Architecture (Python >= 3.10)
- **Async Factory Lifecycle:** Initialization now uses `await PyArlo.create(...)`, running cleanly on single-threaded asyncio event loops with zero loop-blocking calls.
- **Async Device Operations:** All hardware commands (`camera.turn_on()`, `camera.turn_off()`, `camera.get_stream()`, `camera.request_snapshot()`, `camera.get_video()`, `light.set_brightness()`, `base.set_mode()`, `base.siren_on()`, `doorbell.silence_on()`, etc.) are native coroutines.
- **Non-Blocking Clean Shutdown:** `await arlo.stop(logout=...)` gracefully terminates persistent streams and worker tasks.
- **Convenience Property Setters:** Common properties (`is_on`, `brightness`, `siren_state`, `is_silenced`) provide synchronous property setters (e.g. `camera.brightness = 1`, `light.is_on = True`) that automatically schedule the async methods in the background without throwing unawaited coroutine warnings.

### 2. Session & Authentication Overhaul
- **`curl_cffi` as Default Backend:** Uses modern browser TLS fingerprint impersonation (`chrome131`) to bypass Cloudflare anti-bot checks reliably out of the box, with `cloudscraper` and `requests` remaining as optional fallbacks.
- **Dynamic Token Expiry & Automated Renewal:** Automatically tracks session token lifetime and re-authenticates 5 minutes before expiration, eliminating the 2-hour disconnect problem without brute-force reconnect loops.
- **Optimistic Token Reuse:** Skips redundant `/api/validateAccessToken` round-trips on connect when a valid cached session exists on disk.
- **Unified 2FA Specification:** Streamlined two-factor configuration supporting `tfa="email:imap"` (recommended for automated/headless environments), `tfa="push"`, and `tfa="sms"`.

### 3. Real-Time Streaming & Performance
- **MQTT over WebSockets Default (`backend="auto"`):** Connects to Arlo's modern push event stream, dynamically parsing broker URLs from authentication responses. Supports concurrent sessions and lighter overhead.
- **Zero Event Loop Blocking:** SSL context creation (`ssl.create_default_context()`), synchronous MQTT connect calls, and pickle cache operations are safely offloaded to worker threads via `asyncio.to_thread`.
- **Fast One-Shot Mode:** Scripts needing only quick actions or metadata inspection can pass `start_background=False` and `refresh_devices=False` for sub-second execution without starting background event loops.
- **Single-Packet Nightlight Batching:** Added `await camera.set_nightlight(...)` to bundle brightness, RGB color, temperature, and mode into a single network packet.

### 4. Modular Architecture & Packaging
- Clean modular decomposition under `pyaarlo.core.*` (`backend`, `tasks`, `cfg`, `storage`, `logger`).
- Packaging in `setup.py` updated with `find_packages()` to bundle all submodules (`pyaarlo.core`, `pyaarlo.core.backend`, `pyaarlo.cli`, `pyaarlo.utils`).
- Split CLI into three dedicated tools: `pyaarlo`, `pyaarlo-monitor`, and `pyaarlo-utils`.
- Dedicated `pyaarlo.packet` sub-logger for granular control over verbose packet dumps.

---

## 📋 Breaking Changes & Migration from v0.8

1. **Python Version:** Requires Python **>= 3.10**.
2. **Async Factory:** Replace synchronous `PyArlo(...)` instantiation with:
   ```python
   arlo = await PyArlo.create(username="...", password="...", tfa="push")
   try:
       ...
   finally:
       await arlo.stop()
   ```
3. **`await` Device Actions:** Coroutine methods must be awaited (e.g. `await camera.get_stream()`, `await light.turn_on()`, `await base.set_mode("armHome")`).
4. **Renamed Parameter:** `synchronous_mode` has been renamed to `inline_mode` (with backward-compatibility alias).
5. **Logging:** Packet tracing is now routed to `pyaarlo.packet`. Enable via:
   ```python
   logging.getLogger("pyaarlo.packet").setLevel(logging.DEBUG)
   ```
