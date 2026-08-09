"""CoserLens Pipeline - 主题系统

集中管理品牌色、字体、间距、圆角、阴影，生成浅色/暗色 QSS。
支持运行时切换主题，偏好保存到 desktop_state.json。

品牌色：紫蓝渐变 (神秘感) + 青绿 (辅助) + 橙红 (强调)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import config

# ── 品牌色常量 ──────────────────────────────────────────
# 主色：紫蓝渐变 — 神秘 / 电影感
PRIMARY = "#6d28d9"        # 紫
PRIMARY_DARK = "#5b21b6"   # 深紫（hover）
PRIMARY_LIGHT = "#ede9fe"  # 浅紫（selected bg）

# 次色：青绿 — 辅助操作
SECONDARY = "#0d9488"      # 青绿
SECONDARY_DARK = "#0f766e"
SECONDARY_LIGHT = "#ccfbf1"

# 强调：橙红 — 危险/上传
DANGER = "#dc2626"
DANGER_DARK = "#b91c1c"
DANGER_LIGHT = "#fee2e2"

# 警告：琥珀
WARN = "#d97706"
WARN_LIGHT = "#fef3c7"

# 成功：绿
SUCCESS = "#16a34a"
SUCCESS_LIGHT = "#dcfce7"

# 字体
FONT_FAMILY = '"Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif'
FONT_MONO = '"Cascadia Code", "Consolas", "JetBrains Mono", monospace'

# 圆角 / 间距
RADIUS_SM = 4
RADIUS = 6
RADIUS_LG = 10
SPACING_XS = 4
SPACING_SM = 8
SPACING = 12
SPACING_LG = 16


# ── 浅色主题 ────────────────────────────────────────────
_LIGHT_COLORS = {
    "bg":          "#f3f6f8",
    "surface":     "#ffffff",
    "surface_alt": "#f8fafc",
    "text":        "#182230",
    "text_strong": "#101828",
    "text_muted":  "#697586",
    "border":      "#d7dee8",
    "border_strong": "#cfd8e3",
    "selection":   "#ede9fe",
    "selection_text": "#3b0764",
    "hover":       "#f3e8ff",
    "preview_bg":  "#101828",
    "preview_text": "#d6e4f0",
    "log_bg":      "#0f172a",
    "log_text":    "#d6e4f0",
    "scrollbar":   "#cbd5e1",
    "scrollbar_hover": "#94a3b8",
}

# ── 暗色主题 ────────────────────────────────────────────
_DARK_COLORS = {
    "bg":          "#0a0e1a",
    "surface":     "#111827",
    "surface_alt": "#0f172a",
    "text":        "#e2e8f0",
    "text_strong": "#f1f5f9",
    "text_muted":  "#94a3b8",
    "border":      "#1e293b",
    "border_strong": "#334155",
    "selection":   "#4c1d95",
    "selection_text": "#f5f3ff",
    "hover":       "#1e1b4b",
    "preview_bg":  "#020617",
    "preview_text": "#cbd5e1",
    "log_bg":      "#020617",
    "log_text":    "#cbd5e1",
    "scrollbar":   "#334155",
    "scrollbar_hover": "#475569",
}


def _build_stylesheet(colors: dict, dark: bool) -> str:
    """根据颜色字典生成完整 QSS。"""
    c = colors
    # 暗色模式下面板边框更弱
    border_opacity = "1px" if not dark else "1px"
    panel_border = c["border"] if not dark else c["border"]

    return f"""
