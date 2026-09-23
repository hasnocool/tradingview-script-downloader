#!/usr/bin/env python3
"""Fast asynchronous downloader for public, open-source TradingView Pine scripts.

TradingView exposes the publication metadata and Pine source as JSON.  A browser
is not required: the listing component endpoint returns script IDs, and the
Pine facade returns the source for open publications.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import logging
import math
import os
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import quote, urlencode, urljoin

try:
    import aiohttp
except ImportError as exc:  # pragma: no cover - exercised only before installation
    raise SystemExit(
        "Missing dependency 'aiohttp'. Run: python -m pip install -r requirements.txt"
    ) from exc


TRADINGVIEW_ORIGIN = "https://www.tradingview.com"
DEFAULT_PINE_BASE_URL = "https://pine-facade.tradingview.com/pine-facade"
DEFAULT_OUTPUT = "PineScripts"
DEFAULT_FEEDS = "recent,popular,editors-picks,indicators,strategies,libraries"
PAGE_SIZE = 24
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
USER_AGENT = "TradingViewPineDownloader/2.0 (public open-source script archiver)"
TYPE_DIRECTORIES = {
    "indicator": "Indicators",
    "strategy": "Strategies",
    "library": "Libraries",
}

LOGGER = logging.getLogger("tradingview-downloader")


@dataclass(frozen=True)
class Feed:
    """A TradingView publication feed and its server-side filters."""

    name: str
    path: str = "/scripts/"
    sort: Optional[str] = None
    script_type: str = "all"


FEEDS: Dict[str, Feed] = {
    "recent": Feed("recent", sort="recent_extended"),
    "indicators": Feed("indicators", sort="recent_extended", script_type="indicators"),
    "strategies": Feed("strategies", sort="recent_extended", script_type="strategies"),
    "libraries": Feed("libraries", sort="recent_extended", script_type="libraries"),
    "popular": Feed("popular", sort="latest_popular"),
    "editors-picks": Feed("editors-picks", path="/scripts/editors-picks/"),
}


@dataclass(frozen=True)
class ScriptRef:
    """Only the fields required to request and save a publication."""

    script_id_part: str
    version: str
    public_id: str
    name: str
    author: str
    url: str
    script_type: str
    created_at: str = ""
    updated_at: str = ""
    description: str = ""
    author_id: int = 0
    likes_count: int = 0
    views_count: int = 0
    is_picked: bool = False
    is_hot: bool = False


@dataclass
class Stats:
    pages_fetched: int = 0
    listing_items: int = 0
    listed_total: int = 0
    discovered: int = 0
    duplicates: int = 0
    filtered: int = 0
    saved: int = 0
    skipped_existing: int = 0
    failed: int = 0

    @property
    def attempted(self) -> int:
        return self.saved + self.skipped_existing + self.failed


class DownloadError(RuntimeError):
    """A non-success response or invalid payload from TradingView."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class RateLimiter:
    """Small process-wide request scheduler used when --rate-limit is enabled."""

    def __init__(self, requests_per_second: float) -> None:
        self.interval = 0.0 if requests_per_second <= 0 else 1.0 / requests_per_second
        self.next_request_at = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        if self.interval == 0:
            return
        async with self.lock:
            now = time.monotonic()
            scheduled = max(now, self.next_request_at)
            self.next_request_at = scheduled + self.interval
        delay = scheduled - now
        if delay > 0:
            await asyncio.sleep(delay)


