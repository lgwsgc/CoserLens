import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import cosplay_metadata_analyzer
import config

REPO_ROOT = config.REPO_ROOT
VIDEO_DIRS = config.VIDEO_DIRS
STATE_PATH = config.STATE_PATH
CHROME_PROFILE = config.CHROME_PROFILE
CHROME_DEBUG_URL = config.CHROME_DEBUG_URL
CHANNEL_ID = config.CHANNEL_ID
PORT = config.API_PORT

STATE_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}

logger = logging.getLogger(__name__)


CHARACTER_RULES = [
    {
        "patterns": ["顾清寒", "guqinghan", "gu qinghan"],
        "character": "Gu Qinghan",
        "source_patterns": ["永劫无间", "naraka"],
        "source": "Naraka: Bladepoint",
        "title": "Gu Qinghan Cosplay Looks Unreal in Real Life",
        "tags": ["#GuQinghan", "#NarakaBladepoint", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["公孙离", "gongsunli", "gongsun li"],
        "character": "Gongsun Li",
        "source_patterns": ["王者荣耀", "honor of kings"],
        "source": "Honor of Kings",
        "title": "Gongsun Li Cosplay Brings the Character to Life",
        "tags": ["#GongsunLi", "#HonorOfKings", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["萧薰儿", "薰儿", "xiao xun", "xiaoxun"],
        "character": "Xiao Xun'er",
        "source_patterns": ["斗破", "donghua"],
        "source": "Donghua",
        "title": "Xiao Xun'er Cosplay Looks Real in Real Life",
        "tags": ["#XiaoXuner", "#Donghua", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["迦南", "canaan"],
        "character": "Canaan",
        "source_patterns": ["永劫无间", "naraka"],
        "source": "Naraka: Bladepoint",
        "title": "Canaan Cosplay Looks Unreal in Real Life",
        "tags": ["#Canaan", "#NarakaBladepoint", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["露娜", "luna"],
        "character": "Luna",
        "source_patterns": ["王者荣耀", "honor of kings"],
        "source": "Honor of Kings",
        "title": "Luna Cosplay Looks Unreal in Real Life",
        "tags": ["#Luna", "#HonorOfKings", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["殷紫萍", "yin ziping", "yinziping"],
        "character": "Yin Ziping",
        "source_patterns": ["永劫无间", "naraka"],
        "source": "Naraka: Bladepoint",
        "title": "Yin Ziping Cosplay Looks Unreal in Real Life",
        "tags": ["#YinZiping", "#NarakaBladepoint", "#Cosplay", "#shorts"],
    },
    {
        "patterns": ["长离", "changli"],
        "character": "Changli",
        "source_patterns": ["鸣潮", "wuthering waves"],
        "source": "Wuthering Waves",
        "title": "Changli Cosplay Looks Unreal in Real Life",
        "tags": ["#Changli", "#WutheringWaves", "#Cosplay", "#shorts"],
    },
]


CAPTION_TRANSLATIONS = {
    "\u4e00\u66f2\u76f8\u601d": "A Song of Longing",
    "\u6211\u7ec8\u4e8e\u627e\u5230\u6240\u5bfb\u4e4b\u4eba": "I finally found the one I've been searching for.",
    "\u957f\u6c99\u590f\u5929\u7684\u5feb\u4e50\u662f\u5927\u738b\u5c71\u7ed9\u7684": "Summer fun at Dawangshan in Changsha.",
    "\u957f\u6c99\u6e58\u6c5f\u6c34\u4e0a\u4e50\u56ed": "Changsha Xiangjiang Water Park.",
    "\u6cf3\u88c5cos": "swimsuit cosplay",
    "\u6b63\u5e38\u6cf3\u88c5\u7a7f\u642d": "swimsuit outfit",
}


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CoserLens Pipeline</title>
  <style>
    :root {
      --bg: #f5f6f8;
      --panel: #fff;
      --line: #d9dee7;
      --text: #1f2937;
      --muted: #667085;
      --accent: #0f766e;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    header {
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 18px; font-weight: 650; }
    main {
      display: grid;
      grid-template-columns: 420px minmax(520px, 1fr);
      gap: 16px;
      padding: 16px;
      max-width: 1360px;
      margin: 0 auto;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 100px;
    }
    .panel-head {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .panel-head h2 { margin: 0; font-size: 15px; }
    .left-body { height: calc(100vh - 106px); overflow: auto; }
    .item {
      padding: 10px 12px;
      border-bottom: 1px solid #edf0f4;
      cursor: pointer;
    }
    .item:hover, .item.active { background: #eef7f5; }
    .item-title { font-size: 13px; font-weight: 650; line-height: 1.35; word-break: break-word; }
    .item-meta { color: var(--muted); font-size: 12px; margin-top: 5px; }
    .work {
      display: grid;
      grid-template-columns: 340px minmax(360px, 1fr);
      gap: 14px;
      padding: 14px;
    }
    video {
      width: 100%;
      max-height: 620px;
      background: #111;
      border-radius: 8px;
      border: 1px solid var(--line);
    }
    label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin: 12px 0 6px;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      font: 14px/1.45 "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      outline: none;
      background: #fbfcfe;
      color: var(--text);
    }
    textarea { min-height: 176px; resize: vertical; }
    input:focus, textarea:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(15, 118, 110, .12);
    }
    .row { display: flex; gap: 8px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
    button {
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      padding: 9px 12px;
      cursor: pointer;
      font-size: 13px;
    }
    button.secondary {
      color: var(--text);
      background: #f2f4f7;
      border: 1px solid var(--line);
    }
    button.danger { background: var(--danger); }
    button:disabled { opacity: .5; cursor: not-allowed; }
    .path {
      font: 12px/1.45 Consolas, monospace;
      color: var(--muted);
      word-break: break-all;
      padding: 10px;
      background: #fbfcfe;
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .hint { font-size: 12px; color: var(--muted); line-height: 1.45; }
    pre {
      height: 180px;
      overflow: auto;
      white-space: pre-wrap;
      background: #111827;
      color: #e5e7eb;
      border-radius: 6px;
      padding: 10px;
      font: 12px/1.45 Consolas, monospace;
    }
    .empty { padding: 24px; color: var(--muted); }
    @media (max-width: 980px) {
      main, .work { grid-template-columns: 1fr; }
      .left-body { height: 360px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>CoserLens Pipeline</h1>
    <div class="row" style="margin:0">
      <button class="secondary" id="openChrome">打开受控 Chrome</button>
      <button class="secondary" id="refresh">刷新视频</button>
    </div>
  </header>
  <main>
    <section>
      <div class="panel-head">
        <h2>本地视频</h2>
        <span class="hint" id="count">0</span>
      </div>
      <div class="left-body" id="items"></div>
    </section>
    <section>
      <div class="panel-head">
        <h2>标题 / 说明 / 上传</h2>
        <span class="hint" id="selectedStatus">未选择</span>
      </div>
      <div class="work" id="work">
        <div>
          <video id="preview" controls></video>
          <label>文件路径</label>
          <div class="path" id="path">-</div>
        </div>
        <div>
          <label>英文标题</label>
          <input id="title" maxlength="100" />
          <label>视频说明</label>
          <textarea id="description"></textarea>
          <label>公开范围</label>
          <select id="privacy">
            <option value="public">公开</option>
            <option value="unlisted">不公开列出</option>
            <option value="private">私享</option>
          </select>
          <div class="row">
            <button id="saveMeta">保存文案</button>
            <button class="secondary" id="regen">重新生成</button>
            <button class="secondary" id="deepAnalyze">Deep Analyze</button>
            <button class="danger" id="upload">上传到 YouTube</button>
          </div>
          <p class="hint">
            文件名只用于提取角色/作品信息，不会直接作为 YouTube 标题。公开视频说明里不会写 Unknown。
          </p>
          <label>上传日志</label>
          <pre id="log"></pre>
        </div>
      </div>
    </section>
  </main>
  <script>
    let items = [];
    let selected = null;
    let polling = null;

    const $ = id => document.getElementById(id);

    function fmtBytes(n) {
      if (!n) return "-";
      const units = ["B", "KB", "MB", "GB"];
      let value = n, idx = 0;
      while (value >= 1024 && idx < units.length - 1) { value /= 1024; idx++; }
      return value.toFixed(idx ? 1 : 0) + " " + units[idx];
    }

    async function api(path, options) {
      const res = await fetch(path, options);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Request failed");
      return data;
    }

    function renderList() {
      $("count").textContent = items.length + " 个";
      const root = $("items");
      if (!items.length) {
        root.innerHTML = '<div class="empty">没有找到 mp4 文件。</div>';
        return;
      }
      root.innerHTML = "";
      for (const item of items) {
        const div = document.createElement("div");
        div.className = "item" + (selected && selected.id === item.id ? " active" : "");
        div.innerHTML = `
          <div class="item-title">${item.title || item.filename}</div>
          <div class="item-meta">${fmtBytes(item.size)} · ${item.modified_text}</div>
          <div class="item-meta">${item.relative_path}</div>
        `;
        div.onclick = () => selectItem(item.id);
        root.appendChild(div);
      }
    }

    function selectItem(id) {
      selected = items.find(x => x.id === id);
      renderList();
      $("selectedStatus").textContent = selected.filename;
      $("preview").src = "/media?id=" + encodeURIComponent(selected.id);
      $("path").textContent = selected.path;
      $("title").value = selected.title;
      $("description").value = selected.description;
      $("log").textContent = "";
    }

    async function loadItems() {
      const data = await api("/api/videos");
      items = data.items;
      renderList();
      if (!selected && items.length) selectItem(items[0].id);
      if (selected) {
        const refreshed = items.find(x => x.id === selected.id);
        if (refreshed) selectItem(refreshed.id);
      }
    }

    async function saveMeta() {
      if (!selected) return;
      await api("/api/metadata", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          id: selected.id,
          title: $("title").value.trim(),
          description: $("description").value.trim()
        })
      });
      await loadItems();
    }

    async function regenerate() {
      if (!selected) return;
      const data = await api("/api/regenerate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: selected.id})
      });
      $("title").value = data.title;
      $("description").value = data.description;
    }

    async function deepAnalyze() {
      if (!selected) return;
      $("log").textContent = "Analyzing weak clues and cached web evidence...\n";
      const data = await api("/api/regenerate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({id: selected.id, online: true})
      });
      $("title").value = data.title;
      $("description").value = data.description;
      if (data.analysis) {
        const evidence = (data.analysis.evidence || []).join("; ") || "-";
        $("log").textContent += `Character: ${data.analysis.character || "-"}\n`;
        $("log").textContent += `Source: ${data.analysis.source || "-"}\n`;
        $("log").textContent += `Confidence: ${Math.round((data.analysis.confidence || 0) * 100)}%\n`;
        $("log").textContent += `Scene: ${data.analysis.scene || "-"}\n`;
        $("log").textContent += `Evidence: ${evidence}\n`;
      }
      $("log").textContent += "Analysis draft generated.\n";
    }

    async function upload() {
      if (!selected) return;
      await saveMeta();
      $("upload").disabled = true;
      $("log").textContent = "创建上传任务...\n";
      try {
        const data = await api("/api/upload", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            id: selected.id,
            title: $("title").value.trim(),
            description: $("description").value.trim(),
            privacy: $("privacy").value
          })
        });
        pollJob(data.job_id);
      } catch (err) {
        $("log").textContent += err.message + "\n";
        $("upload").disabled = false;
      }
    }

    async function pollJob(jobId) {
      clearInterval(polling);
      polling = setInterval(async () => {
        const job = await api("/api/job?id=" + encodeURIComponent(jobId));
        $("log").textContent = (job.log || []).join("\n");
        $("log").scrollTop = $("log").scrollHeight;
        if (job.status === "done" || job.status === "error") {
          clearInterval(polling);
          $("upload").disabled = false;
          await loadItems();
        }
      }, 1000);
    }

    $("refresh").onclick = loadItems;
    $("saveMeta").onclick = saveMeta;
    $("regen").onclick = regenerate;
    $("deepAnalyze").onclick = deepAnalyze;
    $("upload").onclick = upload;
    $("openChrome").onclick = async () => {
      const data = await api("/api/chrome", {method: "POST"});
      $("log").textContent = data.message;
    };

    loadItems();
  </script>
</body>
</html>
"""


def now_text() -> str:
    return time.strftime("%H:%M:%S")


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"metadata": {}, "uploads": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"metadata": {}, "uploads": {}}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def video_id_for_path(path: Path) -> str:
    return hashlib.sha1(str(path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]


def clean_filename_text(path: Path) -> str:
    text = path.stem
    text = re.sub(r"\d{4}[-_.年]\d{1,2}[-_.月]\d{1,2}.*?(视频|-)", " ", text)
    text = re.sub(r"[#【】\[\]（）()]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_download_desc(path: Path) -> str:
    meta_path = path.parent / "download_meta.json"
    if not meta_path.exists():
        return ""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    output_file = str(data.get("output_file") or "").strip()
    if output_file:
        try:
            if Path(output_file).resolve() != path.resolve():
                return ""
        except Exception:
            return ""
    elif data.get("aweme_id"):
        # Single-work downloads write per-video metadata. Batch folders may contain
        # a stale or unrelated sidecar, so do not trust it unless it names this file.
        return ""
    return str(data.get("desc") or "").strip()


def parse_filename_context(path: Path) -> dict:
    stem = path.stem
    sidecar_desc = read_download_desc(path)
    context = {
        "creator": "",
        "caption": "",
        "caption_en": "",
        "hashtags": [],
        "search_text": stem,
    }
    marker = "-\u89c6\u9891-"
    tail = stem.split(marker, 1)[1] if marker in stem else stem
    if marker in stem and "-" in tail:
        creator, caption = tail.split("-", 1)
        context["creator"] = creator.strip()
    else:
        caption = tail
    if sidecar_desc:
        caption = f"{caption} {sidecar_desc}"
    caption = re.sub(r"^\d{4}[-_.]\d{1,2}[-_.]\d{1,2}\s+\d{1,2}[.:\-]\d{1,2}[.:\-]\d{1,2}[-_\s]*", "", caption)
    hashtags = re.findall(r"#([^\s#]+)", caption)
    caption_text = re.sub(r"#([^\s#]+)", " ", caption)
    caption_text = re.sub(r"[~\uff5e!?.?]+$", "", caption_text)
    caption_text = re.sub(r"\s+", " ", caption_text).strip(" -_")
    context["caption"] = caption_text
    context["hashtags"] = hashtags
    translated_parts = []
    for source, translated in CAPTION_TRANSLATIONS.items():
        if caption_text and source in caption_text and translated not in translated_parts:
            translated_parts.append(translated)
    context["caption_en"] = " ".join(translated_parts)
    context["search_text"] = " ".join([stem, sidecar_desc, caption_text, " ".join(hashtags)])
    return context


def infer_title_from_context(context: dict) -> str | None:
    combined = " ".join([context.get("caption", ""), " ".join(context.get("hashtags", []))])
    lowered = combined.lower()
    if "\u6c38\u52ab\u65e0\u95f4" in combined or "naraka" in lowered:
        return "This Naraka Bladepoint Cosplay Looks Unreal"
    if "\u738b\u8005\u8363\u8000" in combined or "honor of kings" in lowered:
        return "This Honor of Kings Cosplay Looks Unreal"
    if "\u6f2b\u5c55" in combined or "bw" in lowered or "bilibiliworld" in lowered:
        return "Amazing Cosplay Moment at Anime Convention"
    if "\u97e9\u56fd" in combined or "korea" in lowered or "korean" in lowered:
        return "Korean Cosplayer Moment at the Convention"
    if "\u82d7\u7586" in combined or "\u6c11\u65cf\u670d\u9970" in combined or "\u82d7\u5bb6" in combined:
        return "Miao Style Costume Look in Real Life"
    if "\u63a5\u8d22\u795e" in combined or "\u8d22\u795e" in combined:
        return "Cosplayer Welcomes the God of Wealth"
    if "\u6cf3\u88c5" in combined and ("\u6c34\u4e0a\u4e50\u56ed" in combined or "\u6e58\u6c5f" in combined):
        return "Summer Cosplay Moment at the Water Park"
    if "\u6cf3\u88c5" in combined:
        return "Swimsuit Cosplay Look in Real Life"
    if "\u6c34\u4e0a\u4e50\u56ed" in combined or "\u6e58\u6c5f" in combined:
        return "Summer Cosplay Moment at the Water Park"
    return None

def find_rule(text: str) -> dict | None:
    lowered = text.lower()
    for rule in CHARACTER_RULES:
        if any(pattern.lower() in lowered for pattern in rule["patterns"]):
            return rule
    return None


def make_description(rule: dict | None, fallback_title: str, context: dict | None = None) -> str:
    context = context or {}
    moment = context.get("caption_en") or ""
    combined = " ".join([context.get("caption", ""), " ".join(context.get("hashtags", []))])
    if rule:
        lines = [f"Real-life {rule['character']} cosplay short filmed in a cinematic style."]
        if moment:
            lines.append(f"Moment: {moment}")
        lines.append(f"Character: {rule['character']}")
        if rule.get("source"):
            lines.append(f"Source: {rule['source']}")
        lines.extend(["", "Subscribe for more real cosplay moments.", "", " ".join(rule["tags"])])
        return "\n".join(lines)
    if "\u6cf3\u88c5" in combined and ("\u6c34\u4e0a\u4e50\u56ed" in combined or "\u6e58\u6c5f" in combined):
        return "\n".join(
            [
                "Real-life swimsuit cosplay short filmed at a water park.",
                "Location: Changsha Xiangjiang Water Park" if "\u6e58\u6c5f" in combined else "Location: Water park",
                "Style: Swimsuit cosplay / summer water park",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#SwimsuitCosplay #WaterPark #Cosplay #shorts",
            ]
        )
    if "\u6cf3\u88c5" in combined:
        return "\n".join(
            [
                "Real-life swimsuit cosplay short filmed in a cinematic style.",
                "Style: Swimsuit cosplay",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#SwimsuitCosplay #Cosplay #Cosplayer #shorts",
            ]
        )
    if "\u6c38\u52ab\u65e0\u95f4" in combined or "naraka" in combined.lower():
        return "\n".join(
            [
                "Real-life Naraka Bladepoint cosplay short filmed in a cinematic style.",
                "Source: Naraka: Bladepoint",
                "",
                "Subscribe for more real game cosplay moments.",
                "",
                "#NarakaBladepoint #GameCosplay #Cosplay #shorts",
            ]
        )
    if "\u738b\u8005\u8363\u8000" in combined or "honor of kings" in combined.lower():
        return "\n".join(
            [
                "Real-life Honor of Kings cosplay short filmed in a cinematic style.",
                "Source: Honor of Kings",
                "",
                "Subscribe for more real game cosplay moments.",
                "",
                "#HonorOfKings #GameCosplay #Cosplay #shorts",
            ]
        )
    if "\u6f2b\u5c55" in combined or "bw" in combined.lower() or "bilibiliworld" in combined.lower():
        return "\n".join(
            [
                "Real-life anime convention cosplay short filmed on site.",
                "Scene: Convention floor cosplay showcase",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#AnimeConvention #Cosplay #Cosplayer #shorts",
            ]
        )
    if "\u97e9\u56fd" in combined or "korea" in combined.lower() or "korean" in combined.lower():
        return "\n".join(
            [
                "Real-life Korean cosplayer short filmed in a cinematic style.",
                "Scene: Cosplayer showcase",
                "",
                "Subscribe for more real cosplay moments.",
                "",
                "#KoreanCosplayer #Cosplay #Cosplayer #shorts",
            ]
        )
    return "\n".join(
        [line for line in [
            "Real-life cosplayer showcase filmed in a cinematic style.",
            f"Moment: {moment}" if moment else "",
            "",
            "Subscribe for more real cosplay moments.",
            "",
            "#Cosplay #Cosplayer #CosplayShorts #shorts",
        ] if line or line == ""]
    )


def draft_metadata(path: Path, override: dict | None = None, allow_online: bool = False) -> dict:
    context = parse_filename_context(path)
    try:
        metadata = cosplay_metadata_analyzer.draft_metadata_for_path(
            path,
            context=context,
            allow_online=allow_online,
        )
        if override:
            metadata.update({k: v for k, v in override.items() if k in ("title", "description")})
        return metadata
    except Exception as exc:
        logger.warning("元数据分析失败，使用回退逻辑 (%s): %s", path.name, exc)

    text = clean_filename_text(path)
    rule = find_rule(context["search_text"])
    title = f"{rule['character']} Cosplay Looks Unreal in Real Life" if rule else "Beautiful Cosplay Moment in Real Life"
    inferred_title = infer_title_from_context(context) if not rule else None
    if inferred_title:
        title = inferred_title
    elif not rule and context.get("caption_en"):
        title = context["caption_en"].rstrip(".")
    description = make_description(rule, title, context)
    metadata = {"title": title, "description": description}
    if override:
        metadata.update({k: v for k, v in override.items() if k in ("title", "description")})
    return metadata


def validate_publish_copy(title: str, description: str) -> None:
    combined = f"{title}\n{description}".lower()
    blocked = [
        "unknown",
        "\u89d2\u8272\u672a\u77e5",
        "real cosplay moment | cosplay short",
    ]
    for term in blocked:
        if term.lower() in combined:
            raise ValueError(
                "Title/description still contains a weak fallback term. Regenerate or edit it before uploading."
            )


def scan_roots(state: dict | None = None) -> list[Path]:
    if state is None:
        with STATE_LOCK:
            state = load_state()
    roots = list(VIDEO_DIRS)
    for raw in state.get("custom_paths", []):
        path = Path(raw)
        if path.exists():
            roots.append(path if path.is_dir() else path.parent)
    return list(dict.fromkeys(path.resolve() for path in roots))


def add_custom_path(path: Path) -> None:
    path = path.resolve()
    with STATE_LOCK:
        state = load_state()
        paths = state.setdefault("custom_paths", [])
        text = str(path)
        if text not in paths:
            paths.append(text)
        save_state(state)


def scan_videos() -> list[dict]:
    with STATE_LOCK:
        state = load_state()
    metadata_state = state.get("metadata", {})
    uploads = state.get("uploads", {})
    found: list[Path] = []
    for root in scan_roots(state):
        if not root.exists():
            continue
        found.extend(path for path in root.rglob("*.mp4") if path.is_file())
    found = sorted(set(found), key=lambda path: path.stat().st_mtime, reverse=True)
    items = []
    for path in found:
        item_id = video_id_for_path(path)
        stat = path.stat()
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
    return items


def item_by_id(item_id: str) -> dict:
    for item in scan_videos():
        if item["id"] == item_id:
            return item
    raise KeyError("Video not found")


def chrome_executable() -> Path:
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LocalAppData", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Chrome executable not found")


def launch_chrome() -> str:
    chrome = chrome_executable()
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    args = [
        str(chrome),
        "--remote-debugging-port=9222",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={CHROME_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--window-position=0,0",
        "--window-size=1400,1000",
        "https://studio.youtube.com/",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Chrome opened. If needed, log in to YouTube Studio there.\nProfile: {CHROME_PROFILE}"


def chrome_debug_port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=1):
            return True
    except OSError:
        return False


def stop_controlled_chrome() -> None:
    profile_marker = str(CHROME_PROFILE)
    script = rf"""
Get-CimInstance Win32_Process -Filter "name='chrome.exe'" |
    Where-Object {{
        $_.CommandLine -like '*--remote-debugging-port=9222*' -or
        $_.CommandLine -like '*{profile_marker}*'
    }} |
    ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )


