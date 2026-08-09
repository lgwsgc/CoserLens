"""CoserLens Pipeline - 统一配置

所有路径和常量集中管理，避免硬编码。
REPO_ROOT 通过脚本位置自动推导，换电脑/改目录无需修改代码。
"""

import os
import shutil
from pathlib import Path

# ── 核心路径（自动推导，不硬编码）──────────────────────────
# scripts/ 的父目录就是项目根
REPO_ROOT = Path(__file__).resolve().parent.parent

# 视频目录
VIDEO_DIRS = [
    REPO_ROOT / "video",
    REPO_ROOT / "download_ui_outputs",
    REPO_ROOT / "enhanced_outputs",
]

# 状态文件
STATE_PATH = REPO_ROOT / "pipeline_state.json"
DESKTOP_STATE_PATH = REPO_ROOT / ".pipeline_desktop_qt_state.json"

# Chrome 配置
CHROME_PROFILE = REPO_ROOT / ".codex_chrome_youtube_profile"
CHROME_DEBUG_URL = "http://127.0.0.1:9222"

# 运行时目录
THUMB_DIR = REPO_ROOT / ".pipeline_thumbnails"
LOG_DIR = REPO_ROOT / ".pipeline_logs"

# 下载相关
TIKTOK_DOWNLOADER = REPO_ROOT / "TikTokDownloader"
TIKTOK_SETTINGS_PATH = TIKTOK_DOWNLOADER / "Volume" / "settings.json"
DOWNLOAD_OUTPUT_ROOT = REPO_ROOT / "download_ui_outputs"

# 增强相关
ENHANCED_OUTPUT_ROOT = REPO_ROOT / "enhanced_outputs"
REALESRGAN_DIR = REPO_ROOT / "tools" / "realesrgan-ncnn-vulkan-20220424-windows"
REALESRGAN_EXE = REALESRGAN_DIR / "realesrgan-ncnn-vulkan.exe"
REALESRGAN_MODEL_DIR = REALESRGAN_DIR / "models"

# 资源
ASSETS_DIR = REPO_ROOT / "assets"
APP_ICON_PATH = ASSETS_DIR / "coserlens_logo.svg"
CATALOG_PATH = REPO_ROOT / "scripts" / "cosplay_catalog.json"

# 频道
CHANNEL_ID = "UCZczM9s_ppC1spTRCE2oo8A"

# 端口
API_PORT = 7863
DOWNLOAD_UI_PORT = 7862
SINGLE_INSTANCE_PORT = 17864

# 网络
# 抖音/TikTok CDN 在部分地区可能有证书链问题，可通过环境变量 COSERLENS_VERIFY_SSL=0 关闭
VERIFY_SSL = os.environ.get("COSERLENS_VERIFY_SSL", "1") != "0"

# 应用信息
APP_TITLE = "CoserLens Pipeline"
BATCH_DOWNLOAD_LIMIT = 100


def _find_executable(name: str, fallback_dir: Path | None = None) -> str:
    """先从 PATH 查找，找不到再试 fallback_dir"""
    found = shutil.which(name)
    if found:
        return found
    if fallback_dir:
        candidate = fallback_dir / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        f"找不到 {name}。请确保它在 PATH 中，或放在: {fallback_dir}"
    )


# ── 外部工具（自动检测，有回退）──────────────────────────
FFMPEG_DIR = Path(r"D:\Program Files (x86)\ffmpeg\bin")
FFMPEG = _find_executable("ffmpeg", FFMPEG_DIR)

# ffprobe 在当前 FFmpeg 目录中不存在，设为 None（需要时单独安装）
try:
    FFPROBE = _find_executable("ffprobe", FFMPEG_DIR)
except FileNotFoundError:
    FFPROBE = None

# Python 环境（用于启动子进程）
YTB_PYTHON = Path(r"D:\anaconda3\envs\ytb\python.exe")
if not YTB_PYTHON.exists():
    # 回退到当前 Python
    import sys

    YTB_PYTHON = Path(sys.executable)
