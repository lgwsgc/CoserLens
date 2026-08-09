"""CoserLens Pipeline - 通用工具函数

消除跨文件的重复实现（now_text、sanitize_name、format_bytes 等）。
"""

import re
import time


def now_text() -> str:
    """格式化当前时间，用于日志前缀。"""
    return time.strftime("%H:%M:%S")


def sanitize_name(name: str, max_length: int = 120) -> str:
    """清理文件名中的非法字符，返回安全文件名。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_length] or "douyin_video"


def safe_stem(path_name: str) -> str:
    """从文件名（或 stem）中移除非法字符。"""
    return re.sub(r'[\\/:*?"<>|]', "_", path_name)


def format_bytes(num: float) -> str:
    """将字节数格式化为人类可读的字符串。"""
    if not num:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = num
    i = 0
    while value >= 1024 and i < len(units) - 1:
        value /= 1024
        i += 1
    return f"{value:.{2 if i else 0}f} {units[i]}"
