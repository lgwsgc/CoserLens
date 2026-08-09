"""CoserLens Pipeline — HTTP API 路由层。

职责：视频扫描、元数据 CRUD、上传任务调度、静态文件服务。
YouTube 上传逻辑见 youtube_uploader.py，元数据生成见 metadata_helpers.py，
共享状态见 state.py。
"""

import hashlib
import json
import logging
import mimetypes
import re
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
import metadata_helpers
import state
import youtube_uploader

logger = logging.getLogger(__name__)

# ── 向后兼容 re-export（pipeline_desktop_qt.py 通过 pipeline_ui.xxx 访问）──
REPO_ROOT = config.REPO_ROOT
VIDEO_DIRS = config.VIDEO_DIRS
STATE_PATH = config.STATE_PATH
PORT = config.API_PORT
STATE_LOCK = state.STATE_LOCK
JOBS = state.JOBS

# 从 state re-export
now_text = state.now_text
load_state = state.load_state
save_state = state.save_state
video_id_for_path = state.video_id_for_path

# 从 metadata_helpers re-export
CHARACTER_RULES = metadata_helpers.CHARACTER_RULES
CAPTION_TRANSLATIONS = metadata_helpers.CAPTION_TRANSLATIONS
draft_metadata = metadata_helpers.draft_metadata
validate_publish_copy = metadata_helpers.validate_publish_copy

# 从 youtube_uploader re-export
launch_chrome = youtube_uploader.launch_chrome
run_upload = youtube_uploader.run_upload


# ── Web UI 模板 ────────────────────────────────────────────
_HTML_CACHE: str | None = None


def _load_html() -> str:
    global _HTML_CACHE
    if _HTML_CACHE is None:
        _HTML_CACHE = (Path(__file__).parent / "web_ui.html").read_text(encoding="utf-8")
    return _HTML_CACHE


# ── 视频扫描（带 TTL 缓存）─────────────────────────────────

def scan_roots(state_data: dict | None = None) -> list[Path]:
    """返回所有视频搜索根目录（含自定义路径）。"""
    if state_data is None:
        with STATE_LOCK:
            state_data = load_state()
    roots = list(VIDEO_DIRS)
    for raw in state_data.get("custom_paths", []):
        path = Path(raw)
        if path.exists():
            roots.append(path if path.is_dir() else path.parent)
    return list(dict.fromkeys(path.resolve() for path in roots))


def add_custom_path(path: Path) -> None:
    """添加自定义视频目录到状态文件。"""
    path = path.resolve()
    with STATE_LOCK:
        st = load_state()
        paths = st.setdefault("custom_paths", [])
        text = str(path)
        if text not in paths:
            paths.append(text)
        save_state(st)


# 缓存：避免每次 API 请求都重新扫描 1000+ 视频目录
_SCAN_CACHE: list[dict] | None = None
_SCAN_CACHE_TIME: float = 0
_SCAN_CACHE_LOCK = threading.Lock()
_SCAN_TTL = 5.0  # 秒，5 秒内的重复请求使用缓存


