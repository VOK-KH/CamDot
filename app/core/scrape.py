"""Collect reel URLs from a Facebook channel page with Selenium."""
import csv
import os
from time import sleep

from app.core.jobs import check_stop
from app.core.runtime import default_output_root


def ordered_reel_urls(hrefs):
    """Unique reel URLs in page order, so the first reel found is downloaded first."""
    found = {}
    for href in hrefs:
        if href and "/reel/" in href:
            found.setdefault(href.split("/?s=")[0], None)
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
    """Open the channel in Chrome, let the user log in, scroll, and save reel URLs.

    `on_urls` is called with each newly found reel URL list so the Grabber table
    can fill while Chrome is still scrolling.
    """
    output_root = output_root or default_output_root()
    from selenium import webdriver
    from selenium.webdriver.common.by import By

    options = webdriver.ChromeOptions()
    if chrome_binary:
        options.binary_location = chrome_binary
    # Persist the Facebook login between runs so you only sign in once.
    profile_dir = os.path.abspath(os.path.join(output_root, ".chrome-profile"))
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

        # Facebook hides most reels from logged-out users, which is why previously the
        # script only saw the first page. Pause here for a manual login.
        log("Log in to Facebook in the opened Chrome window so you can see ALL reels.")
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
            fresh = harvest_new_reel_urls(
                (
                    element.get_attribute("href")
                    for element in driver.find_elements(By.CSS_SELECTOR, "a")
                ),
                seen,
            )
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
                log(f"Found {len(seen)} reel URL(s) so far.")
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
        log("No reels found on that page. Check that the URL opens the Reels")
        log("tab of the channel and that you were logged in before continuing.")

    os.makedirs(output_root, exist_ok=True)
    csv_path = os.path.join(output_root, f"{channel}.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        for href in found:
            writer.writerow([href])
    log(f"Collected {len(found)} reel URL(s).")
    return csv_path
