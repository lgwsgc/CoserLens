"""CoserLens Pipeline - 视频列表卡片 widget

自定义 QFrame 列表项：缩略图 + 标题 + 元数据 + 状态徽章。
配合 QListWidget.setItemWidget 使用，比纯 QListWidgetItem 灵活得多。
"""

from __future__ import annotations

import config
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import theme

THUMB_DIR = config.THUMB_DIR
THUMB_SIZE = 64  # 缩略图渲染尺寸


class VideoCard(QFrame):
    """单条视频卡片。

    包含：
    - 缩略图（64x64，缺失时显示首字符）
    - 标题（加粗，截断）
    - 元数据行（时间 · 大小）
    - 路径行（次要文字）
    - 状态徽章（已上传/草稿/待上传）
    """

    clicked = Signal(str)  # 发出 item_id

    def __init__(self, item: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.item = item
        self.item_id = item["id"]
        self._build()
        self.setProperty("selected", False)
        self.setProperty("uploaded", bool(item.get("upload", {}).get("url")))
        self.setProperty("draft", bool(item.get("upload", {}).get("draft")))
        # 强制刷新样式（property 改变后需要重新应用）
        self.style().unpolish(self)
        self.style().polish(self)

    def _build(self):
        self.setObjectName("VideoCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # ── 缩略图 ──
        self.thumb = QLabel()
        self.thumb.setObjectName("VideoThumb")
        self.thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        self.thumb.setAlignment(Qt.AlignCenter)
        self._load_thumb()
        layout.addWidget(self.thumb, 0, Qt.AlignVCenter)

        # ── 中部文字区 ──
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_text = self.item["title"]
        if title_text and len(title_text) > 50:
            title_text = title_text[:48] + "…"
        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("VideoTitle")
        self.title_label.setToolTip(self.item["title"])
        text_col.addWidget(self.title_label)

        meta_text = f"{self.item['modified_text']}  ·  {self._format_size(self.item['size'])}"
        self.meta_label = QLabel(meta_text)
        self.meta_label.setObjectName("VideoMeta")
        text_col.addWidget(self.meta_label)

        path_text = self.item.get("relative_path", self.item["filename"])
        if len(path_text) > 60:
            path_text = "…" + path_text[-58:]
        self.path_label = QLabel(path_text)
        self.path_label.setObjectName("VideoPath")
        self.path_label.setToolTip(self.item.get("relative_path", self.item["filename"]))
        text_col.addWidget(self.path_label)

        layout.addLayout(text_col, 1)

        # ── 状态徽章 ──
        status = theme.status_for_item(self.item)
        badge_text, badge_obj = theme.make_status_badge(status)
        self.badge = QLabel(badge_text)
        self.badge.setObjectName(badge_obj)
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedHeight(20)
        self.badge.setMinimumWidth(56)
        layout.addWidget(self.badge, 0, Qt.AlignVCenter)

    def _load_thumb(self):
        """加载缩略图；缺失时显示首字符占位。"""
        thumb_path = THUMB_DIR / f"{self.item_id}.jpg"
        if thumb_path.exists():
            pixmap = QPixmap(str(thumb_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    THUMB_SIZE, THUMB_SIZE,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                # 居中裁剪
                x = (scaled.width() - THUMB_SIZE) // 2
                y = (scaled.height() - THUMB_SIZE) // 2
                scaled = scaled.copy(x, y, THUMB_SIZE, THUMB_SIZE)
                self.thumb.setPixmap(scaled)
                self.thumb.setText("")
                return
        # 占位：取首字符
        first_char = (self.item["title"][:1] if self.item.get("title") else "▶").upper()
        self.thumb.setText(first_char)
        font = self.thumb.font()
        font.setPointSize(22)
        font.setBold(True)
        self.thumb.setFont(font)

    def set_selected(self, selected: bool):
        """设置选中态（红色边框 + 浅紫背景）。"""
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.item_id)
        super().mousePressEvent(event)

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化字节数为人类可读字符串。"""
        units = ["B", "KB", "MB", "GB"]
        value = float(size or 0)
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        return f"{value:.1f} {units[index]}" if index else f"{int(value)} B"
