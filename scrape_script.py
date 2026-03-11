import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_rimi_pumping_scraper():
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    TARGET_ID = "AR17608295264152453121"
    BLACKLIST = ["AR07548724757265383425", "AR17541344781366460417", "AR17615777268980776961"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        print(f"\n--- [START] Pumping Scroll Scan for Rimi ({TARGET_ID}) ---")
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
        
        print("  [ACTION] Monitoring grid with Pumping Scroll logic (Up/Down slams)...")

        while no_growth_count < 40:
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
                            # If we see a new ID that isn't blacklisted, let's log it just in case
                            print(f"  [INFO] Other Advertiser: {current_ar} (Item {total_items_checked})")

                except: continue

            # --- THE PUMPING MANEUVER ---
            # 1. Retreat up to clear the intersection observer sensor
            page.evaluate("window.scrollBy(0, -1200)")
            time.sleep(0.7)
            # 2. Slam back down to the very bottom + extra 200px
            page.evaluate("window.scrollTo(0, document.body.scrollHeight + 200)")
            print(f"  [DEBUG] Pumping bottom (Current Scan: {total_items_checked} items)")
            time.sleep(2.5) # Heavy wait for the network to respond

            new_height = page.evaluate("document.body.scrollHeight")
            
            if new_height == last_height:
                no_growth_count += 1
            else:
                no_growth_count = 0
                last_height = new_height
                if total_items_checked % 100 == 0:
                    print(f"  [STATUS] Total unique ads seen: {total_items_checked}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Unique Ads Scanned: {total_items_checked}")
        print(f"Total Rimi Ads Captured: {rimi_count}")

if __name__ == "__main__":
    run_rimi_pumping_scraper()
