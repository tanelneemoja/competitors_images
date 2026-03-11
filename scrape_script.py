import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_continuous_grid_scraper():
    # Setup Storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (STABLE) ---
        print("\n--- [START] Processing Selver ---")
        page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
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

        # --- SECTION 2: RIMI (CONTINUOUS MONITORING) ---
        print("\n--- [START] Processing Rimi ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        time.sleep(5)

        # Expand Grid
        expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
        if expand_btn.count() > 0:
            expand_btn.first.click()
            time.sleep(4)

        seen_ids = set()
        rimi_count = 0
        last_height = 0
        no_growth_count = 0
        
        print("  [ACTION] Starting Continuous Grid Monitor...")

        # We keep going until the page height stops increasing for a while
        while no_growth_count < 15:  # Increased tolerance for slow loading
            # 1. TIGHT SCAN: Check every single creative-preview currently in the DOM
            current_grid = page.locator("creative-preview").all()
            
            for item in current_grid:
                try:
                    # Get ID immediately to check if we've handled it
                    href_el = item.locator("a").first
                    href = href_el.get_attribute("href")
                    if not href: continue
                    cr_id = re.search(r"(CR\d+)", href).group(1)

                    if cr_id not in seen_ids:
                        # NEW ID FOUND: Now check if it's Media House/Rimi
                        raw_text = item.text_content() or ""
                        
                        if "Media House" in raw_text:
                            save_path = f"data/Rimi/{cr_id}.png"
                            # Try to get the image source
                            img_tag = item.locator("img").first
                            if img_tag.count() > 0 and img_tag.get_attribute("src"):
                                img_url = img_tag.get_attribute("src")
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_url).content)
                            else:
                                item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                            
                            rimi_count += 1
                            print(f"    [MATCH] #{rimi_count} | Found Rimi/Media House (ID: {cr_id})")
                        
                        # Mark as seen regardless of brand so we don't re-scan it
                        seen_ids.add(cr_id)
                except:
                    continue

            # 2. MICRO-SCROLL: Move just a little bit to trigger lazy loading without skipping
            page.evaluate("window.scrollBy(0, 800)") 
            time.sleep(0.5) # Quick pause for DOM update
            
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                no_growth_count += 1
            else:
                no_growth_count = 0
                last_height = new_height
                if len(seen_ids) % 100 == 0:
                    print(f"  [STATUS] Scanned {len(seen_ids)} unique ads in grid so far...")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Unique Ads Scanned: {len(seen_ids)}")
        print(f"Total Rimi Ads Captured: {rimi_count}")

if __name__ == "__main__":
    run_continuous_grid_scraper()
