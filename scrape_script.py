import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_dual_store_scraper():
    # Setup folders
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # Configuration
    SELVER_URL = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE"
    RIMI_DOMAIN_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- 1. PROCESS SELVER ---
        print("\n--- [START] Processing Selver ---")
        page.goto(SELVER_URL, wait_until="networkidle")
        time.sleep(3)
        
        selver_ids = set()
        for _ in range(8): # Scroll Selver
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            ads = page.locator("creative-preview").all()
            for ad in ads:
                try:
                    href = ad.locator("a").first.get_attribute("href")
                    cr_id = href.split("creative/")[-1].split("?")[0]
                    if cr_id not in selver_ids:
                        img = ad.locator("img").first.get_attribute("src")
                        if img:
                            with open(f"data/Selver/{cr_id}.png", "wb") as f:
                                f.write(requests.get(img).content)
                            selver_ids.add(cr_id)
                except: continue
        print(f"  [LOG] Selver Finished. Captured: {len(selver_ids)}")

        # --- 2. PROCESS RIMI (via Domain Search) ---
        print("\n--- [START] Processing Rimi (Media House OÜ Only) ---")
        page.goto(RIMI_DOMAIN_URL, wait_until="networkidle")
        time.sleep(5)

        # Expand if possible
        try:
            page.get_by_role("button", name="See all ads").first.click()
            time.sleep(3)
        except: pass

        rimi_ids = set()
        # Deep scroll for the 778 total ads
        for i in range(40): 
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            cards = page.locator("creative-preview").all()
            for card in cards:
                try:
                    # Filter specifically for Media House to avoid Henkel Latvia
                    adv_name = card.locator(".advertiser-name").inner_text()
                    if "Media House" not in adv_name:
                        continue

                    href = card.locator("a").first.get_attribute("href")
                    cr_id = href.split("creative/")[-1].split("?")[0]

                    if cr_id not in rimi_ids:
                        img_src = card.locator("img").first.get_attribute("src")
                        if img_src and "google" in img_src:
                            with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                f.write(requests.get(img_src).content)
                            rimi_ids.add(cr_id)
                except: continue

            if i % 5 == 0:
                print(f"  [SCROLL {i}] Unique Rimi Ads found so far: {len(rimi_ids)}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Final Count - Selver: {len(selver_ids)} | Rimi: {len(rimi_ids)}")

if __name__ == "__main__":
    run_dual_store_scraper()
