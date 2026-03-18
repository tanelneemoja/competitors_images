import os
import requests
import time
import base64
from playwright.sync_api import sync_playwright

# --- CONFIG ---
SELVER_URL = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE"
RIMI_SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"
RIMI_ID = "AR17608295264152453121"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def get_and_show_image(img_url, name):
    """Downloads the image and prints a base64 string for visibility."""
    if not img_url or "base64" in img_url: return
    try:
        if img_url.startswith("//"): img_url = "https:" + img_url
        res = requests.get(img_url, timeout=10)
        if res.status_code == 200:
            # Save locally
            with open(f"{name}.jpg", "wb") as f:
                f.write(res.content)
            
            # Create a preview string for the logs
            encoded_string = base64.b64encode(res.content).decode('utf-8')
            log(f"📸 PREVIEW GENERATED for {name}: [data:image/jpeg;base64,{encoded_string[:50]}...]")
            return True
    except: pass
    return False

def run_scraper():
    log("🚀 Launching Browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- SELVER (Fast Mode) ---
        log("--- Processing Selver ---")
        page.goto(SELVER_URL, wait_until="networkidle")
        sel_links = page.locator("a[href*='creative/']").all()
        log(f"Found {len(sel_links)} Selver links.")
        # Just grab the first one to show it works
        if sel_links:
            page.goto(f"https://adstransparency.google.com{sel_links[0].get_attribute('href')}")
            time.sleep(3)
            img = page.locator("html-renderer img, fletch-renderer img").first
            get_and_show_image(img.get_attribute("src"), "Selver_Sample")

        # --- RIMI (Force-Discovery Mode) ---
        log("--- Processing Rimi ---")
        page.goto(RIMI_SEARCH_URL, wait_until="networkidle")
        
        # 1. Expand the grid
        expand = page.get_by_role("button", name="See all ads")
        if expand.is_visible():
            log("Expanding Rimi grid...")
            expand.click()
            time.sleep(5)

        # 2. Force links to generate by scrolling slowly
        log("Performing deep-scroll to wake up lazy links...")
        for i in range(5):
            page.mouse.wheel(0, 1000)
            time.sleep(1)

        # 3. Targeted extraction
        rimi_links = page.locator(f"a[href*='{RIMI_ID}'][href*='creative/']").all()
        unique_urls = list(set([l.get_attribute("href") for l in rimi_links if l.get_attribute("href")]))
        
        log(f"✅ SUCCESS: Found {len(unique_urls)} Rimi ad URLs.")

        for i, url in enumerate(unique_urls[:3]): # Preview first 3
            cid = url.split("creative/")[1].split("?")[0]
            log(f"Opening Ad Detail: {cid}")
            page.goto(f"https://adstransparency.google.com{url}", wait_until="domcontentloaded")
            time.sleep(4)
            
            # Check standard images and iframes
            img_src = page.locator("html-renderer img, fletch-renderer img").first.get_attribute("src")
            if not img_src:
                for frame in page.frames:
                    if "adframe" in frame.url:
                        img_src = frame.locator("img").first.get_attribute("src")
                        break
            
            get_and_show_image(img_src, f"Rimi_{cid}")

        browser.close()
        log("--- Done ---")

if __name__ == "__main__":
    run_scraper()
