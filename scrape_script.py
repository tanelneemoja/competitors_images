import os
import requests
import time
import re
import random
from playwright.sync_api import sync_playwright

def run_human_behavior_scraper():
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    TARGET_ID = "AR17608295264152453121"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        print(f"\n--- [START] Human-Behavior Scan for Rimi ---")
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
        stuck_count = 0
        
        print("  [ACTION] Using Mouse-Wheel simulation and erratic pumping...")

        while stuck_count < 25:
            # 1. Capture current view
            current_grid = page.locator("creative-preview").all()
            found_new_this_loop = False

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
                        found_new_this_loop = True
                        
                        if current_ar == TARGET_ID:
                            save_path = f"data/Rimi/{cr_id}.png"
                            img_tag = item.locator("img").first
                            if img_tag.count() > 0 and img_tag.get_attribute("src"):
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_tag.get_attribute("src")).content)
                            else:
                                item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                            rimi_count += 1
                            print(f"    [MATCH] Saved Rimi Ad #{rimi_count}")
                except: continue

            # 2. THE HUMAN SCROLL MOVE
            # Instead of one big jump, we do multiple small "mouse wheel" rolls
            for _ in range(5):
                page.mouse.wheel(0, 400)
                time.sleep(0.2)

            # 3. THE "UP-DOWN" RESET (The fix you found)
            current_height = page.evaluate("document.body.scrollHeight")
            if current_height == last_height:
                stuck_count += 1
                # Erratic retreat: Scroll up by a random amount to confuse the observer
                retreat_val = random.randint(800, 2000)
                print(f"  [STUCK] No height growth. Retreating {retreat_val}px and slamming down...")
                page.evaluate(f"window.scrollBy(0, -{retreat_val})")
                time.sleep(1)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight + 500)")
                time.sleep(3) # Long wait for network
            else:
                stuck_count = 0
                last_height = current_height
                print(f"  [PROGRESS] Scanned {len(seen_ids)} ads | Height: {current_height}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Unique Ads Scanned: {len(seen_ids)}")
        print(f"Total Rimi Ads Captured: {rimi_count}")

if __name__ == "__main__":
    run_human_behavior_scraper()
