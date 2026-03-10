import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_rimi_precision(limit=10):
    # --- 1. CLEAN SLATE ---
    if os.path.exists('data'):
        shutil.rmtree('data')
    os.makedirs('data/Selver', exist_ok=True)
    os.makedirs('data/Rimi', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # --- STEP 1: SELVER (UNCHANGED) ---
        selver_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days"
        print("\n--- Scraping Selver ---")
        try:
            page.goto(selver_url, wait_until="networkidle")
            time.sleep(5)
            ads = page.locator("creative-preview").all()
            for i, ad in enumerate(ads[:limit]):
                link = ad.locator("a[href*='/creative/CR']").first
                if link.count() > 0:
                    cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                    img = ad.locator("html-renderer img").first
                    if img.count() > 0:
                        data = requests.get(img.get_attribute("src")).content
                        with open(f"data/Selver/{cr_id}.png", "wb") as f: f.write(data)
                        print(f"  [SAVED] Selver: {cr_id}")
        except Exception as e: print(f" Selver Error: {e}")

        # --- STEP 2: RIMI (PRECISION ELEMENT CHECK) ---
        rimi_url = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"
        print("\n--- Scraping Rimi (Precision Mode) ---")
        try:
            page.goto(rimi_url, wait_until="networkidle")
            page.wait_for_selector("creative-preview", timeout=30000)
            
            # Important: Agency pages need extra time to load the 'Media House' label
            time.sleep(12) 

            ads = page.locator("creative-preview").all()
            processed = 0
            
            for ad in ads:
                if processed >= limit: break

                # Target the exact class from your snippet: .advertiser-name
                name_element = ad.locator(".advertiser-name")
                
                if name_element.count() > 0:
                    advertiser_text = name_element.inner_text()
                    
                    if "Media House OÜ" in advertiser_text:
                        # Extract CR ID from the href in your snippet
                        link = ad.locator("a[href*='/creative/CR']").first
                        if link.count() == 0: continue
                        
                        cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                        img = ad.locator("html-renderer img").first
                        
                        save_path = f"data/Rimi/{cr_id}.png"
                        
                        if img.count() > 0:
                            src = img.get_attribute("src")
                            img_data = requests.get(src).content
                            with open(save_path, "wb") as f: f.write(img_data)
                            print(f"  [FOUND] Rimi via Media House: {cr_id}")
                            processed += 1
                        else:
                            ad.screenshot(path=save_path)
                            print(f"  [SCREENSHOT] Rimi: {cr_id}")
                            processed += 1
                
        except Exception as e: print(f" Rimi Error: {e}")

        browser.close()

if __name__ == "__main__":
    scrape_rimi_precision(limit=10)