def restart_controlled_chrome() -> str:
    stop_controlled_chrome()
    deadline = time.time() + 10
    while time.time() < deadline and chrome_debug_port_open():
        time.sleep(0.2)
    message = launch_chrome()
    deadline = time.time() + 20
    while time.time() < deadline:
        if chrome_debug_port_open():
            return message
        time.sleep(0.5)
    raise RuntimeError("Controlled Chrome did not open debugging port 9222.")


def log(job: dict, message: str) -> None:
    job.setdefault("log", []).append(f"{now_text()} {message}")


def import_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Python Playwright is not installed. Run: "
            f"{config.YTB_PYTHON} -m pip install playwright"
        ) from exc
    return sync_playwright


# ── YouTube 上传超时常量 (毫秒) ─────────────────────────
TIMEOUT_SHORT = 12000       # 控件点击超时
TIMEOUT_MEDIUM = 30000      # 页面元素可见性等待
TIMEOUT_LONG = 60000        # YouTube Studio 页面加载/处理等待


def first_visible(locator, timeout=TIMEOUT_MEDIUM):
    locator.first.wait_for(state="visible", timeout=timeout)
    return locator.first


def click_first_available(locators: list, timeout=TIMEOUT_SHORT) -> None:
    last_error = None
    for locator in locators:
        try:
            locator.first.wait_for(state="visible", timeout=2000)
            locator.first.click(timeout=timeout)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not click expected YouTube control: {last_error}")


