import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_full_competitor_scraper():
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER ---
        print("\n--- [START] Processing Selver ---")
        page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
        time.sleep(2)
        page.evaluate("window.scrollBy(0, 5000)")
        selver_ads = page.locator("creative-preview").all()
        for ad in selver_ads:
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                img = ad.locator("img").first
                if img.count() > 0:
                    src = img.get_attribute("src")
                    with open(f"data/Selver/{cr_id}.png", "wb") as f:
                        f.write(requests.get(src).content)
            except: continue

        # --- SECTION 2: RIMI (SMART SCROLL) ---
        print("\n--- [START] Processing Rimi ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        time.sleep(5)

        # 1. Expand Grid
        expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
        if expand_btn.count() > 0:
            expand_btn.first.click()
            print("  [ACTION] Grid expanded.")
            time.sleep(4)

        # 2. SMART SCROLL: Keep going until height stops changing
        print("  [ACTION] Scrolling until ~1000 items are loaded...")
        last_height = page.evaluate("document.body.scrollHeight")
        scroll_attempts = 0
        max_attempts = 100 # Safety cap

        while scroll_attempts < max_attempts:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2.5) # Vital for "silent" lazy loading
            
            new_height = page.evaluate("document.body.scrollHeight")
            current_count = page.locator("creative-preview").count()
            
            if scroll_attempts % 10 == 0:
                print(f"    -> Height: {new_height} | Current Ads in DOM: {current_count}")
            
            # If height didn't change, try one more aggressive scroll before stopping
            if new_height == last_height:
                page.evaluate("window.scrollBy(0, -500)") # Scroll up slightly
                time.sleep(0.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)
                if page.evaluate("document.body.scrollHeight") == last_height:
                    print("  [INFO] Reached end of grid or content limit.")
                    break
            
            last_height = new_height
            scroll_attempts += 1

        # 3. Process Items
        grid_items = page.locator("creative-preview").all()
        print(f"  [LOG] Scanning {len(grid_items)} total grid items...")

        rimi_count = 0
        seen_ids = set()

        for idx, item in enumerate(grid_items):
            try:
                raw_text = item.text_content() or ""
                if "Media House" in raw_text:
                    href = item.locator("a").first.get_attribute("href")
                    cr_id = re.search(r"(CR\d+)", href).group(1)
                    
                    if cr_id not in seen_ids:
                        seen_ids.add(cr_id)
                        save_path = f"data/Rimi/{cr_id}.png"
                        
                        img_tag = item.locator("img").first
                        if img_tag.count() > 0 and img_tag.get_attribute("src"):
                            img_url = img_tag.get_attribute("src")
                            with open(save_path, "wb") as f:
                                f.write(requests.get(img_url).content)
                        else:
                            item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                        
                        rimi_count += 1
                elif idx % 200 == 0:
                    print(f"  [STATUS] Index {idx} | Found: {raw_text[:20].strip()}...")
            except: continue

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Selver Ads: {len(selver_ads)}")
        print(f"Total Rimi Ads: {rimi_count}")

if __name__ == "__main__":
    run_full_competitor_scraper()
