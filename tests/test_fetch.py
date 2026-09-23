import argparse
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

import fetch

LISTING_PAYLOAD = {
    "context": {"request_context": {"path": "/scripts/"}},
    "data": {
        "ideas": {
            "data": {
                "total": 1,
                "items": [
                    {
                        "id": 123,
                        "image_url": "AbC_123",
                        "name": "Example / Strategy?",
                        "chart_url": "https://www.tradingview.com/script/AbC_123-Example/",
                        "is_script": True,
                        "script_type": "strategy",
                        "script_access": 1,
                        "script_id_part": "PUB;abc123",
                        "version": "2",
                        "user": {"username": "someone"},
                    }
                ],
                "next": None,
            }
        }
    },
}


class ParsingTests(unittest.TestCase):
    def test_extract_listing_data_supports_component_wrapper(self):
        data = fetch.extract_listing_data(LISTING_PAYLOAD)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["image_url"], "AbC_123")

    def test_parse_script(self):
        script = fetch.parse_script(
            LISTING_PAYLOAD["data"]["ideas"]["data"]["items"][0]
        )
        self.assertIsNotNone(script)
        assert script is not None
        self.assertEqual(script.script_id_part, "PUB;abc123")
        self.assertEqual(script.version, "2")
        self.assertEqual(script.author, "someone")

    def test_parse_script_rejects_non_open_script(self):
        item = dict(LISTING_PAYLOAD["data"]["ideas"]["data"]["items"][0])
        item["script_access"] = 2
        self.assertIsNone(fetch.parse_script(item))

    def test_safe_filename_is_portable_and_unique(self):
        filename = fetch.safe_filename(" Example / Strategy? ", "PUB;abc123")
        self.assertEqual(filename, "Example Strategy__PUBabc123.pine")
        self.assertNotIn("/", filename)

    def test_source_and_metadata(self):
        script = fetch.parse_script(
            LISTING_PAYLOAD["data"]["ideas"]["data"]["items"][0]
        )
        assert script is not None
        source = fetch.extract_source({"source": "//@version=6\r\nindicator('x')\r\n"})
        self.assertEqual(source, "//@version=6\nindicator('x')\n")
        rendered = fetch.render_pine_file(script, source, "now", include_metadata=True)
        self.assertIn("// TradingView ID: AbC_123", rendered)
        self.assertIn("//@version=6", rendered)

    def test_organizes_paths_by_script_type(self):
        script = fetch.parse_script(
            LISTING_PAYLOAD["data"]["ideas"]["data"]["items"][0]
        )
        assert script is not None
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                output=temporary,
                listing_workers=1,
                retries=0,
                verbose=False,
                organize_by_type=True,
            )
            downloader = fetch.Downloader(
                None, args, fetch.Stats(), fetch.RateLimiter(0)
            )
            self.assertIn("Strategies", downloader.output_path(script).parts)

    def test_urls(self):
        recent = fetch.FEEDS["recent"]
        self.assertIn("/scripts/page-7/", fetch.build_listing_url(recent, 7))
        self.assertIn("sort=recent_extended", fetch.build_listing_url(recent, 7))
        self.assertEqual(
            fetch.build_source_url("PUB;abc123", "2", "https://example.test/pine"),
            "https://example.test/pine/get/PUB%3Babc123/2",
        )


class IndexTests(unittest.TestCase):
    def test_writes_jsonl_csv_and_sqlite_indexes(self):
        row = {
            "public_id": "AbC_123",
            "script_id_part": "PUB;abc123",
            "version": "2",
            "name": "Example",
            "author": "someone",
            "author_id": 42,
            "url": "https://www.tradingview.com/script/AbC_123-Example/",
            "script_type": "strategy",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "",
            "description": "Example description",
            "likes_count": 10,
            "views_count": 20,
            "is_picked": True,
            "is_hot": False,
            "status": "saved",
            "file": "Strategies/Example__AbC_123.pine",
            "error": "",
            "indexed_at": "2026-01-02T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            fetch.write_catalog_indexes(output, [row])

            json_record = json.loads((output / "index.jsonl").read_text())
            self.assertEqual(json_record["script_id_part"], "PUB;abc123")
            self.assertTrue((output / "index.csv").is_file())

            connection = sqlite3.connect(output / "index.sqlite3")
            try:
                count = connection.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]
                status = connection.execute(
                    "SELECT status FROM scripts WHERE public_id = ?", ("AbC_123",)
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)
            self.assertEqual(status, "saved")


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.retry_calls = 0
        self.missing_calls = 0
        self.app = web.Application()
        self.app.router.add_get("/retry", self.retry_handler)
        self.app.router.add_get("/missing", self.missing_handler)
        self.server = TestServer(self.app)
        await self.server.start_server()

    async def asyncTearDown(self):
        await self.server.close()

    async def retry_handler(self, request):
        self.retry_calls += 1
        if self.retry_calls == 1:
            return web.Response(status=503, text="try again")
        return web.json_response({"ok": True})

    async def missing_handler(self, request):
        self.missing_calls += 1
        return web.Response(status=404, text="missing")

    def make_downloader(self, session):
        args = argparse.Namespace(
            output=tempfile.gettempdir(),
            listing_workers=1,
            retries=1,
            verbose=False,
        )
        downloader = fetch.Downloader(
            session,
            args,
            fetch.Stats(),
            fetch.RateLimiter(0),
        )
        # Avoid touching a real failure log in unit tests.
        downloader.failure_path = (
            Path(tempfile.gettempdir()) / "unused-download-failures.jsonl"
        )
        return downloader

    async def test_transient_status_is_retried(self):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            downloader = self.make_downloader(session)
            payload = await downloader.get_json(str(self.server.make_url("/retry")))
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(self.retry_calls, 2)

    async def test_permanent_status_is_not_retried(self):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            downloader = self.make_downloader(session)
            with self.assertRaises(fetch.DownloadError):
                await downloader.get_json(str(self.server.make_url("/missing")))
        self.assertEqual(self.missing_calls, 1)


if __name__ == "__main__":
    unittest.main()