class Downloader:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        args: argparse.Namespace,
        stats: Stats,
        rate_limiter: RateLimiter,
    ) -> None:
        self.session = session
        self.args = args
        self.stats = stats
        self.rate_limiter = rate_limiter
        self.output = Path(args.output).expanduser().resolve()
        self.failure_path = self.output / "_download_failures.jsonl"
        self.queue: asyncio.Queue[ScriptRef] = asyncio.Queue(
            maxsize=max(args.listing_workers * 2, 1)
        )
        self.seen: Set[str] = set()
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self.failure_lock = asyncio.Lock()
        self.downloaded_at = datetime.now(timezone.utc).isoformat()

    def output_path(self, script: ScriptRef) -> Path:
        filename = safe_filename(script.name, script.public_id)
        if self.args.organize_by_type:
            category = TYPE_DIRECTORIES.get(script.script_type.lower(), "Other")
            return self.output / category / filename
        return self.output / filename

    def add_to_catalog(self, script: ScriptRef) -> None:
        path = self.output_path(script)
        try:
            relative_path = str(path.relative_to(self.output))
        except ValueError:
            relative_path = str(path)
        self.catalog[script.script_id_part] = {
            "public_id": script.public_id,
            "script_id_part": script.script_id_part,
            "version": script.version,
            "name": script.name,
            "author": script.author,
            "author_id": script.author_id,
            "url": script.url,
            "script_type": script.script_type,
            "created_at": script.created_at,
            "updated_at": script.updated_at,
            "description": script.description,
            "likes_count": script.likes_count,
            "views_count": script.views_count,
            "is_picked": script.is_picked,
            "is_hot": script.is_hot,
            "status": "pending",
            "file": relative_path,
            "error": "",
            "indexed_at": self.downloaded_at,
        }

    def update_catalog(
        self, script: ScriptRef, status: str, error: Optional[BaseException] = None
    ) -> None:
        record = self.catalog[script.script_id_part]
        record["status"] = status
        record["error"] = str(error) if error else ""

    async def get_json(self, url: str) -> Dict[str, Any]:
        """GET JSON with bounded exponential backoff for transient failures."""
        last_error: Optional[BaseException] = None

        for attempt in range(self.args.retries + 1):
            retry_after = 0.0
            try:
                await self.rate_limiter.wait()
                async with self.session.get(url, allow_redirects=True) as response:
                    status = response.status
                    retry_after = parse_retry_after(response.headers.get("Retry-After"))
                    body = await response.text()

                if not 200 <= status < 300:
                    message = compact_http_message(status, body)
                    error = DownloadError(
                        f"HTTP {status} for {url}: {message}",
                        retryable=status in RETRYABLE_STATUS_CODES,
                    )
                    if not error.retryable or attempt >= self.args.retries:
                        raise error
                    last_error = error
                else:
                    try:
                        payload = json.loads(body)
                    except json.JSONDecodeError as exc:
                        error = DownloadError(
                            f"Invalid JSON from {url}: {exc}", retryable=True
                        )
                        if attempt >= self.args.retries:
                            raise error from exc
                        last_error = error
                    else:
                        if not isinstance(payload, dict):
                            error = DownloadError(
                                f"Expected a JSON object from {url}", retryable=True
                            )
                            if attempt >= self.args.retries:
                                raise error
                            last_error = error
                        else:
                            return payload

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt >= self.args.retries:
                    raise DownloadError(
                        f"Request failed for {url}: {exc}", retryable=False
                    ) from exc
                last_error = exc

            delay = max(retry_after, backoff_delay(attempt))
            if self.args.verbose:
                LOGGER.warning(
                    "Retrying in %.1fs after request error (attempt %d/%d): %s",
                    delay,
                    attempt + 1,
                    self.args.retries + 1,
                    last_error,
                )
            await asyncio.sleep(delay)

        raise DownloadError(f"Request failed for {url}: {last_error}")

    async def discover_feed(self, feed: Feed) -> None:
        """Fetch one feed's page 1, then its remaining pages concurrently."""
        if self.discovery_limit_reached():
            return

        first_payload = await self.get_json(build_listing_url(feed, 1))
        first_data = extract_listing_data(first_payload)
        self.stats.pages_fetched += 1
        self.stats.listed_total += int(first_data.get("total") or 0)
        await self.accept_listing_items(feed, 1, first_data.get("items") or [])

        if self.discovery_limit_reached():
            return

        total = int(first_data.get("total") or 0)
        calculated_last_page = math.ceil(total / PAGE_SIZE) if total else 1
        last_page = self.args.max_pages or calculated_last_page
        if last_page <= 1:
            return

        # This queue only holds page numbers (not publications), so filling it up
        # front-to-back is cheap. The publication queue remains bounded.
        page_queue: asyncio.Queue[int] = asyncio.Queue()
        for page in range(2, last_page + 1):
            page_queue.put_nowait(page)

        async def page_worker() -> None:
            while not self.discovery_limit_reached():
                try:
                    page = page_queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    payload = await self.get_json(build_listing_url(feed, page))
                    data = extract_listing_data(payload)
                    self.stats.pages_fetched += 1
                    await self.accept_listing_items(feed, page, data.get("items") or [])
                finally:
                    page_queue.task_done()

        workers = [
            asyncio.create_task(page_worker(), name=f"listing-{feed.name}-{index}")
            for index in range(min(self.args.listing_workers, max(last_page - 1, 1)))
        ]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise

    async def accept_listing_items(
        self, feed: Feed, page: int, items: Iterable[Any]
    ) -> None:
        for raw_item in items:
            if self.discovery_limit_reached():
                return
            if not isinstance(raw_item, dict):
                self.stats.filtered += 1
                continue

            self.stats.listing_items += 1
            script = parse_script(raw_item)
            if script is None:
                self.stats.filtered += 1
                continue
            if script.script_id_part in self.seen:
                self.stats.duplicates += 1
                continue

            self.seen.add(script.script_id_part)
            self.stats.discovered += 1
            self.add_to_catalog(script)
            await self.queue.put(script)
            if self.args.verbose:
                LOGGER.info(
                    "Queued %s (%s) from %s page %d",
                    script.name,
                    script.public_id,
                    feed.name,
                    page,
                )

    def discovery_limit_reached(self) -> bool:
        return (
            self.args.max_scripts is not None
            and self.stats.discovered >= self.args.max_scripts
        )

    async def download_worker(self) -> None:
        while True:
            script = await self.queue.get()
            try:
                path = self.output_path(script)
                if path.exists() and not self.args.overwrite:
                    self.stats.skipped_existing += 1
                    self.update_catalog(script, "existing")
                    continue

                source_url = build_source_url(
                    script.script_id_part,
                    script.version,
                    self.args.pine_base_url,
                )
                payload = await self.get_json(source_url)
                source = extract_source(payload)
                text = render_pine_file(
                    script,
                    source,
                    self.downloaded_at,
                    include_metadata=not self.args.no_metadata,
                )
                await asyncio.to_thread(write_atomically, path, text)
                self.stats.saved += 1
                self.update_catalog(script, "saved")
                if self.args.verbose:
                    LOGGER.info("Saved %s", path)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep one bad publication from stopping the run
                self.stats.failed += 1
                self.update_catalog(script, "failed", exc)
                LOGGER.error("Failed %s (%s): %s", script.name, script.public_id, exc)
                await self.record_failure(script, exc)
            finally:
                self.queue.task_done()

    async def record_failure(self, script: ScriptRef, error: BaseException) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "id": script.public_id,
            "script_id_part": script.script_id_part,
            "version": script.version,
            "name": script.name,
            "author": script.author,
            "url": script.url,
            "error": str(error),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        async with self.failure_lock:
            await asyncio.to_thread(append_line, self.failure_path, line)

    async def write_indexes(self) -> None:
        rows = sorted(
            self.catalog.values(),
            key=lambda row: (
                str(row["script_type"]).lower(),
                str(row["name"]).casefold(),
                str(row["public_id"]),
            ),
        )
        await asyncio.to_thread(write_catalog_indexes, self.output, rows)


