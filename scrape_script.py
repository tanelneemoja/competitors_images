import os
import requests
from playwright.sync_api import sync_playwright

def scrape_ad_detail(url):
    with sync_playwright() as p:
        # 1. Use a non-headless or stealth-like User-Agent
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # 2. Go to the specific ad detail URL
        page.goto(url, wait_until="networkidle")

        # 3. Locate the ad preview image
        # Google often uses a specific class or container for the ad preview
        # We wait for any image that looks like the creative content
        try:
            # Wait for the image to load - targeting images within the creative preview area
            page.wait_for_selector("img[src*='googleusercontent']", timeout=15000)
            
            # Extract all images and filter for the one that is likely the ad
            images = page.query_selector_all("img")
            target_url = None
            
            for img in images:
                src = img.get_attribute("src")
                # Ad images are usually hosted on googleusercontent.com
                if src and "googleusercontent.com" in src:
                    target_url = src
                    break
            
            if target_url:
                print(f"Found image: {target_url}")
                # Download logic
                img_data = requests.get(target_url).content
                filename = f"ad_image_{url.split('/')[-1].split('?')[0]}.png"
                with open(f"data/{filename}", "wb") as f:
                    f.write(img_data)
            else:
                print("No ad image found.")
                
        except Exception as e:
            print(f"Error during scraping: {e}")
        
        browser.close()

# Your specific test ad
scrape_ad_detail("https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE")
