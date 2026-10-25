#!/usr/bin/env bash
set -euo pipefail

downloads="${TRADING_SCRIPT_DOWNLOADS:-${TRADING_SCRIPT_DOWNLOAD_ROOT:-$HOME/Projects/TradingScriptDownloads}}"
mkdir -p "$downloads/Pine/TradingView" "$downloads/Indexes" "$downloads/Logs" "$downloads/Backups"
docker run --rm \
  -v "$downloads:/data" \
  tradingview_pinescript_downloader \
  --output /data/Pine/TradingView "$@"
