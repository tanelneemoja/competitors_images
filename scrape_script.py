import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_diagnostic_scraper(limit=80):
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

        # --- SECTION 2: RIMI (DIAGNOSTIC MODE) ---
        print("\n--- [START] Processing Rimi ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        
        # Aggressive Expansion
        page.wait_for_timeout(3000)
        expand_btn = page.locator('button:has-text("See all ads"), material-button:has-text("See all ads")')
        
        if expand_btn.count() > 0:
            print(f"  [ACTION] Found 'See all ads' button. Clicking...")
            expand_btn.first.click()
            page.wait_for_timeout(4000)
        else:
            print("  [DEBUG] Could not find 'See all ads' button. Check if grid is already full.")

        page.evaluate("window.scrollBy(0, 2000)")
        page.wait_for_timeout(2000)

        grid_ads = page.locator("creative-preview").all()
        print(f"  [LOG] Found {len(grid_ads)} ads in grid.")

        processed = 0
        for i, ad in enumerate(grid_ads[:limit]):
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"

                ad_tab = context.new_page()
                ad_tab.goto(detail_url, wait_until="domcontentloaded")
                ad_tab.wait_for_timeout(3000) # Give it time to render the text

                # --- THE "WHAT THE FUCK" LOGGING ---
                # 1. Try to find the breadcrumb text specifically
                breadcrumb = "NOT_FOUND"
                breadcrumb_locator = ad_tab.locator("breadcrumbs")
                if breadcrumb_locator.count() > 0:
                    breadcrumb = breadcrumb_locator.inner_text().replace('\n', ' ').strip()
                
                # 2. Check for keywords in the whole page as a backup
                full_text = ad_tab.locator("body").inner_text()
                has_media = "Media House" in full_text
                has_rimi = "Rimi" in full_text

                print(f"  [AD {i+1}] ID: {cr_id}")
                print(f"    -> Breadcrumb found: [{breadcrumb}]")
                print(f"    -> Keywords: MediaHouse={has_media}, Rimi={has_rimi}")

                if has_media or has_rimi:
                    print(f"    [MATCH] Saving...")
                    container = ad_tab.locator(".ad-container").first
                    container.screenshot(path=f"data/Rimi/{cr_id}.png")
                    processed += 1
                else:
                    print(f"    [SKIP] Failed verification.")

                ad_tab.close()
            except Exception as e:
                print(f"    [ERROR] On AD {i+1}: {e}")
                if 'ad_tab' in locals(): ad_tab.close()
                continue

        browser.close()
        print(f"\n--- [FINISHED] Total Rimi saved: {processed} ---")

if __name__ == "__main__":
    run_diagnostic_scraper()
