import os
import requests
import time
from playwright.sync_api import sync_playwright
 
# --- CONFIG ---
SELVER_URL = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE"
RIMI_SEARCH_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"
RIMI_ID = "AR17608295264152453121"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_scraper():
    log("🚀 Starting X-Ray Audit...")
    os.makedirs("data/Selver", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- PART 1: SELVER (Silent Save) ---
        log("--- Selver Phase ---")
        try:
            page.goto(SELVER_URL, wait_until="networkidle")
            sel_links = page.locator("a[href*='creative/']").all()
            sel_urls = list(set([l.get_attribute("href") for l in sel_links if l.get_attribute("href")]))
            log(f"✅ Selver: Found {len(sel_urls)} ads. Downloading...")
            for url_tail in sel_urls[:5]: # Limit for speed
                cid = url_tail.split("creative/")[1].split("?")[0]
                page.goto(f"https://adstransparency.google.com{url_tail}", wait_until="domcontentloaded")
                time.sleep(2)
                img_el = page.locator("html-renderer img, fletch-renderer img").first
                if img_el.count() > 0:
                    src = img_el.get_attribute("src")
                    if src: requests.get(src if src.startswith("http") else "https:"+src) # Placeholder for save
        except Exception as e:
            log(f"⚠️ Selver Error: {e}")

        # --- PART 2: RIMI (The X-Ray) ---
        log("--- Rimi X-Ray Phase ---")
        page.goto(RIMI_SEARCH_URL, wait_until="networkidle")
        
        # 1. Check if the "See all ads" button actually exists in the DOM
        expand_btn = page.locator("material-button:has-text('See all ads'), .grid-expansion-button")
        if expand_btn.is_visible():
            log("Found 'See all ads' button. Clicking...")
            expand_btn.click()
            time.sleep(5)
        else:
            log("❓ 'See all ads' button NOT found. Grid might be small or already expanded.")

        # 2. Forced Interaction
        log("Performing deep scroll to trigger lazy-load...")
        for i in range(3):
            page.mouse.wheel(0, 1500)
            time.sleep(2)

        # 3. THE X-RAY: List EVERY link found
        log("--- DOM SCAN START ---")
        all_links = page.locator("a").all()
        log(f"Total links found on page: {len(all_links)}")
        
        ad_links_count = 0
        found_ids = set()
        
        for link in all_links:
            href = link.get_attribute("href") or ""
            if "creative/" in href:
                ad_links_count += 1
                # Extract Advertiser ID from the URL (Format: /advertiser/ARXXXXXXXX/creative/...)
                if "/advertiser/" in href:
                    adv_id = href.split("/advertiser/")[1].split("/")[0]
                    found_ids.add(adv_id)
        
        log(f"Total Ad-specific links found: {ad_links_count}")
        log(f"Unique Advertiser IDs detected: {list(found_ids)}")
        
        # 4. Filter for Rimi
        log(f"Filtering for Target ID: {RIMI_ID}")
        rimi_matches = [h for h in [l.get_attribute("href") for l in all_links] if h and RIMI_ID in h]
        log(f"Final Rimi Match Count: {len(rimi_matches)}")

        if not rimi_matches:
            log("❌ CRITICAL: No Rimi ads found. Checking page text for clues...")
            # Look for the name of the advertiser in the text
            if page.get_by_text("Media House").is_visible():
                log("   - Note: The text 'Media House' IS visible, but links are missing.")
            else:
                log("   - Note: The text 'Media House' is NOT visible. Page might be empty.")

        browser.close()
        log("--- Audit Finished ---")

if __name__ == "__main__":
    run_scraper()
