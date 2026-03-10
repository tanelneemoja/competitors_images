import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_stable_scraper(limit=15):
    # Setup storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (UNTOUCHED) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
            page.wait_for_selector("creative-preview", timeout=10000)
            selver_ads = page.locator("creative-preview").all()
            for ad in selver_ads[:limit]:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                img = ad.locator("img").first
                if img.count() > 0:
                    src = img.get_attribute("src")
                    with open(f"data/Selver/{cr_id}.png", "wb") as f:
                        f.write(requests.get(src).content)
                    print(f"  [SAVED] Selver: {cr_id}")
        except Exception as e:
            print(f"  [SKIP] Selver error: {e}")

        # --- SECTION 2: RIMI (FIXED EXPANSION & VERIFICATION) ---
        print("\n--- [START] Processing Rimi ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="domcontentloaded")
        
        # 1. Click "See all ads" using the text-based selector (most stable)
        try:
            # We look for the button containing "See all ads" specifically
            expand_btn = page.get_by_role("button", name="See all ads")
            if expand_btn.is_visible():
                print("  [ACTION] Clicking 'See all ads'...")
                expand_btn.click()
                time.sleep(4) # Slightly longer wait to let the grid populate
        except:
            print("  [INFO] 'See all ads' button not found.")

        # 2. Scrolling
        print("  [ACTION] Scrolling to populate grid...")
        for _ in range(6):
            page.evaluate("window.scrollBy(0, 2000)")
            time.sleep(0.5)

        grid_ads = page.locator("creative-preview").all()
        print(f"  [LOG] Found {len(grid_ads)} ads in total grid. Scanning...")

        processed = 0
        for ad in grid_ads:
            if processed >= limit: break
            
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"

                ad_tab = context.new_page()
                ad_tab.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
                
                # VERIFICATION: Using the 'buttoncontent' attribute from your snippet
                # This is much more precise than a general breadcrumb search
                advertiser_el = ad_tab.locator('div[buttoncontent]')
                
                # Check for "Media House" in any element with that attribute
                is_media_house = False
                for el in advertiser_el.all():
                    if "Media House" in el.inner_text():
                        is_media_house = True
                        break
                
                if is_media_house:
                    print(f"  [MATCH] ID: {cr_id} | Saving...")
                    
                    container = ad_tab.locator(".ad-container").first
                    save_path = f"data/Rimi/{cr_id}.png"
                    
                    img_tag = container.locator("html-renderer img, fletch-renderer img").first
                    if img_tag.count() > 0:
                        src = img_tag.get_attribute("src")
                        if src and src.startswith("http"):
                            with open(save_path, "wb") as f:
                                f.write(requests.get(src).content)
                        else:
                            container.screenshot(path=save_path)
                    else:
                        container.screenshot(path=save_path)
                    
                    # Handle Variations (1 of 2)
                    next_btn = ad_tab.locator(".variation-right-arrow:not([disabled])")
                    if next_btn.count() > 0:
                        next_btn.click()
                        time.sleep(0.8)
                        container.screenshot(path=f"data/Rimi/{cr_id}_var2.png")
                    
                    processed += 1
                
                ad_tab.close()
            except:
                if 'ad_tab' in locals(): ad_tab.close()
                continue

        browser.close()
        print(f"\n--- [FINISHED] Processed {processed} Rimi ads. ---")

if __name__ == "__main__":
    run_stable_scraper(limit=15)
