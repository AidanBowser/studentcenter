"""Student Center desk. Reads AssetPanda. Never writes to it."""

from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from activity import ASSET_GROUP, desk_view, normalize_asset, sample_assets
from assetpanda import AssetPanda

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
EASTERN = ZoneInfo("America/New_York")
PAGE_SIZE = 40


def cache_file() -> Path:
    return Path(os.environ.get("DESK_CACHE", ROOT / "data" / "asset-index.json"))


def using_sample() -> bool:
    if os.environ.get("ASSETPANDA_SAMPLE") == "1":
        return True
    return not os.environ.get("ASSETPANDA_EMAIL") or not os.environ.get("ASSETPANDA_PASSWORD")


class Desk:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.assets: list[dict] = []
        self.indexing = False
        self.loaded = 0
        self.total = 0
        self.error = ""
        self.built_at = ""
        self.source = "sample"
        self._thread: threading.Thread | None = None

    def load(self) -> None:
        if using_sample():
            with self.lock:
                self.assets = sample_assets()
                self.source = "sample"
                self.indexing = False
                self.loaded = len(self.assets)
                self.total = len(self.assets)
                self.built_at = _now_label()
                self.error = ""
            return
        cached = _read_cache()
        if cached:
            with self.lock:
                self.assets = cached["assets"]
                self.source = "live"
                self.loaded = len(self.assets)
                self.total = cached.get("total") or len(self.assets)
                self.built_at = cached.get("built_at") or ""
                self.indexing = False
                self.error = ""
            return
        self.refresh()

    def refresh(self) -> None:
        if using_sample():
            self.load()
            return
        with self.lock:
            if self.indexing:
                return
            self.indexing = True
            self.error = ""
        self._thread = threading.Thread(target=self._index, name="assetpanda-index", daemon=True)
        self._thread.start()

    def _index(self) -> None:
        try:
            client = AssetPanda(os.environ["ASSETPANDA_EMAIL"], os.environ["ASSETPANDA_PASSWORD"])
            offset = 0
            seen: set[str] = set()
            collected: list[dict] = []
            total = 0
            while offset < 5000:
                page = client.search_objects(ASSET_GROUP, {}, limit=PAGE_SIZE, offset=offset)
                objects = page.get("objects") or []
                total = int((page.get("totals") or {}).get("objects") or total)
                fresh = []
                for obj in objects:
                    key = str(obj.get("id") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    fresh.append(normalize_asset(obj))
                collected.extend(fresh)
                offset += len(objects)
                with self.lock:
                    self.assets = list(collected)
                    self.loaded = len(collected)
                    self.total = total or len(collected)
                    self.source = "live"
                print(f"indexed {len(collected)}/{total or '?'}", flush=True)
                if not objects or (total and offset >= total):
                    break
            built = _now_label()
            with self.lock:
                self.built_at = built
                self.indexing = False
                self.error = ""
            _write_cache({"built_at": built, "total": total or len(collected), "assets": collected})
        except Exception as exc:  # noqa: BLE001 — surface the failure on the desk, keep the last good copy
            traceback.print_exc()
            with self.lock:
                self.indexing = False
                self.error = "Could not finish reading AssetPanda. The last copy is still on screen."
                if not self.assets:
                    self.error = f"Could not read AssetPanda. {exc.__class__.__name__}"

    def payload(self, query: str, start: str, end: str) -> dict:
        with self.lock:
            assets = list(self.assets)
            meta = {
                "source": self.source,
                "indexing": self.indexing,
                "loaded": self.loaded,
                "total": self.total,
                "built_at": self.built_at,
                "error": self.error,
                "read_only": True,
            }
        view = desk_view(assets, query, start or None, end or None)
        view.update(meta)
        return view


def _now_label() -> str:
    moment = datetime.now(timezone.utc).astimezone(EASTERN)
    clock = moment.strftime("%I:%M %p").lstrip("0")
    return moment.strftime("%b ") + str(moment.day) + moment.strftime(", %Y ") + clock + " ET"


def _read_cache() -> dict | None:
    path = cache_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        return None
    return data


def _write_cache(data: dict) -> None:
    path = cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data))
    temporary.replace(path)


DESK = Desk()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/desk":
            params = parse_qs(parsed.query)
            body = DESK.payload(
                _one(params, "q"),
                _one(params, "start"),
                _one(params, "end"),
            )
            self._json(body)
            return
        if parsed.path in {"/", "/index.html"}:
            self._file(STATIC / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._file(STATIC / "styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._file(STATIC / "app.js", "text/javascript; charset=utf-8")
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/refresh":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        DESK.refresh()
        self._json({"ok": True, "read_only": True})

    def log_message(self, fmt: str, *args) -> None:
        if args and str(args[1]).startswith("5"):
            super().log_message(fmt, *args)

    def _json(self, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _one(params: dict, key: str) -> str:
    values = params.get(key) or [""]
    return values[0].strip()


def make_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    DESK.load()
    port = int(os.environ.get("PORT", "8765"))
    server = make_server("127.0.0.1", port)
    print(f"Student Center desk at http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
