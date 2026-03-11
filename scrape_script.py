import os
import requests
import time
from playwright.sync_api import sync_playwright

def run_rimi_robust_scraper():
    if not os.path.exists('data/Rimi'): os.makedirs('data/Rimi', exist_ok=True)

    TARGET_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"\n--- [START] Deep-Scan: Rimi (Media House OÜ) ---")
        page.goto(TARGET_URL, wait_until="networkidle")
        time.sleep(5)

        # --- THE FIX: CLICK "SEE ALL ADS" ---
        try:
            # Look for the button with "See all ads" text
            see_all_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if see_all_btn.count() > 0:
                print("[ACTION] Clicking 'See all ads' button...")
                see_all_btn.click()
                time.sleep(4)
            else:
                # Fallback: try clicking by class if role fails
                page.locator(".search-improvements-see-more-button").click()
                print("[ACTION] Clicked 'See more' via class fallback.")
                time.sleep(4)
        except Exception as e:
            print(f"[NOTE] Could not click 'See all' button (maybe already expanded?): {e}")

        seen_ids = set()
        
        for i in range(40):
            # Refresh list of cards after scroll
            cards = page.locator("creative-preview").all()
            
            for card in cards:
                try:
                    # Robust Name Check
                    adv_element = card.locator(".advertiser-name")
                    if adv_element.count() == 0: continue
                    
                    adv_name = adv_element.inner_text().strip()
                    
                    # Log every 20th name just to prove the scraper is "seeing" content
                    if len(seen_ids) % 20 == 0 and i % 5 == 0:
                        print(f"  [DEBUG] Eyeing ad by: {adv_name}")

                    if "Media House" in adv_name:
                        link = card.locator("a[href*='creative/']").first
                        href = link.get_attribute("href")
                        cr_id = href.split("creative/")[-1].split("?")[0]

                        if cr_id not in seen_ids:
                            img_element = card.locator("img").first
                            if img_element.count() > 0:
                                img_src = img_element.get_attribute("src")
                                if img_src and "http" in img_src:
                                    img_data = requests.get(img_src, timeout=10).content
                                    with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                        f.write(img_data)
                                    seen_ids.add(cr_id)

                except: continue

            # Scroll and Wait
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2) 
            
            if i % 5 == 0:
                print(f"--- [PROGRESS] Scroll {i} | Found: {len(seen_ids)} Media House Ads ---")

        browser.close()
        print(f"\n--- [FINISHED] Captured {len(seen_ids)} Rimi ads. ---")

import re # Added missing import
if __name__ == "__main__":
    run_rimi_robust_scraper()
