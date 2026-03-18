import os
import requests
import time
from playwright.sync_api import sync_playwright

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def scrape_ads():
    # 1. Setup
    TARGET_ID = "AR17608295264152453121" # Media House OÜ
    os.makedirs("data/Rimi", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # 2. Go to the search results
        url = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"
        log("Navigating to Rimi search results...")
        page.goto(url, wait_until="domcontentloaded")
        
        # Wait for the grid to actually exist
        page.wait_for_selector("creative-preview", timeout=20000)

        # 3. Handle "See all ads" if it exists to get the full list
        expand_btn = page.locator("text=See all ads")
        if expand_btn.is_visible():
            log("Expanding grid to see all 82 ads...")
            expand_btn.click()
            time.sleep(3)

        # 4. Collect all unique AD DETAIL URLs
        # We look for <a> tags that contain the Advertiser ID and the word 'creative'
        ad_links = page.locator(f"a[href*='{TARGET_ID}'][href*='creative/']").all()
        detail_urls = list(set([l.get_attribute("href") for l in ad_links if l.get_attribute("href")]))
        
        log(f"Found {len(detail_urls)} unique ad detail pages to visit.")

        # 5. The "Drill-Down" Phase: Visit each page
        for rel_url in detail_urls:
            full_url = f"https://adstransparency.google.com{rel_url}"
            creative_id = rel_url.split("creative/")[1].split("?")[0]
            
            log(f"Entering detail page: {creative_id}")
            try:
                page.goto(full_url, wait_until="domcontentloaded")
                # Wait for the "Renderer" to wake up
                time.sleep(5) 

                img_url = None

                # TYPE A: Standard Image or YouTube Thumbnail
                # These are usually in html-renderer or fletch-renderer
                img_element = page.locator("html-renderer img, fletch-renderer img").first
                if img_element.count() > 0:
                    img_url = img_element.get_attribute("src")

                # TYPE B: Rich Media (Inside the Iframe)
                # If Type A failed, we look for the adframe
                if not img_url:
                    for frame in page.frames:
                        if "adframe" in frame.url:
                            # Search for common ad image IDs/classes inside the frame
                            inner_img = frame.locator("img").first
                            if inner_img.count() > 0:
                                img_url = inner_img.get_attribute("src")
                                break

                # 6. Download the asset
                if img_url:
                    # Clean the URL (sometimes they start with //)
                    if img_url.startswith("//"): img_url = "https:" + img_url
                    
                    response = requests.get(img_url, timeout=15)
                    with open(f"data/Rimi/{creative_id}.jpg", "wb") as f:
                        f.write(response.content)
                    log(f"   Successfully saved: {creative_id}.jpg")
                else:
                    log(f"   [!] Could not find image source for {creative_id}")

            except Exception as e:
                log(f"   [Error] Failed to process {creative_id}: {e}")

        browser.close()
        log("Process complete.")

if __name__ == "__main__":
    scrape_ads()
