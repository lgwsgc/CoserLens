import argparse
import datetime as dt
import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import config
import utils

REPO_ROOT = config.REPO_ROOT
DEFAULT_OUTPUT_ROOT = config.ENHANCED_OUTPUT_ROOT
DEFAULT_DOWNLOAD_DIR = (
    REPO_ROOT
    / "TikTokDownloader"
    / "Volume"
    / "UID1099148033790384_ytb_发布作品"
)
REALESRGAN_DIR = config.REALESRGAN_DIR
REALESRGAN_EXE = config.REALESRGAN_EXE
MODEL_DIR = config.REALESRGAN_MODEL_DIR
FFMPEG = config.FFMPEG
FFPROBE = config.FFPROBE


def format_seconds(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def count_pngs(folder: Path) -> int:
    return sum(1 for _ in folder.glob("*.png")) if folder.exists() else 0


def folder_size_bytes(folder: Path) -> int:
    if not folder.exists():
        return 0
    total = 0
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def free_gb(path: Path) -> float:
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1024**3)


def write_step(message: str, log_path: Path) -> None:
    line = f"[{dt.datetime.now().isoformat()}] {message}"
    print(line)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(line + "\n")


def require_free_space(path: Path, min_free_gb: float, log_path: Path | None = None) -> None:
    available = free_gb(path)
    message = f"Free disk space near {path}: {available:.1f} GB"
    print(f"[{dt.datetime.now().isoformat()}] {message}")
    if log_path is not None:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"[{dt.datetime.now().isoformat()}] {message}\n")
    if available < min_free_gb:
        raise RuntimeError(
            f"Not enough free disk space. Available {available:.1f} GB, "
            f"required at least {min_free_gb:.1f} GB. "
            "Delete old outputs or use a different --output-root."
        )


def remove_dir_if_exists(folder: Path, log_path: Path, label: str) -> None:
    if not folder.exists():
        return
    size_gb = folder_size_bytes(folder) / (1024**3)
    shutil.rmtree(folder)
    write_step(f"Deleted {label}: {folder} ({size_gb:.2f} GB)", log_path)


def default_input_video() -> Path:
    if DEFAULT_DOWNLOAD_DIR.exists():
        videos = sorted(
            DEFAULT_DOWNLOAD_DIR.glob("*.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if videos:
            return videos[0]
    raise FileNotFoundError(
        "No input video was provided and no mp4 was found in the default download folder. "
        r"Pass a path explicitly, for example: python enhance_x4plus_clean.py D:\path\video.mp4"
    )


def print_progress(label: str, done: int, total: int, started_at: float) -> None:
    percent = done / total if total else 0
    elapsed = time.time() - started_at
    fps = done / elapsed if elapsed > 0 and done else 0
    eta = (total - done) / fps if fps > 0 else None
    bar_width = 28
    filled = min(bar_width, int(percent * bar_width))
    bar = "#" * filled + "-" * (bar_width - filled)
    message = (
        f"\r{label}: [{bar}] {done}/{total} "
        f"{percent * 100:5.1f}% | {fps:4.2f} frame/s | ETA {format_seconds(eta)}"
    )
    print(message, end="", flush=True)


def run_command(
    args: list[str],
    log_path: Path,
    progress_dir: Path | None = None,
    progress_total: int | None = None,
    progress_label: str = "Progress",
    progress_interval: int = 10,
    min_free_gb: float | None = None,
    free_space_path: Path | None = None,
) -> None:
    with log_path.open("a", encoding="utf-8") as log:
        line = f"[{dt.datetime.now().isoformat()}] RUN {' '.join(map(str, args))}\n"
        print(line, end="")
        log.write(line)
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdout is None:
            raise RuntimeError("subprocess did not open stdout pipe")
        stdout = process.stdout

        def drain_output() -> None:
            for output_line in stdout:
                log.write(output_line)
                log.flush()

        reader = threading.Thread(target=drain_output, daemon=True)
        reader.start()

        started_at = time.time()
        last_progress = 0.0
        disk_error: RuntimeError | None = None
        if progress_dir and progress_total:
            print_progress(progress_label, count_pngs(progress_dir), progress_total, started_at)
        while process.poll() is None:
            now = time.time()
            if progress_dir and progress_total and now - last_progress >= progress_interval:
                last_progress = now
                done = count_pngs(progress_dir)
                print_progress(progress_label, done, progress_total, started_at)
                if min_free_gb is not None and free_space_path is not None:
                    available = free_gb(free_space_path)
                    if available < min_free_gb:
                        disk_error = RuntimeError(
                            f"Free disk space dropped below {min_free_gb:.1f} GB "
                            f"({available:.1f} GB available). Stopping current command."
                        )
                        process.terminate()
                        break
            time.sleep(0.5)
        reader.join(timeout=5)
        return_code = process.wait()
        if progress_dir and progress_total:
            done = count_pngs(progress_dir)
            print_progress(progress_label, done, progress_total, started_at)
            print()
    if disk_error is not None:
        raise disk_error
    if return_code != 0:
        raise RuntimeError(f"Command failed with exit code {return_code}: {args[0]}")


DEFAULT_FPS = 60.0
logger = logging.getLogger(__name__)


def ffprobe_fps(ffprobe: str, input_video: Path) -> float:
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_video),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        raw = result.stdout.strip()
        if "/" in raw:
            num, den = raw.split("/", 1)
            den_value = float(den)
            if den_value:
                return float(num) / den_value
        return float(raw)
    except Exception as exc:
        logger.warning("ffprobe_fps failed for %s (using default %.0f fps): %s", input_video.name, DEFAULT_FPS, exc)
        return DEFAULT_FPS


def format_fps(fps: float) -> str:
    if abs(fps - round(fps)) < 0.001:
        return str(int(round(fps)))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a clean AI-upscaled 9:16 video using Real-ESRGAN x4plus native 4x."
    )
    parser.add_argument(
        "input_video",
        nargs="?",
        default=None,
        help="Input video path. If omitted, the newest mp4 in the default download folder is used.",
    )
    parser.add_argument(
        "--input-video",
        "--input_video",
        dest="input_video_option",
        default=None,
        help="Input video path, same as positional input_video.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help=f"Output root folder. Default: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument("--base-width", type=int, default=540, help="Intermediate frame width. Default: 540")
    parser.add_argument("--base-height", type=int, default=960, help="Intermediate frame height. Default: 960")
    parser.add_argument("--gpu-id", type=int, default=0, help="Vulkan GPU id. Default: 0.")
    parser.add_argument("--tile-size", type=int, default=512, help="Real-ESRGAN tile size. Default: 512")
    parser.add_argument("--cq", type=int, default=16, help="NVENC constant quality. Lower is larger/cleaner. Default: 16")
    parser.add_argument("--bitrate", default="30M", help="Target video bitrate. Default: 30M")
    parser.add_argument("--maxrate", default="48M", help="Max video bitrate. Default: 48M")
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="Seconds between progress updates during AI upscaling. Default: 10",
    )
    parser.add_argument(
        "--keep-existing-frames",
        action="store_true",
        help="Reuse already extracted/upscaled frames in the output folder if present.",
    )
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep intermediate frame folders after successful encoding. Default: delete them.",
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=20.0,
        help="Stop before major steps if free disk space is below this value. Default: 20 GB.",
    )
    return parser


