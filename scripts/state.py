"""共享状态管理 — 被 pipeline_ui / youtube_uploader / pipeline_desktop_qt 共同引用。"""

import hashlib
import json
import threading
import time
from pathlib import Path

import config

STATE_PATH = config.STATE_PATH
STATE_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}


def now_text() -> str:
    """格式化当前时间，用于日志前缀。"""
    return time.strftime("%H:%M:%S")


def load_state() -> dict:
    """加载 pipeline_state.json，失败时返回空骨架。"""
    if not STATE_PATH.exists():
        return {"metadata": {}, "uploads": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"metadata": {}, "uploads": {}}


def save_state(state: dict) -> None:
    """持久化状态到 pipeline_state.json。"""
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def video_id_for_path(path: Path) -> str:
    """根据文件绝对路径生成稳定的 16 位 hash ID。"""
    return hashlib.sha1(str(path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]
