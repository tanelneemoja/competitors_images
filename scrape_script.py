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
        # headless=True is required for GitHub/Server environments
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER ---
        print("\n--- [START] Processing Selver ---")
        try:
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
                        if src and src.startswith("http"):
                            with open(f"data/Selver/{cr_id}.png", "wb") as f:
                                f.write(requests.get(src).content)
                except: continue
        except Exception as e:
            print(f"  [ERROR] Selver failed: {e}")

        # --- SECTION 2: RIMI (THE SILENT DEEP SCROLLER) ---
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
            time.sleep(5)

            # Force click "See all ads" if visible
            expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if expand_btn.count() > 0:
                print("  [ACTION] Expanding grid...")
                expand_btn.first.click()
                time.sleep(4)

            # THE STEAMROLLER SCROLLER: 150 increments of 1800px
            print("  [ACTION] Scrolling deep into the grid (150 steps)...")
            for i in range(150):
                page.evaluate("window.scrollBy(0, 1800)")
                # Minimal pause to let silent lazy-loading trigger
                if i % 5 == 0:
                    time.sleep(0.4)
                if i % 30 == 0:
                    print(f"    -> Progress: {i}/150 scrolls completed")
            
            # Final rest to ensure the last 800+ items are rendered
            time.sleep(5)

            grid_items = page.locator("creative-preview").all()
            total_items = len(grid_items)
            print(f"  [LOG] Scanning {total_items} total grid items...")

            rimi_count = 0
            seen_ids = set()

            for idx, item in enumerate(grid_items):
                try:
                    # Use text_content() to pierce through potential shadow layers
                    raw_text = item.text_content() or ""
                    
                    if "Media House" in raw_text:
                        href = item.locator("a").first.get_attribute("href")
                        cr_id_match = re.search(r"(CR\d+)", href)
                        if not cr_id_match: continue
                        cr_id = cr_id_match.group(1)
                        
                        if cr_id not in seen_ids:
                            seen_ids.add(cr_id)
                            save_path = f"data/Rimi/{cr_id}.png"
                            
                            # Capture logic
                            img_tag = item.locator("img").first
                            if img_tag.count() > 0 and img_tag.get_attribute("src"):
                                img_url = img_tag.get_attribute("src")
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_url).content)
                            else:
                                # If no img tag, take a clean screenshot of the ad box
                                item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                            
                            rimi_count += 1
                            if rimi_count % 10 == 0:
                                print(f"  [MATCH] Saved {rimi_count} Rimi ads...")
                                
                    # Diagnostic status every 250 items
                    elif idx % 250 == 0:
                        brand_preview = raw_text[:20].strip().replace('\n', ' ')
                        print(f"  [STATUS] Index {idx}/{total_items} | Brand: {brand_preview}...")

                except Exception:
                    continue
        except Exception as e:
            print(f"  [ERROR] Rimi failed: {e}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Selver Ads: {len(selver_ads) if 'selver_ads' in locals() else 0}")
        print(f"Total Rimi Ads: {rimi_count}")

if __name__ == "__main__":
    run_full_competitor_scraper()
