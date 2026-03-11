import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_dual_store_clean_scraper():
    # Setup folders
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # Configuration
    SELVER_URL = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE"
    RIMI_DOMAIN_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- 1. PROCESS SELVER (Direct & Fast) ---
        print("\n--- [START] Processing Selver (Direct ID) ---")
        page.goto(SELVER_URL, wait_until="networkidle")
        time.sleep(4)
        
        selver_ids = set()
        for s in range(12):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            cards = page.locator("creative-preview").all()
            for card in cards:
                try:
                    href = card.locator("a").first.get_attribute("href")
                    cr_id = href.split("creative/")[-1].split("?")[0]
                    if cr_id not in selver_ids:
                        img = card.locator("img").first.get_attribute("src")
                        if img and "http" in img:
                            with open(f"data/Selver/{cr_id}.png", "wb") as f:
                                f.write(requests.get(img).content)
                            selver_ids.add(cr_id)
                except: continue
            if s % 3 == 0: print(f"  [SELVER] Found {len(selver_ids)} ads...")
        print(f"--- [FINISHED] Selver Total: {len(selver_ids)} ---")

        # --- 2. PROCESS RIMI (The Cleanup Method) ---
        print("\n--- [START] Processing Rimi (Media House OÜ Only) ---")
        page.goto(RIMI_DOMAIN_URL, wait_until="networkidle")
        time.sleep(5)

        try:
            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0: 
                btn.click()
                print("[ACTION] Expanded Rimi Grid.")
                time.sleep(3)
        except: pass

        rimi_ids = set()
        total_elements_cleared = 0

        # High loop count because we are deleting elements as we go
        for i in range(150): 
            current_cards = page.locator("creative-preview").all()
            
            if not current_cards:
                # If the screen is empty, scroll to trigger a fetch
                page.evaluate("window.scrollBy(0, 800)")
                time.sleep(2)
                if i > 20: break # Exit if nothing loads for a while
                continue

            for card in current_cards:
                try:
                    # 1. Check for Media House
                    adv_element = card.locator(".advertiser-name")
                    if adv_element.count() > 0:
                        adv_name = adv_element.inner_text()
                        
                        if "Media House" in adv_name:
                            href = card.locator("a[href*='creative/']").first.get_attribute("href")
                            cr_id = href.split("creative/")[-1].split("?")[0]
                            
                            if cr_id not in rimi_ids:
                                img_src = card.locator("img").first.get_attribute("src")
                                if img_src and "http" in img_src:
                                    with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                        f.write(requests.get(img_src).content)
                                    rimi_ids.add(cr_id)

                    # 2. DELETE the element from the page 
                    # This prevents the "again and again" loop by removing the ad 
                    # regardless of whether it was Media House or Henkel.
                    page.evaluate("(el) => el.remove()", card.element_handle())
                    total_elements_cleared += 1

                except: continue

            # Nudge the scroll to keep the internal JS active
            page.evaluate("window.scrollBy(0, 300)")
            
            if i % 10 == 0:
                print(f"--- [RIMI PROGRESS] Loop {i} | Cleared: {total_elements_cleared} | Saved Media House: {len(rimi_ids)} ---")

        browser.close()
        print(f"\n--- [FINAL REPORT] ---")
        print(f"Selver: {len(selver_ids)} ads saved.")
        print(f"Rimi: {len(rimi_ids)} ads saved.")

if __name__ == "__main__":
    run_dual_store_clean_scraper()
