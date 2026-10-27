# 🚀 PyArlo v0.9.0-alpha.4 — Release Notes

> ### ⚠️ Alpha Pre-Release & Community Testing Notice
> This is the fourth alpha pre-release for the **v0.9 native `asyncio` rewrite**.
> 
> Version `0.9.0-alpha.4` focuses on **push 2FA rate-limit protection** and the new **troubleshooting knowledge base**.
> 
> Feedback from users with diverse Arlo hardware remains vital! Please report any regressions or unhandled events on [GitHub Issues](https://github.com/twrecked/pyaarlo/issues) with diagnostic logs generated via `--debug-report`.

---

## 🌟 What's New in v0.9.0-alpha.4

### 1. Fix SSE Stream Never Connecting (Fixes Issue #1177)
Resolves a critical bug where the SSE event stream failed to connect with `connect failed 400` followed by an `AttributeError` loop:
- **Host Header Normalization:** Removed `host: None` and `Content-Type: None` header assignments. In `curl_cffi`, assigning `None` told `libcurl` to completely strip the `Host:` header, causing Arlo's cloud edge servers to reject every SSE connection with `400 Bad Request`.
- **Native Async Generator Streaming:** Switched `AsyncSession` chunk iteration from `iter_content()` (synchronous generator) to `aiter_content()` (asynchronous generator), fixing `AttributeError: 'generator' object has no attribute '__anext__'`.
- **Safe Handle Teardown:** Cleanly cancels the background streaming task on disconnect, eliminating `TypeError: initializer for ctype 'void *'` in `curl_cffi`'s multi-handle pool.

### 2. Push 2FA Rate-Limit Protection (Ported from #222 by @faresd)
- **Early Exit on Lockout:** When Arlo returns `"Too many requests"`, polling `/api/finishAuth` now terminates immediately on attempt #1 rather than burning 10 retries. Continuing to poll when rate-limited resets and extends Arlo's ~24-hour lockout window; exiting immediately prevents extending the ban.
- **Early Exit on Expiration:** Aborts immediately on attempt #1 if the push prompt expires on Arlo's servers (`"Maximum permitted time for authentication exceeded"`).
- **Clear Guidance:** Logs an actionable error message advising the user that the account is rate-limited and to wait 24 hours before retrying.

### 3. Troubleshooting Knowledge Base (`AGENTS.issues.md`)
- Added a comprehensive diagnostic issue cache and troubleshooting lookup table in `AGENTS.issues.md`.
- Synthesizes 1 year of historical issues across 5 core categories:
  1. Authentication & 2FA (Gmail app passwords, error 9306, error 9261, 401 token renewal).
  2. Device Discovery (ReadTimeouts, Wi-Fi direct camera twins, deactivated camera states).
  3. V3 Modes & Arming (desync bypass, location-to-hub propagation, custom mode automations).
  4. Live Streaming & Snapshots (stale RTSPS URLs, error 2016, snapshot error 2503).
  5. Configuration & Environment (`aarlo.yaml` overrides, entity ID naming, `/tmp` restrictions).

---

## 📦 Upgrading to v0.9.0-alpha.4

Install or upgrade directly from the `v0.9-async-refactor` branch:

```bash
pip install --upgrade git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.4
```

Verify your installed version:
```bash
pyaarlo --help
```
