---
name: Stale root requirements.txt
description: Root requirements.txt drifted from pyproject.toml (had flask + pinned old python-telegram-bot==20.8), causing a slow pip dependency backtrack when installing an unrelated package.
---

In this Python project, `pyproject.toml` is the real source of truth for dependencies, but a `requirements.txt` also existed at the repo root and had drifted out of sync (contained `flask` that was never used, plus a stale `python-telegram-bot==20.8` pin that conflicted with the actually-installed 22.x version).

**Why:** Running `installLanguagePackages` triggers `pip install -r requirements.txt` in addition to installing the requested package. If requirements.txt has stale/conflicting pins, pip's resolver backtracks for a long time trying to satisfy them, making an unrelated install look hung or slow.

**How to apply:** If a package install via the sandbox seems to hang or takes unusually long with heavy "Using cached ... backtracking" output, check `requirements.txt` at the project root for drift from `pyproject.toml` and clean it up (remove unused packages, fix stale version pins) rather than assuming the install itself is broken.
