import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_mapped_ad(url):
    # 1. Extract the CR ID from the URL to use as our filename/ID
    cr_match = re.search(r"(CR\d+)", url)
    if not cr_match:
        print("Error: No Creative ID (CR...) found in URL.")
        return
    cr_id = cr_match.group(1)
    
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a large viewport so the 'Skyscraper' or 'Wide' versions load correctly
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        print(f"Syncing with Ad ID: {cr_id}")
        page.goto(url, wait_until="networkidle")
        time.sleep(10) # Wait for the 'html-renderer' to populate

        # 2. Look specifically for the image link you found in the HTML
        # We target the img tag inside the html-renderer
        img_element = page.locator("html-renderer img[src*='2mdn.net'], html-renderer img[src*='googleusercontent']").first
        
        found_src = None
        if img_element.count() > 0:
            found_src = img_element.get_attribute("src")
        
        if found_src:
            print(f"Match found! Downloading asset: {found_src}")
            img_data = requests.get(found_src).content
            with open(f"data/{cr_id}.png", "wb") as f:
                f.write(img_data)
            print(f"Successfully mapped {cr_id} to its visual asset.")
        else:
            # Fallback: If the image is protected/hidden, take a clip of the ad area
            print(f"Could not find direct link for {cr_id}, taking element screenshot...")
            ad_container = page.locator("creative-preview").first
            if ad_container:
                ad_container.screenshot(path=f"data/{cr_id}.png")
            else:
                page.screenshot(path=f"data/debug_{cr_id}.png")

        browser.close()

if __name__ == "__main__":
    # This URL contains the CR ID we want to map
    target = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    scrape_mapped_ad(target)
