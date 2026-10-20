# PyArlo

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

An asynchronous Python library and command-line automation toolkit for Netgear/Arlo security cameras, doorbells, lights, sensors, and base stations.

---

> ### ⚠️ Alpha Release Notice (`v0.9.0-alpha.1`)
>
> **PyArlo v0.9 is a major rewrite transitioning the entire codebase from legacy synchronous threads to native Python `asyncio`.**
>
> **This is an active alpha release — please expect bugs, edge cases, and evolving APIs.**
>
> *Note on Hardware Testing:* The maintainer does not own or have access to every Arlo hardware model (such as all generations of cameras, floodlights, doorbells, chimes, and SmartHubs) and cannot test every permutation. Community testing and feedback are essential to stabilizing this release!
>
> If you encounter issues, regressions, or unexpected behavior with your hardware, please [open a GitHub issue](https://github.com/twrecked/pyaarlo/issues). Please include your Python version, Arlo device models, and sanitized/encrypted debug logs generated with `--debug-report`.
>
> If you need the legacy synchronous documentation for PyArlo v0.8, it is archived in [README_v8.md](README_v8.md).

---

## Table of Contents
- [Breaking Changes in v0.9](#breaking-changes)
- [Installation](#installation)
- [Command Line Interface (CLI)](#command-line-interface)
- [Using the Python Module](#using-the-python-module)
- [Two-Factor Authentication (2FA)](#two-factor-authentication)
- [Operational Notes & Recommendations](#notes--recommendations)
- [Diagnostics & Error Reporting](#diagnostics--error-reporting)
- [Documentation Links](#documentation-links)
- [Credits](#credits)

---

<a name="breaking-changes"></a>
## Breaking Changes in v0.9

If you are upgrading from PyArlo `0.8.x`, please note the following architectural changes:

1. **Native `asyncio` Core**:
   - `PyArlo` must be initialized with the asynchronous factory `await PyArlo.create(...)`. The synchronous `PyArlo(...)` constructor is deprecated.
   - All network and device actions are now coroutines and must be `await`ed (e.g. `await light.turn_on()`, `await location.set_mode()`, `await arlo.stop()`).
2. **`synchronous_mode` renamed to `inline_mode`**:
   - `inline_mode=True` tells PyArlo to wait for an operation's response or event acknowledgment inline before returning.
   - Legacy `synchronous_mode` remains as a deprecated alias.
3. **Execution & Startup Optimizations**:
   - `start_background=False`: Fast one-shot mode that skips connecting to persistent MQTT/SSE event streams and cron loops.
   - `refresh_devices=False`: Skips querying `/users/devices` and reuses locally cached device definitions.
   - Optimistic token reuse: Valid session tokens are reused directly without making redundant network calls to `/api/validateAccessToken`.
4. **CLI Reorganization**:
   - The CLI has been split into three purpose-built tools: `pyaarlo`, `pyaarlo-monitor`, and `pyaarlo-utils`.

---

<a name="installation"></a>
## Installation

Requires **Python >= 3.10**.

```bash
# Install latest release from git
pip install git+https://github.com/twrecked/pyaarlo.git

# Or install locally in editable mode for development
git clone https://github.com/twrecked/pyaarlo.git
cd pyaarlo
pip install -e .
```

---

<a name="command-line-interface"></a>
## Command Line Interface (CLI)

PyArlo provides three command-line tools:

### 1. `pyaarlo` — Device Actions & Automations
Perform instant actions on your devices with sub-second response times:

```bash
# Check token status and expiration
pyaarlo login --status

# Interactive configuration wizard (creates or updates ~/.config/pyaarlo/config.json)
pyaarlo config create
pyaarlo config update
pyaarlo config show

# Authenticate or refresh tokens (supports push, email:imap, sms)
pyaarlo login --push

# Control lights by name or ID
pyaarlo light turn-on "Side Light"
pyaarlo light turn-on --brightness 128 "Side Light"
pyaarlo light turn-off "Side Light"

# Security modes
pyaarlo location list
pyaarlo location set-mode "armHome"

# Media library
pyaarlo media list --days 1 --compact
pyaarlo media list --object animal
pyaarlo media download --limit 5 -o ./media

# Local storage (RATLS direct USB/SD access on SmartHub / Base Station)
pyaarlo local-media status "Front Base"
pyaarlo local-media list --base "Front Base" --compact
pyaarlo local-media download --base "Front Base" --limit 5 -o ./local_media

# List devices and status
pyaarlo list devices --compact
```

### 2. `pyaarlo-monitor` — Real-Time Event Stream
Observe incoming live events (motion, doorbell rings, battery, mode changes):

```bash
# Stream live events
pyaarlo-monitor --compact

# Filter by camera and truncate long payloads
pyaarlo-monitor --filter-device "Front Door Bell" -l 60

# Stream events formatted as JSON lines
pyaarlo-monitor --json
```

### 3. `pyaarlo-utils` — Diagnostic Tools
```bash
# Dump raw device dictionaries
pyaarlo-utils dump lights

# Anonymize logs and encrypt for GitHub issue reporting
cat error.log | pyaarlo-utils anonymize | pyaarlo-utils encrypt > error.log.enc
```

👉 See [docs/cli.md](docs/cli.md) for full configuration, arguments, and options.

---

<a name="using-the-python-module"></a>
## Using the Python Module

```python
import asyncio
from pyaarlo import PyArlo

async def main():
    # Initialize the PyArlo controller
    arlo = await PyArlo.create(
        username="user@example.com",
        password="your-password",
        tfa="push",
    )

    try:
        # Access devices
        for cam in arlo.cameras:
            print(f"Camera: {cam.name} (Battery: {cam.battery_level}%)")

        for light in arlo.lights:
            if not light.is_on:
                await light.turn_on(brightness=200)

        # Set location mode
        if arlo.locations:
            await arlo.locations[0].set_mode("armHome")

    finally:
        # Cleanly stop background tasks and connections
        await arlo.stop(logout=False)

if __name__ == "__main__":
    asyncio.run(main())
```

### Subscribing to Live Events
```python
def on_event(device, attr, value):
    print(f"[{device.name}] {attr} -> {value}")

# Subscribe to motion on a camera
camera.add_attr_callback("motionDetected", on_event)

# Subscribe to doorbell presses
doorbell.add_attr_callback("ding", on_event)

# Subscribe to all events on a device
camera.add_attr_callback("*", on_event)
```

👉 See [docs/api.md](docs/api.md) for detailed API documentation and one-shot execution patterns.

---

<a name="two-factor-authentication"></a>
## Two-Factor Authentication (2FA)

PyArlo supports three primary 2FA methods:

### 1. Push Notification (`push`) — Recommended
When logging in, Arlo sends a push notification to your trusted mobile device. PyArlo waits for you to tap "Approve".

- **CLI:** `pyaarlo login --push` or `export ARLO_TFA="push"`
- **Python:**
  ```python
  arlo = await PyArlo.create(username="...", password="...", tfa="push")
  ```

### 2. Email via IMAP (`email:imap`) — Automated
PyArlo connects to your email account over IMAP and automatically reads the verification code from the email sent by Arlo.

- **CLI:**
  ```bash
  pyaarlo login --tfa email:imap --tfa-host imap.gmail.com --tfa-user user@gmail.com --tfa-pass "app-password"
  ```
- **Python:**
  ```python
  arlo = await PyArlo.create(
      username="...", password="...",
      tfa="email:imap",
      tfa_host="imap.gmail.com", tfa_username="...", tfa_password="..."
  )
  ```

### 3. Interactive Console (`email:console` or `sms`)
PyArlo requests Arlo to send a code via email or SMS, and prompts you to type the code into the terminal.

- **CLI:** `pyaarlo login --tfa sms` or `pyaarlo login --tfa email:console`
- **Python:**
  ```python
  arlo = await PyArlo.create(username="...", password="...", tfa="sms")
  ```

---

<a name="notes--recommendations"></a>
## Operational Notes & Recommendations

### Choosing an Event Stream Backend (MQTT vs. SSE)
PyArlo supports two streaming backends for real-time device updates:

1. **MQTT (`mqtt`) — Default**:
   - Modern, lightweight WebSocket protocol used by Arlo's official mobile apps.
   - **Supports multiple concurrent connections**: you can run `pyaarlo-monitor` in one terminal while running action commands or scripts in another without interrupting your session.
   - *Limitation*: Arlo does not publish every legacy event type (such as stream snapshot notifications) over MQTT.
2. **SSE (`sse`) — Legacy**:
   - HTTP Server-Sent Events stream (`/subscribe`).
   - Emits a broader range of legacy event types (like stream snapshots).
   - *Limitation*: Arlo restricts SSE to a **single active connection** per account. Opening a second stream will disconnect the first. You can select it with `--backend sse` or `--sse` on `pyaarlo-monitor`.

### Dedicated Arlo Account Recommendation
Even though MQTT allows concurrent event streams with your primary mobile app without immediately logging you out, **we strongly recommend creating a separate, dedicated Arlo account and sharing your cameras/devices to it**:
- **Security & Least Privilege**: Protects your primary account credentials and limits access strictly to the shared devices.
- **Session Stability**: Prevents token refresh races and conflicting login state between automation scripts, Home Assistant, and your mobile phone app.

---

<a name="diagnostics--error-reporting"></a>
## Diagnostics & Error Reporting

### Automated Debug Report (`--debug-report`)
You can append `--debug-report` to any `pyaarlo` command. It automatically records all debug logs, anonymizes sensitive tokens/passwords, and encrypts the diagnostic package using PyArlo's public key:

```bash
pyaarlo --debug-report light turn-on "Side Light"
pyaarlo --debug-report login
```
This writes `pyaarlo-debug-report.enc`, which you can safely attach directly to a [GitHub Issue](https://github.com/twrecked/pyaarlo/issues).

### Enabling Verbose Logs
Pass `-v` (INFO) or `-vv` (DEBUG) to any CLI tool, or enable debug logging in Python:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Anonymizing & Encrypting Diagnostics for Issues
To safely report bugs without exposing personal credentials, device IDs, or tokens:

```bash
# Anonymize account identifiers and encrypt using PyArlo's public key
cat trace.log | pyaarlo-utils anonymize | pyaarlo-utils encrypt > trace.log.enc
```
You can paste the resulting `-----BEGIN PYAARLO DUMP-----` block directly into a [GitHub Issue](https://github.com/twrecked/pyaarlo/issues). Only the repository maintainers holding the private key can decrypt it.

### Recording Browser Traffic (.har)
If troubleshooting unexpected Arlo web changes:
1. Open [my.arlo.com](https://my.arlo.com) in Chrome/Firefox.
2. Open Developer Tools (`F12`), switch to the **Network** tab, and check **Preserve log**.
3. Perform the action (e.g. view stream, arm device, toggle light).
4. Right-click any network request and select **Save all as HAR with content**.
5. Anonymize and encrypt the `.har` file using `pyaarlo-utils` before sharing.

---

<a name="documentation-links"></a>
## Documentation Links

- [CLI Reference Guide](docs/cli.md) — Complete manual for `pyaarlo`, `pyaarlo-monitor`, and `pyaarlo-utils`.
- [Python API Reference](docs/api.md) — Asynchronous API documentation, classes, and lifecycle options.
- [Legacy v0.8 Documentation](README_v8.md) — Preserved synchronous v0.8 documentation.

---

<a name="credits"></a>
## Credits

Special thanks to:
* [Pyarlo](https://github.com/tchellomello/python-arlo) and [Arlo](https://github.com/jeffreydwalter/arlo) for the original foundational reverse-engineering work.
* [JetBrains](https://www.jetbrains.com/?from=hass-aarlo) for supporting the project with open source development licenses.