/* === 基础 === */
QMainWindow, QWidget {{
    background: {c['bg']};
    color: {c['text']};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}

/* === 顶部 Header === */
QFrame#HeaderBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PRIMARY}, stop:0.6 {PRIMARY}, stop:1 {SECONDARY});
    border: 0;
    border-radius: {RADIUS_LG}px;
}}
QFrame#HeaderBar QLabel#Title {{
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
    background: transparent;
}}
QFrame#HeaderBar QLabel#Subtitle {{
    color: rgba(255, 255, 255, 0.78);
    font-size: 11px;
    background: transparent;
}}
QFrame#HeaderBar QLabel#HeaderNote {{
    color: rgba(255, 255, 255, 0.72);
    font-size: 11px;
    background: transparent;
}}
QFrame#HeaderBar QPushButton#ToolbarButton {{
    background: rgba(255, 255, 255, 0.14);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: {RADIUS}px;
    padding: 7px 12px;
    font-weight: 500;
}}
QFrame#HeaderBar QPushButton#ToolbarButton:hover {{
    background: rgba(255, 255, 255, 0.26);
    border-color: rgba(255, 255, 255, 0.5);
}}
QFrame#HeaderBar QPushButton#ToolbarButton:pressed {{
    background: rgba(255, 255, 255, 0.32);
}}
QFrame#HeaderBar QPushButton#ThemeToggle {{
    background: rgba(255, 255, 255, 0.18);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: 14px;
    padding: 5px 10px;
    font-size: 14px;
    font-weight: 600;
}}
QFrame#HeaderBar QPushButton#ThemeToggle:hover {{
    background: rgba(255, 255, 255, 0.32);
}}
QFrame#HeaderBar QLineEdit {{
    background: rgba(255, 255, 255, 0.95);
    color: {c['text_strong']};
    border: 1px solid rgba(255, 255, 255, 0.4);
    border-radius: {RADIUS}px;
    padding: 7px 11px;
}}
QFrame#HeaderBar QLineEdit:focus {{
    background: #ffffff;
    border: 1px solid #ffffff;
}}

/* === Panel 通用 === */
QFrame#Panel {{
    background: {c['surface']};
    border: 1px solid {panel_border};
    border-radius: {RADIUS_LG}px;
}}

/* === 标题/标签 === */
QLabel#LogoMark {{ background: transparent; }}
QLabel#SectionTitle {{
    color: {c['text_strong']};
    font-size: 15px;
    font-weight: 700;
    padding: 2px 0;
}}
QLabel#FieldLabel {{
    color: {c['text_muted']};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding-top: 4px;
}}
QLabel#Muted {{ color: {c['text_muted']}; }}
QLabel#Scope {{
    color: {c['text']};
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
    padding: 8px 12px;
}}
QLabel#LocalNote {{
    color: {c['text']};
    background: {c['surface_alt']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
    padding: 10px 12px;
    line-height: 1.5;
}}
QLabel#CountLabel {{
    color: {c['text_muted']};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#StatusLabel {{
    color: {c['text_muted']};
    font-size: 12px;
}}

/* === 状态徽章 === */
QLabel#BadgeUploaded {{
    background: {SUCCESS_LIGHT};
    color: {SUCCESS};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#BadgeDraft {{
    background: {WARN_LIGHT};
    color: {WARN};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#BadgeReady {{
    background: {c['surface_alt']};
    color: {c['text_muted']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 700;
}}

/* === 按钮 === */
QPushButton {{
    background: {PRIMARY};
    color: #ffffff;
    border: 0;
    border-radius: {RADIUS}px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 12px;
}}
QPushButton:hover {{ background: {PRIMARY_DARK}; }}
QPushButton:pressed {{ background: #4c1d95; }}
QPushButton:disabled {{
    background: {c['border']};
    color: {c['text_muted']};
}}
QPushButton#Secondary {{
    background: {c['surface']};
    color: {c['text_strong']};
    border: 1px solid {c['border_strong']};
}}
QPushButton#Secondary:hover {{
    background: {c['hover']};
    border-color: {PRIMARY};
    color: {PRIMARY_DARK};
}}
QPushButton#Secondary:pressed {{
    background: {PRIMARY_LIGHT};
}}
QPushButton#Danger {{
    background: {DANGER};
}}
QPushButton#Danger:hover {{ background: {DANGER_DARK}; }}
QPushButton#Danger:pressed {{ background: #991b1b; }}

/* === 输入控件 === */
QLineEdit, QTextEdit, QComboBox {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border_strong']};
    border-radius: {RADIUS}px;
    padding: 7px 10px;
    selection-background-color: {c['selection']};
    selection-color: {c['selection_text']};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1.5px solid {PRIMARY};
    background: {c['surface']};
}}
QTextEdit#Log {{
    background: {c['log_bg']};
    color: {c['log_text']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
    font-family: {FONT_MONO};
    font-size: 11.5px;
    padding: 8px 10px;
    line-height: 1.5;
    selection-background-color: {PRIMARY};
    selection-color: #ffffff;
}}
QComboBox::drop-down {{
    border: 0;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c['text_muted']};
    margin-right: 6px;
}}

