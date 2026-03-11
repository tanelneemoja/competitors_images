import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_ar_id_scraper():
    # Setup Storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # THE TARGET ID YOU FOUND
    TARGET_AR_ID = "AR17608295264152453121"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER ---
        print("\n--- [START] Processing Selver ---")
        page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        selver_ads = page.locator("creative-preview").all()
        for ad in selver_ads:
            try:
                href = ad.locator("a").first.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                img = ad.locator("img").first
                if img.count() > 0:
                    src = img.get_attribute("src")
                    with open(f"data/Selver/{cr_id}.png", "wb") as f:
                        f.write(requests.get(src).content)
            except: continue

        # --- SECTION 2: RIMI (ADVERTISER ID MATCHING) ---
        print(f"\n--- [START] Processing Rimi (Targeting {TARGET_AR_ID}) ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        time.sleep(5)

        # Expand Grid
        expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
        if expand_btn.count() > 0:
            expand_btn.first.click()
            time.sleep(4)

        seen_ids = set()
        rimi_count = 0
        last_height = 0
        no_growth_count = 0
        
        print("  [ACTION] Starting AR-ID Grid Monitor...")

        # Keep going until we hit the end of the ~800-1000 ads
        while no_growth_count < 10:
            current_grid = page.locator("creative-preview").all()
            
            for item in current_grid:
                try:
                    href_el = item.locator("a").first
                    href = href_el.get_attribute("href")
                    if not href: continue

                    # Check if THIS ad belongs to the target AR ID
                    if TARGET_AR_ID in href:
                        cr_id_match = re.search(r"(CR\d+)", href)
                        if not cr_id_match: continue
                        cr_id = cr_id_match.group(1)

                        if cr_id not in seen_ids:
                            seen_ids.add(cr_id)
                            save_path = f"data/Rimi/{cr_id}.png"
                            
                            # Capture
                            img_tag = item.locator("img").first
                            if img_tag.count() > 0 and img_tag.get_attribute("src"):
                                img_url = img_tag.get_attribute("src")
                                with open(save_path, "wb") as f:
                                    f.write(requests.get(img_url).content)
                            else:
                                item.locator(".creative-bounding-box").first.screenshot(path=save_path)
                            
                            rimi_count += 1
                            print(f"    [MATCH] #{rimi_count} | Found via AR ID (ID: {cr_id})")
                except:
                    continue

            # Micro-scroll to trigger lazy loading
            page.evaluate("window.scrollBy(0, 1000)") 
            time.sleep(0.8) 
            
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                no_growth_count += 1
            else:
                no_growth_count = 0
                last_height = new_height

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Rimi Ads Captured via AR ID: {rimi_count}")

if __name__ == "__main__":
    run_ar_id_scraper()
