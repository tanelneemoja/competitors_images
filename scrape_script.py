import os
import requests
import time
from playwright.sync_api import sync_playwright

def scrape_ad():
    target_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    
    # Ensure data folder exists
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(base_dir, 'data')
    os.makedirs(data_path, exist_ok=True)

    with sync_playwright() as p:
        # Launch with 'stealth' arguments
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        print(f"Navigating to {target_url}...")
        page.goto(target_url, wait_until="networkidle")
        
        # Give Google plenty of time to load the creative (20s is safer for GH Actions)
        time.sleep(20)

        # DEBUG: Take a screenshot to see what Google is showing (helps debug CAPTCHAs)
        page.screenshot(path=os.path.join(data_path, "debug_view.png"))

        found_src = None
        
        # Search ALL frames for the image
        for frame in page.frames:
            try:
                # We look for the image in this specific frame
                img = frame.query_selector("img[src*='googleusercontent']")
                if img:
                    found_src = img.get_attribute("src")
                    print(f"Found image in frame: {frame.url[:50]}...")
                    break
            except:
                continue

        if found_src:
            print(f"Success! Downloading image...")
            img_data = requests.get(found_src).content
            with open(os.path.join(data_path, "test_ad.png"), "wb") as f:
                f.write(img_data)
        else:
            print("Failed to find image element in any frame.")
            # If we fail, the YAML will now handle the empty folder gracefully

        browser.close()

if __name__ == "__main__":
    scrape_ad()
