import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_rimi_diagnostic(limit=10):
    # Setup storage
    if not os.path.exists('data/Rimi'): os.makedirs('data/Rimi', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        print("\n--- [START] Processing Rimi (10 Page Diagnostic) ---")
        # Start at the domain level
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
        
        # Load the grid
        page.wait_for_selector("creative-preview", timeout=10000)
        grid_ads = page.locator("creative-preview").all()
        
        # Limit to the first 10 ads found in the grid
        target_ads = grid_ads[:limit]
        print(f"  [LOG] Found {len(grid_ads)} ads in grid. Checking the first {len(target_ads)}...")

        processed = 0
        for i, ad in enumerate(target_ads):
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"

                # Open Ad Details
                ad_tab = context.new_page()
                ad_tab.goto(detail_url, wait_until="networkidle")

                # --- DIAGNOSTIC LOGGING ---
                # This finds the advertiser name in the breadcrumbs you provided
                breadcrumb_el = ad_tab.locator("breadcrumbs .advertiser-scope-button div[buttoncontent]")
                
                # If the breadcrumb selector fails, try the info card selector
                if breadcrumb_el.count() == 0:
                    breadcrumb_el = ad_tab.locator(".advertiser-info-card .advertiser-name")

                found_advertiser = breadcrumb_el.inner_text().strip() if breadcrumb_el.count() > 0 else "UNKNOWN"
                
                print(f"  [PAGE {i+1}/10] ID: {cr_id} | Advertiser: {found_advertiser}")

                # Verify against Media House
                if "Media House" in found_advertiser:
                    print(f"    [MATCH] Saving Rimi/Media House creative...")
                    
                    container = ad_tab.locator(".ad-container").first
                    save_path = f"data/Rimi/{cr_id}.png"
                    
                    # Try to get the <img> or fallback to screenshot
                    img_tag = container.locator("html-renderer img, fletch-renderer img").first
                    if img_tag.count() > 0:
                        src = img_tag.get_attribute("src")
                        if src.startswith("http"):
                            with open(save_path, "wb") as f:
                                f.write(requests.get(src).content)
                        else:
                            container.screenshot(path=save_path)
                    else:
                        container.screenshot(path=save_path)
                    
                    processed += 1
                else:
                    print(f"    [SKIP] Not Media House.")

                ad_tab.close()
            except Exception as e:
                print(f"    [ERROR] Could not process page: {e}")
                continue

        browser.close()
        print(f"\n--- [FINISHED] Diagnostic Complete. Total Rimi saved: {processed} ---")

if __name__ == "__main__":
    run_rimi_diagnostic(limit=10)
