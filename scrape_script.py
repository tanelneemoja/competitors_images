import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_hybrid(targets, limit=10):
    # --- 1. CLEAN SLATE ---
    if os.path.exists('data'):
        shutil.rmtree('data')
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for brand_name, info in targets.items():
            brand_folder = f"data/{brand_name}"
            os.makedirs(brand_folder, exist_ok=True)
            
            search_url = f"https://adstransparency.google.com/advertiser/{info['id']}?region=EE&preset-date=Last+30+days"
            print(f"\n--- Processing {brand_name} ---")
            
            try:
                # Use the networkidle wait that worked for Selver
                page.goto(search_url, wait_until="networkidle", timeout=90000)
                
                # For Agency pages (Rimi), we need an extra pause for the "rimi.ee" text to hydrate
                if info.get('is_agency'):
                    print("  Agency account detected. Waiting for brand labels...")
                    time.sleep(15) 
                else:
                    time.sleep(5)

                ads = page.locator("creative-preview").all()
                processed = 0

                for ad in ads:
                    if processed >= limit: break

                    # Check if the brand keyword is visible anywhere in the card
                    # (This catches the "rimi.ee" in the header from your screenshot)
                    if info['keyword'].lower() in ad.inner_text().lower():
                        
                        link_el = ad.locator("a[href*='/creative/CR']").first
                        if link_el.count() == 0: continue
                        cr_id = re.search(r"(CR\d+)", link_el.get_attribute("href")).group(1)
                        
                        # Target the img inside the html-renderer from your snippet
                        img_el = ad.locator("html-renderer img").first
                        
                        if img_el.count() > 0:
                            src = img_el.get_attribute("src")
                            img_data = requests.get(src).content
                            with open(f"{brand_folder}/{cr_id}.png", "wb") as f:
                                f.write(img_data)
                            processed += 1
                            print(f"  [SAVED] {brand_name}: {cr_id}.png")
                        else:
                            # Fallback if image isn't directly scrapable
                            ad.screenshot(path=f"{brand_folder}/{cr_id}.png")
                            processed += 1
                            print(f"  [SCREENSHOT] {brand_name}: {cr_id}.png")

            except Exception as e:
                print(f"  [ERROR] {brand_name}: {e}")

        browser.close()

if __name__ == "__main__":
    competitors = {
        "Selver": {
            "id": "AR08638735883022893057", 
            "keyword": "selver", 
            "is_agency": False
        },
        "Rimi": {
            "id": "AR17608295264152453121", 
            "keyword": "rimi.ee", 
            "is_agency": True
        }
    }
    scrape_hybrid(competitors, limit=10)
