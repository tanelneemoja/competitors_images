import os
import requests
import time
from playwright.sync_api import sync_playwright

# --- CONFIG ---
RIMI_SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_scraper():
    log("🚀 Starting Element-Direct Audit...")
    os.makedirs("data/Rimi", exist_ok=True)
    os.makedirs("data/Selver", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        log("Loading Rimi Results...")
        page.goto(RIMI_SEARCH_URL, wait_until="networkidle")
        
        # Expand and Scroll to wake up the renderers
        expand = page.get_by_role("button", name="See all ads")
        if expand.is_visible():
            expand.click()
            time.sleep(5)
        
        for _ in range(3):
            page.mouse.wheel(0, 1000)
            time.sleep(1)

        # 1. Target the exact element type from your snippet
        # We look for <creative> tags
        creatives = page.locator("creative").all()
        log(f"Found {len(creatives)} <creative> elements on the page.")

        count = 0
        for i, creative in enumerate(creatives):
            # Check if this creative card belongs to Rimi
            # Since <a> tags are missing, we check the card text for "rimi"
            card_text = creative.inner_text().lower()
            
            if "rimi" in card_text:
                # 2. Reach inside the <html-renderer> for the <img>
                img_el = creative.locator("html-renderer img, fletch-renderer img").first
                
                if img_el.count() > 0:
                    img_url = img_el.get_attribute("src")
                    if img_url:
                        count += 1
                        log(f"✅ Rimi Ad {count} found! Source: {img_url[:60]}...")
                        
                        # 3. Save it since we finally caught it
                        try:
                            res = requests.get(img_url, timeout=10)
                            if res.status_code == 200:
                                with open(f"data/Rimi/ad_{count}.jpg", "wb") as f:
                                    f.write(res.content)
                        except:
                            log(f"   ⚠️ Failed to download image for ad {count}")

        log(f"🏁 Done. Saved {count} Rimi images to data/Rimi/")
        browser.close()

if __name__ == "__main__":
    run_scraper()
