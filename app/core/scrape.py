"""Collect reel/post URLs from a Facebook or Instagram page with Selenium."""
import csv
import json
import os
import re
import sys
from time import sleep
from urllib.parse import urlparse

from app.core.jobs import check_stop
from app.core.runtime import chrome_profile_dir, collect_csv_path, default_output_root
from app.core.urls import INSTAGRAM_SINGLE_KINDS, detect_platform

_CAPTION_NOISE = {"reel", "reels", "video", "facebook", "watch", "play reel", "open reel"}
_CAPTION_PREFIXES = ("reel by ", "reels by ", "video by ", "reel: ", "reels: ")
_VIEW_COUNT_RE = re.compile(r"^\d+(?:\.\d+)?[kmb]?$", re.IGNORECASE)


def looks_like_view_count(text):
    """True for grid labels such as ``10.8k`` or ``1,082 views``."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return False
    lowered = raw.lower()
    for suffix in (" views", " view", " likes", " like", " plays", " play"):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)].strip()
    compact = lowered.replace(" ", "").replace(",", "")
    return bool(_VIEW_COUNT_RE.fullmatch(compact)) and (
        compact[-1:].lower() in "kmb" or "." in compact or "," in raw
    )


def _clean_caption(text):
    """Keep a Facebook reel caption; drop empty chrome labels."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text or text.lower() in _CAPTION_NOISE or looks_like_view_count(text):
        return ""
    lowered = text.lower()
    for prefix in _CAPTION_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    for sep in (": ", " — ", " – ", " - "):
        if sep in text:
            head, _, tail = text.partition(sep)
            if tail.strip() and len(head.split()) <= 6:
                return tail.strip()
    return text


def caption_from_link(element):
    """Read aria-label / title / img alt from a Selenium reel <a>."""
    for attr in ("aria-label", "title"):
        try:
            caption = _clean_caption(element.get_attribute(attr) or "")
        except Exception:
            caption = ""
        if caption:
            return caption
    try:
        caption = _clean_caption(element.text or "")
    except Exception:
        caption = ""
    if caption:
        return caption
    try:
        img = element.find_element("css selector", "img")
        return _clean_caption(img.get_attribute("alt") or "")
    except Exception:
        return ""


def instagram_media_url(href):
    """Canonical /p/, /reel/, or /tv/ URL, or empty for tabs/profile links."""
    if not href:
        return ""
    parts = urlparse(href)
    host = parts.netloc.lower().split(":")[0].removeprefix("www.")
    if host and host != "instagram.com" and not host.endswith(".instagram.com"):
        return ""
    segments = [part for part in parts.path.split("/") if part]
    kinds = set(INSTAGRAM_SINGLE_KINDS)
    if len(segments) >= 2 and segments[0].lower() in kinds:
        return f"https://www.instagram.com/{segments[0].lower()}/{segments[1]}/"
    if len(segments) >= 3 and segments[1].lower() in kinds:
        return f"https://www.instagram.com/{segments[1].lower()}/{segments[2]}/"
    return ""


def media_url_from_href(href):
    """Facebook /reel/ id or Instagram post URL; skip profile/reels/reposts tabs."""
    media = instagram_media_url(href)
    if media:
        return media
    if href and "/reel/" in href:
        return href.split("/?s=")[0]
    return ""


def ordered_reel_urls(hrefs):
    """Unique reel/post URLs in page order, so the first found is downloaded first."""
    found = {}
    for href in hrefs:
        url = media_url_from_href(href)
        if url:
            found.setdefault(url, None)
    return list(found)


def harvest_new_reel_urls(hrefs, seen):
    """Return reel URLs not yet in `seen` and record them, keeping page order."""
    fresh = []
    for url in ordered_reel_urls(hrefs):
        if url in seen:
            continue
        seen[url] = None
        fresh.append(url)
    return fresh


def harvest_reel_cards(links, seen):
    """links is (href, caption). New cards plus later captions for already-listed reels."""
    fresh = []
    for href, caption in links:
        url = media_url_from_href(href)
        if not url:
            continue
        caption = _clean_caption(caption)
        if url in seen:
            if caption and not seen[url]:
                seen[url] = caption
                fresh.append({"url": url, "title": caption, "description": caption})
            continue
        seen[url] = caption
        fresh.append({"url": url, "title": caption, "description": caption})
    return fresh


