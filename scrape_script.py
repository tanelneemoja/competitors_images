import os
import requests
import time
import re
import random
from playwright.sync_api import sync_playwright

def run_final_integrated_scraper():
    # Setup Storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    TARGET_AR_ID = "AR17608295264152453121"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER (Restored) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
            time.sleep(3)
            # Scroll a few times for Selver
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1)
            selver_ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(selver_ads)} Selver ads.")
            # Note: Add capture logic here if you want to save Selver images specifically
        except Exception as e:
            print(f"  [ERROR] Selver failed: {e}")

        # --- SECTION 2: RIMI (Anchor-Based Pumping) ---
        print(f"\n--- [START] Processing Rimi (Targeting {TARGET_AR_ID}) ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        time.sleep(5)

        try:
            expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if expand_btn.count() > 0:
                expand_btn.first.click()
                time.sleep(4)
        except: pass

        seen_ids = set()
        rimi_count = 0
        stuck_count = 0
        
        print("  [ACTION] Using Anchor-Element Scrolling (targeting last ad in DOM)...")

        while stuck_count < 30:
            current_ads = page.locator("creative-preview").all()
            found_new_in_loop = False

            for item in current_ads:
                try:
                    href = item.locator("a").first.get_attribute("href")
                    if not href: continue

                    ar_match = re.search(r"advertiser/(AR\d+)", href)
                    current_ar = ar_match.group(1) if ar_match else "UNKNOWN"
                    cr_match = re.search(r"creative/(CR\d+)", href)
                    cr_id = cr_match.group(1) if cr_match else "UNKNOWN"

                    if cr_id not in seen_ids:
                        seen_ids.add(cr_id)
                        found_new_in_loop = True
                        
                        if current_ar == TARGET_AR_ID:
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

            if found_new_in_loop:
                stuck_count = 0
                # --- THE ANCHOR MOVE ---
                # Find the last element currently in the DOM and scroll it into view
                if len(current_ads) > 0:
                    last_ad = current_ads[-1]
                    last_ad.scroll_into_view_if_needed()
                    print(f"  [PROGRESS] Scanned {len(seen_ids)} ads. Anchored to last item.")
                
                # Small mouse wheel nudge to simulate activity
                page.mouse.wheel(0, 500)
                time.sleep(1.5)
            else:
                stuck_count += 1
                # --- THE RESET PUMP ---
                # Move up significantly to "un-trigger" the observer
                retreat = random.randint(1500, 3000)
                page.evaluate(f"window.scrollBy(0, -{retreat})")
                time.sleep(1)
                # Slam back to the bottom ad
                if len(current_ads) > 0:
                    current_ads[-1].scroll_into_view_if_needed()
                print(f"  [STUCK {stuck_count}/30] Resetting viewport...")
                time.sleep(3)

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Unique Ads Scanned: {len(seen_ids)}")
        print(f"Total Rimi Ads Captured: {rimi_count}")

if __name__ == "__main__":
    run_final_integrated_scraper()
