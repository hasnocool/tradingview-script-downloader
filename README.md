# TradingView Pine Script Downloader

A fast, resumable downloader for **public, open-source TradingView Pine scripts**.

The old implementation used Selenium/Firefox and obsolete CSS selectors. Modern TradingView pages expose the same data directly:

- Publication listings: `www.tradingview.com/.../?component-data-only=1`
- Open-source Pine source: `pine-facade.tradingview.com/pine-facade/get/...`

That means **JavaScript rendering, Selenium, Firefox, and geckodriver are not required**. This is both much faster and substantially lighter than opening a browser tab for every publication.

## Install

Python 3.9+ is supported.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

Download every unique script exposed by the default public feeds:

```bash
python fetch.py
```

The default output is `PineScripts/`. Existing `.pine` files are skipped, so an interrupted run can simply be restarted.

Useful options:

```bash
# Higher I/O concurrency
python fetch.py --workers 64 --listing-workers 12

# Pace requests to reduce the chance of HTTP 429 responses
python fetch.py --workers 32 --rate-limit 40

# Select one or more feeds
python fetch.py --feeds recent,popular
python fetch.py --feeds indicators
python fetch.py --feeds strategies,libraries
python fetch.py --feeds editors-picks

# Small live smoke test
python fetch.py --feeds recent --max-pages 1 --max-scripts 3 --overwrite

# Organize into Indicators/, Strategies/, Libraries/, and Other/
python fetch.py --organize-by-type

# Save clean Pine source without download metadata comments
python fetch.py --no-metadata
```

Run `python fetch.py --help` for every option.

## Feeds and coverage

TradingView does not provide an official, unlimited catalog API for all community publications. Its unauthenticated listing feeds are capped and change over time. At the time this version was tested, the combined recent feed exposed 12,000 items, while popular and Editors' Picks exposed smaller overlapping sets.

The default runs these overlapping feeds and deduplicates by TradingView script ID:

- `recent` — newest `recent_extended` publications
- `popular` — `latest_popular`
- `editors-picks` — Editors' Picks
- `indicators` — the same recent ordering filtered to indicators, extending coverage at the feed boundary
- `strategies` — all strategy items exposed by the strategy feed
- `libraries` — all library items exposed by the library feed

The downloader fetches **all pages and items exposed by the selected feeds**, but it cannot honestly guarantee every publication in TradingView's full catalog when the server enforces a result cap. Protected, invite-only, and closed-source scripts are intentionally skipped because their source cannot be downloaded anonymously.

These JSON routes are frontend endpoints rather than a supported public API, so TradingView could change them in the future. The parser and URL builders are isolated near the top of `fetch.py` to make such changes easy to maintain.

## Output and resume behavior

Files are named with a readable title and the unique TradingView publication ID, for example:

```text
PineScripts/SSL Channel Pro--PERIWBXb.pine
```

The ID prevents title collisions. By default, a short comment header records the title, author, ID, URL, and download time before the Pine source. Use `--no-metadata` for source-only files.

Per-publication failures are appended to:

```text
PineScripts/_download_failures.jsonl
```

A rerun skips completed files and retries failures. Pass `--overwrite` to refresh existing files.

Count only `.pine` files (excluding the JSONL failure log):

```bash
python count.py PineScripts
```

Every run writes three searchable indexes containing title, author, URL, type, dates, description, popularity fields, status, and the relative `.pine` path:

- `index.sqlite3` — indexed relational catalog
- `index.csv` — spreadsheet-friendly catalog
- `index.jsonl` — line-oriented catalog for scripts

Example SQLite query:

```bash
sqlite3 PineScripts/index.sqlite3 \
  "SELECT author, name, url FROM scripts WHERE status='saved' ORDER BY likes_count DESC LIMIT 20;"
```

## Performance notes

This workload is network- and I/O-bound, so one `aiohttp` process with a bounded worker queue is usually faster and more efficient than creating many OS threads. A starting point is:

- `--workers 32` for source requests
- `--listing-workers 8` for catalog pages
- `--rate-limit 40` if TradingView returns `429 Too Many Requests`

Hundreds of browser instances are not beneficial: they consume much more RAM and CPU while generating far more traffic. Tune the HTTP worker count to the connection and rate limits of your host. Retry/backoff is automatic for `429` and transient server failures.

## Tests

Unit tests do not contact TradingView:

```bash
python -m unittest discover -s tests -v
```

The downloader itself can be smoke-tested against the live service with the bounded `--max-scripts` command shown above.

## Docker

```bash
./docker-build.sh
./docker-run.sh
# Arguments after the script are passed to fetch.py:
./docker-run.sh --workers 32 --rate-limit 40
```

Or:

```bash
docker compose up --build
```

## Use and redistribution

Only download publications that TradingView marks as open-source. Preserve each author's license and attribution, follow TradingView's terms, and do not redistribute code in violation of its license. This tool is for personal archival, study, and interoperability work.
