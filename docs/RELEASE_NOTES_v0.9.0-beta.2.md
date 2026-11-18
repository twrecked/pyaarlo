# 🚀 PyArlo v0.9.0-beta.2 — Release Notes

> Version `0.9.0-beta.2` is a targeted update for the **PyArlo v0.9 architecture**, delivering real-time contact sensor event handling for Arlo Security Systems (Keypad Sensor Hub) and refining Home Assistant CLI environment support.

---

## 🌟 What's New in v0.9.0-beta.2

### 1. MS1001 Real-Time Contact State on Keypad Sensor Hub (SH1001)
* **Real-Time Open/Close Events ([#1190](https://github.com/twrecked/hass-aarlo/issues/1190)):** Arlo Keypad Sensor Hubs (`SH1001`) publish door/window open and close transitions via location-level `automation/exceptionSensors` event streams rather than per-device MQTT topics.
* **Child Event Routing:** `ArloLocation` now captures `automation/exceptionSensors` and delegates events to child `ArloSensor` devices.
* **Sensor-Level Event Handling:** `ArloSensor.handle_exception_sensors()` parses exception state across all modes, updating `contactState` in real time (`True` when open in any mode, `False` when closed or omitted).

### 2. Improved Home Assistant CLI Options (`--hass` & `--hass-dir`)
* **`--hass` Flag:** Converted to a pure boolean flag (defaults to `/config`), ideal for container and Home Assistant OS environments without requiring path arguments.
* **`--hass-dir <PATH>` Option:** Added an explicit directory option that implies `--hass`, ideal for development environments and host-level access to bind-mounted Home Assistant directories.
* **Full Toolchain Support:** Fixed parameter handling so `--hass` and `--hass-dir` operate seamlessly across `pyaarlo`, `pyaarlo-monitor`, and `pyaarlo-utils`.

---

## 📦 Installation & Upgrading

Install the beta release via pip:

```bash
pip install pyaarlo==0.9.0-beta.2
```

Or install directly from GitHub tag:

```bash
pip install git+https://github.com/twrecked/pyaarlo.git@v0.9.0-beta.2#pyaarlo==0.9.0-beta.2
```
