#!/usr/bin/env python3
"""Compatibility entry point for fetching public open-source strategies."""

from fetch import main

if __name__ == "__main__":
    raise SystemExit(
        main(default_feeds="strategies", default_output="PineScripts_Strategies")
    )
