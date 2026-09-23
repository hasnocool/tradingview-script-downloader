#!/usr/bin/env python3
"""Compatibility entry point for fetching recent and popular scripts."""

from fetch import main

if __name__ == "__main__":
    raise SystemExit(main(default_feeds="recent,popular", default_output="PineScripts"))
