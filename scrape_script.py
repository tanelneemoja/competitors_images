import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_grid_name_scraper(limit=15):
    if not os.path.exists('data/Rimi'): os.makedirs('data/Rimi', exist_ok=True)
    if not os.path.exists('data/Selver'): os.makedirs('data/Selver', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (STABLE) ---
        print("\n--- [START] Processing Selver ---")
        page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
        selver_ads = page.locator("creative-preview").all()
        for ad in selver_ads[:10]:
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                print(f"  [SAVED] Selver: {cr_id}")
            except: continue

        # --- SECTION 2: RIMI (GRID-BASED NAME SEARCH) ---
        print("\n--- [START] Processing Rimi ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        
        # 1. Expand the grid
        print("  [ACTION] Expanding grid...")
        try:
            expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if expand_btn.count() > 0:
                expand_btn.first.click()
                time.sleep(3)
        except: pass

        # 2. Heavy Scroll to force 'advertiser-name' to render
        print("  [ACTION] Scrolling 80 times to load names...")
        for i in range(80):
            page.evaluate("window.scrollBy(0, 1000)")
            if i % 20 == 0:
                time.sleep(1) # Breathe every 20 scrolls

        # 3. Scan the grid for Media House OÜ specifically
        # We use a broader selector because the 'ymd-37' part changes
        grid_items = page.locator("creative-preview").all()
        print(f"  [LOG] Scanning {len(grid_items)} grid items for 'Media House OÜ'...")

        processed = 0
        for i, item in enumerate(grid_items):
            if processed >= limit: break
            
            try:
                # Check the text of the advertiser name div inside this specific grid item
                # We look for the div containing the text directly
                name_div = item.locator(".advertiser-name")
                name_text = name_div.inner_text().strip() if name_div.count() > 0 else "HIDDEN"

                if "Media House" in name_text:
                    print(f"  [MATCH] Found Media House at index {i}!")
                    
                    href = item.locator("a").first.get_attribute("href")
                    cr_id = re.search(r"(CR\d+)", href).group(1)
                    
                    # Capture the preview directly from the grid to save time/resources
                    # Since we are already looking at it
                    save_path = f"data/Rimi/{cr_id}.png"
                    item.screenshot(path=save_path)
                    print(f"    -> Saved grid preview for {cr_id}")
                    
                    processed += 1
                elif i < 10: # Only log the first 10 for "the fuck" diagnostic
                    print(f"  [DEBUG] Item {i} name: [{name_text}]")
                    
            except Exception as e:
                continue

        browser.close()
        print(f"\n--- [FINISHED] Total Rimi saved: {processed} ---")

if __name__ == "__main__":
    run_grid_name_scraper()
