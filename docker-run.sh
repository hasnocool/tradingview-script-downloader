#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$(pwd)/PineScripts"
docker run --rm \
  -v "$(pwd)/PineScripts:/data/PineScripts" \
  tradingview_pinescript_downloader "$@"