def wait_for_studio_ready(page, job: dict, timeout=TIMEOUT_LONG) -> None:
    deadline = time.time() + timeout / 1000
    last_url = ""
    while time.time() < deadline:
        try:
            url = page.url
            if url != last_url:
                last_url = url
                log(job, f"Studio page state: {url}")
            if "accounts.youtube.com" in url or "accounts.google.com" in url:
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                time.sleep(1)
                continue
            if "studio.youtube.com" in url:
                if page.locator("input[type=file]").count():
                    return
                if page.locator("#upload-button button").count() or page.locator("#upload-button").count():
                    page.locator("#upload-button").first.wait_for(state="visible", timeout=5000)
                    return
                if page.get_by_text(re.compile("(Upload videos|\u4e0a\u4f20\u89c6\u9891)")).count():
                    return
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"YouTube Studio upload page was not ready. Last URL: {page.url}")


def fill_upload_textboxes(page, title: str, description: str) -> None:
    boxes = page.locator('div[role="textbox"][contenteditable="true"]')
    boxes.nth(0).wait_for(state="visible", timeout=60000)
    boxes.nth(0).fill(title)
    boxes.nth(1).wait_for(state="visible", timeout=30000)
    boxes.nth(1).fill(description)


def attach_youtube_video(page, video_path: Path, job: dict) -> None:
    """Attach a local video to Studio's intentionally hidden Filedata input.

    YouTube keeps the real file field hidden and occasionally leaves the first
    Studio load in a transitional state. Re-query it on retry instead of
    holding a stale locator.
    """
    last_error = None
    for attempt in range(1, 3):
        file_input = page.locator('input[type="file"][name="Filedata"]')
        if not file_input.count():
            file_input = page.locator('input[type="file"]')
        try:
            file_input.first.wait_for(state="attached", timeout=30000)
            info = file_input.first.evaluate(
                "el => ({disabled: !!el.disabled, name: el.name || '', accept: el.accept || ''})"
            )
            if info.get("disabled"):
                raise RuntimeError("YouTube Studio file input is temporarily disabled.")
            log(job, f"Attaching video (attempt {attempt}/2): {video_path.name}")
            # The input is expected to be aria-hidden; Playwright can still set
            # files on an attached file input without opening a native dialog.
            file_input.first.set_input_files(str(video_path), timeout=90000)
            log(job, "Video file accepted by YouTube Studio")
            return
        except Exception as exc:
            last_error = exc
            log(job, f"File input attempt {attempt}/2 failed: {exc}")
            if attempt == 1:
                log(job, "Reloading the Studio upload page and retrying file attachment")
                page.goto(
                    f"https://studio.youtube.com/channel/{CHANNEL_ID}/videos/upload",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                wait_for_studio_ready(page, job, timeout=60000)
                page.wait_for_timeout(2000)
    raise RuntimeError(f"YouTube Studio could not accept the video file after retry: {last_error}")


def click_next(page) -> None:
    click_first_available(
        [
            page.get_by_role("button", name=re.compile("^(Next|\u4e0b\u4e00\u6b65|\u7ee7\u7eed)$")),
            page.locator("#next-button button"),
            page.locator("ytcp-button").filter(has_text=re.compile("(Next|\u4e0b\u4e00\u6b65|\u7ee7\u7eed)")),
        ],
        timeout=30000,
    )


def click_visibility(page, privacy: str) -> None:
    css_names = {
        "public": "PUBLIC",
        "unlisted": "UNLISTED",
        "private": "PRIVATE",
    }
    text_names = {
        "public": re.compile("^(Public|\u516c\u5f00)$"),
        "unlisted": re.compile("^(Unlisted|\u4e0d\u516c\u5f00\u5217\u51fa)$"),
        "private": re.compile("^(Private|\u79c1\u4eab)$"),
    }
    locators = [
        page.locator(f'tp-yt-paper-radio-button[name="{css_names.get(privacy, "PUBLIC")}"]'),
        page.get_by_text(text_names.get(privacy, text_names["public"])),
        page.locator("tp-yt-paper-radio-button").filter(has_text=text_names.get(privacy, text_names["public"])),
    ]
    click_first_available(locators, timeout=30000)


def click_publish_or_save(page, privacy: str) -> None:
    labels = (
        re.compile("^(Publish|\u53d1\u5e03)$")
        if privacy == "public"
        else re.compile("^(Save|\u4fdd\u5b58)$")
    )
    click_first_available(
        [
            page.get_by_role("button", name=labels),
            page.locator("#done-button button"),
            page.locator("ytcp-button").filter(has_text=labels),
        ],
        timeout=60000,
    )


def connect_controlled_chrome(playwright, job: dict):
    last_error = None
    for attempt in range(1, 3):
        try:
            log(job, f"Connecting to controlled Chrome (attempt {attempt}/2)")
            browser = playwright.chromium.connect_over_cdp(CHROME_DEBUG_URL, timeout=15000)
            log(job, "Controlled Chrome connected")
            return browser
        except Exception as exc:
            last_error = exc
            log(job, f"Chrome connection failed: {exc}")
            if attempt == 1:
                log(job, "Restarting controlled Chrome and retrying")
                restart_controlled_chrome()
                time.sleep(2)
    raise RuntimeError(f"Could not connect to controlled Chrome after restart: {last_error}")


def run_upload(job_id: str, item: dict, title: str, description: str, privacy: str) -> None:
    job = JOBS[job_id]
    try:
        validate_publish_copy(title, description)
        sync_playwright = import_playwright()
        video_path = Path(item["path"])
        if not video_path.exists():
            raise FileNotFoundError(video_path)

        with sync_playwright() as p:
            browser = connect_controlled_chrome(p, job)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = next((candidate for candidate in context.pages if "studio.youtube.com" in candidate.url), None)
            page = page or context.new_page()

            log(job, "Opening YouTube Studio upload page")
            page.goto(
                f"https://studio.youtube.com/channel/{CHANNEL_ID}/videos/upload",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            wait_for_studio_ready(page, job, timeout=60000)

            if not page.locator("input[type=file]").count():
                click_first_available(
                    [
                        page.locator("#upload-button button"),
                        page.locator("#upload-button"),
                        page.get_by_role("button", name=re.compile("(Upload videos|\u4e0a\u4f20\u89c6\u9891)")),
                        page.get_by_text(re.compile("(Upload videos|\u4e0a\u4f20\u89c6\u9891)")),
                    ],
                    timeout=45000,
                )
                page.wait_for_timeout(1500)
                wait_for_studio_ready(page, job, timeout=45000)

            log(job, f"Uploading file: {video_path.name} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")
            attach_youtube_video(page, video_path, job)
            page.wait_for_timeout(6000)

            log(job, "Filling title and description")
            fill_upload_textboxes(page, title, description)

            body = page.locator("body").inner_text(timeout=10000)
            if (
                "made for kids" in body.lower()
                or "\u4e3a\u513f\u7ae5\u6253\u9020" in body
                or "\u9762\u5411\u513f\u7ae5" in body
            ):
                click_first_available(
                    [
                        page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'),
                        page.get_by_text(
                            re.compile(
                                "(No, it's not made for kids|No, set this video as not made for kids|\u4e0d.*\u9762\u5411\u513f\u7ae5)"
                            )
                        ),
                        page.locator("tp-yt-paper-radio-button").filter(
                            has_text=re.compile("(not made for kids|\u4e0d.*\u9762\u5411\u513f\u7ae5)", re.I)
                        ),
                    ],
                    timeout=10000,
                )
                page.wait_for_timeout(1000)

            for step in ("details", "elements", "checks"):
                log(job, f"Continuing from {step}")
                click_next(page)
                page.wait_for_timeout(4000)
            page.wait_for_timeout(8000)

            log(job, f"Selecting visibility: {privacy}")
            click_visibility(page, privacy)
            page.wait_for_timeout(1000)

            log(job, "Publishing" if privacy == "public" else "Saving")
            click_publish_or_save(page, privacy)
            page.wait_for_timeout(12000)

            body = page.locator("body").inner_text(timeout=10000)
            url_match = re.search(r"https://youtube\.com/shorts/[A-Za-z0-9_-]+", body)
            video_url = url_match.group(0) if url_match else ""
            job["video_url"] = video_url
            log(job, f"Done: {video_url or 'uploaded'}")

            with STATE_LOCK:
                state = load_state()
                state.setdefault("uploads", {})[item["id"]] = {
                    "uploaded_at": time.time(),
                    "title": title,
                    "description": description,
                    "privacy": privacy,
                    "url": video_url,
                }
                save_state(state)
            job["status"] = "done"
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        log(job, f"Error: {exc}")


def send_json(handler: BaseHTTPRequestHandler, data: dict, status: int = 200) -> None:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


class Handler(BaseHTTPRequestHandler):
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
                    state = load_state()
                    state.setdefault("metadata", {})[item["id"]] = {
                        "title": body.get("title", "").strip(),
                        "description": body.get("description", "").strip(),
                    }
                    save_state(state)
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
