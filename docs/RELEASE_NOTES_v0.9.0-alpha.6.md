# 🚀 PyArlo v0.9.0-alpha.6 — Release Notes

> ### ⚠️ Alpha Pre-Release & Community Testing Notice
> This is the sixth alpha pre-release for the **v0.9 native `asyncio` rewrite**.
> 
> Version `0.9.0-alpha.6` cleans up repository packaging, deprecating the legacy `bin/` directory scripts in favor of standardized `console_scripts` entry points and editable installs (`pip install -e .`).
> 
> Feedback from users with diverse Arlo hardware remains vital! Please report any regressions or unhandled events on [GitHub Issues](https://github.com/twrecked/pyaarlo/issues) with diagnostic logs generated via `--debug-report`.

---

## 🌟 What's New in v0.9.0-alpha.6

### 1. CLI Packaging Standardization
- **Removed Legacy `bin/` Directory:** The standalone wrapper scripts in `bin/` (`pyaarlo`, `pyaarlo-monitor`, `pyaarlo-utils`, `pyaarlo-encrypt`) have been retired.
- **Native Entry Points:** All CLI tools are managed natively via `setuptools` `console_scripts`:
  - `pyaarlo = pyaarlo.cli.main_cmd:cli`
  - `pyaarlo-monitor = pyaarlo.cli.monitor_cmd:cli`
  - `pyaarlo-utils = pyaarlo.cli.utils_cmd:cli`
- **Editable Development Workflows:** Developers and contributors can test local changes immediately using standard editable installs:
  ```bash
  pip install -e .
  ```

---

## 📦 Upgrading to v0.9.0-alpha.6

Install or upgrade directly from the `v0.9-async-refactor` branch:

```bash
pip install --upgrade git+https://github.com/twrecked/pyaarlo.git@v0.9.0-alpha.6
```

Verify your installed version:
```bash
pyaarlo --help
```
