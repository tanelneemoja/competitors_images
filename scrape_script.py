import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_exact_cr_id(url):
    # 1. Extract the CR ID from the URL
    cr_match = re.search(r"(CR\d+)", url)
    if not cr_match:
        print("No CR ID found in URL.")
        return
    cr_id = cr_match.group(1)
    
    os.makedirs('data', exist_ok=True)
    # This ensures the file is named after the CR ID, overwriting if it exists
    save_path = f"data/{cr_id}.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()
        
        print(f"Targeting: {cr_id}")
        page.goto(url, wait_until="networkidle")
        time.sleep(12) 

        # 2. Find the anchor tag matching the CR ID
        specific_ad_container = page.locator(f"a[href*='{cr_id}']")

        if specific_ad_container.count() > 0:
            # Target the internal image asset
            img_element = specific_ad_container.locator("html-renderer img").first
            
            if img_element.count() > 0:
                src = img_element.get_attribute("src")
                print(f"Found asset: {src}")
                img_data = requests.get(src).content
                with open(save_path, "wb") as f:
                    f.write(img_data)
                print(f"Successfully saved/overwrote {save_path}")
            else:
                # If no direct img, screenshot the specific ad block
                print("Image element missing. Screenshotting container.")
                specific_ad_container.screenshot(path=save_path)
        else:
            print(f"Failed to find container for {cr_id}")

        browser.close()

if __name__ == "__main__":
    test_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    scrape_exact_cr_id(test_url)
