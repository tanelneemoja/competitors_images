import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_advertiser_page():
    # The "Search" page where all ads are listed
    search_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days"
    base_url = "https://adstransparency.google.com"
    
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        print(f"Opening advertiser page: {search_url}")
        page.goto(search_url, wait_until="networkidle")
        time.sleep(10) # Let the grid of ads load

        # 1. FIND ALL CREATIVE LINKS
        # We look for all <a> tags that contain "/creative/CR"
        links = page.locator("a[href*='/creative/CR']").all()
        
        # Use a set to get unique URLs only
        unique_urls = set()
        for link in links:
            href = link.get_attribute("href")
            if href:
                full_url = base_url + href if href.startswith("/") else href
                unique_urls.add(full_url)

        print(f"Found {len(unique_urls)} unique ad URLs. Starting download...")

        # 2. LOOP THROUGH EACH AD PAGE
        for ad_url in unique_urls:
            cr_match = re.search(r"(CR\d+)", ad_url)
            if not cr_match: continue
            
            cr_id = cr_match.group(1)
            save_path = f"data/{cr_id}.png"
            
            print(f"Processing: {cr_id}")
            try:
                page.goto(ad_url, wait_until="networkidle")
                time.sleep(8)

                # Look for the specific container for this CR ID
                specific_ad_container = page.locator(f"a[href*='{cr_id}']")
                
                if specific_ad_container.count() > 0:
                    # Try to find the img inside the html-renderer
                    img_element = specific_ad_container.locator("html-renderer img").first
                    
                    if img_element.count() > 0:
                        src = img_element.get_attribute("src")
                        img_data = requests.get(src).content
                        with open(save_path, "wb") as f:
                            f.write(img_data)
                        print(f"Saved image for {cr_id}")
                    else:
                        # Fallback to high-res screenshot of the ad element
                        specific_ad_container.screenshot(path=save_path)
                        print(f"Captured screenshot for {cr_id}")
                else:
                    print(f"Skipping {cr_id}: Ad container not found on detail page.")

            except Exception as e:
                print(f"Error on {cr_id}: {e}")

        browser.close()

if __name__ == "__main__":
    scrape_advertiser_page()
