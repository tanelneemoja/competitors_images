import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_and_overwrite(url):
    # Extract CR ID just for logging/finding the right <a> tag
    cr_match = re.search(r"(CR\d+)", url)
    if not cr_match:
        print("No CR ID found in URL.")
        return
    cr_id = cr_match.group(1)
    
    os.makedirs('data', exist_ok=True)
    # OVERWRITE MODE: Always saving to the same filename for testing
    save_path = "data/test_ad.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()
        
        print(f"Testing Anchor-Link for: {cr_id}")
        page.goto(url, wait_until="networkidle")
        time.sleep(12) 

        # Find the specific <a> tag that contains this CR ID
        specific_ad_container = page.locator(f"a[href*='{cr_id}']")

        if specific_ad_container.count() > 0:
            # Look for the 300x600 image inside THAT specific container
            img_element = specific_ad_container.locator("html-renderer img").first
            
            if img_element.count() > 0:
                src = img_element.get_attribute("src")
                print(f"Found asset: {src}")
                img_data = requests.get(src).content
                with open(save_path, "wb") as f:
                    f.write(img_data)
                print(f"Success! {save_path} has been updated.")
            else:
                print("Container found, but image missing. Taking screenshot of container.")
                specific_ad_container.screenshot(path=save_path)
        else:
            print(f"Failed to find container for {cr_id}")

        browser.close()

if __name__ == "__main__":
    test_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    scrape_and_overwrite(test_url)
