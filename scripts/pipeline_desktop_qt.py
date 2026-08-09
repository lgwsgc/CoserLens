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
import pipeline_ui
import config
import translation


APP_TITLE = config.APP_TITLE
SINGLE_INSTANCE_PORT = config.SINGLE_INSTANCE_PORT
THUMB_DIR = config.THUMB_DIR
LOG_DIR = config.LOG_DIR
DESKTOP_STATE_PATH = config.DESKTOP_STATE_PATH
FFMPEG = Path(config.FFMPEG)
BATCH_DOWNLOAD_LIMIT = config.BATCH_DOWNLOAD_LIMIT
APP_ICON_PATH = config.APP_ICON_PATH


STYLE = """
QMainWindow, QWidget {
    background: #f3f6f8;
    color: #182230;
    font-family: "Segoe UI", "Microsoft YaHei";
    font-size: 13px;
}
QFrame#HeaderBar {
    background: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 8px;
}
QFrame#Panel {
    background: #ffffff;
    border: 1px solid #d7dee8;
    border-radius: 8px;
}
QLabel#LogoMark {
    background: transparent;
}
QLabel#Title {
    color: #101828;
    font-size: 23px;
    font-weight: 700;
}
QLabel#Subtitle {
    color: #667085;
    font-size: 12px;
}
QLabel#SectionTitle {
    color: #111827;
    font-size: 15px;
    font-weight: 700;
}
QLabel#Muted {
    color: #697586;
}
QLabel#Scope {
    color: #475467;
    background: #ffffff;
    border: 1px solid #dfe5ed;
    border-radius: 6px;
    padding: 8px 11px;
}
QLabel#LocalNote {
    color: #475467;
    background: #f8fafc;
    border: 1px solid #dfe5ed;
    border-radius: 6px;
    padding: 9px 10px;
}
QPushButton {
    background: #0f766e;
    color: #ffffff;
    border: 0;
    border-radius: 6px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #115e59;
}
QPushButton:disabled {
    background: #98a2b3;
}
QPushButton#Secondary {
    background: #344054;
}
QPushButton#Secondary:hover {
    background: #293548;
}
QPushButton#Danger {
    background: #c9342c;
}
QPushButton#Danger:hover {
    background: #a52a24;
}
QPushButton#ToolbarButton {
    background: #ffffff;
    color: #344054;
    border: 1px solid #cfd8e3;
}
QPushButton#ToolbarButton:hover {
    background: #eef8f6;
    border-color: #8bb9b4;
    color: #0f5f59;
}
QLineEdit, QTextEdit, QComboBox {
    background: #ffffff;
    color: #182230;
    border: 1px solid #cfd8e3;
    border-radius: 6px;
    padding: 8px;
    selection-background-color: #dbeafe;
    selection-color: #182230;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #0f766e;
    background: #ffffff;
}
QTextEdit#InputText {
    background: #ffffff;
    color: #172033;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}
QTextEdit#Description {
    background: #ffffff;
    color: #172033;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}
QTextEdit#Log {
    background: #101828;
    color: #d6e4f0;
    border: 1px solid #202f46;
    font-family: Consolas;
    selection-background-color: #334155;
    selection-color: #ffffff;
}
QListWidget {
    background: #fbfcfe;
    border: 1px solid #d7dee8;
    border-radius: 8px;
    outline: 0;
}
QListWidget::item {
    padding: 12px;
    border-bottom: 1px solid #e8edf4;
    color: #182230;
}
QListWidget::item:hover {
    background: #eef8f6;
}
QListWidget::item:selected {
    background: #d9f0ec;
    color: #101828;
    border-left: 3px solid #0f766e;
}
QSplitter::handle {
    background: #d4dce7;
    border-radius: 3px;
}
QSplitter::handle:hover {
    background: #8bb9b4;
}
QSplitter::handle:horizontal {
    width: 8px;
    margin: 2px 0;
}
QSplitter::handle:vertical {
    height: 8px;
    margin: 0 2px;
}
QScrollBar:vertical {
    background: #f1f5f9;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar:horizontal {
    background: #f1f5f9;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #cbd5e1;
    border-radius: 5px;
    min-width: 32px;
}
"""


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
    def __init__(self, lock_socket):
        super().__init__()
        self.lock_socket = lock_socket
        self.items = []
        self.selected_id = None
        self.last_log_text = ""
        self.upload_log_offsets = {}
        self.pending_thumbnails = set()
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

        header_frame = QFrame()
        header_frame.setObjectName("HeaderBar")
        header_frame.setMinimumHeight(66)
        header = QHBoxLayout(header_frame)
        header.setContentsMargins(16, 10, 16, 10)
        header.setSpacing(11)
        logo = QLabel()
        logo.setObjectName("LogoMark")
        logo.setFixedSize(42, 42)
        if APP_ICON_PATH.exists():
            logo_pixmap = QPixmap(str(APP_ICON_PATH)).scaled(
                42,
                42,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            logo.setPixmap(logo_pixmap)
        header.addWidget(logo)
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(1)
        title = QLabel("CoserLens Pipeline")
        title.setObjectName("Title")
        title_block.addWidget(title)
        subtitle = QLabel("Creator upload workbench")
        subtitle.setObjectName("Subtitle")
        title_block.addWidget(subtitle)
        header.addLayout(title_block)

        for text, handler in [
            ("Refresh", self.refresh_videos),
            ("Add files", self.add_files),
            ("Choose Folder", self.choose_folder),
            ("Show All Library", self.show_all),
            ("Open Chrome", self.open_chrome),
        ]:
            button = QPushButton(text)
            button.setObjectName("ToolbarButton")
            button.clicked.connect(handler)
            header.addWidget(button)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, filename, or path")
        self.search.textChanged.connect(self.render_list)
        header.addWidget(self.search, 1)

        note = QLabel("Filename is used only as a clue, never as the final YouTube title.")
        note.setObjectName("Muted")
        header.addWidget(note)
        root.addWidget(header_frame)

        self.scope_label = self.muted_label("")
        self.scope_label.setObjectName("Scope")
        self.scope_label.setWordWrap(True)
        root.addWidget(self.scope_label)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = self.panel()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(10)

        left_splitter = QSplitter(Qt.Vertical)
        left_layout.addWidget(left_splitter, 1)

        batch_box = QWidget()
        batch_layout = QVBoxLayout(batch_box)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(10)
        batch_layout.addWidget(self.section_label("Current Batch"))
        self.count_label = self.muted_label("0 videos")
        batch_layout.addWidget(self.count_label)
        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self.on_list_changed)
        batch_layout.addWidget(self.list_widget, 1)
        left_splitter.addWidget(batch_box)

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
        self.apply_light_text_palette(self.download_text)
        self.download_text.setStyleSheet(
            "QTextEdit { background: #ffffff; color: #182230; border: 1px solid #cfd8e3; "
            "border-radius: 6px; padding: 7px; selection-background-color: #dbeafe; "
            "selection-color: #182230; }"
        )
        self.download_text.setPlaceholderText("Paste a Douyin work, account, or share link")
        self.download_text.setMinimumHeight(96)
        self.download_text.textChanged.connect(self.update_download_button)
        download_layout.addWidget(self.download_text, 1)
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.start_downloads)
        download_layout.addWidget(self.download_button)
        left_splitter.addWidget(download_box)
        left_splitter.setCollapsible(0, False)
        left_splitter.setCollapsible(1, False)
        left_splitter.setHandleWidth(10)
        left_splitter.setSizes([620, 180])
        splitter.addWidget(left)

        middle = self.panel()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(14, 14, 14, 14)
        middle_layout.setSpacing(10)
        middle_layout.addWidget(self.section_label("Preview"))
        self.path_label = self.muted_label("-")
        self.path_label.setWordWrap(True)
        middle_layout.addWidget(self.path_label)
        self.preview = QLabel("Select a video on the left to preview it.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(520)
        self.preview.setStyleSheet(
            "background:#101828;color:#d6e4f0;border:1px solid #202f46;border-radius:8px;"
        )
        middle_layout.addWidget(self.preview, 1)
        preview_buttons = QHBoxLayout()
        play_button = QPushButton("Play Video")
        play_button.clicked.connect(self.open_video)
        preview_buttons.addWidget(play_button)
        folder_button = QPushButton("Open Folder")
        folder_button.setObjectName("Secondary")
        folder_button.clicked.connect(self.open_folder)
        preview_buttons.addWidget(folder_button)
        self.status_label = self.muted_label("No selection")
        preview_buttons.addWidget(self.status_label, 1)
        middle_layout.addLayout(preview_buttons)
        splitter.addWidget(middle)

        right = self.panel()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(10)

        right_splitter = QSplitter(Qt.Vertical)
        right_layout.addWidget(right_splitter, 1)

        meta_box = QWidget()
        meta_layout = QVBoxLayout(meta_box)
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(8)
        meta_layout.addWidget(self.section_label("Metadata and Upload"))
        meta_layout.addWidget(QLabel("English title"))
        self.title_edit = QLineEdit()
        meta_layout.addWidget(self.title_edit)
        meta_layout.addWidget(QLabel("Description"))
        self.description_edit = QTextEdit()
        self.description_edit.setObjectName("Description")
        self.description_edit.setAcceptRichText(False)
        self.apply_light_text_palette(self.description_edit)
        self.description_edit.setMinimumHeight(120)
        self.description_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        meta_layout.addWidget(self.description_edit, 3)
        self.local_note = self.muted_label("\u4e2d\u6587\u53c2\u8003\uff1a-")
        self.local_note.setObjectName("LocalNote")
        self.local_note.setWordWrap(True)
        self.local_note.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.local_note.setMinimumHeight(82)
        self.local_note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        meta_layout.addWidget(self.local_note, 2)
        self.title_edit.textChanged.connect(self.refresh_local_note)
        self.description_edit.textChanged.connect(self.refresh_local_note)

        controls = QHBoxLayout()
        self.privacy = QComboBox()
        self.privacy.addItems(["public", "unlisted", "private"])
        controls.addWidget(self.privacy)
        save_button = QPushButton("Save Draft")
        save_button.clicked.connect(lambda: self.save_metadata())
        controls.addWidget(save_button)
        regen_button = QPushButton("Regenerate")
        regen_button.setObjectName("Secondary")
        regen_button.clicked.connect(self.regenerate_metadata)
        controls.addWidget(regen_button)
        analyze_button = QPushButton("Deep Analyze")
        analyze_button.setObjectName("Secondary")
        analyze_button.clicked.connect(self.deep_analyze_metadata)
        controls.addWidget(analyze_button)
        self.upload_button = QPushButton("Upload YouTube")
        self.upload_button.setObjectName("Danger")
        self.upload_button.clicked.connect(self.upload_selected)
        controls.addWidget(self.upload_button)
        meta_layout.addLayout(controls)

        hint = self.muted_label(
            "No Unknown fields are written. Check title and description before publishing."
        )
        hint.setWordWrap(True)
        meta_layout.addWidget(hint)
        right_splitter.addWidget(meta_box)

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

        splitter.setSizes([360, 520, 560])
        self.setCentralWidget(central)

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
        palette = widget.palette()
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.Text, QColor("#182230"))
        palette.setColor(QPalette.Highlight, QColor("#dbeafe"))
        palette.setColor(QPalette.HighlightedText, QColor("#182230"))
        widget.setPalette(palette)

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
        query = self.search.text().strip().lower()
        current_id = self.selected_id
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        visible = []
        for item in self.items:
            haystack = f"{item['title']} {item['filename']} {item['relative_path']}".lower()
            if not query or query in haystack:
                visible.append(item)
        for item in visible:
            marker = " [uploaded]" if item.get("upload", {}).get("url") else ""
            text = (
                f"{item['title']}{marker}\n"
                f"{item['modified_text']} | {self.format_bytes(item['size'])}\n"
                f"{item['relative_path']}"
            )
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.UserRole, item["id"])
            self.list_widget.addItem(list_item)
            if item["id"] == current_id:
                self.list_widget.setCurrentItem(list_item)
        self.list_widget.blockSignals(False)
        self.count_label.setText(f"{len(visible)} / {len(self.items)} videos")
        self.update_scope_label()

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
        self.selected_id = item_id
        item = self.current_item()
        if not item:
            return
        self.path_label.setText(item["path"])
        self.status_label.setText(f"{item['modified_text']} | {self.format_bytes(item['size'])}")
        self.title_edit.setText(item["title"])
        self.description_edit.setPlainText(item["description"])
        self.update_local_note(item)
        self.load_thumbnail(item)

    def update_local_note(self, item):
        title = self.title_edit.text().strip()
        description = self.description_edit.toPlainText().strip()
        self.local_note.setText(self.translate_upload_copy(title, description))

    def translate_upload_copy(self, title, description):
        lines = []
        if title:
            lines.append(f"\u4e2d\u6587\u6807\u9898\uff1a{self.translate_english_line(title)}")
        if description:
            translated = [self.translate_english_line(line) for line in description.splitlines()]
            lines.extend(["", "\u4e2d\u6587\u8bf4\u660e\uff1a", *translated])
        return "\n".join(lines) if lines else "\u4e2d\u6587\u53c2\u8003\uff1a-"

    def translate_english_line(self, line):
        text = line.strip()
        if not text:
            return ""
        exact = {
            "Real-life cosplay short filmed in a cinematic style.": "\u771f\u5b9e Cosplay \u77ed\u89c6\u9891\uff0c\u7535\u5f71\u611f\u62cd\u6444\u3002",
            "Real-life swimsuit cosplay short filmed in a cinematic style.": "\u771f\u5b9e\u6cf3\u88c5 Cosplay \u77ed\u89c6\u9891\uff0c\u7535\u5f71\u611f\u62cd\u6444\u3002",
            "Real-life swimsuit cosplay short filmed at a water park.": "\u771f\u5b9e\u6cf3\u88c5 Cosplay \u77ed\u89c6\u9891\uff0c\u5728\u6c34\u4e0a\u4e50\u56ed\u62cd\u6444\u3002",
            "Subscribe for more real cosplay moments.": "\u8ba2\u9605\u83b7\u53d6\u66f4\u591a\u771f\u5b9e Cosplay \u77ac\u95f4\u3002",
            "Style: Swimsuit cosplay": "\u98ce\u683c\uff1a\u6cf3\u88c5 Cosplay",
            "Style: Swimsuit cosplay / summer water park": "\u98ce\u683c\uff1a\u6cf3\u88c5 Cosplay / \u590f\u65e5\u6c34\u4e0a\u4e50\u56ed",
            "Location: Water park": "\u5730\u70b9\uff1a\u6c34\u4e0a\u4e50\u56ed",
            "Location: Changsha Xiangjiang Water Park": "\u5730\u70b9\uff1a\u957f\u6c99\u6e58\u6c5f\u6c34\u4e0a\u4e50\u56ed",
            "Real Cosplay Moment | Cosplay Short": "\u771f\u5b9e Cosplay \u77ac\u95f4 | Cosplay \u77ed\u89c6\u9891",
            "Swimsuit Cosplay at Water Park | Cosplay Short": "\u6c34\u4e0a\u4e50\u56ed\u6cf3\u88c5 Cosplay | Cosplay \u77ed\u89c6\u9891",
            "Swimsuit Cosplay Look | Cosplay Short": "\u6cf3\u88c5 Cosplay \u9020\u578b | Cosplay \u77ed\u89c6\u9891",
            "Water Park Cosplay Moment | Cosplay Short": "\u6c34\u4e0a\u4e50\u56ed Cosplay \u77ac\u95f4 | Cosplay \u77ed\u89c6\u9891",
        }
        if text in exact:
            return exact[text]
        inspired_match = re.fullmatch(
            r"A real-life cosplay short inspired by (.+), filmed in a cinematic short-video style\.",
            text,
        )
        if inspired_match:
            source = self.translate_source_name(inspired_match.group(1))
            return f"\u771f\u5b9e Cosplay \u77ed\u89c6\u9891\uff0c\u7075\u611f\u6765\u81ea {source}\uff0c\u7535\u5f71\u611f\u77ed\u89c6\u9891\u98ce\u683c\u3002"
        featuring_match = re.fullmatch(
            r"A short cosplay moment featuring (.+) from (.+), filmed in a cinematic short-video style\.",
            text,
        )
        if featuring_match:
            character = self.translate_character_name(featuring_match.group(1))
            source = self.translate_source_name(featuring_match.group(2))
            return f"{character} Cosplay \u77ac\u95f4\uff0c\u89d2\u8272\u6765\u81ea {source}\uff0c\u7535\u5f71\u611f\u77ed\u89c6\u9891\u98ce\u683c\u3002"
        transformation_match = re.fullmatch(
            r"One touch of the mirror, and (.+) suddenly feels real\. A fantasy cosplay transformation inspired by (.+)\.",
            text,
        )
        if transformation_match:
            character = self.translate_character_name(transformation_match.group(1))
            source = self.translate_source_name(transformation_match.group(2))
            return f"\u8f7b\u89e6\u955c\u5b50\uff0c{character}\u5c31\u50cf\u771f\u7684\u8d70\u5230\u4e86\u73b0\u5b9e\u4e2d\u3002\u4e00\u6bb5\u7075\u611f\u6765\u81ea {source} \u7684\u5e7b\u60f3 Cosplay \u53d8\u88c5\u89c6\u9891\u3002"
        throne_match = re.fullmatch(
            r"A real-life (.+) cosplay from Throne of Seal, captured in a cinematic walk\.",
            text,
        )
        if throne_match:
            character = self.translate_character_name(throne_match.group(1))
            return f"\u5979\u4e0d\u662f\u8d70\u8fdb\u4e86\u753b\u9762\uff0c\u5979\u662f\u4ece\u52a8\u753b\u91cc\u8d70\u51fa\u6765\u7684\u3002{character}\u6765\u81ea\u300a\u795e\u5370\u738b\u5ea7\u300b\uff0c\u73b0\u5728\u771f\u7684\u51fa\u73b0\u5728\u73b0\u5b9e\u4e2d\u3002\u4f60\u662f\u770b\u5230\u6807\u7b7e\u524d\u8ba4\u51fa\u5979\u7684\u5417\uff1f"
        if text.startswith("Real-life ") and " cosplay short filmed in a cinematic style." in text:
            name = text.removeprefix("Real-life ").removesuffix(" cosplay short filmed in a cinematic style.")
            return f"\u771f\u5b9e {self.translate_character_name(name)} Cosplay \u77ed\u89c6\u9891\uff0c\u7535\u5f71\u611f\u62cd\u6444\u3002"
        if text.startswith("Character: "):
            return "\u89d2\u8272\uff1a" + self.translate_character_name(text.removeprefix("Character: "))
        if text.startswith("Source: "):
            return "\u51fa\u5904\uff1a" + self.translate_source_name(text.removeprefix("Source: "))
        if text.startswith("Moment: "):
            return "\u77ac\u95f4\uff1a" + text.removeprefix("Moment: ")
        if text.startswith("#"):
            return "\u6807\u7b7e\uff1a" + "\u3001".join(self.translate_hashtag(tag) for tag in text.split())
        return self.translate_title_terms(text)

    def translate_character_name(self, text):
        return translation.character_en_to_cn(text)

    def translate_source_name(self, text):
        # "Donghua" 是泛称，不在 catalog 里，单独处理
        if text == "Donghua":
            return "国漫"
        return translation.source_en_to_cn(text)

    def translate_hashtag(self, tag):
        clean = tag.lstrip("#")
        return {
            "Cosplay": "Cosplay",
            "Cosplayer": "Coser",
            "AnimeCosplay": "\u52a8\u6f2b Cosplay",
            "shorts": "Shorts",
            "SwimsuitCosplay": "\u6cf3\u88c5 Cosplay",
            "WaterPark": "\u6c34\u4e0a\u4e50\u56ed",
            "HonorOfKings": "\u738b\u8005\u8363\u8000",
            "NarakaBladepoint": "\u6c38\u52ab\u65e0\u95f4",
            "WutheringWaves": "\u9e23\u6f6e",
            "GameCosplay": "\u6e38\u620f Cosplay",
            "Donghua": "\u56fd\u6f2b",
            "XiaoXuner": "\u8427\u85b0\u513f",
            "AnimeCosplay": "\u52a8\u6f2b Cosplay",
            "ChineseCostume": "\u4e2d\u56fd\u98ce\u9020\u578b",
            "CostumeShorts": "\u670d\u9970\u77ed\u89c6\u9891",
            "HonkaiStarRail": "\u5d29\u574f\u661f\u7a79\u94c1\u9053",
            "GenshinImpact": "\u539f\u795e",
            "LeagueOfLegends": "\u82f1\u96c4\u8054\u76df",
            "Ahri": "\u963f\u72f8",
            "ZenlessZoneZero": "\u7edd\u533a\u96f6",
            "BlueArchive": "\u851a\u84dd\u6863\u6848",
            "AzurLane": "\u78a7\u84dd\u822a\u7ebf",
            "IcePrincess": "\u51b0\u516c\u4e3b",
            "YeLuoli": "\u53f6\u7f57\u4e3d",
            "CosplayTransition": "Cosplay \u53d8\u88c5\u8f6c\u573a",
            "ShengCaier": "\u5723\u91c7\u513f",
            "ThroneOfSeal": "\u795e\u5370\u738b\u5ea7",
        }.get(clean, clean)

    def translate_title_terms(self, text):
        exact = {
            "Wait... That's Not CGI?": "\u7b49\u7b49\uff0c\u8fd9\u4e0d\u662f CGI\uff1f",
            "The Mirror Just Glitched": "\u955c\u5b50\u521a\u521a\u5361\u51fa\u4e86\u4e00\u4e2a\u52a8\u753b\u4e16\u754c",
            "She Wasn't There a Second Ago": "\u4e00\u79d2\u524d\u5979\u8fd8\u4e0d\u5728\u90a3\u91cc",
            "This Cosplay Is Breaking Reality": "\u8fd9\u4e2a Cosplay \u5feb\u628a\u73b0\u5b9e\u641e\u574f\u4e86",
            "The Anime Girl Is Looking Back": "\u52a8\u753b\u91cc\u7684\u5973\u5b69\u6b63\u5728\u56de\u5934\u770b\u6211",
            "She Just Stole the Entire Scene": "\u5979\u4e00\u51fa\u573a\u5c31\u62a2\u8d70\u4e86\u5168\u573a\u7126\u70b9",
            "That Entrance Was Everything": "\u8fd9\u4e2a\u51fa\u573a\u592a\u7edd\u4e86",
            "The Main Character Just Arrived": "\u4e3b\u89d2\u767b\u573a\u4e86",
            "No One Was Ready for That Entrance": "\u6ca1\u6709\u4eba\u80fd\u51c6\u5907\u597d\u8fd9\u4e2a\u51fa\u573a",
            "Don't Blink": "\u522b\u7728\u773c",
        }
        if text in exact:
            return exact[text]
        replacements = {
            "Battle Through the Heavens": "\u6597\u7834\u82cd\u7a79",
            "Honor of Kings": "\u738b\u8005\u8363\u8000",
            "Naraka Bladepoint": "\u6c38\u52ab\u65e0\u95f4",
            "Naraka: Bladepoint": "\u6c38\u52ab\u65e0\u95f4",
            "Wuthering Waves": "\u9e23\u6f6e",
            "Honkai Star Rail": "\u5d29\u574f\u661f\u7a79\u94c1\u9053",
            "Genshin Impact": "\u539f\u795e",
            "League of Legends": "\u82f1\u96c4\u8054\u76df",
            "Cosplay Brought to Life": "Cosplay \u771f\u4eba\u8fd8\u539f",
            "Cosplay Brings the Character to Life": "Cosplay \u628a\u89d2\u8272\u5e26\u5230\u73b0\u5b9e",
            "Just Stepped Out of the Screen": "\u50cf\u4ece\u5c4f\u5e55\u91cc\u8d70\u51fa\u6765",
            "This ": "\u8fd9\u4e2a ",
            " Is So Accurate": " \u8fd8\u539f\u5ea6\u5f88\u9ad8",
            "Real Cosplay Moment": "\u771f\u5b9e Cosplay \u77ac\u95f4",
            "Cosplay Short": "Cosplay \u77ed\u89c6\u9891",
            "Honor of Kings Short": "\u738b\u8005\u8363\u8000\u77ed\u89c6\u9891",
            "Naraka Bladepoint Short": "\u6c38\u52ab\u65e0\u95f4\u77ed\u89c6\u9891",
            "Game Cosplay Short": "\u6e38\u620f Cosplay \u77ed\u89c6\u9891",
            "Donghua Short": "\u56fd\u6f2b\u77ed\u89c6\u9891",
            "Looks Unreal in Real Life": "\u771f\u4eba\u8fd8\u539f\u611f\u5f88\u5f3a",
            "Looks Real": "\u8fd8\u539f\u611f\u5f88\u5f3a",
            "Cosplay Walk": "Cosplay \u8d70\u79c0",
            "Cosplay Looks Unreal": "Cosplay \u8fd8\u539f\u5ea6\u5f88\u9ad8",
            "Cosplay": "Cosplay",
            "Short": "\u77ed\u89c6\u9891",
        }
        translated = text
        for source, target in replacements.items():
            translated = translated.replace(source, target)
        # 角色名替换：从 catalog 动态获取，不再硬编码
        for char in translation.all_characters():
            en = char.get("character_en", "")
            cn = char.get("character_cn", "")
            if en and cn:
                translated = translated.replace(en, cn)
        return translated

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
            with httpx.Client(headers=headers, follow_redirects=True, timeout=20, verify=False) as client:
                final_url = str(client.get(text).url)
            sec_uid = re.search(r"(?:sec_uid=|/share/user/)([^&/?]+)", final_url)
            if sec_uid:
                return f"https://www.douyin.com/user/{sec_uid.group(1)}"
        except Exception as exc:
            self.log_queue.put(f"Could not normalize Douyin source, using original link: {exc}")
        return text

    def batch_new_files(self, output_root, before_dirs, started_at):
        if not output_root.exists():
            return []
        files = []
        for video in output_root.rglob("*.mp4"):
            if not video.is_file():
                continue
            folder = video.parent
            modified = video.stat().st_mtime
            if folder not in before_dirs or modified >= started_at:
                files.append(video)
        return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)

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
        self.log.append(message.rstrip())

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
    app.setStyleSheet(STYLE)
    write_trace("creating MainWindow")
    window = MainWindow(lock)
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
