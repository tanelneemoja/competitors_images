import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_full_competitor_scraper():
    # 1. Setup Storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        # headless=True for GitHub Runners/Servers; change to False to watch it locally
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (STABLE) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
            page.wait_for_selector("creative-preview", timeout=10000)
            
            # Scroll to load ads
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(1)

            selver_ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(selver_ads)} Selver ads. Saving...")
            
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
                except: continue
        except Exception as e:
            print(f"  [ERROR] Selver section failed: {e}")

        # --- SECTION 2: RIMI (INNER_TEXT DIAGNOSTIC) ---
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
            time.sleep(3)

            # Click "See all ads" if it appears
            expand_btn = page.locator('button:has-text("See all ads"), material-button:has-text("See all ads")')
            if expand_btn.count() > 0:
                print("  [ACTION] Clicking 'See all ads'...")
                expand_btn.first.click()
                time.sleep(4)

            # Deep scroll to populate the grid (80 scrolls as requested)
            print("  [ACTION] Scrolling 80 times to load Media House / Rimi ads...")
            for i in range(80):
                page.evaluate("window.scrollBy(0, 1500)")
                if i % 20 == 0:
                    time.sleep(1)

            grid_items = page.locator("creative-preview").all()
            print(f"  [LOG] Scanning {len(grid_items)} grid items...")

            rimi_count = 0
            seen_ids = set()

            for item in grid_items:
                try:
                    # Looking for "Media House" anywhere in the item text
                    if "Media House" in item.inner_text():
                        href_el = item.locator("a").first
                        href = href_el.get_attribute("href")
                        cr_id = re.search(r"(CR\d+)", href).group(1)
                        
                        if cr_id in seen_ids: continue
                        seen_ids.add(cr_id)
                        
                        save_path = f"data/Rimi/{cr_id}.png"
                        
                        # Try to find the image tag for high quality
                        img_tag = item.locator("html-renderer img, fletch-renderer img").first
                        if img_tag.count() > 0:
                            img_url = img_tag.get_attribute("src")
                            if img_url and img_url.startswith("http"):
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_url).content)
                            else:
                                item.screenshot(path=save_path)
                        else:
                            # Screenshot bounding box fallback
                            item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                        
                        rimi_count += 1
                except:
                    continue
        except Exception as e:
            print(f"  [ERROR] Rimi section failed: {e}")

        browser.close()
        print(f"\n--- [COMPLETED] ---")
        print(f"Selver total: {len(selver_ads) if 'selver_ads' in locals() else 0}")
        print(f"Rimi total: {rimi_count}")

if __name__ == "__main__":
    run_full_competitor_scraper()
