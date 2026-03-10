import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_specific_ad(url):
    cr_match = re.search(r"(CR\d+)", url)
    if not cr_match: return
    cr_id = cr_match.group(1)
    
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        # 1. Launch browser
        browser = p.chromium.launch(headless=True)
        
        # 2. Set the Viewport to a standard Desktop size (1920x1080)
        # This is usually what makes the difference in which 'variant' loads
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Scraping Desktop version for: {cr_id}")
        page.goto(url, wait_until="networkidle")
        time.sleep(12) # Give extra time for the responsive iframe to 'settle'

        # 3. Find the image
        # Google often uses a high-res source for the main 'detail' view
        found_src = None
        for frame in page.frames:
            # We look for the largest image in the frame
            images = frame.query_selector_all("img")
            for img in images:
                src = img.get_attribute("src")
                # We want the actual ad content, not the small logo
                if src and ("googleusercontent" in src or "2mdn.net" in src):
                    found_src = src
                    break

        if found_src:
            img_data = requests.get(found_src).content
            with open(f"data/{cr_id}.png", "wb") as f:
                f.write(img_data)
            print(f"Saved Desktop variant for {cr_id}")
        else:
            # Fallback: take a high-res screenshot of the ad element itself
            # This ensures we get exactly what you see even if we can't 'download' the file
            ad_element = page.locator("html-renderer").first
            if ad_element:
                ad_element.screenshot(path=f"data/{cr_id}.png")
                print(f"Captured screenshot variant for {cr_id}")

        browser.close()

if __name__ == "__main__":
    test_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    scrape_specific_ad(test_url)
