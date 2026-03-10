import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_unlimited_scraper():
    # Setup storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (UNLIMITED) ---
        print("\n--- [START] Processing Selver (Full Scan) ---")
        page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
        
        # Scroll to the bottom of Selver's portfolio
        print("  [ACTION] Scrolling to load all Selver ads...")
        last_height = page.evaluate("document.body.scrollHeight")
        while True:
            page.evaluate("window.scrollBy(0, 2000)")
            time.sleep(1)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height: break
            last_height = new_height

        selver_ads = page.locator("creative-preview").all()
        print(f"  [LOG] Found {len(selver_ads)} total Selver ads. Saving...")
        
        for ad in selver_ads:
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                img = ad.locator("img").first
                if img.count() > 0:
                    src = img.get_attribute("src")
                    if src and src.startswith("http"):
                        with open(f"data/Selver/{cr_id}.png", "wb") as f:
                            f.write(requests.get(src).content)
                # print(f"  [SAVED] Selver: {cr_id}") # Optional: uncomment if you want to see every ID
            except: continue

        # --- SECTION 2: RIMI (UNLIMITED GRID SCAN) ---
        print("\n--- [START] Processing Rimi (Full Scan) ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        
        # Expand the grid if button exists
        try:
            expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if expand_btn.count() > 0:
                expand_btn.first.click()
                time.sleep(3)
        except: pass

        # Deep scroll for Rimi (80 scrolls as requested to ensure lazy load)
        print("  [ACTION] Scrolling 80 times to load all Media House / Rimi ads...")
        for i in range(80):
            page.evaluate("window.scrollBy(0, 1500)")
            if i % 20 == 0: time.sleep(1)

        grid_items = page.locator("creative-preview").all()
        print(f"  [LOG] Scanning {len(grid_items)} grid items for Media House...")

        rimi_count = 0
        seen_ids = set()

        for item in grid_items:
            try:
                # Get Advertiser Name from the grid div we identified
                name_div = item.locator(".advertiser-name")
                name_text = name_div.inner_text().strip() if name_div.count() > 0 else ""

                if "Media House" in name_text:
                    href = item.locator("a").first.get_attribute("href")
                    cr_id = re.search(r"(CR\d+)", href).group(1)
                    
                    if cr_id in seen_ids: continue
                    seen_ids.add(cr_id)
                    
                    save_path = f"data/Rimi/{cr_id}.png"
                    
                    # Try to get the direct image first for better quality
                    img_tag = item.locator("html-renderer img, fletch-renderer img").first
                    if img_tag.count() > 0:
                        img_url = img_tag.get_attribute("src")
                        if img_url and img_url.startswith("http"):
                            with open(save_path, "wb") as f:
                                f.write(requests.get(img_url).content)
                        else:
                            item.screenshot(path=save_path)
                    else:
                        item.screenshot(path=save_path)
                    
                    rimi_count += 1
            except:
                continue

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Selver Ads Saved: {len(selver_ads)}")
        print(f"Total Rimi/Media House Ads Found: {rimi_count}")

if __name__ == "__main__":
    run_unlimited_scraper()
