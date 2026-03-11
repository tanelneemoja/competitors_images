import os
import requests
import time
import re
import datetime
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING MONTHLY SEGMENTED CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # 1. Generate 6 months of ranges (March 2026 back to Oct 2025)
    # URL format: &start-date=2026-01-01&end-date=2026-01-31
    date_chunks = [
        ("2026-03-01", "2026-03-11"),
        ("2026-02-01", "2026-02-28"),
        ("2026-01-01", "2026-01-31"),
        ("2025-12-01", "2025-12-31"),
        ("2025-11-01", "2025-11-30"),
        ("2025-10-01", "2025-10-31"),
    ]

    with sync_playwright() as p:
        log("Launching Browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER (Direct Link) ---
        try:
            log("--- [STAGE 1] SELVER ---")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(6)
            sel_ids = set()
            for s in range(10):
                cards = page.locator("creative-preview").all()
                new_sel = 0
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img_url = card.locator("img").first.get_attribute("src", timeout=500)
                            if img_url:
                                with open(f"data/Selver/{cid}.png", "wb") as f:
                                    f.write(requests.get(img_url, timeout=5).content)
                                sel_ids.add(cid)
                                new_sel += 1
                    except: continue
                log(f"  Loop {s}: +{new_sel} ads. (Total Selver: {len(sel_ids)})")
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(2)
        except Exception as e: log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI (Monthly URL Segments) ---
        log("--- [STAGE 2] RIMI (Monthly Segments) ---")
        rimi_saved = 0
        seen_ids = set() # This prevents duplicates across different month ranges

        for start_date, end_date in date_chunks:
            log(f"  [RANGE] Fetching: {start_date} to {end_date}")
            
            # Applying your specific URL format
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(10)

                btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
                if btn.count() > 0:
                    log(f"    Opening grid for {start_date}...")
                    btn.click()
                    time.sleep(8)
                else:
                    log(f"    No 'See all ads' for this range. Skipping.")
                    continue

                for i in range(20):
                    all_cards = page.locator("creative-preview")
                    cards_list = all_cards.all()
                    
                    found_this_loop = 0
                    duplicates_this_loop = 0
                    
                    for card in cards_list:
                        try:
                            h = card.locator("a").first.get_attribute("href", timeout=400)
                            if not h: continue
                            cid = h.split("creative/")[-1].split("?")[0]
                            
                            # DUPLICATE PROTECTION
                            if cid in seen_ids:
                                duplicates_this_loop += 1
                                continue
                            
                            seen_ids.add(cid)
                            
                            name_el = card.locator(".advertiser-name")
                            if name_el.count() > 0 and "Media House" in name_el.first.inner_text():
                                img = card.locator("img").first.get_attribute("src")
                                if img:
                                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                                        f.write(requests.get(img, timeout=5).content)
                                    rimi_saved += 1
                                    found_this_loop += 1
                        except: continue
                    
                    log(f"    Loop {i}: +{found_this_loop} new, {duplicates_this_loop} skipped. (Rimi Total: {rimi_saved})")
                    
                    # If we aren't finding anything new for 4 loops, this month is exhausted
                    if i > 4 and found_this_loop == 0:
                        log("    Month exhausted. Moving to next range.")
                        break

                    page.evaluate("window.scrollBy(0, 1200)")
                    time.sleep(3)

            except Exception as e:
                log(f"    Error in {start_date} range: {e}")
                continue

        browser.close()
        log("--- FINAL REPORT ---")
        log(f"Total Selver Ads: {len(sel_ids)}")
        log(f"Total Rimi (Media House) Ads: {rimi_saved}")
        log("!!! ALL STAGES COMPLETE !!!")

if __name__ == "__main__":
    run_scraper()
