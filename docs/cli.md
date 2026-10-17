# PyArlo Command-Line Interface (CLI) Reference

PyArlo provides three standalone command-line tools:

1. **`pyaarlo`**: End-user automation tool for controlling lights, changing modes, querying media, and checking account status.
2. **`pyaarlo-monitor`**: Real-time event stream listener for observing device activities and state changes live.
3. **`pyaarlo-utils`**: Developer diagnostic utilities for dumping, anonymizing, and encrypting logs.

---

## Configuration & Environment Variables

All three tools share configuration settings. PyArlo resolves settings using the following hierarchy (highest precedence first):

1. **CLI flags** (e.g., `--username`, `--password`, `--backend`)
2. **Environment variables** (prefixed with `ARLO_`)
3. **JSON configuration file** (`~/.config/pyaarlo/config.json` on Linux)
4. **Built-in defaults**

### Configuration File Locations
PyArlo uses standard, OS-preferred directories:
- **Linux:** `~/.config/pyaarlo/config.json`
- **macOS:** `~/Library/Application Support/pyaarlo/config.json`
- **Windows:** `%LOCALAPPDATA%\pyaarlo\config.json`

Example `config.json`:
```json
{
  "username": "user@example.com",
  "password": "your-password",
  "tfa": "push",
  "backend": "mqtt"
}
```

### Environment Variables
| Variable | Description |
|---|---|
| `ARLO_USERNAME` | Arlo account username (email) |
| `ARLO_PASSWORD` | Arlo account password |
| `ARLO_TFA` or `ARLO_TFA_TYPE` | 2FA specification (e.g. `push`, `email:imap`, `email:console`, `sms`) |
| `ARLO_TFA_SOURCE` | Explicit 2FA retrieval source (`push`, `console`, `imap`) |
| `ARLO_TFA_HOST` | IMAP server host for email 2FA (or `IMAP_HOST`) |
| `ARLO_TFA_USERNAME` | IMAP username (or `IMAP_USERNAME`) |
| `ARLO_TFA_PASSWORD` | IMAP app-password (or `IMAP_PASSWORD`) |
| `ARLO_BACKEND` | Event stream backend (`auto`, `mqtt`, `sse`) |
| `ARLO_INLINE_MODE` | Wait inline for commands (`true` / `false`) |
| `ARLO_START_BACKGROUND` | Start background event stream (`true` / `false`) |
| `ARLO_CACHE_DIR` | Custom directory for session and cache files |

---

## Common Options

These flags are available across `pyaarlo`, `pyaarlo-monitor`, and `pyaarlo-utils`:

- `-c, --config <path>`: Path to custom JSON configuration file.
- `-v, --verbose`: Increase verbosity (`-v` for INFO, `-vv` for DEBUG).
- `-u, --username <email>`: Arlo username override.
- `-p, --password <pass>`: Arlo password override.
- `--backend [auto|sse|mqtt]`: Select event stream protocol.
- `--inline / --no-inline`: Wait for operations to complete inline before returning.
- `--ignore-cache`: Bypass local cache and query Arlo servers directly.

---

## 1. `pyaarlo`

### `pyaarlo login`
Authenticates with Arlo, verifies tokens, and updates the local device catalog.

```bash
# Check current authentication status and token expiry times without network calls
pyaarlo login --status

# Login or refresh session
pyaarlo login

# Force a full re-authentication with 2FA even if token is still valid
pyaarlo login --force

# Login using mobile push notification approval
pyaarlo login --push
# or
pyaarlo login --tfa push

# Login using automated IMAP email code retrieval
pyaarlo login --tfa email:imap --tfa-host imap.gmail.com --tfa-user user@gmail.com --tfa-pass "app-password"

# Login prompting for SMS code on terminal
pyaarlo login --tfa sms
```

### `pyaarlo cache`
Manages the local device and location cache stored under your OS cache directory (`~/.cache/pyaarlo/cache.json`).

