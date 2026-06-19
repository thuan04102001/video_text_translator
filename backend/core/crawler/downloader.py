import os
import yt_dlp
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.crawler.task_control import wait_if_paused, is_cancelled
from core.crawler.utils import video_exists_in_folder
from core.crawler.fb_scraper import get_facebook_reels



def detect_platform(url):
    if "tiktok.com" in url:
        return "tiktok"

    if "facebook.com" in url or "fb.watch" in url:
        return "facebook"

    return "unknown"


def get_platform_prefix(platform):
    if platform == "tiktok":
        return "tik"

    if platform == "facebook":
        return "fb"

    return "unk"


def extract_video_id(video_url):
    clean_url = video_url.split("?")[0]
    return clean_url.rstrip("/").split("/")[-1]


def extract_profile_id(info, url):
    uploader_id = info.get("uploader_id")
    if uploader_id:
        return str(uploader_id)

    channel_id = info.get("channel_id")
    if channel_id:
        return str(channel_id)

    uploader = info.get("uploader")
    if uploader:
        return str(uploader)

    return url.rstrip("/").split("/")[-1]


def is_tiktok_real_video(entry):
    if entry.get("_type") == "multi_video":
        return False, "Slideshow ảnh"

    duration = entry.get("duration", 0)
    if duration and duration < 3:
        return False, "Duration quá ngắn"

    formats = entry.get("formats", [])

    if not formats:
        return True, ""

    for fmt in formats:
        vcodec = fmt.get("vcodec")
        width = fmt.get("width") or 0

        if vcodec and vcodec != "none" and width >= 540:
            return True, ""

    return False, "Không phải video thật"


def build_extract_opts():
    return {
        "extract_flat": False,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "playlistreverse": True,
        "compat_opts": ["no-youtube-unavailable-videos"],
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.tiktok.com/",
        },
    }


def build_download_opts(output_template):
    return {
        "format": "best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "restrictfilenames": True,
        "windowsfilenames": True,
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "keepvideo": False,
        "concurrent_fragment_downloads": 5,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 60,
        "overwrites": False,
        "nopart": True,
        "postprocessors": [
            {
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4",
            }
        ],
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            )
        },
    }


def dedupe_video_list(video_data_list):
    seen = set()
    unique_list = []

    for item in video_data_list:
        key = item["video_id"]

        if key in seen:
            continue

        seen.add(key)
        unique_list.append(item)

    return unique_list

def download_single_video(video_url, output_template):
    ydl_download_opts = build_download_opts(output_template)

    with yt_dlp.YoutubeDL(ydl_download_opts) as ydl:
        ydl.download([video_url])

