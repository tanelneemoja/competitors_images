import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_test_batch(targets, limit=10):
    # --- 1. GLOBAL RESET ---
    if os.path.exists('data'):
        shutil.rmtree('data')
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for brand_name, advertiser_id in targets.items():
            brand_folder = f"data/{brand_name}"
            os.makedirs(brand_folder, exist_ok=True)
            
            search_url = f"https://adstransparency.google.com/advertiser/{advertiser_id}?region=EE&preset-date=Last+30+days"
            print(f"\n--- Testing {brand_name} (Limit: {limit} ads) ---")
            
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(".ads-count", timeout=30000)
                
                # Small scroll to get the first batch
                page.keyboard.press("End")
                time.sleep(5)

                ads = page.locator("creative-preview").all()
                processed = 0

                for ad in ads:
                    # Check if we hit our test limit
                    if processed >= limit:
                        print(f"Reached test limit of {limit} for {brand_name}. Stopping.")
                        break

                    ad_content = ad.inner_text().lower()
                    
                    # Keyword Filter
                    if brand_name.lower() in ad_content:
                        link_element = ad.locator("a[href*='/creative/CR']").first
                        if link_element.count() == 0: continue
                        
                        cr_id = re.search(r"(CR\d+)", link_element.get_attribute("href")).group(1)
                        img_element = ad.locator("html-renderer img").first
                        
                        if img_element.count() > 0:
                            src = img_element.get_attribute("src")
                            img_data = requests.get(src).content
                            with open(f"{brand_folder}/{cr_id}.png", "wb") as f:
                                f.write(img_data)
                            processed += 1
                            print(f"  [SAVED {processed}/{limit}] {brand_name}: {cr_id}.png")

            except Exception as e:
                print(f"  [ERROR] {brand_name} failed: {e}")

        browser.close()

if __name__ == "__main__":
    competitors = {
        "Selver": "AR08638735883022893057",
        "Rimi": "AR17608295264152453121" 
    }
