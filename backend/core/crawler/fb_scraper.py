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


def start_debug_chrome(hidden=True):

    chrome_path = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )

    command = [
        "cmd",
        "/c",
        "start",
    ]
    if hidden:
        command.append("/min")
    command.extend([
        "",
        chrome_path,
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={CHROME_USER_DATA}",
        "--no-first-run",
        "--no-default-browser-check",
    ])
    if hidden:
        command.extend([
            "--window-position=-32000,-32000",
            "--window-size=1200,900",
        ])

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

    patterns = [
        r'"userID":"(\d+)"',
        r'"pageID":"(\d+)"',
        r'"profile_id":"(\d+)"',
        r'"entity_id":"(\d+)"',
        r'profile\.php\?id=(\d+)',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html)
        if matches:
            return matches[0]

    return None


def is_facebook_logged_in(page):

    page.goto(
        "https://www.facebook.com/",
        timeout=120000
    )

    time.sleep(3)

    return facebook_auth_state(page) == "ok"


def _facebook_session_cookies(page):
    try:
        cookies = page.context.cookies("https://www.facebook.com/")
    except Exception:
        return {}
    return {
        cookie.get("name"): cookie.get("value")
        for cookie in cookies
        if cookie.get("domain", "").endswith("facebook.com")
    }


def _has_facebook_session_cookie(page):
    cookies = _facebook_session_cookies(page)
    return bool(cookies.get("c_user") and cookies.get("xs"))


def _facebook_auth_url_state(url):
    lowered = str(url or "").lower()
    auth_paths = [
        "/login",
        "login.php",
        "/recover",
        "/checkpoint",
        "/two_step_verification",
        "/privacy/consent",
    ]
    if "/checkpoint" in lowered or "/two_step_verification" in lowered:
        return "checkpoint"
    if any(marker in lowered for marker in auth_paths):
        return "login"
    return ""


def _visible_count(page, selector):
    try:
        return page.locator(selector).filter(visible=True).count()
    except Exception:
        return 0


def _has_visible_login_form(page):
    email_visible = _visible_count(page, 'input[name="email"]') > 0
    password_visible = _visible_count(page, 'input[name="pass"]') > 0
    login_button_visible = _visible_count(
        page,
        'button[name="login"], [data-testid="royal_login_button"]'
    ) > 0
    return (email_visible and password_visible) or (password_visible and login_button_visible)


def _has_visible_checkpoint_prompt(page):
    checkpoint_selectors = [
        'form[action*="checkpoint"]',
        'input[name="approvals_code"]',
        'input[name="checkpoint_data"]',
        'input[name="verification_method"]',
    ]
    return any(_visible_count(page, selector) > 0 for selector in checkpoint_selectors)


def _has_logged_in_facebook_ui(page):
    positive_selectors = [
        '[aria-label="Search Facebook"]',
        '[aria-label="Home"]',
        '[aria-label="Menu"]',
        '[aria-label="Messenger"]',
        '[aria-label="Notifications"]',
        'a[href*="/reels/"]',
        'a[href*="sk=reels_tab"]',
    ]
    return any(_visible_count(page, selector) > 0 for selector in positive_selectors)


def facebook_auth_state(page):
    url_state = _facebook_auth_url_state(page.url)
    if url_state:
        return url_state

    has_session = _has_facebook_session_cookie(page)
    if has_session and _has_logged_in_facebook_ui(page):
        return "ok"
    if _has_visible_checkpoint_prompt(page):
        return "checkpoint"
    if _has_visible_login_form(page):
        return "login"
    if has_session:
        return "ok"
    return "login"


def wait_for_login(page, callback=None):

    while True:

        if is_facebook_logged_in(page):

            log(
                "[LOGIN_OK] Facebook login thành công",
                callback
            )

            return

        time.sleep(3)


def open_facebook_login_browser(callback=None):
    if not is_debug_chrome_running():
        log("[BROWSER] Open visible Chrome for Facebook login...", callback)
        start_debug_chrome(hidden=False)
        for _ in range(20):
            if is_debug_chrome_running():
                break
            time.sleep(1)
    if not is_debug_chrome_running():
        raise Exception("Cannot open Chrome debug profile for Facebook login.")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(DEBUG_URL)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            session = context.new_cdp_session(page)
            window = session.send("Browser.getWindowForTarget")
            session.send(
                "Browser.setWindowBounds",
                {
                    "windowId": window["windowId"],
                    "bounds": {
                        "windowState": "normal",
                        "left": 80,
                        "top": 60,
                        "width": 1280,
                        "height": 900,
                    },
                },
            )
        except Exception:
            pass
        page.goto("https://www.facebook.com/login", timeout=120000)
        page.bring_to_front()
        return {"status": "opened"}


def get_facebook_reels(
    profile_url,
    callback=None,
    interactive_login=True,
    max_items=None,
    stop_after_known=0,
    known_item_ids=None,
    hidden=True,
):

    reels_urls = []
    known_item_ids = set(known_item_ids or [])

    if not is_debug_chrome_running():
        log("[BROWSER] Chrome debug chưa bật -> đang mở...", callback)

        start_debug_chrome(hidden=hidden)

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

            if not interactive_login:
                raise Exception(
                    "facebook_login_required: Facebook crawler session is not logged in. "
                    "Open Video Crawler once and log in to the Chrome debug profile."
                )

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

        auth_state = facebook_auth_state(page)
        if auth_state == "checkpoint":
            raise Exception("facebook_checkpoint_required: Facebook checkpoint or verification is required.")
        if auth_state == "login":
            raise Exception("facebook_login_required: Facebook login is required.")

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

        auth_state = facebook_auth_state(page)
        if auth_state == "checkpoint":
            raise Exception("facebook_checkpoint_required: Facebook checkpoint or verification is required.")
        if auth_state == "login":
            raise Exception("facebook_login_required: Facebook login is required.")

        last_height = 0
        known_streak = 0
        processed_ids = set()
        should_stop = False

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
                source_id = parts[-1] if parts else ""

                if (
                    "/reel/" in clean_url
                    and len(source_id) > 5
                ):
                    if source_id in processed_ids:
                        continue
                    processed_ids.add(source_id)

                    if source_id in known_item_ids and stop_after_known:
                        known_streak += 1
                        if known_streak >= stop_after_known:
                            should_stop = True
                            break
                        continue
                    known_streak = 0

                    if clean_url not in reels_urls:

                        reels_urls.append(
                            clean_url
                        )
                        if max_items and len(reels_urls) >= max_items:
                            should_stop = True
                            break

            if should_stop:
                break

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

    return {

        "profile_id": uid,

        "reels_urls": reels_urls
    }
