# 🚀 PyArlo v0.9.0-alpha.5 — Release Notes

> ### ⚠️ Alpha Pre-Release & Community Testing Notice
> This is the fifth alpha pre-release for the **v0.9 native `asyncio` rewrite**.
> 
> Version `0.9.0-alpha.5` focuses on fixing **Server-Sent Events (SSE) stream connectivity**, **asynchronous chunk iteration**, and **clean stream teardown** with the `curl_cffi` backend (fixing [hass-aarlo#1177](https://github.com/twrecked/hass-aarlo/issues/1177)).
> 
> Feedback from users with diverse Arlo hardware remains vital! Please report any regressions or unhandled events on [GitHub Issues](https://github.com/twrecked/pyaarlo/issues) with diagnostic logs generated via `--debug-report`.

---

## 🌟 What's New in v0.9.0-alpha.5

### 1. Fix SSE Stream Never Connecting (Fixes Issue #1177)
Resolves a critical bug where the SSE event stream failed to connect with `connect failed 400` followed by an `AttributeError` loop:
- **Host Header Normalization:** Removed `host: None` and `Content-Type: None` header assignments. In `curl_cffi`, assigning `None` told `libcurl` to completely strip the `Host:` header, causing Arlo's cloud edge servers to reject every SSE connection with `400 Bad Request`.
- **Native Async Generator Streaming:** Switched `AsyncSession` chunk iteration from `iter_content()` (synchronous generator) to `aiter_content()` (asynchronous generator), fixing `AttributeError: 'generator' object has no attribute '__anext__'`.
- **Clean Stream Teardown & Handle Safety:** 
  - On stream close, signals `STREAM_END` into `resp.queue` and cancels the background stream task, unblocking `queue.get()` immediately without waiting for a new network packet.
  - Avoids calling `resp.close()` on `AsyncSession`, preventing `curl._curl` pointer destruction before `AsyncSession` releases the handle from the `curl_multi` pool.
  - Added a defensive 2.0s timeout with cancellation fallback in `backend.stop()`, ensuring `stop()` never hangs during teardown.

---

## 📦 Upgrading to v0.9.0-alpha.5

Install or upgrade directly from the `v0.9-async-refactor` branch:

```bash
pip install --upgrade git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.5
```

Verify your installed version:
```bash
pyaarlo --help
```
