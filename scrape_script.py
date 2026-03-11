import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_verbose_media_house_scraper():
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    MEDIA_HOUSE_URL = "https://adstransparency.google.com/advertiser/AR17608295264152453121?region=EE&preset-date=Last+30+days"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (UNTOUCHED) ---
        print("\n--- [START] Processing Selver ---")
        page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
        time.sleep(3)
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1)
        print(f"  [LOG] Found {len(page.locator('creative-preview').all())} Selver ads.")

        # --- SECTION 2: MEDIA HOUSE (DEEP SCAN) ---
        print(f"\n--- [START] Deep-Scanning Media House Grid ---")
        page.goto(MEDIA_HOUSE_URL, wait_until="load")
        time.sleep(5)

        # SCROLLING TO GET ALL 200+ ADS
        last_height = 0
        while True:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                # Try a "nudge" in case it's stuck
                page.evaluate("window.scrollBy(0, -500)")
                time.sleep(0.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
                if page.evaluate("document.body.scrollHeight") == new_height:
                    break
            last_height = new_height
            print(f"  [GRID] Current height: {last_height}...")

        ad_elements = page.locator("creative-preview").all()
        ad_links = []
        for el in ad_elements:
            try:
                href = el.locator("a").first.get_attribute("href")
                if href: ad_links.append("https://adstransparency.google.com" + href)
            except: continue

        print(f"  [INFO] Total ads found in grid: {len(ad_links)}")

        rimi_found = 0
        for i, ad_url in enumerate(ad_links):
            try:
                cr_match = re.search(r"creative/(CR\d+)", ad_url)
                cr_id = cr_match.group(1) if cr_match else f"UNK_{i}"

                page.goto(ad_url, wait_until="load")
                time.sleep(1.5)

                # VERBOSE LOGGING OF TOPIC
                topic_locator = page.locator(".subject-matter")
                if topic_locator.count() > 0:
                    topic_text = topic_locator.inner_text().replace("Topic (labelled by Google):", "").strip()
                else:
                    topic_text = "NO TOPIC FOUND"

                print(f"  [INSPECTING {i+1}/{len(ad_links)}] ID: {cr_id} | Topic: {topic_text}")

                # Check for "Food and Groceries" or "Food and Drinks" based on your observation
                if "Food" in topic_text or "Groceries" in topic_text:
                    print(f"    >>> [MATCH] Saving Rimi Ad: {cr_id}")
                    
                    img_element = page.locator("html-renderer img").first
                    if img_element.count() > 0:
                        img_src = img_element.get_attribute("src")
                        if img_src:
                            img_data = requests.get(img_src).content
                            with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                f.write(img_data)
                            rimi_found += 1
                            continue

                    # Screenshot as backup if <img> isn't found
                    page.locator(".creative-container").first.screenshot(path=f"data/Rimi/{cr_id}.png")
                    rimi_found += 1

            except Exception as e:
                print(f"  [ERROR] Problem with {cr_id}: {str(e)[:50]}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Rimi Ads Captured: {rimi_found}")

if __name__ == "__main__":
    run_verbose_media_house_scraper()
