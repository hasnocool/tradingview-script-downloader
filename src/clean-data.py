#!/usr/bin/env python3
"""Compatibility wrapper for the organized cleaner."""

from __future__ import annotations

import runpy
from pathlib import Path

target = (
    Path.home()
    / "Projects"
    / "TradingScriptDownloaders"
    / "tradingview-publication-downloader"
    / "clean-data.py"
)
runpy.run_path(str(target), run_name="__main__")