def screen_work_area():
    """Desktop work area as ``(left, top, right, bottom)`` pixels."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            if rect.right > rect.left and rect.bottom > rect.top:
                return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    return (0, 0, 1600, 900)


def prefer_large_chrome_window(profile_dir, bounds):
    """Remember a full-size window so Chrome does not restore a small one."""
    path = os.path.join(profile_dir, "Default", "Preferences")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    left, top, right, bottom = bounds
    placement = {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
        "maximized": True,
        "work_area_left": int(left),
        "work_area_top": int(top),
        "work_area_right": int(right),
        "work_area_bottom": int(bottom),
    }
    browser = data.get("browser")
    if not isinstance(browser, dict):
        browser = {}
        data["browser"] = browser
    browser["window_placement"] = placement
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
    except OSError:
        return False
    return True


def present_browser_window(driver, bounds):
    """Put the scraper Chrome on the work area instead of a restored small window."""
    left, top, right, bottom = bounds
    width = max(int(right) - int(left), 1200)
    height = max(int(bottom) - int(top), 800)
    try:
        driver.set_window_rect(int(left), int(top), width, height)
    except Exception:
        pass
    try:
        driver.maximize_window()
    except Exception:
        pass


def dismiss_signup_dialog(driver):
    """Close Instagram or Facebook's login wall so the grid can be scrolled."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    xpaths = (
        "//*[@aria-label='Close']",
        "//*[@aria-label='close']",
        "//div[@role='dialog']//*[@aria-label='Close']",
    )
    for xpath in xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue
        for element in elements[:4]:
            try:
                element.click()
                return True
            except Exception:
                continue
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass
    try:
        clicked = driver.execute_script(
            """
            const close = document.querySelector(
              '[aria-label="Close"], [aria-label="close"]'
            );
            if (!close) return false;
            (close.closest('button, [role="button"]') || close).click();
            return true;
            """
        )
        return bool(clicked)
    except Exception:
        return False


def scrape_reel_urls(
    channel,
    url,
    *,
    log=print,
    wait_for_login=None,
    should_stop=None,
    output_root=None,
    chrome_binary="",
    on_urls=None,
):
    """Open the channel in Chrome, let the user log in, scroll, and save post URLs.

    `on_urls` is called with each newly found URL list so the Grabber table
    can fill while Chrome is still scrolling. Instagram harvests /p/, /reel/,
    and /tv/ links; Facebook still harvests /reel/.
    """
    output_root = output_root or default_output_root()
    from selenium import webdriver
    from selenium.webdriver.common.by import By

    options = webdriver.ChromeOptions()
    if chrome_binary:
        options.binary_location = chrome_binary
    # Persist the site login between runs so you only sign in once.
    profile_dir = os.path.abspath(chrome_profile_dir())
    os.makedirs(profile_dir, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--start-maximized")
    options.add_argument("--window-position=0,0")
    bounds = screen_work_area()
    prefer_large_chrome_window(profile_dir, bounds)

    driver = webdriver.Chrome(options=options)
    try:
        present_browser_window(driver, bounds)
        driver.get(url)
        present_browser_window(driver, bounds)
        sleep(1)
        present_browser_window(driver, bounds)
        sleep(2)
        check_stop(should_stop)

        # The Reels grid sits under a Sign up dialog. Close it and collect;
        # waiting here leaves the grabber stuck on that modal.
        dismiss_signup_dialog(driver)
        sleep(0.5)
        dismiss_signup_dialog(driver)

        site = "Instagram" if detect_platform(url) == "instagram" else "Facebook"
        if site == "Instagram":
            log("Closed the Instagram sign-up dialog and started collecting reels.")
        else:
            log(f"Log in to {site} in the opened Chrome window so you can see ALL posts.")
            log("When the page is ready, continue to start scrolling.")
            if wait_for_login:
                wait_for_login()
            else:
                input("Press Enter to start scrolling and collecting reels... ")
        check_stop(should_stop)

        # Scroll to the bottom repeatedly to lazy-load every reel.
        scroll_steps = 100
        scroll_interval = 4
        prev_scroll_position = -1
        seen = {}

        def _harvest():
            pairs = []
            for element in driver.find_elements(
                By.CSS_SELECTOR, "a[href*='/reel/'], a[href*='/p/'], a[href*='/tv/']"
            ):
                pairs.append((element.get_attribute("href"), caption_from_link(element)))
            fresh = harvest_reel_cards(pairs, seen)
            if fresh and on_urls:
                on_urls(fresh)
            return fresh

        _harvest()
        for step in range(scroll_steps):
            check_stop(should_stop)
            dismiss_signup_dialog(driver)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            sleep(scroll_interval)
            curr_scroll_position = driver.execute_script("return window.pageYOffset;")
            found_now = _harvest()
            if found_now:
                log(f"Found {len(seen)} post URL(s) so far.")
            if curr_scroll_position == prev_scroll_position:
                log("Reached the bottom of the page.")
                break
            prev_scroll_position = curr_scroll_position
            if step == 0 or (step + 1) % 5 == 0:
                log(f"Scrolling… step {step + 1}/{scroll_steps}")

        _harvest()
        found = list(seen)
    finally:
        driver.quit()

    if not found:
        if detect_platform(url) == "instagram":
            log("No posts found on that page. Check that the profile, Reels, or")
            log("Reposts tab is open and that you were logged in before continuing.")
        else:
            log("No reels found on that page. Check that the URL opens the Reels")
            log("tab of the channel and that you were logged in before continuing.")

    csv_path = collect_csv_path(channel)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        for href in found:
            writer.writerow([href])
    log(f"Collected {len(found)} post URL(s).")
    return csv_path
