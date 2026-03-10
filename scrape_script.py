import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_full_verified_scraper(limit=15):
    # Setup storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (Restored & Working) ---
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
            print(f"  [ERROR] Selver section failed: {e}")

        # --- SECTION 2: RIMI (Restored Expansion + Deep Check) ---
        print("\n--- [START] Processing Rimi ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="domcontentloaded")
        
        # 1. THE "SEE MORE ADS" EXPANSION
        try:
            # Wait for the button to appear
            expand_btn = page.locator("material-button.grid-expansion-button")
            if expand_btn.is_visible():
                print("  [ACTION] Clicking 'See all ads' to expand grid...")
                expand_btn.click()
                time.sleep(3) # Wait for expansion
        except:
            print("  [INFO] Expansion button not found or already expanded.")

        # 2. SCROLLING TO LOAD HIDDEN ADS
        print("  [ACTION] Scrolling to populate grid...")
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 2000)")
            time.sleep(1)

        grid_ads = page.locator("creative-preview").all()
        print(f"  [LOG] Found {len(grid_ads)} ads in total grid.")

        processed = 0
        # We check the first 50 ads in the grid to find your 'limit' of Media House ads
        for i, ad in enumerate(grid_ads[:50]):
            if processed >= limit: break
            
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"

                # Open Ad Details with a faster wait strategy to avoid timeouts
                ad_tab = context.new_page()
                ad_tab.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
                
                # Wait for the breadcrumb or info card specifically
                ad_tab.wait_for_selector("breadcrumbs, .advertiser-name", timeout=5000)

                # DIAGNOSTIC LOGGING
                breadcrumb = ad_tab.locator("breadcrumbs").inner_text()
                
                if "Media House" in breadcrumb:
                    print(f"  [MATCH {processed+1}] ID: {cr_id} | Advertiser: Media House OÜ")
                    
                    container = ad_tab.locator(".ad-container").first
                    img_tag = container.locator("html-renderer img, fletch-renderer img").first
                    save_path = f"data/Rimi/{cr_id}.png"
                    
                    if img_tag.count() > 0:
                        src = img_tag.get_attribute("src")
                        if src and src.startswith("http"):
                            with open(save_path, "wb") as f:
                                f.write(requests.get(src).content)
                            print(f"    -> Image Saved.")
                        else:
                            container.screenshot(path=save_path)
                            print(f"    -> Screenshot (Blob).")
                    else:
                        container.screenshot(path=save_path)
                        print(f"    -> Screenshot (No tag).")
                    
                    processed += 1
                else:
                    # Optional: uncomment to see why it's skipping
                    # print(f"  [SKIP] ID: {cr_id} | Advertiser: Other")
                    pass

                ad_tab.close()
            except Exception as e:
                if 'ad_tab' in locals(): ad_tab.close()
                continue

        browser.close()
        print(f"\n--- [FINISHED] Check folders. Total Rimi saved: {processed} ---")

if __name__ == "__main__":
    run_full_verified_scraper(limit=10)
