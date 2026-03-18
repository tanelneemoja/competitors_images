import os
import requests
import time
from playwright.sync_api import sync_playwright

# This URL forces Media House (Agency) to only show ads for rimi.ee (Client)
TARGET_URL = "https://adstransparency.google.com/advertiser/AR17608295264152453121?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"

def run_scraper():
    print(f"🚀 Starting Filtered Rimi Audit (Media House + rimi.ee)...")
    os.makedirs("data/Rimi", exist_ok=True)
    
    captured_urls = set()

    with sync_playwright() as p:
        # We use a headed browser or a specific user-agent to ensure Google renders the 'src'
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        page.goto(TARGET_URL, wait_until="networkidle")
        time.sleep(5) # Allow the grid to settle

        # 1. Expand the grid
        expand_btn = page.get_by_role("button", name="See all ads")
        if expand_btn.is_visible():
            expand_btn.click()
            time.sleep(3)

        # 2. Step-Scroll and Capture
        # We don't wait for the end; we grab images as they appear in the viewport
        for step in range(10):
            print(f"📡 Scanning batch {step}...")
            
            # Find all potential images in the current view
            # This covers both static (html-renderer) and video thumbnails (fletch-renderer)
            images = page.locator("html-renderer img, fletch-renderer img").all()
            
            for img in images:
                src = img.get_attribute("src")
                if src and src not in captured_urls:
                    # Filter out tiny tracking pixels or icons
                    if "googlesyndication" in src or "ytimg" in src:
                        captured_urls.add(src)
                        idx = len(captured_urls)
                        
                        try:
                            # Handle relative URLs
                            final_url = src if src.startswith('http') else f"https:{src}"
                            res = requests.get(final_url, timeout=10)
                            if res.status_code == 200:
                                with open(f"data/Rimi/rimi_ad_{idx}.jpg", "wb") as f:
                                    f.write(res.content)
                                print(f"   ✅ Saved: rimi_ad_{idx}.jpg")
                        except Exception as e:
                            print(f"   ❌ Failed download: {e}")

            # Scroll down just enough to trigger the next lazy-load
            page.mouse.wheel(0, 800)
            time.sleep(2.5) # Time for Google to swap 'loading' icons for real images

        print(f"🏁 Done. Total 'Official' Rimi Ads saved: {len(captured_urls)}")
        browser.close()

if __name__ == "__main__":
    run_scraper()
