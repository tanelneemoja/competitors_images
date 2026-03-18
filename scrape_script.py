import os
import requests
import time
from playwright.sync_api import sync_playwright

# --- CONFIG ---
# This is the static ID we are locking onto
TARGET_AR = "AR17608295264152453121" 
SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_scraper():
    log(f"🚀 Locked on Target AR: {TARGET_AR}")
    os.makedirs("data/Rimi", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        page.goto(SEARCH_URL, wait_until="networkidle")
        
        # Expand & Scroll
        expand = page.get_by_role("button", name="See all ads")
        if expand.is_visible():
            expand.click()
            time.sleep(5)
        
        page.mouse.wheel(0, 3000)
        time.sleep(3)

        # 1. Grab all grid items
        # We look for the container that holds the creative and the link
        items = page.locator("creative-preview").all()
        log(f"Scanning {len(items)} items for the Static AR...")

        saved = 0
        for i, item in enumerate(items):
            # 2. Check the HTML of the entire preview block for the AR string
            # This catches it even if it's hidden in a data-attribute or deep link
            raw_html = item.inner_html()
            
            if TARGET_AR in raw_html:
                # 3. If the AR matches, grab the image inside the <html-renderer>
                img_el = item.locator("html-renderer img, fletch-renderer img").first
                img_url = img_el.get_attribute("src") if img_el.count() > 0 else None

                if img_url:
                    log(f"✅ Match Found! Item [{i}] matches {TARGET_AR}")
                    try:
                        res = requests.get(img_url if img_url.startswith('http') else f"https:{img_url}", timeout=10)
                        if res.status_code == 200:
                            path = f"data/Rimi/official_{i}.jpg"
                            with open(path, "wb") as f:
                                f.write(res.content)
                            saved += 1
                            log(f"   Stored: {path}")
                    except:
                        log(f"   ❌ Failed download for {i}")
            else:
                # Log a snippet of the 'wrong' ARs so we can see what we are skipping
                if "AR" in raw_html:
                    other_ar = raw_html.split("advertiser/")[1].split("/")[0] if "advertiser/" in raw_html else "Unknown"
                    log(f"   ⏭️ Skipping: Found {other_ar} (Not our target)")

        log(f"🏁 Done. Total Official Rimi Ads Saved: {saved}")
        browser.close()

if __name__ == "__main__":
    run_scraper()
