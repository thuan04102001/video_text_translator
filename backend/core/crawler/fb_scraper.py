import re
import time
import random
import socket
import subprocess
from playwright.sync_api import sync_playwright


DEBUG_PORT = 9222

DEBUG_URL = f"http://127.0.0.1:{DEBUG_PORT}"

CHROME_USER_DATA = r"C:\ChromeDebug"


def log(message, callback=None):

    print(message)

    if callback:
        callback(message)


def is_debug_chrome_running():

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    sock.settimeout(1)

    try:

        result = sock.connect_ex(
            ("127.0.0.1", DEBUG_PORT)
        )

        return result == 0

    finally:

        sock.close()


def start_debug_chrome():

    chrome_path = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )

    command = [
        "cmd",
        "/c",
        "start",
        "/min",
        "",
        chrome_path,
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={CHROME_USER_DATA}",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    subprocess.Popen(command)


def resolve_facebook_uid(page):

    current_url = page.url

    match = re.search(
        r"id=(\d+)",
        current_url
    )

    if match:
        return match.group(1)

    html = page.content()

    matches = re.findall(
        r'"userID":"(\d+)"',
        html
    )

    if matches:
        return matches[0]

    return None


def is_facebook_logged_in(page):

    page.goto(
        "https://www.facebook.com/",
        timeout=120000
    )

    time.sleep(3)

    current_url = page.url.lower()

    if "login" in current_url:
        return False

    html = page.content().lower()

    login_markers = [

        'name="email"',

        'name="pass"',

        "login_form",

        "log in",

        "create new account"
    ]

    for marker in login_markers:

        if marker in html:
            return False

    return True


def wait_for_login(page, callback=None):

    while True:

        if is_facebook_logged_in(page):

            log(
                "[LOGIN_OK] Facebook login thành công",
                callback
            )

            return

        time.sleep(3)


def get_facebook_reels(
    profile_url,
    callback=None
):

    reels_urls = []

    if not is_debug_chrome_running():
        log("[BROWSER] Chrome debug chưa bật -> đang mở...", callback)

        start_debug_chrome()

        for _ in range(20):
            if is_debug_chrome_running():
                log("[BROWSER] Chrome debug đã mở thành công", callback)
                break

            time.sleep(1)

        if not is_debug_chrome_running():
            raise Exception(
                "Không mở được Chrome debug port 9222. "
                "Hãy kiểm tra đường dẫn Chrome và CHROME_USER_DATA."
            )
    else:
        log("[BROWSER] Chrome debug đã bật", callback)

    with sync_playwright() as p:

        browser = p.chromium.connect_over_cdp(
            DEBUG_URL
        )

        if browser.contexts:

            context = browser.contexts[0]

        else:

            context = browser.new_context()

        page = context.new_page()

        log(
            "[LOGIN_CHECK] Kiểm tra login Facebook...",
            callback
        )

        if not is_facebook_logged_in(page):

            log(
                "[LOGIN_REQUIRED] HÃY LOGIN FACEBOOK",
                callback
            )

            page.goto(
                "https://www.facebook.com/login",
                timeout=120000
            )

            wait_for_login(
                page,
                callback
            )

        log(
            f"[FB] Open profile: {profile_url}",
            callback
        )

        page.goto(
            profile_url,
            timeout=120000
        )

        time.sleep(5)

        uid = resolve_facebook_uid(page)

        if not uid:
            raise Exception(
                "Không lấy được Facebook UID"
            )

        log(
            f"[FB UID] {uid}",
            callback
        )

        reels_url = (

            f"https://www.facebook.com/"
            f"profile.php?id={uid}&sk=reels_tab"
        )

        log(
            f"[FB REELS] {reels_url}",
            callback
        )

        page.goto(
            reels_url,
            timeout=120000
        )

        time.sleep(5)

        last_height = 0

        for _ in range(100):

            links = page.query_selector_all("a")

            for link in links:

                href = link.get_attribute("href")

                if not href:
                    continue

                if "/reel/" not in href:
                    continue

                if "login.php" in href:
                    continue

                if "_fb_noscript" in href:
                    continue

                if "next=" in href:
                    continue

                if href.startswith("/"):

                    href = (
                        "https://www.facebook.com"
                        + href
                    )

                clean_url = href.split("?")[0]

                parts = (
                    clean_url
                    .rstrip("/")
                    .split("/")
                )

                if (
                    "/reel/" in clean_url
                    and len(parts[-1]) > 5
                ):

                    if clean_url not in reels_urls:

                        reels_urls.append(
                            clean_url
                        )

            page.mouse.wheel(0, 5000)

            time.sleep(
                random.uniform(1.5, 3.5)
            )

            new_height = page.evaluate(
                "document.body.scrollHeight"
            )

            log(
                f"[SCROLL] {len(reels_urls)} reels",
                callback
            )

            if new_height == last_height:
                break

            last_height = new_height

        log(
            "[BROWSER] Đã đóng tab crawler",
            callback
        )

        try:
            page.close()
        except:
            pass

        try:
            browser.close()
        except:
            pass

    reels_urls = list(reels_urls)

    reels_urls = reels_urls[::-1]

    return {

        "profile_id": uid,

        "reels_urls": reels_urls
    }