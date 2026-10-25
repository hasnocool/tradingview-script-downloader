#!/usr/bin/env python3
"""Compatibility entry point for fetching public open-source indicators."""

from fetch import main

if __name__ == "__main__":
    raise SystemExit(
        main(default_feeds="indicators", default_output="PineScripts_Indicators")
    )
