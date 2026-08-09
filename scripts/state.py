"""共享状态管理 — 被 pipeline_ui / youtube_uploader / pipeline_desktop_qt 共同引用。"""

import hashlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

import config
import utils

logger = logging.getLogger(__name__)

STATE_PATH = config.STATE_PATH
STATE_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}

# 向后兼容：now_text 统一由 utils 提供
now_text = utils.now_text


def load_state() -> dict:
    """加载 pipeline_state.json，失败时返回空骨架。"""
    if not STATE_PATH.exists():
        return {"metadata": {}, "uploads": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load state file: %s", exc)
        return {"metadata": {}, "uploads": {}}


def save_state(state: dict) -> None:
    """原子写入状态文件，防止写入中途崩溃导致数据损坏。

    先写入同目录临时文件，再用 os.replace() 原子替换。
    """
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=STATE_PATH.parent, suffix=".tmp", prefix=".state_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_PATH)
    except BaseException:
        # 写入失败时清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def video_id_for_path(path: Path) -> str:
    """根据文件绝对路径生成稳定的 16 位 hash ID。"""
    return hashlib.sha1(str(path.resolve()).encode("utf-8", errors="ignore")).hexdigest()[:16]
