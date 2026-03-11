import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING FULL BRUTE-FORCE CRAWLER (SELVER & RIMI) !!!")
    
    # Setup directories
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # Required Date Ranges
    date_chunks = [
        ("2026-03-01", "2026-03-11"),
        ("2026-02-01", "2026-02-28"),
        ("2026-01-01", "2026-01-31"),
        ("2025-12-01", "2025-12-31"),
        ("2025-11-01", "2025-11-30"),
        ("2025-10-01", "2025-10-31"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 1920x1200 helps trigger the grid's lazy loader more effectively
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER (Direct Advertiser Account) ---
        log("--- [STAGE 1] SELVER (Direct Scan) ---")
        sel_ids = set()
        try:
            # Selver uses a fixed advertiser ID
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            
            for s in range(10): # Scroll to capture history
                cards = page.locator("creative-preview").all()
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href")
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img = card.locator("img").first.get_attribute("src")
                            if img:
                                r = requests.get(img, timeout=10)
                                with open(f"data/Selver/{cid}.png", "wb") as f:
                                    f.write(r.content)
                                sel_ids.add(cid)
                    except: continue
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(2)
            log(f"  [SELVER] Found {len(sel_ids)} ads.")
        except Exception as e: 
            log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI (Domain-wide Brute Force) ---
        log("--- [STAGE 2] RIMI (Media House OÜ Matcher) ---")
        rimi_total_saved = 0
        global_seen_ids = set()
        
        # Confirmed Target ID and Keywords from your HTML/Screenshots
        TARGET_ID = "AR17608295264152453121" 
        KEYWORDS = ["media house", "mediahouse", "rimi eesti"]

        for start_date, end_date in date_chunks:
            log(f"  [RANGE] {start_date} to {end_date}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(8)

                # Expansion: Click the gatekeeper button to load 17-58 ads
                expand_btn = page.locator(".grid-expansion-button").filter(has_text="See all ads")
                if expand_btn.count() > 0:
                    log("    [ACTION] Clicking 'See all ads'...")
                    expand_btn.click()
                    time.sleep(5)

                # Detect count for this range
                count_el = page.locator(".ads-count").first
                range_target = 0
                if count_el.count() > 0:
                    range_target = int(re.sub(r'\D', '', count_el.inner_text()))
                    log(f"    [INFO] UI reports {range_target} ads in range.")

                # Scroll Loop
                for i in range(25): 
                    cards = page.locator("creative-preview").all()
                    new_found = 0
                    matches_saved = 0
                    
                    for card in cards:
                        try:
                            h_elem = card.locator("a").first
                            href = h_elem.get_attribute("href")
                            if not href: continue
                            cid = href.split("creative/")[-1].split("?")[0]
                            
                            if cid not in global_seen_ids:
                                global_seen_ids.add(cid)
                                new_found += 1
                                
                                # Clean matching logic
                                card_text = card.inner_text().lower()
                                clean_text = re.sub(r'[^a-z0-9 ]', '', card_text)
                                
                                is_match = (TARGET_ID in href) or any(k in clean_text for k in KEYWORDS)
                                
                                if is_match:
                                    img_url = card.locator("img").first.get_attribute("src")
                                    if img_url:
                                        res = requests.get(img_url, timeout=10)
                                        with open(f"data/Rimi/{cid}.png", "wb") as f:
                                            f.write(res.content)
                                        rimi_total_saved += 1
                                        matches_saved += 1
                        except: continue

                    log(f"    Loop {i}: New:{new_found} | Saved:{matches_saved} | Total Processed:{len(global_seen_ids)}")
                    
                    # Exit range if we've processed everything the UI reported
                    if range_target > 0 and len(global_seen_ids) >= range_target and i > 5:
                        break
                    
                    # Stop range if no new ads appear after multiple scrolls
                    if new_found == 0 and i > 5:
                        break

                    page.evaluate("window.scrollBy(0, 900)")
                    time.sleep(3)

            except Exception as e:
                log(f"    [ERROR] Range {start_date} failed: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Selver: {len(sel_ids)} | Rimi: {rimi_total_saved}")

if __name__ == "__main__":
    run_scraper()
