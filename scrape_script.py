import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_specific_ad(url):
    # 1. Extract the CR ID from the URL using Regex
    # This matches the 'CR' followed by digits
    cr_match = re.search(r"(CR\d+)", url)
    if not cr_match:
        print("Could not find CR ID in URL")
        return
    cr_id = cr_match.group(1)
    
    os.makedirs('data', exist_ok=True)
    filename = f"{cr_id}.png"
    save_path = os.path.join('data', filename)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Targeting Ad ID: {cr_id}")
        page.goto(url, wait_until="networkidle")
        
        # Google takes time to load the creative inside the iframe
        time.sleep(10)

        found_src = None
        # 2. Look for the image inside ALL iframes
        for frame in page.frames:
            # On detail pages, the image is often on googleusercontent.com
            img = frame.query_selector("img[src*='googleusercontent'], img[src*='2mdn.net']")
            if img:
                found_src = img.get_attribute("src")
                break

        if found_src:
            print(f"Found source: {found_src}")
            img_data = requests.get(found_src).content
            with open(save_path, "wb") as f:
                f.write(img_data)
            print(f"Success! Saved as {filename}")
        else:
            print(f"Failed to find image for {cr_id}")
            # Optional: save screenshot to see why it failed
            page.screenshot(path=f"data/error_{cr_id}.png")

        browser.close()

if __name__ == "__main__":
    # You can change this URL or make it an input
    test_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    scrape_specific_ad(test_url)
