import os
import requests
import time
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
SELVER_URL = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE"
RIMI_SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"
RIMI_ADVERTISER_ID = "AR17608295264152453121" # Media House OÜ

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def save_image(img_url, folder, creative_id):
    if not img_url:
        return False
    try:
        if img_url.startswith("//"): img_url = "https:" + img_url
        res = requests.get(img_url, timeout=15)
        if res.status_code == 200:
            with open(f"data/{folder}/{creative_id}.jpg", "wb") as f:
                f.write(res.content)
            return True
    except Exception as e:
        log(f"      [Download Error] {e}")
    return False

def run_scraper():
    log("!!! INITIALIZING SCRAPER !!!")
    os.makedirs("data/Selver", exist_ok=True)
    os.makedirs("data/Rimi", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- PART 1: SELVER ---
        log("--- STARTING SELVER (Direct Advertiser) ---")
        page.goto(SELVER_URL, wait_until="networkidle")
        page.wait_for_selector("creative-preview", timeout=10000)
        
        selver_links = page.locator("creative-preview a[href*='creative/']").all()
        selver_urls = list(set([l.get_attribute("href") for l in selver_links]))
        log(f"Found {len(selver_urls)} Selver ads. Processing...")

        for rel_url in selver_urls:
            cid = rel_url.split("creative/")[1].split("?")[0]
            page.goto(f"https://adstransparency.google.com{rel_url}", wait_until="domcontentloaded")
            time.sleep(3)
            # Find image in any renderer
            img = page.locator("html-renderer img, fletch-renderer img").first
            if img.count() > 0 and save_image(img.get_attribute("src"), "Selver", cid):
                log(f"   [Selver] Saved {cid}")

        # --- PART 2: RIMI ---
        log("--- STARTING RIMI (Domain Search + Filter) ---")
        page.goto(RIMI_SEARCH_URL, wait_until="networkidle")
        
        # Click "See all ads" if present
        expand_btn = page.locator("text=See all ads")
        if expand_btn.is_visible():
            log("Clicking 'See all ads' expansion button...")
            expand_btn.click()
            time.sleep(4)

        log("Scrolling to force-load Rimi ad links...")
        # Scroll down and up to trigger the JavaScript that attaches 'href' to the cards
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, 0)")
        
        # Look for links that specifically belong to Media House OÜ (Rimi)
        log(f"Filtering for Advertiser ID: {RIMI_ADVERTISER_ID}")
        rimi_links = page.locator(f"a[href*='{RIMI_ADVERTISER_ID}'][href*='creative/']").all()
        
        rimi_urls = list(set([l.get_attribute("href") for l in rimi_links if l.get_attribute("href")]))
        
        if len(rimi_urls) == 0:
            log("[!] WARNING: 0 Rimi ads found. Taking debug screenshot.")
            page.screenshot(path="rimi_debug.png")
        else:
            log(f"Found {len(rimi_urls)} Rimi ads. Starting drill-down...")

        for rel_url in rimi_urls:
            cid = rel_url.split("creative/")[1].split("?")[0]
            log(f"   Opening Rimi Ad Detail: {cid}")
            try:
                page.goto(f"https://adstransparency.google.com{rel_url}", wait_until="domcontentloaded")
                time.sleep(5) # Critical wait for renderers

                # 1. Check for standard image
                img_src = None
                img_el = page.locator("html-renderer img, fletch-renderer img").first
                if img_el.count() > 0:
                    img_src = img_el.get_attribute("src")

                # 2. Check inside iframes (for Rich Media/Fletch)
                if not img_src:
                    for frame in page.frames:
                        if "adframe" in frame.url:
                            inner_img = frame.locator("img").first
                            if inner_img.count() > 0:
                                img_src = inner_img.get_attribute("src")
                                break

                if save_image(img_src, "Rimi", cid):
                    log(f"      >>> Image saved for {cid}")
                else:
                    log(f"      [SKIP] No image found for {cid}")

            except Exception as e:
                log(f"      [Error] Could not process {cid}: {e}")

        browser.close()
        log("!!! ALL TASKS COMPLETE !!!")

if __name__ == "__main__":
    run_scraper()
