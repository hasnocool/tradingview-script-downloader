#!/usr/bin/env python3
"""Compatibility entry point for fetching the recent script feed."""

from fetch import main

if __name__ == "__main__":
    raise SystemExit(main(default_feeds="recent", default_output="PineScripts"))
