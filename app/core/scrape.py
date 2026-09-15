"""Collect reel/post URLs from a Facebook or Instagram page with Selenium."""
import csv
import os
import re
from time import sleep
from urllib.parse import urlparse

from app.core.jobs import check_stop
from app.core.runtime import chrome_profile_dir, collect_csv_path, default_output_root
from app.core.urls import INSTAGRAM_SINGLE_KINDS, detect_platform

_CAPTION_NOISE = {"reel", "reels", "video", "facebook", "watch", "play reel", "open reel"}
_CAPTION_PREFIXES = ("reel by ", "reels by ", "video by ", "reel: ", "reels: ")


def _clean_caption(text):
    """Keep a Facebook reel caption; drop empty chrome labels."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text or text.lower() in _CAPTION_NOISE:
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

    driver = webdriver.Chrome(options=options)
    try:
        driver.maximize_window()
        driver.get(url)
        sleep(3)
        check_stop(should_stop)

        # Close the login pop-up if it shows, so the page is usable. Don't crash if
        # the button isn't there (Facebook changes this markup often).
        try:
            driver.find_element(By.XPATH, "//div[@aria-label='Close']").click()
        except Exception:
            pass

        site = "Instagram" if detect_platform(url) == "instagram" else "Facebook"
        # Feeds hide most posts from logged-out users. Pause here for a manual login.
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
