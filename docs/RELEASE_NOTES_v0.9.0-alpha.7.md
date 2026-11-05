# 🚀 PyArlo v0.9.0-alpha.7 — Release Notes

> ### ⚠️ Alpha Pre-Release & Community Testing Notice
> This is the seventh alpha pre-release for the **v0.9 native `asyncio` rewrite**.
> 
> Version `0.9.0-alpha.7` introduces **media retention policies and automated disk space management**, including an offline **`pyaarlo media prune`** CLI command, background retention pruning in `ArloMediaDownloader`, and recording timestamp preservation.
> 
> Feedback from users with diverse Arlo hardware remains vital! Please report any regressions or unhandled events on [GitHub Issues](https://github.com/twrecked/pyaarlo/issues) with diagnostic logs generated via `--debug-report`.

---

## 🌟 What's New in v0.9.0-alpha.7

### 1. Automated Media Retention in `ArloMediaDownloader`
- **`media_retention_days` Option:** Configure a retention policy in days (default: `0` = retain indefinitely).
- **Non-Blocking Background Tasks:** When retention is configured, `ArloMediaDownloader` schedules an initial cleanup pass 30 seconds after startup and continues running daily retention passes every 24 hours.
- **Async Safety:** All file system scanning, age calculation, file unlinking, and empty directory removal execute inside a threadpool executor (`loop.run_in_executor`), ensuring the asyncio event loop is never blocked.
- **Clean Subdirectory Pruning:** Bottom-up directory cleanup removes empty date subfolders (e.g. `YYYY/MM/DD/`) while strictly preserving the base media directory root.

### 2. Standalone Offline CLI Pruner (`pyaarlo media prune`)
- **Cloud-Free Local Operation:** `pyaarlo media prune` directly inspects local disk directories without logging into Arlo Cloud or requiring 2FA.
- **Simulation Mode (`--dry-run`):** Accurately calculates and displays all candidate files, their age, their file size, and the total reclaimable disk space without modifying any files.
- **Full File Listing (`--list`):** Detailed breakdown of all prunable files and timestamps.
- **Targeted Filters:** Filter pruners by directory (`--dir`), retention cutoff (`--days`), or camera name/serial (`-c`, `--camera`).
- **Interactive Safeguard:** Prompts for interactive confirmation before deleting files unless `-y`/`--yes` is supplied.

### 3. Recording Creation Timestamp Alignment
- **Accurate File Timestamps (`os.utime`):** Downloaded videos and snapshots now have their filesystem modification timestamps aligned with their actual cloud recording creation date (`created_at`). This ensures accurate age tracking and retention pruning even if media files are fetched from the cloud days after recording.

---

## 📦 Upgrading to v0.9.0-alpha.7

Install or upgrade directly from the `v0.9-async-refactor` branch:

```bash
pip install --upgrade git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.7
```

Verify your installed version:

```bash
pyaarlo --version
```