def scan_videos(force_refresh: bool = False) -> list[dict]:
    """扫描所有根目录下的 mp4 文件，返回带元数据的视频列表。

    带 TTL 缓存：5 秒内的重复调用直接返回缓存结果，
    避免对 1000+ 视频频繁调用 draft_metadata。
    """
    global _SCAN_CACHE, _SCAN_CACHE_TIME

    if not force_refresh:
        with _SCAN_CACHE_LOCK:
            if _SCAN_CACHE is not None and (time.time() - _SCAN_CACHE_TIME) < _SCAN_TTL:
                return _SCAN_CACHE

    with STATE_LOCK:
        st = load_state()
    metadata_state = st.get("metadata", {})
    uploads = st.get("uploads", {})
    found: list[Path] = []
    for root in scan_roots(st):
        if not root.exists():
            continue
        try:
            found.extend(path for path in root.rglob("*.mp4") if path.is_file())
        except PermissionError as exc:
            logger.warning("扫描目录 %s 时权限不足: %s", root, exc)
    # 排序时缓存 stat，避免重复调用
    found_with_stat: list[tuple[Path, float]] = []
    for path in set(found):
        try:
            found_with_stat.append((path, path.stat().st_mtime))
        except OSError:
            continue
    found_with_stat.sort(key=lambda pair: pair[1], reverse=True)
    items = []
    for path, mtime in found_with_stat:
        item_id = video_id_for_path(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        meta = draft_metadata(path, metadata_state.get(item_id))
        try:
            relative = str(path.relative_to(REPO_ROOT))
        except ValueError:
            relative = str(path)
        upload = uploads.get(item_id, {})
        items.append(
            {
                "id": item_id,
                "path": str(path),
                "relative_path": relative,
                "filename": path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "modified_text": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                "title": meta["title"],
                "description": meta["description"],
                "upload": upload,
            }
        )

    with _SCAN_CACHE_LOCK:
        _SCAN_CACHE = items
        _SCAN_CACHE_TIME = time.time()

    return items


def item_by_id(item_id: str) -> dict:
    """按 ID 查找视频，找不到抛出 KeyError。"""
    for item in scan_videos():
        if item["id"] == item_id:
            return item
    raise KeyError("Video not found")


# ── HTTP 工具函数 ──────────────────────────────────────────

def send_json(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


MAX_REQUEST_BODY = 1024 * 1024  # 1MB — 防止超大请求耗尽内存


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    if length > MAX_REQUEST_BODY:
        raise ValueError(f"Request body too large ({length} bytes, max {MAX_REQUEST_BODY})")
    return json.loads(handler.rfile.read(length).decode("utf-8"))


# ── HTTP 请求处理 ──────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            payload = _load_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/videos":
            send_json(self, {"items": scan_videos()})
            return
        if parsed.path == "/api/job":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            job = JOBS.get(job_id)
            if not job:
                send_json(self, {"error": "Job not found"}, 404)
                return
            send_json(self, job)
            return
        if parsed.path == "/media":
            self.serve_media(parse_qs(parsed.query).get("id", [""])[0])
            return
        self.send_error(404)

    def do_POST(self):
        try:
            if self.path == "/api/chrome":
                send_json(self, {"message": launch_chrome()})
                return
            body = read_body(self)
            if self.path == "/api/metadata":
                item = item_by_id(body.get("id", ""))
                with STATE_LOCK:
                    st = load_state()
                    st.setdefault("metadata", {})[item["id"]] = {
                        "title": body.get("title", "").strip(),
                        "description": body.get("description", "").strip(),
                    }
                    save_state(st)
                # 元数据已更新，使扫描缓存失效以便下次请求获取新数据
                with _SCAN_CACHE_LOCK:
                    _SCAN_CACHE = None
                send_json(self, {"ok": True})
                return
            if self.path == "/api/regenerate":
                item = item_by_id(body.get("id", ""))
                meta = draft_metadata(Path(item["path"]), None, allow_online=bool(body.get("online")))
                send_json(self, meta)
                return
            if self.path == "/api/upload":
                item = item_by_id(body.get("id", ""))
                title = body.get("title", "").strip()
                description = body.get("description", "").strip()
                privacy = body.get("privacy", "public")
                if not title:
                    raise ValueError("Title is required")
                if not description:
                    raise ValueError("Description is required")
                job_id = hashlib.sha1(f"{item['id']}:{time.time()}".encode()).hexdigest()[:16]
                JOBS[job_id] = {"status": "running", "log": [f"{now_text()} Created upload job"]}
                thread = threading.Thread(
                    target=run_upload,
                    args=(job_id, item, title, description, privacy),
                    daemon=True,
                )
                thread.start()
                send_json(self, {"job_id": job_id})
                return
            self.send_error(404)
        except Exception as exc:
            send_json(self, {"error": str(exc)}, 500)

    def serve_media(self, item_id: str) -> None:
        """支持 Range 请求的视频文件流式传输。"""
        try:
            item = item_by_id(item_id)
            path = Path(item["path"])
            size = path.stat().st_size
            range_header = self.headers.get("Range")
            mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
            if range_header:
                match = re.match(r"bytes=(\d+)-(\d*)", range_header)
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2) or size - 1)
                    end = min(end, size - 1)
                    self.send_response(206)
                    self.send_header("Content-Type", mime)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.end_headers()
                    with path.open("rb") as file:
                        file.seek(start)
                        remaining = end - start + 1
                        while remaining > 0:
                            chunk = file.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with path.open("rb") as file:
                shutil.copyfileobj(file, self.wfile)
        except Exception:
            self.send_error(404)

    def log_message(self, format, *args):
        return


def main() -> int:
    for folder in VIDEO_DIRS:
        folder.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"CoserLens Pipeline: http://127.0.0.1:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
