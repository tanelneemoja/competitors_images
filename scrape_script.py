import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_ads_from_grid():
    search_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days"
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # We increase the timeout and use a realistic user agent
        context = browser.new_context(
            viewport={'width': 1920, 'height': 2000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"Loading Advertiser Grid...")
        try:
            # Set a longer timeout (60s) to prevent the error you saw
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            
            # Wait for the grid specifically rather than 'networkidle'
            page.wait_for_selector("creative-preview", timeout=30000)
            time.sleep(5) # Final settle time

            # 1. Find all ad preview cards
            ads = page.locator("creative-preview").all()
            print(f"Detected {len(ads)} ads in the grid.")

            for ad in ads:
                # 2. Get the CR ID from the link
                link_element = ad.locator("a[href*='/creative/CR']").first
                href = link_element.get_attribute("href") if link_element.count() > 0 else None
                
                if not href: continue
                
                cr_match = re.search(r"(CR\d+)", href)
                if not cr_match: continue
                cr_id = cr_match.group(1)
                
                # 3. Get the image inside this specific ad card
                img_element = ad.locator("html-renderer img").first
                if img_element.count() > 0:
                    img_src = img_element.get_attribute("src")
                    
                    print(f"Found {cr_id} -> Downloading: {img_src}")
                    img_data = requests.get(img_src).content
                    with open(f"data/{cr_id}.png", "wb") as f:
                        f.write(img_data)
                else:
                    print(f"Image not found for {cr_id}, taking card screenshot.")
                    ad.screenshot(path=f"data/{cr_id}.png")

        except Exception as e:
            print(f"Scraper encountered an issue: {e}")
            page.screenshot(path="data/error_debug.png")
        
        browser.close()

if __name__ == "__main__":
    scrape_ads_from_grid()