/* === 视频列表 === */
QListWidget {{
    background: {c['surface_alt']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
    outline: 0;
    padding: 4px;
}}
QListWidget::item {{
    background: transparent;
    border: 0;
    padding: 0;
    margin: 3px 2px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['scrollbar']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['scrollbar_hover']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background: transparent;
    height: 0;
}}

/* === 视频卡片（自定义 widget） === */
QFrame#VideoCard {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
    padding: 0;
}}
QFrame#VideoCard:hover {{
    border-color: {PRIMARY};
    background: {c['hover']};
}}
QFrame#VideoCard[selected="true"] {{
    background: {c['selection']};
    border: 2px solid {PRIMARY};
}}
QFrame#VideoCard[uploaded="true"] {{
    border-left: 3px solid {SUCCESS};
}}
QFrame#VideoCard[draft="true"] {{
    border-left: 3px solid {WARN};
}}
QLabel#VideoThumb {{
    background: {c['preview_bg']};
    color: {c['preview_text']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS_SM}px;
}}
QLabel#VideoTitle {{
    color: {c['text_strong']};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#VideoMeta {{
    color: {c['text_muted']};
    font-size: 11px;
}}
QLabel#VideoPath {{
    color: {c['text_muted']};
    font-size: 10.5px;
    font-style: italic;
}}

/* === 预览区 === */
QLabel#VideoPreview {{
    background: {c['preview_bg']};
    color: {c['preview_text']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
}}

/* === Splitter === */
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:horizontal {{
    width: 8px;
}}
QSplitter::handle:vertical {{
    height: 8px;
}}
QSplitter::handle:hover {{
    background: {PRIMARY_LIGHT};
}}

/* === 进度对话框 === */
QProgressBar {{
    background: {c['surface_alt']};
    border: 1px solid {c['border']};
    border-radius: {RADIUS}px;
    text-align: center;
    color: {c['text']};
    height: 18px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {PRIMARY}, stop:1 {SECONDARY});
    border-radius: {RADIUS - 1}px;
}}

/* === 工具提示 === */
QToolTip {{
    background: {c['text_strong']};
    color: {c['surface']};
    border: 0;
    border-radius: {RADIUS_SM}px;
    padding: 5px 8px;
    font-size: 11px;
}}

/* === 滚动条 === */
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {c['scrollbar']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {c['scrollbar_hover']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    background: transparent;
    width: 0;
}}
"""


def get_stylesheet(theme: Literal["light", "dark"] = "light") -> str:
    """获取主题 QSS。"""
    colors = _DARK_COLORS if theme == "dark" else _LIGHT_COLORS
    return _build_stylesheet(colors, theme == "dark")


# ── 主题偏好持久化 ──────────────────────────────────────
_THEME_PREF_FILE = config.REPO_ROOT / ".theme_preference"


def load_theme_preference() -> str:
    """从磁盘加载主题偏好。"""
    try:
        if _THEME_PREF_FILE.exists():
            text = _THEME_PREF_FILE.read_text(encoding="utf-8").strip()
            if text in ("light", "dark"):
                return text
    except Exception:
        pass
    return "light"


def save_theme_preference(theme: str) -> None:
    """保存主题偏好到磁盘。"""
    try:
        _THEME_PREF_FILE.write_text(theme, encoding="utf-8")
    except Exception:
        pass


# ── 工具函数 ────────────────────────────────────────────
def make_status_badge(status: str) -> tuple[str, str]:
    """根据状态返回 (徽章文本, ObjectName)。"""
    if status == "uploaded":
        return "已上传", "BadgeUploaded"
    if status == "draft":
        return "草稿", "BadgeDraft"
    return "待上传", "BadgeReady"


def status_for_item(item: dict) -> str:
    """从 video item 中提取状态字符串。"""
    if item.get("upload", {}).get("url"):
        return "uploaded"
    if item.get("upload", {}).get("draft"):
        return "draft"
    return "ready"
