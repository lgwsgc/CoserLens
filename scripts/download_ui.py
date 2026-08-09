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


REPO_ROOT = Path(r"D:\AI-Projects\youtube_pipeline")
TIKTOK_DOWNLOADER = REPO_ROOT / "TikTokDownloader"
SETTINGS_PATH = TIKTOK_DOWNLOADER / "Volume" / "settings.json"
OUTPUT_ROOT = REPO_ROOT / "download_ui_outputs"
YTB_PYTHON = Path(r"D:\anaconda3\envs\ytb\python.exe")

sys.path.insert(0, str(TIKTOK_DOWNLOADER))

from src.interface.detail import Detail  # noqa: E402
from src.testers import Params  # noqa: E402
import src.interface.template as template  # noqa: E402


JOBS: dict[str, dict] = {}


class QuietLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


async def no_wait():
    return None


template.wait = no_wait


def read_settings() -> dict:
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))


def cookie_to_str(cookie) -> str:
    if isinstance(cookie, dict):
        return "; ".join(f"{k}={v}" for k, v in cookie.items())
    return cookie or ""


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def sanitize_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] or "douyin_video"


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
    with httpx.Client(headers=headers, follow_redirects=True, timeout=20, verify=False) as client:
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
        job["log"].append(f"{now_text()} 解析作品 ID")
        aweme_id = resolve_aweme_id(source, cookie)
        job["aweme_id"] = aweme_id

        job["log"].append(f"{now_text()} 获取作品详情")
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
        output_dir = Path(output_dir) if output_dir else OUTPUT_ROOT / sanitize_name(f"{prefix}-{desc}")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{sanitize_name(prefix + '-' + desc)}.mp4"
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
            f"{now_text()} 下载最高码率：{meta['width']}x{meta['height']} "
            f"{meta['fps']}fps {meta['bit_rate']}bps"
        )
        total = int(play_addr.get("data_size") or 0)
        downloaded = 0
        with httpx.Client(headers=headers, follow_redirects=True, timeout=120, verify=False) as client:
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
        job["log"].append(f"{now_text()} 完成：{output_file}")
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["log"].append(f"{now_text()} 失败：{exc}")


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>视频下载控制台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d8dde6;
      --text: #1f2937;
      --muted: #667085;
      --accent: #126b5b;
      --accent-2: #234f9a;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { font-size: 18px; margin: 0; font-weight: 650; }
    main {
      display: grid;
      grid-template-columns: minmax(360px, 520px) 1fr;
      gap: 18px;
      padding: 18px;
      max-width: 1280px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }
    h2 {
      font-size: 15px;
      margin: 0 0 14px;
      font-weight: 650;
    }
    label {
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 8px;
    }
    textarea {
      width: 100%;
      min-height: 124px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      font: 14px/1.45 Consolas, "Microsoft YaHei", monospace;
      color: var(--text);
      background: #fbfcfe;
      outline: none;
    }
    textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(18,107,91,.12); }
    .row { display: flex; gap: 10px; align-items: center; margin-top: 12px; }
    button {
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      font-size: 14px;
      cursor: pointer;
      background: var(--accent);
      color: white;
    }
    button.secondary { background: #eef2f7; color: var(--text); border: 1px solid var(--line); }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .hint { color: var(--muted); font-size: 13px; line-height: 1.5; }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(120px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-height: 64px;
      background: #fbfcfe;
    }
    .metric span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .metric strong { font-size: 14px; word-break: break-all; }
    .progress {
      height: 12px;
      background: #e9edf3;
      border-radius: 999px;
      overflow: hidden;
      margin: 12px 0 8px;
    }
    .bar { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .2s; }
    pre {
      height: 300px;
      overflow: auto;
      background: #111827;
      color: #e5e7eb;
      border-radius: 6px;
      padding: 12px;
      font: 12px/1.5 Consolas, monospace;
      white-space: pre-wrap;
    }
    .path {
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
      word-break: break-all;
      font: 12px/1.5 Consolas, monospace;
    }
    .error { color: var(--danger); }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
      .status-grid { grid-template-columns: repeat(2, 1fr); }
    }
  </style>