def resolve_input(args) -> Path:
    """解析输入视频路径（位置参数 > --input-video > 默认最新文件）。"""
    selected = args.input_video_option or args.input_video
    if selected:
        return Path(selected).expanduser().resolve()
    return default_input_video()


def prepare_job_dirs(input_video: Path, args) -> dict:
    """创建输出目录结构，返回路径字典。"""
    output_root = Path(args.output_root).expanduser().resolve()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    job_dir = output_root / f"{utils.safe_stem(input_video.stem)}_x4plus_clean_{stamp}"
    frames_small = job_dir / f"frames_{args.base_width}x{args.base_height}"
    frames_ai = job_dir / "frames_x4plus_4x"
    job_dir.mkdir(parents=True, exist_ok=True)
    frames_small.mkdir(parents=True, exist_ok=True)
    frames_ai.mkdir(parents=True, exist_ok=True)
    return {
        "job_dir": job_dir,
        "frames_small": frames_small,
        "frames_ai": frames_ai,
        "log_path": job_dir / "run.log",
        "output_video": job_dir / f"{utils.safe_stem(input_video.stem)}_x4plus-clean_{args.base_width}x{args.base_height}_to_4x_h265.mp4",
        "compare_video": job_dir / f"{utils.safe_stem(input_video.stem)}_compare_left-original_right-x4plus-clean.mp4",
    }


def extract_frames(ffmpeg: str, input_video: Path, frames_small: Path,
                   args, log_path: Path) -> int:
    """用 FFmpeg 将视频解帧为缩小尺寸的 PNG 序列，返回帧数。"""
    if count_pngs(frames_small) == 0:
        require_free_space(frames_small.parent, args.min_free_gb, log_path)
        write_step("Extracting downscaled frames", log_path)
        run_command(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(input_video),
                "-vf", f"scale={args.base_width}:{args.base_height}:flags=lanczos",
                str(frames_small / "%08d.png"),
            ],
            log_path,
        )
    small_count = count_pngs(frames_small)
    write_step(f"Extracted frames: {small_count}", log_path)
    if small_count == 0:
        raise RuntimeError("No frames extracted.")
    return small_count


