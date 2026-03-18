import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_competitor_ads():
    # URL for the specific competitor
    search_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days"
    
    # --- 1. CLEAN SLATE ---
    # Wipe the local data folder so old ads from previous runs are GONE
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

        try:
            print(f"Loading Advertiser Page...")
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(".ads-count", timeout=30000)
            
            # --- 2. GET TARGET COUNT ---
            count_text = page.locator(".ads-count").inner_text()
            max_ads = int(re.search(r"(\d+)", count_text).group(1))
            print(f"Targeting {max_ads} ads. Starting scroll...")

            # --- 3. INFINITE SCROLL ---
            # This handles the '60 vs 120' ads problem
            last_count = 0
            for _ in range(15): # Try scrolling up to 15 times
                page.keyboard.press("End")
                time.sleep(4) # Wait for Google to load more
                current_count = page.locator("creative-preview").count()
                print(f"Discovered {current_count}/{max_ads} ads...")
                if current_count >= max_ads or current_count == last_count:
                    break
                last_count = current_count

            # --- 4. SCRAPE ALL ---
            ads = page.locator("creative-preview").all()
            for i, ad in enumerate(ads):
                if i >= max_ads: break # Stop at the official UI count
                
                link_element = ad.locator("a[href*='/creative/CR']").first
                if link_element.count() == 0: continue
                
                cr_id = re.search(r"(CR\d+)", link_element.get_attribute("href")).group(1)
                img_element = ad.locator("html-renderer img").first
                
                if img_element.count() > 0:
                    src = img_element.get_attribute("src")
                    img_data = requests.get(src).content
                    with open(f"data/{cr_id}.png", "wb") as f:
                        f.write(img_data)
                    print(f"Saved ({i+1}/{max_ads}): {cr_id}")

        except Exception as e:
            print(f"Scraper Error: {e}")
        
        browser.close()

if __name__ == "__main__":
    scrape_competitor_ads()
