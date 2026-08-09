"""YouTube 上传逻辑 — Chrome CDP 管理 + Playwright 自动化上传。

从 pipeline_ui.py 抽离，使上传流程独立于 HTTP API 层。
"""

import logging
import os
import re
import socket
import subprocess
import time
from pathlib import Path

import config
import metadata_helpers
import state

logger = logging.getLogger(__name__)

CHROME_PROFILE = config.CHROME_PROFILE
CHROME_DEBUG_URL = config.CHROME_DEBUG_URL
CHANNEL_ID = config.CHANNEL_ID


# ── Chrome 受控实例管理 ────────────────────────────────────

def chrome_executable() -> Path:
    """查找系统 Chrome 可执行文件路径。"""
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
    """启动受控 Chrome 实例，打开 YouTube Studio。"""
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
    """检查 Chrome 调试端口 9222 是否在监听。"""
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=1):
            return True
    except OSError:
        return False


def stop_controlled_chrome() -> None:
    """关闭受控 Chrome 进程。"""
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
    """重启受控 Chrome 实例。"""
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


# ── Playwright 上传辅助 ───────────────────────────────────

def log(job: dict, message: str) -> None:
    """向上传任务的日志列表追加一条带时间戳的记录。"""
    job.setdefault("log", []).append(f"{state.now_text()} {message}")


def import_playwright():
    """延迟导入 Playwright，给出友好的安装提示。"""
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
    """等待 locator 第一个元素可见并返回。"""
    locator.first.wait_for(state="visible", timeout=timeout)
    return locator.first


def click_first_available(locators: list, timeout=TIMEOUT_SHORT) -> None:
    """依次尝试点击 locators 列表中的第一个可点击元素。"""
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
    """等待 YouTube Studio 上传页面就绪（处理登录重定向等）。"""
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
                if page.get_by_text(re.compile("(Upload videos|上传视频)")).count():
                    return
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception as exc:
            logger.debug("wait_for_studio_ready transient error (will retry): %s", exc)
        time.sleep(1)
    raise RuntimeError(f"YouTube Studio upload page was not ready. Last URL: {page.url}")


def fill_upload_textboxes(page, title: str, description: str) -> None:
    """填写 YouTube Studio 的标题和描述文本框。"""
    boxes = page.locator('div[role="textbox"][contenteditable="true"]')
    boxes.nth(0).wait_for(state="visible", timeout=60000)
    boxes.nth(0).fill(title)
    boxes.nth(1).wait_for(state="visible", timeout=30000)
    boxes.nth(1).fill(description)


def attach_youtube_video(page, video_path: Path, job: dict) -> None:
    """将本地视频文件附加到 YouTube Studio 的隐藏文件输入框。

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
    """点击 YouTube Studio 上传向导的「下一步」按钮。"""
    click_first_available(
        [
            page.get_by_role("button", name=re.compile("^(Next|下一步|继续)$")),
            page.locator("#next-button button"),
            page.locator("ytcp-button").filter(has_text=re.compile("(Next|下一步|继续)")),
        ],
        timeout=30000,
    )


def click_visibility(page, privacy: str) -> None:
    """选择视频可见性（公开/不公开列出/私享）。"""
    css_names = {
        "public": "PUBLIC",
        "unlisted": "UNLISTED",
        "private": "PRIVATE",
    }
    text_names = {
        "public": re.compile("^(Public|公开)$"),
        "unlisted": re.compile("^(Unlisted|不公开列出)$"),
        "private": re.compile("^(Private|私享)$"),
    }
    locators = [
        page.locator(f'tp-yt-paper-radio-button[name="{css_names.get(privacy, "PUBLIC")}"]'),
        page.get_by_text(text_names.get(privacy, text_names["public"])),
        page.locator("tp-yt-paper-radio-button").filter(has_text=text_names.get(privacy, text_names["public"])),
    ]
    click_first_available(locators, timeout=30000)


def click_publish_or_save(page, privacy: str) -> None:
    """点击「发布」或「保存」按钮。"""
    labels = (
        re.compile("^(Publish|发布)$")
        if privacy == "public"
        else re.compile("^(Save|保存)$")
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
    """通过 CDP 连接受控 Chrome 实例，带重试。"""
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


# ── 主上传流程 ─────────────────────────────────────────────

def run_upload(job_id: str, item: dict, title: str, description: str, privacy: str) -> None:
    """执行完整的 YouTube 上传流程（在后台线程中运行）。

    流程：连接 Chrome → 打开 Studio → 附加视频 → 填写文案 →
          跳过步骤 → 选择可见性 → 发布/保存 → 记录结果
    """
    job = state.JOBS[job_id]
    try:
        metadata_helpers.validate_publish_copy(title, description)
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
                        page.get_by_role("button", name=re.compile("(Upload videos|上传视频)")),
                        page.get_by_text(re.compile("(Upload videos|上传视频)")),
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
                or "为儿童打造" in body
                or "面向儿童" in body
            ):
                click_first_available(
                    [
                        page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'),
                        page.get_by_text(
                            re.compile(
                                "(No, it's not made for kids|No, set this video as not made for kids|不.*面向儿童)"
                            )
                        ),
                        page.locator("tp-yt-paper-radio-button").filter(
                            has_text=re.compile("(not made for kids|不.*面向儿童)", re.I)
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

            with state.STATE_LOCK:
                st = state.load_state()
                st.setdefault("uploads", {})[item["id"]] = {
                    "uploaded_at": time.time(),
                    "title": title,
                    "description": description,
                    "privacy": privacy,
                    "url": video_url,
                }
                state.save_state(st)
            job["status"] = "done"
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        log(job, f"Error: {exc}")
