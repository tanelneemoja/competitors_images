import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_targeted_rimi_scraper():
    # Setup Storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # Rimi / Media House Target
    MEDIA_HOUSE_URL = "https://adstransparency.google.com/advertiser/AR17608295264152453121?region=EE&preset-date=Last+30+days"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (UNTOUCHED) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
            time.sleep(3)
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
            selver_ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(selver_ads)} Selver ads.")
        except Exception as e:
            print(f"  [ERROR] Selver failed: {e}")

        # --- SECTION 2: RIMI / MEDIA HOUSE (TOPIC FILTERING) ---
        print(f"\n--- [START] Processing Media House for Rimi Topics ---")
        page.goto(MEDIA_HOUSE_URL, wait_until="load")
        time.sleep(5)

        # Get all individual ad links from the grid
        ad_elements = page.locator("creative-preview").all()
        ad_links = []
        for el in ad_elements:
            try:
                href = el.locator("a").first.get_attribute("href")
                if href: ad_links.append("https://adstransparency.google.com" + href)
            except: continue

        print(f"  [INFO] Found {len(ad_links)} total ads to inspect for Media House.")

        rimi_found = 0
        for ad_url in ad_links:
            try:
                # Extract CR ID for naming
                cr_match = re.search(r"creative/(CR\d+)", ad_url)
                cr_id = cr_match.group(1) if cr_match else "UNKNOWN"

                # Navigate to the specific ad detail page
                page.goto(ad_url, wait_until="load")
                time.sleep(2)

                # CHECK TOPIC: "Food and Groceries"
                # Based on your HTML: <div class="property subject-matter">
                topic_locator = page.locator(".subject-matter")
                topic_text = topic_locator.inner_text() if topic_locator.count() > 0 else ""

                if "Food and Groceries" in topic_text:
                    print(f"  [MATCH] Found Rimi Ad ({cr_id}) - Topic: {topic_text}")
                    
                    # Target the specific image inside html-renderer
                    img_element = page.locator("html-renderer img").first
                    img_src = img_element.get_attribute("src")

                    if img_src:
                        save_path = f"data/Rimi/{cr_id}.png"
                        img_data = requests.get(img_src).content
                        with open(save_path, "wb") as f:
                            f.write(img_data)
                        rimi_found += 1
                    else:
                        # Fallback to screenshot of the creative container if direct img fails
                        page.locator(".creative-container").first.screenshot(path=f"data/Rimi/{cr_id}.png")
                        rimi_found += 1
                else:
                    # It's Media House, but maybe a different client (Henkel, etc.)
                    pass

            except Exception as e:
                print(f"  [SKIP] Error inspecting {ad_url}: {e}")
                continue

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Media House Ads inspected: {len(ad_links)}")
        print(f"Total Rimi (Food & Groceries) ads captured: {rimi_found}")

if __name__ == "__main__":
    run_targeted_rimi_scraper()
