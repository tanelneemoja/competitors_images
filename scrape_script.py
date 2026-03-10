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
        browser = p.chromium.launch(headless=False) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
            time.sleep(2)
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(0.5)

            selver_ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(selver_ads)} Selver ads.")
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
            print(f"  [ERROR] Selver failed: {e}")

        # --- SECTION 2: RIMI (DEEP DIAGNOSTIC) ---
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
            time.sleep(4)

            expand_btn = page.locator('button:has-text("See all ads"), material-button:has-text("See all ads")')
            if expand_btn.count() > 0:
                print("  [ACTION] Clicking 'See all ads'...")
                expand_btn.first.click()
                time.sleep(5)

            print("  [ACTION] Scrolling 80 times...")
            for i in range(80):
                page.evaluate("window.scrollBy(0, 1500)")
                if i % 20 == 0: time.sleep(1)

            grid_items = page.locator("creative-preview").all()
            print(f"  [LOG] Scanning {len(grid_items)} grid items...")

            rimi_count = 0
            seen_ids = set()

            for idx, item in enumerate(grid_items):
                try:
                    # DIAGNOSTIC: Get text via multiple methods to catch hidden text
                    text_content = item.text_content() or ""
                    inner_text = item.inner_text() or ""
                    
                    # Log the first 10 items regardless, then only every 50th or matches
                    if idx < 10 or "Media House" in text_content or "Media House" in inner_text:
                        clean_text = inner_text.replace('\n', ' ').strip()[:50]
                        print(f"  [ITEM {idx}] Detected Text: [{clean_text}...]")

                    if "Media House" in text_content or "Media House" in inner_text:
                        href = item.locator("a").first.get_attribute("href")
                        cr_id = re.search(r"(CR\d+)", href).group(1)
                        
                        if cr_id not in seen_ids:
                            seen_ids.add(cr_id)
                            save_path = f"data/Rimi/{cr_id}.png"
                            
                            # Use the img src we saw in your HTML snippet
                            img_tag = item.locator("img").first
                            if img_tag.count() > 0 and img_tag.get_attribute("src"):
                                img_url = img_tag.get_attribute("src")
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_url).content)
                                print(f"    -> [MATCH] Saved via Image URL: {cr_id}")
                            else:
                                item.screenshot(path=save_path)
                                print(f"    -> [MATCH] Saved via Screenshot: {cr_id}")
                            
                            rimi_count += 1
                except Exception as e:
                    continue
        except Exception as e:
            print(f"  [ERROR] Rimi failed: {e}")

        browser.close()
        print(f"\n--- [COMPLETED] ---")
        print(f"Selver total: {len(selver_ads) if 'selver_ads' in locals() else 0}")
        print(f"Rimi total: {rimi_count}")

if __name__ == "__main__":
    run_full_competitor_scraper()