def download_profile_videos(url, folder, task_id=None, max_workers=1):
    platform = detect_platform(url)

    if platform == "unknown":
        raise Exception("Không hỗ trợ nền tảng này")

    if not os.path.exists(folder):
        os.makedirs(folder)

    yield f"[PLATFORM] {platform}"

    video_data_list = []

    downloaded_count = 0
    duplicate_count = 0
    photo_skip_count = 0
    error_count = 0

    platform_prefix = get_platform_prefix(platform)
    max_workers = max(1, min(int(max_workers), 10))
    yield f"[WORKERS] Số luồng tải: {max_workers}"
    if task_id and is_cancelled(task_id):
        yield "[CANCELLED] Đã hủy tiến trình"
        yield "[FINISHED]"
        return

    if platform == "facebook":
        yield "[FB] Đang cào reels bằng Playwright..."

        fb_logs = []

        def fb_callback(message):

            fb_logs.append(message)

        fb_data = get_facebook_reels(
            url,
            callback=fb_callback
        )

        for message in fb_logs:

            yield message

        profile_id = fb_data["profile_id"]
        reels_urls = fb_data["reels_urls"]

        for index, reel_url in enumerate(reversed(reels_urls), start=1):
            video_data_list.append(
                {
                    "url": reel_url,
                    "timestamp": index,
                    "video_id": extract_video_id(reel_url),
                }
            )

    else:
        ydl_extract_opts = build_extract_opts()

        with yt_dlp.YoutubeDL(ydl_extract_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            yield "[ERROR] Không lấy được dữ liệu từ link"
            yield "[FINISHED]"
            return

        profile_id = extract_profile_id(info, url)

        yield f"Profile ID: {profile_id}"

        entries = info.get("entries") or [info]

        for entry in entries:
            if task_id and is_cancelled(task_id):
                yield "[CANCELLED] Đã hủy tiến trình"
                yield "[FINISHED]"
                return
            if not entry:
                continue

            video_url = entry.get("webpage_url") or entry.get("url")

            if not video_url:
                continue

            if platform == "tiktok":
                is_real_video, reason = is_tiktok_real_video(entry)

                if not is_real_video:
                    photo_skip_count += 1
                    yield f"[SKIP PHOTO] {reason}"
                    continue

            video_data_list.append(
                {
                    "url": video_url,
                    "timestamp": entry.get("timestamp", 0) or 0,
                    "video_id": extract_video_id(video_url),
                }
            )

        video_data_list = sorted(
            video_data_list,
            key=lambda item: item["timestamp"],
        )

    video_data_list = dedupe_video_list(video_data_list)
    if task_id and is_cancelled(task_id):
        yield "[CANCELLED] Đã hủy tiến trình"
        yield "[FINISHED]"
        return

    total = len(video_data_list)

    yield f"[SYSTEM] TOTAL = {total}"
    yield f"Tổng video hợp lệ: {total}"

    download_jobs = []

    for index, video_data in enumerate(video_data_list, start=1):

        video_url = video_data["url"]
        video_id = video_data["video_id"]

        file_code = (
            f"{index}-"
            f"{platform_prefix}-"
            f"{profile_id}-"
            f"{video_id}"
        )

        if video_exists_in_folder(folder, profile_id, video_id):
            duplicate_count += 1
            yield f"[SKIP] {file_code}"
            continue

        output_template = os.path.join(
            folder,
            f"{index}-{platform_prefix}-{profile_id}-{video_id}.%(ext)s",
        )

        download_jobs.append(
            {
                "url": video_url,
                "output_template": output_template,
                "file_code": file_code,
            }
        )

    yield f"[QUEUE] Video cần tải mới: {len(download_jobs)}"

    job_index = 0

    while job_index < len(download_jobs):

        if task_id and is_cancelled(task_id):
            yield "[CANCELLED] Đã hủy tiến trình"
            yield "[FINISHED]"
            return

        if task_id:
            can_continue = wait_if_paused(task_id)

            if not can_continue:
                yield "[CANCELLED] Đã hủy tiến trình"
                yield "[FINISHED]"
                return

        batch = download_jobs[
            job_index: job_index + max_workers
        ]

        yield (
            f"[BATCH] Đang tải "
            f"{len(batch)} video song song"
        )

        cancel_after_batch = False

        with ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:

            future_map = {}

            for job in batch:

                if task_id and is_cancelled(task_id):
                    cancel_after_batch = True
                    break

                yield f"[DOWNLOAD] {job['file_code']}"

                future = executor.submit(
                    download_single_video,
                    job["url"],
                    job["output_template"]
                )

                future_map[future] = job

            for future in as_completed(future_map):

                job = future_map[future]

                try:
                    future.result()

                    downloaded_count += 1

                    yield f"[DONE] {job['file_code']}"

                except Exception as e:
                    error_count += 1

                    yield f"[ERROR] {job['file_code']}"
                    yield str(e)
        job_index += max_workers
        if task_id and is_cancelled(task_id):
            yield "[CANCELLED] Đã hủy sau batch hiện tại"
            yield "[FINISHED]"
            return
    yield "==================================="
    yield "           TỔNG KẾT"
    yield "==================================="
    yield f"Video hợp lệ : {total}"

    if platform == "tiktok":
        yield f"Ảnh slideshow bỏ qua : {photo_skip_count}"

    yield f"Đã tải mới : {downloaded_count}"
    yield f"Duplicate bỏ qua : {duplicate_count}"
    yield f"Lỗi tải : {error_count}"
    yield "==================================="

    yield (
        f"Tải mới {downloaded_count} video | "
        f"Duplicate {duplicate_count} | "
        f"Lỗi {error_count}"
    )

    yield "[FINISHED]"
