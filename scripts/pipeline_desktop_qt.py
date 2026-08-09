import os
import ctypes
import json
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import download_ui
import logging_config
import pipeline_ui
import config
import theme
import translation
import video_card


APP_TITLE = config.APP_TITLE
SINGLE_INSTANCE_PORT = config.SINGLE_INSTANCE_PORT
THUMB_DIR = config.THUMB_DIR
LOG_DIR = config.LOG_DIR
DESKTOP_STATE_PATH = config.DESKTOP_STATE_PATH
FFMPEG = Path(config.FFMPEG)
BATCH_DOWNLOAD_LIMIT = config.BATCH_DOWNLOAD_LIMIT
APP_ICON_PATH = config.APP_ICON_PATH


def get_app_stylesheet(theme_name: str = "light") -> str:
    """从 theme 模块获取当前主题的 QSS。"""
    return theme.get_stylesheet(theme_name)



def write_error(exc: BaseException) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "desktop_qt_error.log").open("a", encoding="utf-8") as log:
        log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {exc}\n")
        log.write(traceback.format_exc())


def write_trace(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "desktop_qt_startup.log").open("a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.exists() else QIcon()


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CoserLens.Pipeline.Workbench")
    except Exception:
        pass


def acquire_single_instance():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        sock.listen(1)
        return sock
    except OSError:
        return None


def load_desktop_state() -> dict:
    if not DESKTOP_STATE_PATH.exists():
        return {}
    try:
        return json.loads(DESKTOP_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_desktop_state(state: dict) -> None:
    DESKTOP_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class MainWindow(QMainWindow):
    def __init__(self, lock_socket, initial_theme: str = "light"):
        super().__init__()
        self.lock_socket = lock_socket
        self.items = []
        self.selected_id = None
        self.last_log_text = ""
        self.upload_log_offsets = {}
        self.pending_thumbnails = set()
        self.current_theme = initial_theme
        self.video_cards: dict[str, video_card.VideoCard] = {}
        desktop_state = load_desktop_state()
        default_folder = pipeline_ui.REPO_ROOT / "video"
        self.active_folder = Path(desktop_state.get("active_folder") or default_folder)
        self.show_all_library = bool(desktop_state.get("show_all_library", False))
        self.log_queue = queue.Queue()
        self.upload_thread = None
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self.reload_current_thumbnail)

        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        self.setWindowTitle(APP_TITLE)
        icon = app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1440, 860)
        self.setMinimumSize(1120, 720)
        self.build_ui()

        self.queue_timer = QTimer(self)
        self.queue_timer.timeout.connect(self.drain_log_queue)
        self.queue_timer.start(300)

        QTimer.singleShot(200, self.refresh_videos)

    def build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        self._build_header(root)
        self._build_scope_label(root)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        self._build_left_panel(splitter)
        self._build_middle_panel(splitter)
        self._build_right_panel(splitter)

        splitter.setSizes([360, 520, 560])
        self.setCentralWidget(central)

    def _build_header(self, root):
        """顶部工具栏：Logo、标题、操作按钮、搜索框、主题切换。"""
        header_frame = QFrame()
        header_frame.setObjectName("HeaderBar")
        header_frame.setMinimumHeight(68)
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(18, 10, 18, 10)
        header.setSpacing(12)

        # Logo
        logo = QLabel()
        logo.setObjectName("LogoMark")
        logo.setFixedSize(40, 40)
        if APP_ICON_PATH.exists():
            logo_pixmap = QPixmap(str(APP_ICON_PATH)).scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            logo.setPixmap(logo_pixmap)
        header.addWidget(logo)

        # 标题 + 副标题
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(0)
        title = QLabel("CoserLens Pipeline")
        title.setObjectName("Title")
        title_block.addWidget(title)
        subtitle = QLabel("Creator upload workbench")
        subtitle.setObjectName("Subtitle")
        title_block.addWidget(subtitle)
        header.addLayout(title_block)

        # 操作按钮
        for text, handler in [
            ("Refresh", self.refresh_videos),
            ("Add files", self.add_files),
            ("Choose Folder", self.choose_folder),
            ("Show All Library", self.show_all),
            ("Open Chrome", self.open_chrome),
        ]:
            button = QPushButton(text)
            button.setObjectName("ToolbarButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(handler)
            header.addWidget(button)

        # 搜索框
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, filename, or path")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.render_list)
        header.addWidget(self.search, 1)

        # 主题切换按钮
        self.theme_button = QPushButton(self._theme_button_text())
        self.theme_button.setObjectName("ThemeToggle")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.setToolTip("Switch light / dark theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme_button)

        root.addWidget(header_frame)

    def _build_scope_label(self, root):
        """当前作用域标签（显示文件夹路径）。"""
        self.scope_label = self.muted_label("")
        self.scope_label.setObjectName("Scope")
        self.scope_label.setWordWrap(True)
        root.addWidget(self.scope_label)

    def _build_left_panel(self, splitter):
        """左面板：视频列表 + 下载区域。"""
        left = self.panel()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)

        left_splitter = QSplitter(Qt.Vertical)
        left_layout.addWidget(left_splitter, 1)

        # ── 视频列表 ──
        batch_box = QWidget()
        batch_layout = QVBoxLayout(batch_box)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(10)
        batch_layout.addWidget(self.section_label("Current Batch"))
        self.count_label = self.muted_label("0 videos")
        self.count_label.setObjectName("CountLabel")
        batch_layout.addWidget(self.count_label)
        self.list_widget = QListWidget()
        self.list_widget.setSpacing(2)
        self.list_widget.currentItemChanged.connect(self.on_list_changed)
        batch_layout.addWidget(self.list_widget, 1)
        left_splitter.addWidget(batch_box)

        # ── 下载区域 ──
        download_box = QWidget()
        download_layout = QVBoxLayout(download_box)
        download_layout.setContentsMargins(0, 0, 0, 0)
        download_layout.setSpacing(10)
        download_layout.addWidget(self.section_label("Download"))
        self.download_mode = QComboBox()
        self.download_mode.addItems(["Auto detect", "Single work", "Batch source"])
        self.download_mode.currentIndexChanged.connect(self.update_download_mode)
        download_layout.addWidget(self.download_mode)
        self.download_text = QTextEdit()
        self.download_text.setObjectName("InputText")
        self.download_text.setAcceptRichText(False)
        self.download_text.setPlaceholderText("Paste a Douyin work, account, or share link")
        self.download_text.setMinimumHeight(96)
        self.download_text.textChanged.connect(self.update_download_button)
        download_layout.addWidget(self.download_text, 1)
        self.download_button = QPushButton("⬇  Download")
        self.download_button.setCursor(Qt.PointingHandCursor)
        self.download_button.clicked.connect(self.start_downloads)
        download_layout.addWidget(self.download_button)
        left_splitter.addWidget(download_box)

        left_splitter.setCollapsible(0, False)
        left_splitter.setCollapsible(1, False)
        left_splitter.setHandleWidth(10)
        left_splitter.setSizes([620, 180])
        splitter.addWidget(left)

    def _build_middle_panel(self, splitter):
        """中间面板：视频预览 + 文件信息 + 打开操作。"""
        middle = self.panel()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(16, 16, 16, 16)
        middle_layout.setSpacing(10)
        middle_layout.addWidget(self.section_label("Preview"))
        self.path_label = self.muted_label("-")
        self.path_label.setWordWrap(True)
        self.path_label.setObjectName("Muted")
        middle_layout.addWidget(self.path_label)
        self.preview = QLabel("Select a video on the left to preview it.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(520)
        self.preview.setObjectName("VideoPreview")
        middle_layout.addWidget(self.preview, 1)

        preview_buttons = QHBoxLayout()
        preview_buttons.setSpacing(8)
        play_button = QPushButton("▶  Play Video")
        play_button.setCursor(Qt.PointingHandCursor)
        play_button.clicked.connect(self.open_video)
        preview_buttons.addWidget(play_button)
        folder_button = QPushButton("Open Folder")
        folder_button.setObjectName("Secondary")
        folder_button.setCursor(Qt.PointingHandCursor)
        folder_button.clicked.connect(self.open_folder)
        preview_buttons.addWidget(folder_button)
        self.status_label = self.muted_label("No selection")
        self.status_label.setObjectName("StatusLabel")
        preview_buttons.addWidget(self.status_label, 1)
        middle_layout.addLayout(preview_buttons)
        splitter.addWidget(middle)

    def _build_right_panel(self, splitter):
        """右面板：元数据编辑 + 上传控制 + 运行日志。"""
        right = self.panel()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        right_splitter = QSplitter(Qt.Vertical)
        right_layout.addWidget(right_splitter, 1)

        # ── 元数据编辑区 ──
        meta_box = QWidget()
        meta_layout = QVBoxLayout(meta_box)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(6)
        meta_layout.addWidget(self.section_label("Metadata and Upload"))

        title_label = QLabel("English title")
        title_label.setObjectName("FieldLabel")
        meta_layout.addWidget(title_label)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Enter a catchy YouTube title...")
        meta_layout.addWidget(self.title_edit)

        desc_label = QLabel("Description")
        desc_label.setObjectName("FieldLabel")
        meta_layout.addWidget(desc_label)
        self.description_edit = QTextEdit()
        self.description_edit.setObjectName("Description")
        self.description_edit.setAcceptRichText(False)
        self.description_edit.setMinimumHeight(120)
        self.description_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        meta_layout.addWidget(self.description_edit, 3)

        self.local_note = self.muted_label("中文参考：-")
        self.local_note.setObjectName("LocalNote")
        self.local_note.setWordWrap(True)
        self.local_note.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.local_note.setMinimumHeight(82)
        self.local_note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        meta_layout.addWidget(self.local_note, 2)
        self.title_edit.textChanged.connect(self.refresh_local_note)
        self.description_edit.textChanged.connect(self.refresh_local_note)

        # ── 上传控制按钮 ──
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.privacy = QComboBox()
        self.privacy.addItems(["public", "unlisted", "private"])
        self.privacy.setMinimumWidth(90)
        controls.addWidget(self.privacy)
        save_button = QPushButton("Save Draft")
        save_button.setCursor(Qt.PointingHandCursor)
        save_button.clicked.connect(lambda: self.save_metadata())
        controls.addWidget(save_button)
        regen_button = QPushButton("Regenerate")
        regen_button.setObjectName("Secondary")
        regen_button.setCursor(Qt.PointingHandCursor)
        regen_button.clicked.connect(self.regenerate_metadata)
        controls.addWidget(regen_button)
        analyze_button = QPushButton("Deep Analyze")
        analyze_button.setObjectName("Secondary")
        analyze_button.setCursor(Qt.PointingHandCursor)
        analyze_button.clicked.connect(self.deep_analyze_metadata)
        controls.addWidget(analyze_button)
        self.upload_button = QPushButton("Upload YouTube")
        self.upload_button.setObjectName("Danger")
        self.upload_button.setCursor(Qt.PointingHandCursor)
        self.upload_button.clicked.connect(self.upload_selected)
        controls.addWidget(self.upload_button)
        meta_layout.addLayout(controls)

        hint = self.muted_label(
            "No Unknown fields are written. Check title and description before publishing."
        )
        hint.setWordWrap(True)
        meta_layout.addWidget(hint)
        right_splitter.addWidget(meta_box)

        # ── 运行日志 ──
        log_box = QWidget()
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(10)
        log_layout.addWidget(QLabel("Run log"))
        self.log = QTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        log_layout.addWidget(self.log, 1)
        right_splitter.addWidget(log_box)

        right_splitter.setCollapsible(0, False)
        right_splitter.setCollapsible(1, False)
        right_splitter.setHandleWidth(10)
        right_splitter.setStretchFactor(0, 4)
        right_splitter.setStretchFactor(1, 5)
        right_splitter.setSizes([360, 460])
        splitter.addWidget(right)

    def panel(self):
        frame = QFrame()
        frame.setObjectName("Panel")
        return frame

    def section_label(self, text):
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def muted_label(self, text):
        label = QLabel(text)
        label.setObjectName("Muted")
        return label

    def apply_light_text_palette(self, widget):
        """已废弃：theme.py 通过 QSS 自动处理文本颜色。保留以防外部调用。"""
        pass

    def _theme_button_text(self) -> str:
        """返回主题切换按钮的当前文字。"""
        return "☀" if self.current_theme == "dark" else "🌙"

    def toggle_theme(self):
        """切换浅色/暗色主题。"""
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        QApplication.instance().setStyleSheet(get_app_stylesheet(self.current_theme))
        self.theme_button.setText(self._theme_button_text())
        theme.save_theme_preference(self.current_theme)
        self.append_log(f"Theme switched to {self.current_theme}.")

    def refresh_videos(self):
        try:
            self.items = pipeline_ui.scan_videos() if self.show_all_library else self.scan_active_folder()
            if self.selected_id and not any(item["id"] == self.selected_id for item in self.items):
                self.selected_id = None
            self.render_list()
            if not self.selected_id and self.items:
                self.select_item(self.items[0]["id"])
        except Exception as exc:
            write_error(exc)
            QMessageBox.critical(self, APP_TITLE, f"Refresh failed: {exc}")

    def render_list(self):
        """渲染视频列表为卡片形式。"""
        query = self.search.text().strip().lower()
        current_id = self.selected_id
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.video_cards.clear()
        visible = []
        for item in self.items:
            haystack = f"{item['title']} {item['filename']} {item['relative_path']}".lower()
            if not query or query in haystack:
                visible.append(item)
        for item in visible:
            card = video_card.VideoCard(item)
            card.clicked.connect(self._on_card_clicked)
            list_item = QListWidgetItem()
            list_item.setData(Qt.UserRole, item["id"])
            # 设置项大小（卡片高度 + 一些边距）
            list_item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, card)
            self.video_cards[item["id"]] = card
            if item["id"] == current_id:
                self.list_widget.setCurrentItem(list_item)
                card.set_selected(True)
        self.list_widget.blockSignals(False)
        self.count_label.setText(f"{len(visible)} / {len(self.items)} videos")
        # 若有选中项，确保对应卡片高亮
        if current_id and current_id in self.video_cards:
            self.video_cards[current_id].set_selected(True)
        self.update_scope_label()

    def _on_card_clicked(self, item_id: str):
        """视频卡片被点击（不依赖 QListWidget 的选中信号）。"""
        if item_id != self.selected_id:
            self.select_item(item_id)

    def scan_active_folder(self):
        folder = self.active_folder.resolve()
        if not folder.exists():
            return []
        with pipeline_ui.STATE_LOCK:
            state = pipeline_ui.load_state()
        metadata_state = state.get("metadata", {})
        uploads = state.get("uploads", {})
        found = sorted(
            {path for path in folder.rglob("*.mp4") if path.is_file()},
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        items = []
        for path in found:
            item_id = pipeline_ui.video_id_for_path(path)
            stat = path.stat()
            meta = pipeline_ui.draft_metadata(path, metadata_state.get(item_id))
            try:
                relative = str(path.relative_to(folder))
            except ValueError:
                relative = str(path)
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
                    "upload": uploads.get(item_id, {}),
                }
            )
        return items

    def update_scope_label(self):
        if self.show_all_library:
            text = "Mode: All Library. This shows default folders plus saved custom paths."
        else:
            text = f"Mode: Current Folder only. Folder: {self.active_folder}"
        self.scope_label.setText(text)

    def save_scope(self):
        save_desktop_state(
            {
                "active_folder": str(self.active_folder),
                "show_all_library": self.show_all_library,
            }
        )

    def on_list_changed(self, current, _previous):
        if current:
            self.select_item(current.data(Qt.UserRole))

    def select_item(self, item_id):
        # 取消上一张卡片的高亮
        if self.selected_id and self.selected_id in self.video_cards:
            self.video_cards[self.selected_id].set_selected(False)
        self.selected_id = item_id
        # 高亮新选中的卡片
        if item_id in self.video_cards:
            self.video_cards[item_id].set_selected(True)
        item = self.current_item()
        if not item:
            return
        self.path_label.setText(item["path"])
        self.status_label.setText(f"{item['modified_text']}  ·  {self.format_bytes(item['size'])}")
        self.title_edit.setText(item["title"])
        self.description_edit.setPlainText(item["description"])
        self.update_local_note(item)
        self.load_thumbnail(item)

    def update_local_note(self, item):
        title = self.title_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        self.local_note.setText(translation.translate_upload_copy(title, description))

    def refresh_local_note(self):
        item = self.current_item()
        if item:
            self.update_local_note(item)

    def current_item(self):
        if not self.selected_id:
            return None
        return next((item for item in self.items if item["id"] == self.selected_id), None)

    def reload_current_thumbnail(self):
        item = self.current_item()
        if item:
            self.load_thumbnail(item)

    def load_thumbnail(self, item):
        try:
            thumb = self.thumbnail_path(item)
            self.preview.setPixmap(QPixmap())
            if not thumb.exists():
                self.preview.setText("Generating preview...")
                self.generate_thumbnail_async(item)
                return
            pixmap = QPixmap(str(thumb))
            if pixmap.isNull():
                self.preview.setText("Thumbnail failed to load.")
                return
            scaled = pixmap.scaled(
                self.preview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.preview.setText("")
            self.preview.setPixmap(scaled)
        except Exception as exc:
            write_error(exc)
            self.preview.setText("Thumbnail failed. Use Play Video for preview.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_item():
            self.thumbnail_timer.start(150)

    def thumbnail_path(self, item):
        return THUMB_DIR / f"{item['id']}.jpg"

    def generate_thumbnail_async(self, item):
        thumb = self.thumbnail_path(item)
        if thumb.exists() or not FFMPEG.exists() or item["id"] in self.pending_thumbnails:
            return
        item_id = item["id"]
        video_path = item["path"]
        self.pending_thumbnails.add(item_id)

        def runner():
            try:
                self.generate_thumbnail(video_path, thumb)
                self.log_queue.put(("__THUMB_READY__", item_id))
            except Exception as exc:
                write_error(exc)
                self.log_queue.put(("__THUMB_FAILED__", item_id))
            finally:
                self.log_queue.put(("__THUMB_DONE__", item_id))

        threading.Thread(target=runner, daemon=True).start()

    def generate_thumbnail(self, video_path, thumb):
        if not FFMPEG.exists():
            return thumb
        subprocess.run(
            [
                str(FFMPEG),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "00:00:00.5",
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(thumb),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
        return thumb

    def save_metadata(self, refresh=True, log_message=True):
        item = self.current_item()
        if not item:
            return False
        title = self.title_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        if not title or not description:
            QMessageBox.warning(self, APP_TITLE, "Title and description cannot be empty.")
            return False
        with pipeline_ui.STATE_LOCK:
            state = pipeline_ui.load_state()
            state.setdefault("metadata", {})[item["id"]] = {
                "title": title,
                "description": description,
            }
            pipeline_ui.save_state(state)
        item["title"] = title
        item["description"] = description
        if log_message:
            self.append_log("Draft saved.")
        if refresh:
            self.render_list()
        return True

    def regenerate_metadata(self):
        item = self.current_item()
        if not item:
            return
        meta = pipeline_ui.draft_metadata(Path(item["path"]), None)
        self.title_edit.setText(meta["title"])
        self.description_edit.setPlainText(meta["description"])
        self.update_local_note(item)
        self.append_log("Draft regenerated.")

    def deep_analyze_metadata(self):
        item = self.current_item()
        if not item:
            return
        self.append_log("Running deep analysis with cached web evidence...")
        QApplication.processEvents()
        meta = pipeline_ui.draft_metadata(Path(item["path"]), None, allow_online=True)
        self.title_edit.setText(meta["title"])
        self.description_edit.setPlainText(meta["description"])
        self.update_local_note(item)
        analysis = meta.get("analysis") or {}
        if analysis:
            confidence = int(round(float(analysis.get("confidence") or 0) * 100))
            evidence = "; ".join(analysis.get("evidence") or []) or "-"
            self.append_log(
                "Analysis: "
                f"character={analysis.get('character') or '-'}, "
                f"source={analysis.get('source') or '-'}, "
                f"confidence={confidence}%, "
                f"scene={analysis.get('scene') or '-'}"
            )
            self.append_log(f"Evidence: {evidence}")
        self.append_log("Deep analysis draft generated.")

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select video files",
            str(pipeline_ui.REPO_ROOT),
            "MP4 videos (*.mp4);;All files (*.*)",
        )
        for raw in files:
            pipeline_ui.add_custom_path(Path(raw))
        if files:
            self.active_folder = Path(files[0]).parent
            self.show_all_library = False
            self.save_scope()
            self.append_log(f"Added {len(files)} file(s).")
            self.refresh_videos()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose current work folder",
            str(self.active_folder if self.active_folder.exists() else pipeline_ui.REPO_ROOT),
        )
        if folder:
            self.active_folder = Path(folder)
            self.show_all_library = False
            self.save_scope()
            self.selected_id = None
            self.append_log(f"Current folder: {folder}")
            self.refresh_videos()

    def show_all(self):
        self.show_all_library = True
        self.save_scope()
        self.selected_id = None
        self.append_log("Showing all library videos.")
        self.refresh_videos()

    def open_video(self):
        item = self.current_item()
        if item:
            os.startfile(item["path"])

    def open_folder(self):
        item = self.current_item()
        if item:
            subprocess.Popen(["explorer", "/select,", item["path"]])

    def open_chrome(self):
        try:
            self.append_log(pipeline_ui.launch_chrome())
        except Exception as exc:
            write_error(exc)
            QMessageBox.critical(self, APP_TITLE, str(exc))

    def start_downloads(self):
        source = self.extract_single_download_source()
        if not source:
            QMessageBox.information(self, APP_TITLE, "Paste a source link or work ID first.")
            return
        self.download_button.setEnabled(False)
        self.append_log("")
        mode = self.download_mode.currentIndex()
        if mode == 0:
            self.append_log("---- Auto download task ----")
        elif mode == 1:
            self.append_log("---- Single work download ----")
        else:
            self.append_log("---- Batch account download ----")

        def runner():
            try:
                if mode == 0:
                    detected = self.detect_download_mode(source)
                    self.log_queue.put(f"Auto detected: {detected}")
                    if detected == "single work":
                        self.perform_single_download(source)
                    else:
                        self.perform_batch_source_download(source)
                elif mode == 1:
                    self.perform_single_download(source)
                else:
                    self.perform_batch_source_download(source)
            except Exception as exc:
                write_error(exc)
                self.log_queue.put(f"Download error: {exc}")
            finally:
                self.log_queue.put("__DOWNLOAD_DONE__")

        threading.Thread(target=runner, daemon=True).start()

    def extract_single_download_source(self):
        text = self.download_text.toPlainText()
        link = re.search(r"https?://[^\s]+", text)
        if link:
            return link.group(0).rstrip("??,.!???)")
        return text.strip()

    def detect_download_mode(self, source):
        if re.fullmatch(r"\d{10,30}", source.strip()):
            return "single work"
        try:
            settings = download_ui.read_settings()
            cookie = download_ui.cookie_to_str(settings.get("cookie", ""))
            download_ui.resolve_aweme_id(source, cookie)
            return "single work"
        except Exception as exc:
            self.log_queue.put(f"No single work ID found, switching to batch source: {exc}")
            return "batch source"

    def perform_single_download(self, source):
        self.log_queue.put("Starting single work download")
        job_id = f"qt-download-{int(time.time())}"
        download_ui.JOBS[job_id] = {
            "status": "starting",
            "progress": 0,
            "downloaded": 0,
            "total": 0,
            "log": [f"{download_ui.now_text()} Created task"],
        }
        self.log_queue.put(f"Downloading: {source}")
        download_ui.run_download(job_id, source)
        job = download_ui.JOBS.get(job_id, {})
        if job.get("status") == "done":
            output = job.get("output", "")
            self.log_queue.put(f"Done: {output}")
            if output:
                pipeline_ui.add_custom_path(Path(output))
                self.log_queue.put(("__SET_ACTIVE_FOLDER__", str(Path(output).parent)))
        else:
            raise RuntimeError(job.get("error", "single work download failed"))

    def perform_batch_source_download(self, source):
        started_at = time.time()
        source = self.normalize_douyin_batch_source(source)
        self.log_queue.put(f"Batch source: {source}")
        self.log_queue.put("Fetching account works with TikTokDownloader API")
        sec_user_id, aweme_ids = self.fetch_account_aweme_ids(source)
        if not aweme_ids:
            raise RuntimeError("No works were found for this account link.")
        total_found = len(aweme_ids)
        aweme_ids = aweme_ids[:BATCH_DOWNLOAD_LIMIT]
        self.log_queue.put(
            f"Batch works found: {total_found}. Download limit: {len(aweme_ids)}/{BATCH_DOWNLOAD_LIMIT}"
        )
        batch_folder = download_ui.OUTPUT_ROOT / download_ui.sanitize_name(
            f"UID{sec_user_id}_ytb_发布作品_{time.strftime('%Y%m%d_%H%M%S')}"
        )
        batch_folder.mkdir(parents=True, exist_ok=True)
        self.log_queue.put(f"Batch output folder: {batch_folder}")
        outputs = []
        failures = 0
        for index, aweme_id in enumerate(aweme_ids, start=1):
            self.log_queue.put(f"[{index}/{len(aweme_ids)}] Downloading work {aweme_id}")
            job_id = f"qt-batch-{int(time.time())}-{index}"
            download_ui.JOBS[job_id] = {
                "status": "starting",
                "progress": 0,
                "downloaded": 0,
                "total": 0,
                "log": [f"{download_ui.now_text()} Created task"],
            }
            download_ui.run_download(job_id, aweme_id, output_dir=batch_folder, write_meta=False)
            job = download_ui.JOBS.get(job_id, {})
            if job.get("status") == "done" and job.get("output"):
                output = Path(job["output"])
                outputs.append(output)
                pipeline_ui.add_custom_path(output)
                self.log_queue.put(f"[{index}/{len(aweme_ids)}] Done: {output.name}")
            else:
                failures += 1
                self.log_queue.put(f"[{index}/{len(aweme_ids)}] Failed: {job.get('error', 'unknown error')}")
        if outputs:
            self.log_queue.put(("__SET_ACTIVE_FOLDER__", str(batch_folder)))
        elapsed = int(time.time() - started_at)
        self.log_queue.put(
            f"Batch finished. Success: {len(outputs)}, Failed: {failures}, Elapsed: {elapsed}s"
        )

    def fetch_account_aweme_ids(self, source):
        import asyncio
        from src.interface.account import Account
        from src.link.extractor import Extractor
        from src.testers import Params

        async def runner():
            settings = download_ui.read_settings()
            cookie = download_ui.cookie_to_str(settings.get("cookie", ""))
            async with Params() as params:
                params.logger = download_ui.QuietLogger()
                params.cookie_str = cookie
                params.headers["Cookie"] = cookie
                params.proxy = settings.get("proxy") or None
                params.max_pages = settings.get("max_pages", 0)
                extractor = Extractor(params)
                ids = await asyncio.wait_for(extractor.run(source, "user"), timeout=30)
                if not ids:
                    return "", []
                self.log_queue.put(f"Account sec_user_id: {ids[0]}")
                account = Account(
                    params,
                    cookie=cookie,
                    proxy=params.proxy,
                    sec_user_id=ids[0],
                    tab="post",
                    pages=params.max_pages,
                    count=18,
                )

                async def stop_at_limit():
                    if len(account.response or []) >= BATCH_DOWNLOAD_LIMIT:
                        account.finished = True

                await asyncio.wait_for(account.run(callback=stop_at_limit), timeout=120)
                works = account.response or []
                aweme_ids = list(
                    dict.fromkeys(str(item.get("aweme_id")) for item in works if item.get("aweme_id"))
                )[:BATCH_DOWNLOAD_LIMIT]
                return ids[0], aweme_ids

        return asyncio.run(runner())

    def normalize_douyin_batch_source(self, source):
        text = source.strip()
        if "v.douyin.com" not in text and "iesdouyin.com/share/user" not in text:
            return text
        try:
            import httpx
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            with httpx.Client(headers=headers, follow_redirects=True, timeout=20, verify=config.VERIFY_SSL) as client:
                final_url = str(client.get(text).url)
            sec_uid = re.search(r"(?:sec_uid=|/share/user/)([^&/?]+)", final_url)
            if sec_uid:
                return f"https://www.douyin.com/user/{sec_uid.group(1)}"
        except Exception as exc:
            self.log_queue.put(f"Could not normalize Douyin source, using original link: {exc}")
        return text

    def update_download_button(self):
        if self.download_mode.currentIndex() == 0:
            self.download_button.setText("Auto Download")
        elif self.download_mode.currentIndex() == 1:
            self.download_button.setText("Download Single Work")
        else:
            self.download_button.setText("Start Batch Download")

    def update_download_mode(self):
        if self.download_mode.currentIndex() == 0:
            self.download_text.setPlaceholderText("Paste a Douyin work, account, or share link")
        elif self.download_mode.currentIndex() == 1:
            self.download_text.setPlaceholderText("Paste one Douyin work link or work ID")
        else:
            self.download_text.setPlaceholderText("Paste one Douyin account homepage/share link for batch download")
        self.update_download_button()

    def upload_selected(self):
        item = self.current_item()
        if not item:
            return
        if not self.save_metadata(refresh=False, log_message=False):
            return
        item = self.current_item()
        title = self.title_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        privacy = self.privacy.currentText()
        if not title or not description:
            return
        if self.upload_thread and self.upload_thread.is_alive():
            QMessageBox.information(self, APP_TITLE, "An upload task is already running.")
            return
        self.append_log("---- Upload task ----")
        self.upload_button.setEnabled(False)
        job_id = f"qt-upload-{int(time.time())}"
        pipeline_ui.JOBS[job_id] = {
            "status": "running",
            "log": [f"{pipeline_ui.now_text()} Created upload job"],
        }
        self.upload_log_offsets[job_id] = 0

        def runner():
            try:
                pipeline_ui.run_upload(job_id, item, title, description, privacy)
            except Exception as exc:
                write_error(exc)
                pipeline_ui.JOBS[job_id] = {
                    "status": "error",
                    "error": str(exc),
                    "log": [str(exc)],
                }

        self.upload_thread = threading.Thread(target=runner, daemon=True)
        self.upload_thread.start()
        self.poll_upload(job_id)

    def poll_upload(self, job_id):
        job = pipeline_ui.JOBS.get(job_id, {})
        lines = job.get("log", [])
        offset = self.upload_log_offsets.get(job_id, 0)
        for line in lines[offset:]:
            self.append_log(line)
        self.upload_log_offsets[job_id] = len(lines)
        if job.get("status") in {"done", "error"}:
            self.upload_button.setEnabled(True)
            if job.get("status") == "done":
                self.mark_current_uploaded(job)
                self.append_log(f"Upload complete: {job.get('video_url', '')}")
            else:
                QMessageBox.critical(self, APP_TITLE, job.get("error", "Upload failed"))
            return
        QTimer.singleShot(1000, lambda: self.poll_upload(job_id))

    def mark_current_uploaded(self, job):
        item = self.current_item()
        if not item:
            return
        item["upload"] = {
            "uploaded_at": time.time(),
            "title": self.title_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "privacy": self.privacy.currentText(),
            "url": job.get("video_url", ""),
        }
        self.status_label.setText(f"Uploaded | {job.get('video_url', '')}")
        self.render_list()

    def drain_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message == "__DOWNLOAD_DONE__":
                    self.download_button.setEnabled(True)
                    self.refresh_videos()
                    self.append_log("Batch download finished.")
                elif isinstance(message, tuple) and message[0] == "__SET_ACTIVE_FOLDER__":
                    self.active_folder = Path(message[1])
                    self.show_all_library = False
                    self.save_scope()
                elif isinstance(message, tuple) and message[0] == "__THUMB_READY__":
                    if self.selected_id == message[1]:
                        self.reload_current_thumbnail()
                elif isinstance(message, tuple) and message[0] == "__THUMB_FAILED__":
                    if self.selected_id == message[1]:
                        self.preview.setText("Thumbnail failed. Use Play Video for preview.")
                elif isinstance(message, tuple) and message[0] == "__THUMB_DONE__":
                    self.pending_thumbnails.discard(message[1])
                else:
                    self.append_log(str(message))
        except queue.Empty:
            pass

    def append_log(self, message):
        """追加一行日志，自动加时间戳前缀并按级别着色。

        规则：
        - 含 "ERROR"/"Failed"/"critical" → 红色
        - 含 "WARN"/"warning" → 琥珀
        - 含 "complete"/"done"/"finished"/"success" → 绿色
        - 含 "Theme switched" → 紫色
        - 其余 → 浅蓝
        """
        text = message.rstrip()
        # 时间戳前缀
        timestamp = time.strftime("%H:%M:%S")
        lower = text.lower()
        if any(tag in lower for tag in ("error", "failed", "critical", "exception")):
            color = "#f87171"  # red-400
        elif any(tag in lower for tag in ("warn", "warning")):
            color = "#fbbf24"  # amber-400
        elif any(tag in lower for tag in ("complete", "done", "finished", "success", "finished")):
            color = "#4ade80"  # green-400
        elif "theme" in lower:
            color = "#a78bfa"  # violet-400
        else:
            color = "#93c5fd"  # blue-300
        # 用 HTML 上色
        html = (
            f'<span style="color:#64748b">[{timestamp}]</span> '
            f'<span style="color:{color}">{text}</span>'
        )
        self.log.append(html)

    @staticmethod
    def format_bytes(size):
        units = ["B", "KB", "MB", "GB"]
        value = float(size or 0)
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        return f"{value:.1f} {units[index]}" if index else f"{int(value)} B"

    def closeEvent(self, event):
        try:
            self.lock_socket.close()
        except Exception:
            pass
        event.accept()


def main():
    logging_config.setup_logging()
    write_trace("main entered")
    set_windows_app_id()
    lock = acquire_single_instance()
    if lock is None:
        write_trace("another instance detected")
        app = QApplication(sys.argv)
        icon = app_icon()
        if not icon.isNull():
            app.setWindowIcon(icon)
        QMessageBox.information(
            None,
            APP_TITLE,
            "CoserLens Pipeline is already running. Use the existing window.",
        )
        return 0
    write_trace("creating QApplication")
    app = QApplication(sys.argv)
    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    initial_theme = theme.load_theme_preference()
    app.setStyleSheet(get_app_stylesheet(initial_theme))
    write_trace("creating MainWindow")
    window = MainWindow(lock, initial_theme=initial_theme)
    window.move(40, 40)
    window.show()
    window.showNormal()
    window.raise_()
    window.activateWindow()
    write_trace("window shown")
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        write_error(exc)
        raise
