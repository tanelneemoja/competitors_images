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

        print(f"Loading Advertiser Page with Filter...")
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            
            # THE FIX: Wait for the 'ads-count' element to show the filtered number
            # This forces the bot to wait until the "6 ads" text is rendered.
            page.wait_for_selector(".ads-count", timeout=30000)
            time.sleep(5) # Extra buffer for the grid to refresh

            # Double check the count in logs
            count_text = page.locator(".ads-count").inner_text()
            print(f"UI confirms: {count_text}")

            # 1. Target only the ads currently visible in the grid
            ads = page.locator("creative-preview").all()
            
            # Safety check: if we wanted 6 but got 40, the filter failed.
            if "6" in count_text and len(ads) > 10:
                print("Filter mismatch detected. Re-filtering results...")
                # We can refine the selection by only taking ads within the priority grid
                ads = page.locator("priority-creative-grid creative-preview").all()

            print(f"Scraping {len(ads)} ads...")

            for ad in ads:
                # Get CR ID
                link_element = ad.locator("a[href*='/creative/CR']").first
                href = link_element.get_attribute("href") if link_element.count() > 0 else None
                
                if not href: continue
                cr_id = re.search(r"(CR\d+)", href).group(1)
                
                # Get Image
                img_element = ad.locator("html-renderer img").first
                if img_element.count() > 0:
                    img_src = img_element.get_attribute("src")
                    img_data = requests.get(img_src).content
                    with open(f"data/{cr_id}.png", "wb") as f:
                        f.write(img_data)
                    print(f"Saved: {cr_id}")

        except Exception as e:
            print(f"Error: {e}")
        
        browser.close()

if __name__ == "__main__":
    scrape_filtered_ads()
