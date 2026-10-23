# 🚀 PyArlo v0.9.0-alpha.3 — Release Notes

> ### ⚠️ Alpha Pre-Release & Community Testing Notice
> This is the third alpha pre-release for the **v0.9 native `asyncio` rewrite**.
> 
> Version `0.9.0-alpha.3` focuses on **session transaction co-location**, **resilient filesystem persistence**, and **CLI inline live stream execution**.
> 
> Feedback from users with diverse Arlo hardware remains vital! Please report any regressions or unhandled events on [GitHub Issues](https://github.com/twrecked/pyaarlo/issues) with diagnostic logs generated via `--debug-report`.

---

## 🌟 What's New in v0.9.0-alpha.3

### 1. Transaction Co-Location in `ArloSession`
In Arlo's architecture, asynchronous device notifications and resource-state changes require waiting for a correlated reply packet over MQTT/SSE:
- **Unified Request Tracking:** Pending stream transactions (`_requests`, `_requests_empty_event`) now live directly within `ArloSession`, placing stream transactions on the same architectural level as in-flight HTTP calls.
- **Symmetric Draining:** Added `session.drain_transactions(timeout=5.0)` and unified `await session.drain(in_flight_timeout=2.0, transactions_timeout=5.0)` to gracefully finish active transactions during token rotation and re-login.
- **Clean Backend Decoupling:** `ArloBackEnd` no longer manages low-level transaction dicts or regex matching, delegating incoming event correlation cleanly to `session.signal_transaction_completed()`.

### 2. Defensive Filesystem & Directory Auto-Creation
- **Missing Cache Path Resilience:** Resolved an issue where saving cookies or session state on a clean system or container failed with `FileNotFoundError: [Errno 2]` if `~/.cache/pyaarlo/` had not yet been created.
- `session.save()` and `session.save_cookies()` now ensure all parent directories exist prior to writing, with defensive exception handling so filesystem hiccups never crash authentication.

### 3. CLI Live Stream Support for Inline Commands
- One-shot CLI device commands (`pyaarlo light turn-on`, `pyaarlo light turn-off`, `pyaarlo light brightness`, and `pyaarlo location set-mode`) now automatically spin up the background event stream when `--inline` is provided.
- Commands remain fast and lightweight by default, but with `--inline` they wait for live confirmation from hardware over the MQTT event stream before returning.

### 4. Co-Located Log Encryption Service (`pyaarlo-log-encrypter`)
- Moved the Google App Engine log encryption service (`https://aarlo-dot-twrecked-tools.nn.r.appspot.com`) directly into the repository under `pyaarlo-log-encrypter/` (mirroring the structure of `momentary-device-editor` in `hass-momentary`).
- Includes a clean `app.yaml`, standalone local execution support without external GCP dependencies, web UI templates, and deployment documentation, paving the way to deprecate the separate `pyaarlo-tfa-helper` repository.

---

## 📦 Upgrading to v0.9.0-alpha.3

Install or upgrade directly from the `v0.9-async-refactor` branch:

```bash
pip install --upgrade git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.3
```

Verify your installed version:
```bash
pyaarlo --help
```
