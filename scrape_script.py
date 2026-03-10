import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_with_flexible_logs(limit=10):
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

        # --- STEP 1: SELVER (STAYS WORKING) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days", wait_until="networkidle")
            page.wait_for_selector("creative-preview", timeout=15000)
            ads = page.locator("creative-preview").all()
            for ad in ads[:limit]:
                link = ad.locator("a[href*='/creative/CR']").first
                if link.count() > 0:
                    cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                    img = ad.locator("html-renderer img").first
                    if img.count() > 0:
                        data = requests.get(img.get_attribute("src")).content
                        with open(f"data/Selver/{cr_id}.png", "wb") as f: f.write(data)
                        print(f"  [SAVED] Selver: {cr_id}")
        except Exception as e: print(f"  [ERROR] Selver: {e}")

        # --- STEP 2: RIMI (FLEXIBLE WAIT) ---
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            
            # Wait for the advertiser-name tag to exist at all, rather than specific text
            print("  [LOG] Waiting for grid to populate...")
            page.wait_for_selector(".advertiser-name", timeout=30000)
            
            # Allow a massive hydration buffer for agency metadata
            time.sleep(15) 
            
            ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(ads)} total cards. Scanning for Media House...")
            
            processed = 0
            for i, ad in enumerate(ads):
                if processed >= limit: break

                # Get all text from the card to avoid selector misses
                all_text = ad.inner_text()
                
                # Use a case-insensitive check for "Media House"
                if "media house" in all_text.lower():
                    link = ad.locator("a[href*='/creative/CR']").first
                    if link.count() == 0: continue
                    
                    cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                    img = ad.locator("html-renderer img").first
                    save_path = f"data/Rimi/{cr_id}.png"
                    
                    if img.count() > 0:
                        src = img.get_attribute("src")
                        img_data = requests.get(src).content
                        with open(save_path, "wb") as f: f.write(img_data)
                        print(f"  [MATCH] Card {i+1}: Saved {cr_id}")
                        processed += 1
                    else:
                        ad.screenshot(path=save_path)
                        print(f"  [SCREENSHOT] Card {i+1}: Saved {cr_id}")
                        processed += 1
                else:
                    # Log what it actually found so we can debug the "0 found"
                    # We take the first 30 chars of the card text
                    preview_text = all_text.replace('\n', ' ')[:30]
                    print(f"  [SKIP] Card {i+1}: Content: '{preview_text}...'")

        except Exception as e:
            print(f"  [ERROR] Rimi: {e}")

        browser.close()

if __name__ == "__main__":
    scrape_with_flexible_logs(limit=10)
