#!/usr/bin/env python3
"""Compatibility entry point for fetching Editors' Picks scripts."""

from fetch import main

if __name__ == "__main__":
    raise SystemExit(
        main(default_feeds="editors-picks", default_output="PineScripts_Editors-Picks")
    )