</head>
<body>
  <header>
    <h1>视频下载控制台</h1>
    <div class="hint">单作品最高码率下载</div>
  </header>
  <main>
    <section>
      <h2>下载任务</h2>
      <label for="source">作品链接或作品 ID</label>
      <textarea id="source" placeholder="例如：https://www.douyin.com/video/7433368409930206522 或 v.douyin.com 短链"></textarea>
      <div class="row">
        <button id="startBtn">开始下载</button>
        <button class="secondary" id="clearBtn">清空</button>
      </div>
      <p class="hint">保存目录固定为 D:\AI-Projects\youtube_pipeline\download_ui_outputs。Cookie 读取现有 settings.json，不会在界面显示。</p>
    </section>
    <section>
      <h2>任务状态</h2>
      <div class="status-grid">
        <div class="metric"><span>状态</span><strong id="status">待开始</strong></div>
        <div class="metric"><span>作品 ID</span><strong id="aweme">-</strong></div>
        <div class="metric"><span>规格</span><strong id="spec">-</strong></div>
        <div class="metric"><span>大小</span><strong id="size">-</strong></div>
      </div>
      <div class="progress"><div class="bar" id="bar"></div></div>
      <div class="hint" id="progressText">0%</div>
      <h2 style="margin-top:16px;">输出文件</h2>
      <div class="path" id="output">-</div>
      <h2 style="margin-top:16px;">日志</h2>
      <pre id="log"></pre>
    </section>
  </main>
  <script>
    let jobId = null;
    let timer = null;
    const $ = (id) => document.getElementById(id);

    function fmtBytes(n) {
      if (!n) return "-";
      const units = ["B", "KB", "MB", "GB"];
      let value = n, i = 0;
      while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
      return value.toFixed(i ? 2 : 0) + " " + units[i];
    }

    async function start() {
      const source = $("source").value.trim();
      if (!source) return;
      $("startBtn").disabled = true;
      const res = await fetch("/api/download", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({source})
      });
      const data = await res.json();
      if (!res.ok) {
        $("status").innerHTML = '<span class="error">' + (data.error || "启动失败") + "</span>";
        $("startBtn").disabled = false;
        return;
      }
      jobId = data.job_id;
      poll();
      timer = setInterval(poll, 1000);
    }

    async function poll() {
      if (!jobId) return;
      const res = await fetch("/api/status?id=" + encodeURIComponent(jobId));
      const job = await res.json();
      $("status").textContent = job.status || "-";
      $("aweme").textContent = job.aweme_id || "-";
      const meta = job.meta || {};
      $("spec").textContent = meta.width ? `${meta.width}x${meta.height} ${meta.fps || "-"}fps` : "-";
      $("size").textContent = fmtBytes(job.downloaded || meta.data_size);
      $("output").textContent = job.output || "-";
      $("log").textContent = (job.log || []).join("\n");
      $("bar").style.width = (job.progress || 0).toFixed(1) + "%";
      $("progressText").textContent = (job.progress || 0).toFixed(1) + "%";
      if (job.status === "done" || job.status === "error") {
        clearInterval(timer);
        $("startBtn").disabled = false;
      }
    }

    $("startBtn").addEventListener("click", start);
    $("clearBtn").addEventListener("click", () => {
      $("source").value = "";
      $("log").textContent = "";
    });
  </script>
</body>
</html>
"""


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
            payload = HTML.encode("utf-8")
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
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            source = body.get("source", "")
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {
                "status": "starting",
                "progress": 0,
                "downloaded": 0,
                "total": 0,
                "log": [f"{now_text()} 创建任务"],
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
    port = 7862
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Download UI: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
