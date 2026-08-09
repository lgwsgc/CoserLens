import asyncio
import json
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import config
import utils

REPO_ROOT = config.REPO_ROOT
TIKTOK_DOWNLOADER = config.TIKTOK_DOWNLOADER
SETTINGS_PATH = config.TIKTOK_SETTINGS_PATH
OUTPUT_ROOT = config.DOWNLOAD_OUTPUT_ROOT
YTB_PYTHON = config.YTB_PYTHON

sys.path.insert(0, str(TIKTOK_DOWNLOADER))

from src.interface.detail import Detail  # noqa: E402
from src.testers import Params  # noqa: E402
import src.interface.template as template  # noqa: E402


JOBS: dict[str, dict] = {}


class QuietLogger:
    """TikTokDownloader 日志拦截器：屏蔽 info/warning，但保留 error 日志"""

    def __init__(self):
        import logging

        self._logger = logging.getLogger("tiktok_downloader")

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        self._logger.error("TikTokDownloader 错误: %s", args[0] if args else kwargs)


async def no_wait():
    return None


template.wait = no_wait


def read_settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))


def cookie_to_str(cookie) -> str:
    if isinstance(cookie, dict):
        return "; ".join(f"{k}={v}" for k, v in cookie.items())
    return cookie or ""


def resolve_aweme_id(raw: str, cookie: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError("请输入作品链接或作品 ID")
    if re.fullmatch(r"\d{10,30}", text):
        return text

    url_match = re.search(r"https?://\S+", text)
    if not url_match:
        raise ValueError("没有识别到有效链接")
    url = url_match.group(0).strip()

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("modal_id", "aweme_id"):
        if query.get(key):
            return query[key][0]

    path_match = re.search(r"/video/(\d+)", parsed.path)
    if path_match:
        return path_match.group(1)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie,
    }
    with httpx.Client(headers=headers, follow_redirects=True, timeout=20, verify=config.VERIFY_SSL) as client:
        response = client.get(url)
        final_url = str(response.url)

    final = urlparse(final_url)
    final_query = parse_qs(final.query)
    for key in ("modal_id", "aweme_id"):
        if final_query.get(key):
            return final_query[key][0]
    path_match = re.search(r"/video/(\d+)", final.path)
    if path_match:
        return path_match.group(1)
    decoded = unquote(final_url)
    any_id = re.search(r"(?:modal_id|aweme_id|video/)[=/]?(\d{10,30})", decoded)
    if any_id:
        return any_id.group(1)
    raise ValueError(f"链接已打开，但没有找到作品 ID：{final_url}")


async def fetch_detail(aweme_id: str, cookie: str) -> dict:
    settings = read_settings()
    async with Params() as params:
        params.logger = QuietLogger()
        params.cookie_str = cookie
        params.headers["Cookie"] = cookie
        params.proxy = settings.get("proxy") or None
        detail = Detail(params, cookie=cookie, proxy=params.proxy, detail_id=aweme_id)
        data = await detail.run()
        return data if isinstance(data, dict) else (data[0] if data else {})


def choose_best(bit_rates: list[dict]) -> dict:
    if not bit_rates:
        raise ValueError("作品详情里没有可下载的视频码率信息")
    return max(
        bit_rates,
        key=lambda item: (
            ((item.get("play_addr") or {}).get("height") or 0),
            ((item.get("play_addr") or {}).get("width") or 0),
            item.get("FPS") or 0,
            item.get("bit_rate") or 0,
            (item.get("play_addr") or {}).get("data_size") or 0,
        ),
    )


def run_download(job_id: str, source: str, output_dir: Path | str | None = None, write_meta: bool = True):
    job = JOBS[job_id]
    try:
        settings = read_settings()
        cookie = cookie_to_str(settings.get("cookie", ""))
        job["log"].append(f"{utils.now_text()} 解析作品 ID")
        aweme_id = resolve_aweme_id(source, cookie)
        job["aweme_id"] = aweme_id

        job["log"].append(f"{utils.now_text()} 获取作品详情")
        detail = asyncio.run(fetch_detail(aweme_id, cookie))
        video = detail.get("video") or {}
        bit_rates = video.get("bit_rate") or []
        best = choose_best(bit_rates)
        play_addr = best.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        if not url_list:
            raise ValueError("最高码率条目没有下载地址")

        desc = detail.get("desc") or aweme_id
        create_time = detail.get("create_time")
        prefix = time.strftime("%Y-%m-%d %H.%M.%S", time.localtime(create_time)) if create_time else aweme_id
        output_dir = Path(output_dir) if output_dir else OUTPUT_ROOT / utils.sanitize_name(f"{prefix}-{desc}")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{utils.sanitize_name(prefix + '-' + desc)}.mp4"
        meta_file = output_dir / "download_meta.json"

        meta = {
            "aweme_id": aweme_id,
            "desc": desc,
            "create_time": create_time,
            "width": play_addr.get("width"),
            "height": play_addr.get("height"),
            "fps": best.get("FPS"),
            "bit_rate": best.get("bit_rate"),
            "data_size": play_addr.get("data_size"),
            "uri": play_addr.get("uri"),
            "bit_rate_count": len(bit_rates),
            "output_file": str(output_file),
        }
        if write_meta:
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        job["meta"] = meta
        job["output"] = str(output_file)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.douyin.com/",
            "Cookie": cookie,
        }
        job["status"] = "downloading"
        job["log"].append(
            f"{utils.now_text()} 下载最高码率：{meta['width']}x{meta['height']} "
            f"{meta['fps']}fps {meta['bit_rate']}bps"
        )
        total = int(play_addr.get("data_size") or 0)
        downloaded = 0
        with httpx.Client(headers=headers, follow_redirects=True, timeout=120, verify=config.VERIFY_SSL) as client:
            with client.stream("GET", url_list[0]) as response:
                response.raise_for_status()
                total = total or int(response.headers.get("content-length") or 0)
                job["total"] = total
                with output_file.open("wb") as file:
                    for chunk in response.iter_bytes(1024 * 512):
                        if not chunk:
                            continue
                        file.write(chunk)
                        downloaded += len(chunk)
                        job["downloaded"] = downloaded
                        job["progress"] = min(100, downloaded / total * 100) if total else 0

        job["status"] = "done"
        job["progress"] = 100
        job["downloaded"] = output_file.stat().st_size
        job["total"] = output_file.stat().st_size
        job["log"].append(f"{utils.now_text()} 完成：{output_file}")
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["log"].append(f"{utils.now_text()} 失败：{exc}")


_HTML_CACHE: str | None = None


def _load_html() -> str:
    """从外部文件加载 HTML 模板，避免大段 HTML 内嵌在 Python 中。"""
    global _HTML_CACHE
    if _HTML_CACHE is None:
        _HTML_CACHE = (Path(__file__).parent / "download_ui.html").read_text(encoding="utf-8")
    return _HTML_CACHE


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict, status: int = 200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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
        if parsed.path == "/api/status":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            job = JOBS.get(job_id)
            if not job:
                self._send_json({"error": "任务不存在"}, 404)
                return
            self._send_json(job)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/download":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024 * 1024:  # 1MB 限制
            self._send_json({"error": "Request body too large"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            source = body.get("source", "")
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {
                "status": "starting",
                "progress": 0,
                "downloaded": 0,
                "total": 0,
                "log": [f"{utils.now_text()} 创建任务"],
            }
            thread = threading.Thread(target=run_download, args=(job_id, source), daemon=True)
            thread.start()
            self._send_json({"job_id": job_id})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def log_message(self, format, *args):
        return


def main():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    port = config.DOWNLOAD_UI_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Download UI: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
