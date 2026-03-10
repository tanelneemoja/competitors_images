import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_ads(url_list):
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using a large viewport ensures responsive ads render correctly
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        for url in url_list:
            # Extract CR ID from the current URL
            cr_match = re.search(r"(CR\d+)", url)
            if not cr_match:
                print(f"Skipping: No CR ID found in {url}")
                continue
            
            cr_id = cr_match.group(1)
            save_path = f"data/{cr_id}.png"
            
            print(f"--- Processing {cr_id} ---")
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(10) # Give the ad-renderer time to load assets

                # Use the anchor logic: Find the <a> tag for THIS specific CR ID
                specific_ad_container = page.locator(f"a[href*='{cr_id}']")

                if specific_ad_container.count() > 0:
                    # Look for the image asset inside this specific container
                    img_element = specific_ad_container.locator("html-renderer img").first
                    
                    if img_element.count() > 0:
                        src = img_element.get_attribute("src")
                        print(f"Downloading high-res: {src}")
                        img_data = requests.get(src).content
                        with open(save_path, "wb") as f:
                            f.write(img_data)
                    else:
                        # Fallback to screenshot if the raw image link is hidden
                        print("Taking container screenshot as fallback.")
                        specific_ad_container.screenshot(path=save_path)
                else:
                    print(f"Could not find container for {cr_id}")
            
            except Exception as e:
                print(f"Error scraping {cr_id}: {e}")

        browser.close()

if __name__ == "__main__":
    # Add your new URLs to this list
    urls_to_scrape = [
        "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE",
        "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR17811241479729840129?region=EE",
        "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR01262577731980230657?region=EE",
        "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR15983061505994129409?region=EE"
    ]
    scrape_ads(urls_to_scrape)
