import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING FULL BRUTE-FORCE CRAWLER !!!")
    
    # Ensure directories exist
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # Date ranges as requested
    date_chunks = [
        ("2026-03-01", "2026-03-11"),
        ("2026-02-01", "2026-02-28"),
        ("2026-01-01", "2026-01-31"),
        ("2025-12-01", "2025-12-31"),
        ("2025-11-01", "2025-11-30"),
        ("2025-10-01", "2025-10-31"),
    ]

    with sync_playwright() as p:
        # Using headless=True for performance; switch to False if debugging
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER ---
        log("--- [STAGE 1] SELVER (Standard Scan) ---")
        sel_ids = set()
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            for s in range(8):  # Increased scroll loops
                cards = page.locator("creative-preview").all()
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href")
                        if not h: continue
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
        except Exception as e: log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI ---
        log("--- [STAGE 2] RIMI (Multi-Advertiser Brute-Force) ---")
        rimi_total_saved = 0
        global_seen_ids = set()
        
        TARGET_ID = "AR17608295264152453121" # Media House OÜ
        TARGET_NAME = "media house"

        for start_date, end_date in date_chunks:
            log(f"  [STARTING RANGE] {start_date} to {end_date}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(7)

                # Detect target count from the UI (e.g., "58 ads")
                count_el = page.locator(".ads-count").first
                target_count = 0
                if count_el.count() > 0:
                    target_count = int(re.sub(r'\D', '', count_el.inner_text()))
                    log(f"    [INFO] Detected {target_count} ads in range.")

                # Expand the grid if button exists
                btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
                if btn.count() > 0:
                    btn.click()
                    time.sleep(5)
                
                range_seen_count = 0
                
                # Loop until we reach the target_count or stop finding new ads
                for i in range(25): 
                    cards = page.locator("creative-preview").all()
                    analyzed_this_loop = 0
                    matches_this_loop = 0
                    
                    for card in cards:
                        try:
                            h_elem = card.locator("a").first
                            href = h_elem.get_attribute("href")
                            if not href: continue
                            
                            creative_id = href.split("creative/")[-1].split("?")[0]
                            
                            # range_seen tracks progress for THIS date chunk
                            # global_seen prevents re-downloading the same ad file
                            if creative_id not in global_seen_ids:
                                analyzed_this_loop += 1
                                
                                # Brute force matching: check ID in URL or Name in text
                                inner_text = card.inner_text().lower()
                                if (TARGET_ID in href) or (TARGET_NAME in inner_text):
                                    img_url = card.locator("img").first.get_attribute("src")
                                    if img_url:
                                        r = requests.get(img_url, timeout=10)
                                        with open(f"data/Rimi/{creative_id}.png", "wb") as f:
                                            f.write(r.content)
                                        rimi_total_saved += 1
                                        matches_this_loop += 1
                                
                                global_seen_ids.add(creative_id)

                        except: continue

                    range_seen_count = len([x for x in global_seen_ids]) # Simple proxy
                    log(f"    Loop {i}: Analyzed {analyzed_this_loop} new. Matched: {matches_this_loop}. (Total Saved: {rimi_total_saved})")
                    
                    # Exit loop if we've analyzed everything reported by the page
                    if analyzed_this_loop == 0 and i > 3:
                        break

                    # Incremental scroll to trigger lazy loading effectively
                    page.evaluate("window.scrollBy(0, 900)")
                    time.sleep(2.5)

            except Exception as e:
                log(f"    [ERROR] Range failed: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Selver: {len(sel_ids)} | Rimi (Matched): {rimi_total_saved}")

if __name__ == "__main__":
    run_scraper()
