import os
import requests
import time
from playwright.sync_api import sync_playwright

# The static ID identified from your snippet
TARGET_AR = "AR17608295264152453121" 
SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_scraper():
    log(f"🚀 Targeting Official Rimi ID: {TARGET_AR}")
    os.makedirs("data/Rimi", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        log("Opening Google Ads Transparency Center...")
        page.goto(SEARCH_URL, wait_until="networkidle")
        
        # 1. Expand the grid properly
        expand_btn = page.get_by_role("button", name="See all ads")
        if expand_btn.is_visible():
            log("Expanding grid to show all 82 ads...")
            expand_btn.click()
            time.sleep(5) # Give it time to load the extra cards

        # 2. Infinite Scroll to hydrate all 82 ads
        log("Scrolling to hydrate all ad cards...")
        last_height = page.evaluate("document.body.scrollHeight")
        for _ in range(10): # Scroll 10 times to ensure we hit the end
            page.mouse.wheel(0, 1500)
            time.sleep(1.5)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # 3. Targeted Extraction
        # We find every 'creative-preview' and check its specific internal links
        previews = page.locator("creative-preview").all()
        log(f"Detected {len(previews)} total ad previews on page.")

        saved_count = 0
        for i, preview in enumerate(previews):
            # We look for the AR in any link inside this specific preview block
            links = preview.locator(f"a[href*='{TARGET_AR}'], div[href*='{TARGET_AR}']").count()
            
            if links > 0:
                log(f"✅ Match found at index {i} (Media House OÜ)")
                
                # Check for image in both renderer types found in your HTML
                img_el = preview.locator("html-renderer img, fletch-renderer img").first
                img_url = img_el.get_attribute("src") if img_el.count() > 0 else None

                if img_url:
                    try:
                        # Handle protocol-relative URLs
                        final_url = img_url if img_url.startswith('http') else f"https:{img_url}"
                        res = requests.get(final_url, timeout=10)
                        if res.status_code == 200:
                            file_name = f"data/Rimi/rimi_official_{saved_count}.jpg"
                            with open(file_name, "wb") as f:
                                f.write(res.content)
                            log(f"   Saved asset: {file_name}")
                            saved_count += 1
                    except Exception as e:
                        log(f"   ❌ Download error: {e}")
                else:
                    log(f"   ⚠️ Media House ad found, but no image source detected.")
            else:
                # Log non-matches briefly so we know the logic is working
                pass 

        log(f"🏁 Final Count: Saved {saved_count} official Rimi/Media House ads.")
        browser.close()

if __name__ == "__main__":
    run_scraper()
