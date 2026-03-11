import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_rimi_overscroll_scraper():
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # TARGET: Media House OÜ / Rimi
    TARGET_ID = "AR17608295264152453121"
    # NOISE: Henkel and others to ignore in logs
    BLACKLIST = ["AR07548724757265383425", "AR17541344781366460417", "AR17615777268980776961"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        print(f"\n--- [START] Overscroll Scan for Rimi ({TARGET_ID}) ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        time.sleep(5)

        try:
            expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if expand_btn.count() > 0:
                expand_btn.first.click()
                time.sleep(5)
        except: pass

        seen_ids = set()
        rimi_count = 0
        last_height = 0
        no_growth_count = 0
        total_items_checked = 0
        
        print("  [ACTION] Monitoring grid with Over-Scroll logic...")

        while no_growth_count < 60:
            current_grid = page.locator("creative-preview").all()
            
            for item in current_grid:
                try:
                    href = item.locator("a").first.get_attribute("href")
                    if not href: continue

                    ar_match = re.search(r"advertiser/(AR\d+)", href)
                    current_ar = ar_match.group(1) if ar_match else "UNKNOWN"
                    
                    cr_match = re.search(r"creative/(CR\d+)", href)
                    cr_id = cr_match.group(1) if cr_match else "UNKNOWN"

                    if cr_id not in seen_ids:
                        seen_ids.add(cr_id)
                        total_items_checked += 1

                        if current_ar == TARGET_ID:
                            save_path = f"data/Rimi/{cr_id}.png"
                            img_tag = item.locator("img").first
                            if img_tag.count() > 0 and img_tag.get_attribute("src"):
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_tag.get_attribute("src")).content)
                            else:
                                item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                            
                            rimi_count += 1
                            print(f"  [MATCH] Found Rimi Ad #{rimi_count} (ID: {cr_id})")
                        
                        elif current_ar not in BLACKLIST:
                            print(f"  [INFO] New Advertiser Found: {current_ar} at Item {total_items_checked}")

                except: continue

            # --- THE OVER-SCROLL MANEUVER ---
            # 1. Scroll to the current absolute bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.5)
            # 2. Perform the "Extra Scroll" to trigger the UI's new ad fetch
            page.evaluate("window.scrollBy(0, 500)") 
            time.sleep(2.0) # Give Google time to respond to the overscroll

            new_height = page.evaluate("document.body.scrollHeight")
            
            if new_height == last_height:
                no_growth_count += 1
                # If still stuck after 5 tries, do a "jiggle" reset
                if no_growth_count % 5 == 0:
                    page.evaluate("window.scrollBy(0, -1000)")
                    time.sleep(0.5)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                no_growth_count = 0
                last_height = new_height
                if total_items_checked % 100 == 0:
                    print(f"  [STATUS] Total scanned: {total_items_checked} | Current Height: {new_height}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Unique Ads Scanned: {total_items_checked}")
        print(f"Total Rimi Ads Captured: {rimi_count}")

if __name__ == "__main__":
    run_rimi_overscroll_scraper()
