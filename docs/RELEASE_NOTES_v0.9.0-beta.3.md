# 🚀 PyArlo v0.9.0-beta.3 — Release Notes

> Version `0.9.0-beta.3` enhances shared account diagnostics and permissions detection across the library and CLI toolchain.

---

## 🌟 What's New in v0.9.0-beta.3

### 1. Shared Device Permissions Detection & Warning
* **Ownership and Rights Properties:** Added `owner_id`, `is_shared`, and `has_access_rights` properties to `ArloDevice`.
* **Restricted Account Detection:** Detects when devices are shared from another primary account without full administrative privileges (`userRole != "ADMIN"`, typically `GUEST`).
* **Startup Warning:** `PyArlo` logs an explicit warning during device discovery when restricted shared devices are encountered, guiding users to enable "Allow Access Rights" in the primary Arlo app under Settings → Grant Access.

### 2. CLI Shared Device Visibility & Status
* **Device List Status (`pyaarlo list`):** The `list` command now outputs device access status (`Owner`, `Shared (ADMIN)`, or `Shared (GUEST - Restricted: No Access Rights ⚠️)`), including concise badges in `--compact` mode.
* **Cached Login Status (`pyaarlo login --status`):** Highlights restricted shared devices directly from the cache so users can diagnose permission problems without making live cloud calls.
* **Cache Persistence:** `fill_cache` records `is_shared`, `has_access_rights`, and `user_role` across base stations, cameras, lights, doorbells, sensors, and sirens.

---

## 📦 Installation & Upgrading

Install the beta release via pip:

```bash
pip install pyaarlo==0.9.0-beta.3
```

Or install directly from GitHub tag:

```bash
pip install git+https://github.com/twrecked/pyaarlo.git@v0.9.0-beta.3#pyaarlo==0.9.0-beta.3
```
