import time
import requests
import base64
from playwright.sync_api import sync_playwright

# --- CONFIG ---
RIMI_SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"
RIMI_ID = "AR17608295264152453121"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def describe_asset(url, cid):
    """Instead of saving, this explains the asset in the logs."""
    if not url:
        log(f"   ❌ [ID: {cid}] No asset found.")
        return
    
    try:
        # Determine asset type
        if "ytimg" in url:
            asset_type = "YouTube Video Thumbnail"
        elif "googleusercontent" in url:
            asset_type = "Google Hosted Image"
        elif "simgad" in url:
            asset_type = "Static Display Ad"
        else:
            asset_type = "Rich Media / HTML5"

        log(f"   ✅ [ID: {cid}] Found {asset_type}")
        log(f"      🔗 Source: {url[:100]}...") # Print first 100 chars of URL
        
    except Exception as e:
        log(f"   ⚠️ Error describing asset {cid}: {e}")

def run_scraper():
    log("🚀 Starting Rimi Visual Audit...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        log(f"Navigating to Rimi Domain Search...")
        page.goto(RIMI_SEARCH_URL, wait_until="networkidle")
        
        # 1. Expand the Grid
        expand = page.get_by_role("button", name="See all ads")
        if expand.is_visible():
            log("Clicking 'See all ads'...")
            expand.click()
            time.sleep(5)

        # 2. Force Link Generation (The "Wake Up" Scroll)
        log("Scrolling to wake up lazy-loaded links...")
        for _ in range(3):
            page.mouse.wheel(0, 1000)
            time.sleep(1)

        # 3. Find Rimi-specific Ads
        # We look for the advertiser ID within the hrefs of all links
        all_links = page.locator("a[href*='creative/']").all()
        rimi_links = [l.get_attribute("href") for l in all_links if RIMI_ID in (l.get_attribute("href") or "")]
        unique_urls = list(set(rimi_links))
        
        log(f"Found {len(unique_urls)} unique Rimi ads in the grid.")

        # 4. Drill Down & Log Details
        for url_tail in unique_urls[:5]: # Let's audit the first 5
            cid = url_tail.split("creative/")[1].split("?")[0]
            full_url = f"https://adstransparency.google.com{url_tail}"
            
            log(f"Inspecting Ad: {cid}")
            page.goto(full_url, wait_until="domcontentloaded")
            time.sleep(4) # Wait for renderer to fire
            
            # Extract Image from any possible container
            img_src = None
            
            # Check main page renderers first
            img_el = page.locator("html-renderer img, fletch-renderer img").first
            if img_el.count() > 0:
                img_src = img_el.get_attribute("src")
            
            # If not found, dive into iframes (Rich Media)
            if not img_src:
                for frame in page.frames:
                    if "adframe" in frame.url:
                        inner_img = frame.locator("img").first
                        if inner_img.count() > 0:
                            img_src = inner_img.get_attribute("src")
                            break
            
            describe_asset(img_src, cid)

        browser.close()
        log("🏁 Audit Complete.")

if __name__ == "__main__":
    run_scraper()
