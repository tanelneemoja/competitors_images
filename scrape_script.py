import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_filtered_ads():
    search_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days"
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 3000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"Loading Advertiser Page...")
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector(".ads-count", timeout=30000)
            time.sleep(8) # Wait for JS to hide the non-filtered ads

            # Extract the number from "6 ads"
            count_text = page.locator(".ads-count").inner_text()
            match = re.search(r"(\d+)", count_text)
            max_ads = int(match.group(1)) if match else 6
            print(f"Targeting exactly {max_ads} ads based on UI count.")

            # Focus only on the 'priority' grid which usually holds the filtered results
            ads = page.locator("priority-creative-grid creative-preview").all()
            
            count = 0
            for ad in ads:
                if count >= max_ads:
                    break # Stop once we reach the limit
                
                link_element = ad.locator("a[href*='/creative/CR']").first
                href = link_element.get_attribute("href") if link_element.count() > 0 else None
                
                if not href: continue
                cr_id = re.search(r"(CR\d+)", href).group(1)
                
                img_element = ad.locator("html-renderer img").first
                if img_element.count() > 0:
                    img_src = img_element.get_attribute("src")
                    img_data = requests.get(img_src).content
                    with open(f"data/{cr_id}.png", "wb") as f:
                        f.write(img_data)
                    print(f"Saved ({count+1}/{max_ads}): {cr_id}")
                    count += 1

        except Exception as e:
            print(f"Error: {e}")
        
        browser.close()

if __name__ == "__main__":
    scrape_filtered_ads()
