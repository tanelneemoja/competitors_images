import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING URL-BASED BRUTE-FORCE CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

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
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- STAGE 1: SELVER ---
        log("--- [STAGE 1] SELVER ---")
        sel_ids = set()
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            for _ in range(5):
                for card in page.locator("creative-preview").all():
                    try:
                        href = card.locator("a").first.get_attribute("href")
                        cid = href.split("creative/")[-1].split("?")[0]
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
        except Exception as e: log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI ---
        log("--- [STAGE 2] RIMI (URL-Targeting: Media House) ---")
        rimi_saved = 0
        global_seen_ids = set()
        TARGET_AR_ID = "AR17608295264152453121"

        for start, end in date_chunks:
            log(f"  [RANGE] {start} to {end}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start}&end-date={end}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(10)

                # Click Expand
                btn = page.locator(".grid-expansion-button")
                if btn.count() > 0:
                    log("    [ACTION] Clicking 'See all ads'...")
                    btn.click()
                    time.sleep(5)

                for i in range(20):
                    cards = page.locator("creative-preview").all()
                    found_new_this_loop = 0
                    matches_this_loop = 0
                    
                    for card in cards:
                        try:
                            anchor = card.locator("a").first
                            href = anchor.get_attribute("href")
                            if not href: continue
                            
                            # Extracting IDs for logging
                            creative_id = href.split("creative/")[-1].split("?")[0]
                            # Extracting the AR ID from the URL string
                            found_ar_id = href.split("/advertiser/")[1].split("/")[0]

                            if creative_id not in global_seen_ids:
                                global_seen_ids.add(creative_id)
                                found_new_this_loop += 1
                                
                                # LOG EVERY FIND TO CONSOLE
                                log(f"    [CHECK] ID: {creative_id} | Advertiser: {found_ar_id}")

                                if TARGET_AR_ID in href:
                                    img_url = card.locator("img").first.get_attribute("src")
                                    if img_url:
                                        res = requests.get(img_url, timeout=10)
                                        with open(f"data/Rimi/{creative_id}.png", "wb") as f:
                                            f.write(res.content)
                                        rimi_saved += 1
                                        matches_this_loop += 1
                                        log(f"    >>> MATCH SAVED: {creative_id}")
                        except Exception as e: continue

                    log(f"    Loop {i} Summary: {found_new_this_loop} new ads checked, {matches_this_loop} Rimi matches saved.")
                    
                    if found_new_this_loop == 0 and i > 4: 
                        break

                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(3)

            except Exception as e:
                log(f"    [ERROR] Critical failure in range: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Selver: {len(sel_ids)} | Rimi (Media House): {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