def parse_retry_after(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except ValueError:
        # HTTP-date form is uncommon here; exponential backoff remains safe.
        return 0.0


def backoff_delay(attempt: int) -> float:
    return min(30.0, 0.5 * (2**attempt)) + random.uniform(0.0, 0.25)


def compact_http_message(status: int, body: str) -> str:
    text = " ".join(body.split())
    if not text:
        return "empty response"
    return text[:240] + ("..." if len(text) > 240 else "")


def append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)


def write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_catalog_indexes(output: Path, rows: List[Dict[str, Any]]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "public_id",
        "script_id_part",
        "version",
        "name",
        "author",
        "author_id",
        "url",
        "script_type",
        "created_at",
        "updated_at",
        "description",
        "likes_count",
        "views_count",
        "is_picked",
        "is_hot",
        "status",
        "file",
        "error",
        "indexed_at",
    ]

    jsonl = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    write_atomically(output / "index.jsonl", jsonl)

    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    write_atomically(output / "index.csv", csv_buffer.getvalue())

    database_path = output / "index.sqlite3"
    temporary_database = output / ".index.sqlite3.part"
    try:
        temporary_database.unlink()
    except FileNotFoundError:
        pass
    connection = sqlite3.connect(temporary_database)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            CREATE TABLE scripts (
                public_id TEXT NOT NULL,
                script_id_part TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                name TEXT NOT NULL,
                author TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                script_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                description TEXT NOT NULL,
                likes_count INTEGER NOT NULL,
                views_count INTEGER NOT NULL,
                is_picked INTEGER NOT NULL,
                is_hot INTEGER NOT NULL,
                status TEXT NOT NULL,
                file TEXT NOT NULL,
                error TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE INDEX scripts_type_idx ON scripts(script_type);
            CREATE INDEX scripts_status_idx ON scripts(status);
            CREATE INDEX scripts_author_idx ON scripts(author);
            CREATE INDEX scripts_name_idx ON scripts(name);
            """
        )
        placeholders = ", ".join("?" for _ in fieldnames)
        connection.executemany(
            f"INSERT INTO scripts ({', '.join(fieldnames)}) VALUES ({placeholders})",
            ([row.get(field, "") for field in fieldnames] for row in rows),
        )
        connection.commit()
    finally:
        connection.close()
    os.replace(temporary_database, database_path)


def normalize_feed_path(path: str) -> str:
    clean = "/" + path.strip().strip("/") + "/"
    return clean


def build_listing_url(feed: Feed, page: int) -> str:
    if page < 1:
        raise ValueError("page must be at least 1")
    path = normalize_feed_path(feed.path)
    if page > 1:
        path = path.rstrip("/") + f"/page-{page}/"
    query: Dict[str, str] = {"component-data-only": "1", "script_access": "open"}
    if feed.sort:
        query["sort"] = feed.sort
    if feed.script_type != "all":
        query["script_type"] = feed.script_type
    return urljoin(TRADINGVIEW_ORIGIN, path.lstrip("/")) + "?" + urlencode(query)


def build_source_url(script_id_part: str, version: str, pine_base_url: str) -> str:
    encoded_id = quote(script_id_part, safe="")
    encoded_version = quote(str(version or "1"), safe="")
    return f"{pine_base_url.rstrip('/')}/get/{encoded_id}/{encoded_version}"


def find_ideas_data(node: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(node, dict):
        return None
    ideas = node.get("ideas")
    if isinstance(ideas, dict) and isinstance(ideas.get("data"), dict):
        return ideas["data"]
    for value in node.values():
        if isinstance(value, dict):
            found = find_ideas_data(value)
            if found is not None:
                return found
    return None


def extract_listing_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    ideas_data = find_ideas_data(payload)
    if ideas_data is None:
        raise DownloadError("TradingView listing response did not contain ideas data")
    return ideas_data


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_script(item: Dict[str, Any]) -> Optional[ScriptRef]:
    if item.get("is_script") is False:
        return None

    script_id_part = str(item.get("script_id_part") or "").strip()
    if not script_id_part:
        return None

    # Numeric access 1 is TradingView's public/open publication access.
    access = item.get("script_access")
    if isinstance(access, int) and access != 1:
        return None

    public_id = str(item.get("image_url") or "").strip()
    if not public_id:
        public_id = script_id_part.split(";", 1)[-1]
    public_id = re.sub(r"[^A-Za-z0-9_-]", "", public_id) or "script"

    name = clean_inline(item.get("name")) or public_id
    user = item.get("user")
    author = ""
    author_id = 0
    if isinstance(user, dict):
        author = clean_inline(user.get("username") or user.get("display_name"))
        author_id = safe_int(user.get("id"))
    url = str(item.get("chart_url") or "").strip()
    if not url:
        url = f"{TRADINGVIEW_ORIGIN}/script/{public_id}/"
    if not url.startswith(f"{TRADINGVIEW_ORIGIN}/script/"):
        return None

    version = str(item.get("version") or "1").strip() or "1"
    script_type = str(item.get("script_type") or "unknown").strip() or "unknown"
    return ScriptRef(
        script_id_part=script_id_part,
        version=version,
        public_id=public_id,
        name=name,
        author=author,
        url=url,
        script_type=script_type,
        created_at=str(item.get("created_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
        description=str(item.get("description") or ""),
        author_id=author_id,
        likes_count=safe_int(item.get("likes_count")),
        views_count=safe_int(item.get("views_count")),
        is_picked=bool(item.get("is_picked")),
        is_hot=bool(item.get("is_hot")),
    )


def clean_inline(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def safe_filename(title: str, public_id: str) -> str:
    """Create a portable, unique filename while retaining a readable title."""
    name = clean_inline(title)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"[-_ ]+", " ", name).strip(" .-")
    if not name:
        name = "script"

    # Leave ample room below common 255-byte filesystem limits.
    encoded = name.encode("utf-8")
    if len(encoded) > 160:
        name = encoded[:160].decode("utf-8", errors="ignore").rstrip(" .-") or "script"

    suffix = re.sub(r"[^A-Za-z0-9_-]", "", public_id) or "script"
    return f"{name}__{suffix}.pine"


def extract_source(payload: Dict[str, Any]) -> str:
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        # Keep compatibility with older facade response shapes.
        for key in ("il_template", "script_source", "script"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                source = candidate
                break
    if not isinstance(source, str) or not source.strip():
        detail = (
            payload.get("detail") or payload.get("message") or "source field is empty"
        )
        raise DownloadError(f"Pine source unavailable: {detail}")
    return source.replace("\r\n", "\n").replace("\r", "\n").strip("\n") + "\n"


def render_pine_file(
    script: ScriptRef, source: str, downloaded_at: str, include_metadata: bool
) -> str:
    if not include_metadata:
        return source
    header = "\n".join(
        (
            f"// TradingView title: {clean_inline(script.name)}",
            f"// TradingView author: {clean_inline(script.author)}",
            f"// TradingView ID: {script.public_id}",
            f"// TradingView URL: {script.url}",
            f"// Downloaded at: {downloaded_at}",
        )
    )
    return header + "\n\n" + source


async def async_progress(stats: Stats, args: argparse.Namespace) -> None:
    started = time.monotonic()
    last_line = -1
    while True:
        await asyncio.sleep(args.progress_interval)
        elapsed = max(time.monotonic() - started, 0.001)
        rate = stats.attempted / elapsed
        line = (
            f"pages={stats.pages_fetched} listed={stats.listing_items} "
            f"unique={stats.discovered} saved={stats.saved} "
            f"existing={stats.skipped_existing} failed={stats.failed} "
            f"pending={args.downloader.queue.qsize()} rate={rate:.1f}/s"
        )
        if line != last_line:
            print(line, flush=True)
            last_line = line


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return parsed


def parse_feed_names(value: str) -> List[str]:
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise argparse.ArgumentTypeError("at least one feed is required")
    unknown = sorted(set(names).difference(FEEDS))
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown feed(s): {', '.join(unknown)}; choose from {', '.join(FEEDS)}"
        )
    return list(dict.fromkeys(names))


def build_parser(
    default_feeds: str = DEFAULT_FEEDS, default_output: str = DEFAULT_OUTPUT
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download public, open-source TradingView Pine scripts concurrently. "
            "No Selenium, Firefox, or JavaScript rendering is required."
        )
    )
    parser.add_argument(
        "-o",
        "--output",
        default=default_output,
        help=f"output directory (default: {default_output})",
    )
    parser.add_argument(
        "--feeds",
        type=parse_feed_names,
        default=parse_feed_names(default_feeds),
        help=(
            "comma-separated feeds: recent, indicators, strategies, libraries, popular, "
            "editors-picks (default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=32,
        help="parallel source downloads (default: 32)",
    )
    parser.add_argument(
        "--listing-workers",
        type=positive_int,
        default=8,
        help="parallel listing-page requests (default: 8)",
    )
    parser.add_argument(
        "--rate-limit",
        type=nonnegative_float,
        default=0.0,
        help="maximum combined requests/second; 0 disables pacing (default: 0)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=4,
        help="retries after a transient request failure (default: 4)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="timeout in seconds for each request (default: 30)",
    )
    parser.add_argument(
        "--max-pages",
        type=positive_int,
        help="fetch at most this many pages per feed (useful for tests)",
    )
    parser.add_argument(
        "--max-scripts",
        type=positive_int,
        help="stop after discovering this many unique scripts",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace existing .pine files"
    )
    parser.add_argument(
        "--organize-by-type",
        action="store_true",
        help="place scripts in Indicators/, Strategies/, Libraries/, and Other/ subdirectories",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="save only Pine source, without comment metadata",
    )
    parser.add_argument(
        "--pine-base-url",
        default=os.environ.get("TRADINGVIEW_PINE_BASE_URL", DEFAULT_PINE_BASE_URL),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="log each queued/saved script and retries",
    )
    parser.add_argument(
        "--progress-interval",
        type=float,
        default=5.0,
        help="seconds between progress lines; 0 disables progress (default: 5)",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 2.0")
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.retries < 0:
        parser.error("--retries must be 0 or greater")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than 0")
    if args.progress_interval < 0:
        parser.error("--progress-interval must be 0 or greater")


async def run_download(args: argparse.Namespace) -> Stats:
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "_download_failures.jsonl").touch(exist_ok=True)

    timeout = aiohttp.ClientTimeout(
        total=args.timeout, connect=min(args.timeout, 15.0), sock_read=args.timeout
    )
    connector = aiohttp.TCPConnector(
        limit=args.workers + args.listing_workers,
        limit_per_host=args.workers + args.listing_workers,
        ttl_dns_cache=300,
        keepalive_timeout=30,
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{TRADINGVIEW_ORIGIN}/scripts/",
    }

    stats = Stats()
    limiter = RateLimiter(args.rate_limit)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
        trust_env=True,
    ) as session:
        downloader = Downloader(session, args, stats, limiter)
        # Used only by the progress formatter.
        args.downloader = downloader

        download_tasks = [
            asyncio.create_task(downloader.download_worker(), name=f"download-{index}")
            for index in range(args.workers)
        ]
        progress_task = (
            asyncio.create_task(async_progress(stats, args), name="progress")
            if args.progress_interval > 0
            else None
        )

        try:
            for feed_name in args.feeds:
                LOGGER.info("Discovering feed: %s", feed_name)
                await downloader.discover_feed(FEEDS[feed_name])
            await downloader.queue.join()
        finally:
            for task in download_tasks:
                task.cancel()
            await asyncio.gather(*download_tasks, return_exceptions=True)
            if progress_task is not None:
                progress_task.cancel()
                await asyncio.gather(progress_task, return_exceptions=True)
            await downloader.write_indexes()

    return stats


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(
    default_feeds: str = DEFAULT_FEEDS, default_output: str = DEFAULT_OUTPUT
) -> int:
    parser = build_parser(default_feeds=default_feeds, default_output=default_output)
    args = parser.parse_args()
    validate_args(args, parser)
    configure_logging(args.verbose)

    print(
        f"Downloading open-source scripts to {Path(args.output).expanduser().resolve()} "
        f"with {args.workers} source workers and feeds: {', '.join(args.feeds)}",
        flush=True,
    )
    try:
        stats = asyncio.run(run_download(args))
    except KeyboardInterrupt:
        print(
            "\nInterrupted; completed .pine files are safe and reruns will resume.",
            file=sys.stderr,
        )
        return 130

    print(
        "Finished: "
        f"{stats.saved} saved, {stats.skipped_existing} already existed, "
        f"{stats.failed} failed, {stats.duplicates} duplicates, "
        f"{stats.filtered} non-public/non-script items filtered "
        f"from {stats.pages_fetched} listing pages."
    )
    output_path = Path(args.output).expanduser().resolve()
    print(
        f"Index: {output_path / 'index.sqlite3'}, "
        f"{output_path / 'index.csv'}, {output_path / 'index.jsonl'}"
    )
    if stats.failed:
        print(
            f"Failure details were appended to {Path(args.output).expanduser().resolve() / '_download_failures.jsonl'}",
            file=sys.stderr,
        )
        return 1
    if stats.discovered == 0:
        print("No public open-source scripts were discovered.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
