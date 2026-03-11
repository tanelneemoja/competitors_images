import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def run_ar_id_full_log_scraper():
    # Setup Storage
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # THE TARGET ID FROM YOUR SNIPPET (Media House OÜ)
    TARGET_AR_ID = "AR17608295264152453121"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SECTION 1: SELVER ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            selver_ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(selver_ads)} Selver ads.")
        except: pass

        # --- SECTION 2: RIMI (FULL LOG MONITOR) ---
        print(f"\n--- [START] Processing Rimi (Targeting {TARGET_AR_ID}) ---")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="load")
        time.sleep(5)

        # Expand Grid
        expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
        if expand_btn.count() > 0:
            expand_btn.first.click()
            print("  [ACTION] Grid expanded.")
            time.sleep(4)

        seen_ids = set()
        rimi_count = 0
        last_height = 0
        no_growth_count = 0
        total_items_checked = 0
        
        print("  [ACTION] Starting Continuous Full-Log Monitor...")

        # Keep scrolling as long as new content appears
        while no_growth_count < 15:
            current_grid = page.locator("creative-preview").all()
            
            for item in current_grid:
                try:
                    # Target the link to find the Advertiser ID
                    href_el = item.locator("a").first
                    href = href_el.get_attribute("href")
                    
                    if not href: continue

                    # Identify the AR ID in this specific box
                    ar_match = re.search(r"advertiser/(AR\d+)", href)
                    current_ar = ar_match.group(1) if ar_match else "UNKNOWN"
                    
                    # EXTRACT CREATIVE ID
                    cr_match = re.search(r"creative/(CR\d+)", href)
                    cr_id = cr_match.group(1) if cr_match else "UNKNOWN"

                    # Log every single item found
                    if cr_id not in seen_ids:
                        print(f"  [CHECK] Item {total_items_checked}: Found ID [{current_ar}] | Creative: {cr_id}")
                        
                        # IF IT MATCHES OUR RIMI TARGET
                        if current_ar == TARGET_AR_ID:
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
                            print(f"    >>> [MATCH SUCCESS] Saved Rimi Ad #{rimi_count}")

                        seen_ids.add(cr_id)
                        total_items_checked += 1
                except:
                    continue

            # Scroll and wait for lazy-load
            page.evaluate("window.scrollBy(0, 1500)") 
            time.sleep(1.5) 
            
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                no_growth_count += 1
            else:
                no_growth_count = 0
                last_height = new_height

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Total Unique Items Processed: {total_items_checked}")
        print(f"Total Rimi Ads Captured: {rimi_count}")

if __name__ == "__main__":
    run_ar_id_full_log_scraper()
