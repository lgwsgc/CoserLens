"""CoserLens Pipeline - 统一日志配置

所有模块通过 logging.getLogger(__name__) 获取 logger，
此模块负责统一配置格式和输出目标。

调用 setup_logging() 一次即可（通常在应用入口处）。
"""

import logging
import sys

from pathlib import Path

import config


def setup_logging(level: int = logging.INFO) -> None:
    """配置全局日志：控制台 + 文件。

    在应用入口（如 pipeline_desktop_qt.py 的 main）中调用一次。
    多次调用安全（使用 force=True 覆盖旧配置）。
    """
    log_dir = config.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pipeline.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,  # 覆盖任何已有的配置
    )
