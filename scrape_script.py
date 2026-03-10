import os
import requests
import time
from playwright.sync_api import sync_playwright

def scrape_selver_ads():
    # URL for Selver AS ads in Estonia based on your HTML
    target_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE"
    
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Navigating to {target_url}...")
        page.goto(target_url, wait_until="networkidle")
        
        # Give the grid time to render all thumbnails
        time.sleep(10)

        # According to your HTML, images are inside <html-renderer> tags
        # and their source contains 'simgad' or '2mdn.net'
        ads = page.query_selector_all("html-renderer img")
        
        print(f"Found {len(ads)} potential ad images.")

        for i, img in enumerate(ads):
            src = img.get_attribute("src")
            if src:
                print(f"Downloading ad {i}: {src}")
                try:
                    img_data = requests.get(src, timeout=10).content
                    # Using a generic name or extracting the ID from the URL
                    filename = f"selver_ad_{i}.png"
                    with open(os.path.join('data', filename), "wb") as f:
                        f.write(img_data)
                except Exception as e:
                    print(f"Failed to download image {i}: {e}")

        browser.close()

if __name__ == "__main__":
    scrape_selver_ads()