def upscale_frames(frames_small: Path, frames_ai: Path,
                   small_count: int, args, log_path: Path) -> int:
    """用 Real-ESRGAN 对帧做 4x 超分辨率，返回帧数。"""
    if count_pngs(frames_ai) != small_count:
        for file in frames_ai.glob("*.png"):
            file.unlink()
        require_free_space(frames_ai.parent, args.min_free_gb, log_path)
        write_step("Running Real-ESRGAN x4plus native 4x", log_path)
        run_command(
            [
                str(REALESRGAN_EXE),
                "-i", str(frames_small),
                "-o", str(frames_ai),
                "-n", "realesrgan-x4plus",
                "-s", "4",
                "-t", str(args.tile_size),
                "-m", str(MODEL_DIR),
                "-g", str(args.gpu_id),
                "-j", "1:1:1",
                "-f", "png",
            ],
            log_path,
            progress_dir=frames_ai,
            progress_total=small_count,
            progress_label="AI upscale",
            progress_interval=args.progress_interval,
            min_free_gb=args.min_free_gb,
            free_space_path=frames_ai.parent,
        )
    ai_count = count_pngs(frames_ai)
    write_step(f"AI frames: {ai_count}", log_path)
    if ai_count != small_count:
        raise RuntimeError(f"Frame count mismatch. Extracted {small_count}, AI output {ai_count}.")
    return ai_count


def encode_enhanced_video(ffmpeg: str, frames_ai: Path, input_video: Path,
                          output_video: Path, fps_text: str, args, log_path: Path) -> None:
    """将 AI 增强帧编码为 H.265 视频（带原始音轨）。"""
    require_free_space(output_video.parent, args.min_free_gb, log_path)
    write_step("Encoding enhanced video", log_path)
    run_command(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", fps_text,
            "-i", str(frames_ai / "%08d.png"),
            "-i", str(input_video),
            "-map", "0:v:0",
            "-map", "1:a?",
            "-c:v", "hevc_nvenc",
            "-preset", "p7",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(args.cq),
            "-b:v", args.bitrate,
            "-maxrate", args.maxrate,
            "-bufsize", "96M",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-shortest",
            str(output_video),
        ],
        log_path,
    )


def encode_comparison_video(ffmpeg: str, input_video: Path,
                            output_video: Path, compare_video: Path,
                            min_free_gb: float, log_path: Path) -> None:
    """编码左右对比视频（原始 vs 增强）。"""
    require_free_space(compare_video.parent, min_free_gb, log_path)
    write_step("Encoding comparison video", log_path)
    run_command(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_video),
            "-i", str(output_video),
            "-filter_complex",
            "[0:v]scale=1080:1920:flags=lanczos[left];"
            "[1:v]scale=1080:1920:flags=lanczos[right];"
            "[left][right]hstack=inputs=2",
            "-map", "0:a?",
            "-c:v", "hevc_nvenc",
            "-preset", "p7",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "18",
            "-b:v", "24M",
            "-maxrate", "40M",
            "-bufsize", "80M",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-shortest",
            str(compare_video),
        ],
        log_path,
    )


def main() -> int:
    args = build_parser().parse_args()

    input_video = resolve_input(args)
    if not input_video.exists():
        raise FileNotFoundError(f"Input video not found: {input_video}")
    if not REALESRGAN_EXE.exists():
        raise FileNotFoundError(f"Real-ESRGAN executable not found: {REALESRGAN_EXE}")

    ffmpeg = FFMPEG
    try:
        ffprobe = FFPROBE
    except FileNotFoundError:
        ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))

    paths = prepare_job_dirs(input_video, args)
    log_path = paths["log_path"]
    frames_small = paths["frames_small"]
    frames_ai = paths["frames_ai"]

    fps = ffprobe_fps(ffprobe, input_video)
    fps_text = format_fps(fps)

    write_step(f"Input: {input_video}", log_path)
    write_step(f"Output directory: {paths['job_dir']}", log_path)
    write_step(f"Detected FPS: {fps_text}", log_path)
    write_step(f"GPU ID: {args.gpu_id}", log_path)
    require_free_space(paths["job_dir"], args.min_free_gb, log_path)

    if not args.keep_existing_frames:
        for folder in (frames_small, frames_ai):
            for file in folder.glob("*.png"):
                file.unlink()

    small_count = extract_frames(ffmpeg, input_video, frames_small, args, log_path)
    upscale_frames(frames_small, frames_ai, small_count, args, log_path)

    if not args.keep_frames:
        remove_dir_if_exists(frames_small, log_path, "downscaled frames")

    encode_enhanced_video(ffmpeg, frames_ai, input_video,
                          paths["output_video"], fps_text, args, log_path)
    encode_comparison_video(ffmpeg, input_video,
                            paths["output_video"], paths["compare_video"],
                            args.min_free_gb, log_path)

    write_step("Done", log_path)
    if not args.keep_frames:
        remove_dir_if_exists(frames_ai, log_path, "AI frames")

    print()
    print(f"Enhanced video: {paths['output_video']}")
    print(f"Comparison video: {paths['compare_video']}")
    print(f"Log: {log_path}")
    if args.keep_frames:
        print(f"Intermediate frames kept in: {paths['job_dir']}")
    else:
        print("Intermediate frames deleted after successful encoding.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
