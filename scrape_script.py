import os
import requests
import time
from playwright.sync_api import sync_playwright

TARGET_AR = "AR17608295264152453121" 
SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"

def run_scraper():
    print(f"🚀 Starting Continuous Collection for Rimi...")
    os.makedirs("data/Rimi", exist_ok=True)
    
    # We use a set to keep track of unique image URLs so we don't download duplicates
    captured_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(SEARCH_URL, wait_until="networkidle")
        
        # Expand the grid
        expand_btn = page.get_by_role("button", name="See all ads")
        if expand_btn.is_visible():
            expand_btn.click()
            time.sleep(4)

        # SCROLLING LOOP: Catch them in the act
        for scroll_step in range(15):  # Incremental small scrolls
            print(f"📡 Scanning viewport at step {scroll_step}...")
            
            # Find all previews currently in the DOM
            previews = page.locator("creative-preview").all()
            
            for preview in previews:
                # Check if this specific preview is for Media House
                if TARGET_AR in (preview.get_attribute("inner_html") or "") or \
                   preview.locator(f"a[href*='{TARGET_AR}']").count() > 0:
                    
                    # Target both renderer types
                    img_el = preview.locator("html-renderer img, fletch-renderer img").first
                    img_url = img_el.get_attribute("src") if img_el.count() > 0 else None
                    
                    if img_url and img_url not in captured_urls:
                        captured_urls.add(img_url)
                        idx = len(captured_urls)
                        print(f"   ✨ Caught New Rimi Ad! ({idx})")
                        
                        # Download immediately before Google clears the cache
                        try:
                            res = requests.get(img_url if img_url.startswith('http') else f"https:{img_url}")
                            with open(f"data/Rimi/rimi_official_{idx}.jpg", "wb") as f:
                                f.write(res.content)
                        except:
                            pass

            # Small scroll to trigger next batch
            page.mouse.wheel(0, 600)
            time.sleep(2) # Give renderer time to wake up

        print(f"🏁 Finished. Collected {len(captured_urls)} unique Official Rimi Ads.")
        browser.close()

if __name__ == "__main__":
    run_scraper()
