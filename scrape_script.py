import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING BRUTE-FORCE LOGGING CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # Date ranges per your requirement
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
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER ---
        log("--- [STAGE 1] SELVER (Standard Scan) ---")
        sel_ids = set()
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            for s in range(5):
                cards = page.locator("creative-preview").all()
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href")
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img = card.locator("img").first.get_attribute("src")
                            if img:
                                with open(f"data/Selver/{cid}.png", "wb") as f:
                                    f.write(requests.get(img).content)
                                sel_ids.add(cid)
                    except: continue
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(2)
            log(f"  [SELVER] Found {len(sel_ids)} ads.")
        except Exception as e: log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI ---
        log("--- [STAGE 2] RIMI (Brute-Force Matcher) ---")
        rimi_saved = 0
        seen_ids = set()
        
        # Target IDs and Names from your HTML
        TARGET_ID = "AR17608295264152453121"
        TARGET_NAME = "media house"

        for start_date, end_date in date_chunks:
            log(f"  [STARTING RANGE] {start_date} to {end_date}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(8)

                # Initialize grid
                btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
                if btn.count() > 0:
                    btn.click()
                    time.sleep(8)
                
                for i in range(15):
                    cards = page.locator("creative-preview").all()
                    processed_this_loop = 0
                    matches_this_loop = 0
                    
                    for card in cards:
                        try:
                            # 1. Get unique ID
                            inner_html = card.inner_html()
                            h_elem = card.locator("a").first
                            href = h_elem.get_attribute("href")
                            if not href: continue
                            
                            creative_id = href.split("creative/")[-1].split("?")[0]
                            
                            if creative_id in seen_ids:
                                continue
                            
                            seen_ids.add(creative_id)
                            processed_this_loop += 1
                            
                            # 2. BRUTE FORCE MATCHING
                            # Check URL for Advertiser ID OR check inner text for name
                            is_match = (TARGET_ID in href) or (TARGET_NAME in inner_html.lower())
                            
                            if is_match:
                                img_tag = card.locator("img").first
                                img_url = img_tag.get_attribute("src")
                                
                                if img_url:
                                    with open(f"data/Rimi/{creative_id}.png", "wb") as f:
                                        f.write(requests.get(img_url).content)
                                    rimi_saved += 1
                                    matches_this_loop += 1
                        except Exception as e:
                            continue

                    log(f"    Loop {i}: Analyzed {processed_this_loop} ads. Matched & Saved: {matches_this_loop}. (Total: {rimi_saved})")
                    
                    if processed_this_loop == 0 and i > 2:
                        log("    [LOG] No more new ads found in this range.")
                        break

                    page.evaluate("window.scrollBy(0, 1200)")
                    time.sleep(3)

            except Exception as e:
                log(f"    [ERROR] Range failed: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Selver: {len(sel_ids)} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