```bash
# Display cache location, age, device counts, and status
pyaarlo cache show

# Populate or refresh the cache from Arlo
pyaarlo cache fill

# Clear the local cache file
pyaarlo cache clear
```

### `pyaarlo light`
Controls Arlo smart lights and floodlights. Targets can be specified by friendly name (case-insensitive) or device ID, separated by spaces or commas.

```bash
# Turn on lights
pyaarlo light turn-on "Side Light"
pyaarlo light turn-on "Side Light" "Front Light"
pyaarlo light turn-on "Side Light, Front Light"

# Turn on with brightness (0-255)
pyaarlo light turn-on --brightness 128 "Side Light"

# Turn off lights
pyaarlo light turn-off "Side Light"

# Set brightness level directly
pyaarlo light brightness 200 "Side Light"
```

### `pyaarlo location`
Views and modifies location modes (e.g. Armed, Standby).

```bash
# List locations, current active modes, and available modes
pyaarlo location list

# Change location mode
pyaarlo location set-mode "armHome"
pyaarlo location set-mode "standby"
pyaarlo location set-mode "armAway" --location "Home"
```

### `pyaarlo media`
Lists and downloads recordings from Arlo Cloud Storage.

```bash
# List recordings from the last 24 hours (compact view)
pyaarlo media list --days 1 --compact

# Filter recordings by camera
pyaarlo media list -c "Front Door Bell" --days 3

# Filter recordings by detected object (person, vehicle, animal, package, motion)
pyaarlo media list --object animal --compact

# Date range filtering
pyaarlo media list --date 2026-10-17
pyaarlo media list --from 2026-10-10 --to 2026-10-17

# Export recordings metadata as JSON lines
pyaarlo media list --json

# Download latest 5 videos to ./media
pyaarlo media download --limit 5 -o ./media

# Download thumbnails instead of full videos
pyaarlo media download -c "Front Door Bell" --thumbnails --limit 3
```

### `pyaarlo camera`
Interacts with cameras.

```bash
# Request a new snapshot from camera(s)
pyaarlo camera snapshot "Front Door Bell"

# Obtain live stream URL
pyaarlo camera stream "Driveway"

# Start live stream with local ffmpeg capture
pyaarlo camera stream "Driveway" --start-ffmpeg
```

### `pyaarlo list`
Displays discovered devices, locations, or subsystems.

```bash
# List all devices and locations
pyaarlo list

# Filter by type with compact view
pyaarlo list lights --compact
pyaarlo list cameras --compact
pyaarlo list locations --compact
```

---

## 2. `pyaarlo-monitor`

Connects to Arlo's live event stream (MQTT or SSE) and streams incoming events (motion detection, doorbell rings, battery changes, mode updates) in real time.

```bash
# Stream live events (standard formatted view)
pyaarlo-monitor

# Compact single-line format
pyaarlo-monitor --compact

# Limit maximum line/value length (defaults to 80 chars in compact mode)
pyaarlo-monitor --compact -l 60

# Stream events as JSON lines
pyaarlo-monitor --json

# Filter by specific device(s)
pyaarlo-monitor --filter-device "Front Door Bell, Driveway"

# Filter by specific event attributes
pyaarlo-monitor --filter-event "motionDetected,battery,activeMode"

# Exclude noisy attributes
pyaarlo-monitor --exclude-event "signalStrength"

# Force SSE backend instead of MQTT
pyaarlo-monitor --sse
```

---

## 3. `pyaarlo-utils`

Low-level utilities for debugging, diagnostics, and issue reporting.

```bash
# Dump raw device dictionaries
pyaarlo-utils dump all
pyaarlo-utils dump lights

# Anonymize sensitive account IDs from stdin
cat arlo.log | pyaarlo-utils anonymize > arlo-clean.log

# Encrypt data using the PyArlo public key (safe for public issues)
cat arlo-clean.log | pyaarlo-utils encrypt > arlo-clean.log.enc

# Decrypt encrypted data (using private key)
cat arlo-clean.log.enc | pyaarlo-utils decrypt -K ./rsa.private
```
