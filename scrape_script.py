import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def scrape_exact_ad_variant(url):
    cr_match = re.search(r"(CR\d+)", url)
    if not cr_match: return
    cr_id = cr_match.group(1)
    
    os.makedirs('data', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Larger viewport to ensure we don't truncate the ad
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()
        
        print(f"Analyzing ad layout for {cr_id}...")
        page.goto(url, wait_until="networkidle")
        time.sleep(10)

        # 1. Detect the target dimensions from the UI container style
        # In your HTML, this was style="width: 300px; height: 600px;"
        container = page.locator(".creative-container[style*='width']").first
        style = container.get_attribute("style") if container.count() > 0 else ""
        
        # Extract numbers using regex (e.g., extracts '300' and '600')
        dims = re.findall(r"(\d+)px", style)
        target_w, target_h = (dims[0], dims[1]) if len(dims) >= 2 else (None, None)
        
        print(f"Target dimensions detected: {target_w}x{target_h}")

        # 2. Find the image that matches these dimensions
        img_element = None
        if target_w and target_h:
            img_element = page.locator(f"html-renderer img[width='{target_w}'][height='{target_h}']").first
        
        # 3. Download or Screenshot
        if img_element and img_element.count() > 0:
            src = img_element.get_attribute("src")
            print(f"Downloading high-res asset: {src}")
            img_data = requests.get(src).content
            with open(f"data/{cr_id}.png", "wb") as f:
                f.write(img_data)
        else:
            # If the image attributes don't match, capture the visual container exactly
            print("Attribute match failed. Capturing visual container...")
            page.locator("creative-preview").first.screenshot(path=f"data/{cr_id}.png")

        browser.close()

if __name__ == "__main__":
    target = "https://adstransparency.google.com/advertiser/AR08638735883022893057/creative/CR16900379659001135105?region=EE"
    scrape_exact_ad_variant(target)
