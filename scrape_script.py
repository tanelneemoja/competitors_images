import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING TARGETED RIMI CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # Use the specific ID confirmed in your HTML
    TARGET_ID = "AR17608295264152453121"

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
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER (Static ID) ---
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

        # --- STAGE 2: RIMI (Deep Link Inspection) ---
        log(f"--- [STAGE 2] RIMI (Targeting {TARGET_ID}) ---")
        rimi_saved = 0
        global_seen_ids = set()

        for start, end in date_chunks:
            log(f"  [RANGE] {start} to {end}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start}&end-date={end}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(10)

                # Expansion Button
                btn = page.locator(".grid-expansion-button")
                if btn.count() > 0:
                    btn.click()
                    time.sleep(5)

                for i in range(20):
                    # Locate all preview cards (including priority-creative-grid)
                    cards = page.locator("creative-preview").all()
                    found_new = 0
                    
                    for card in cards:
                        try:
                            # 1. Look for any link containing our ID inside this specific card
                            links = card.locator("a").all()
                            match_found = False
                            creative_id = "unknown"
                            
                            for link in links:
                                href = link.get_attribute("href") or ""
                                if TARGET_ID in href:
                                    match_found = True
                                    # Try to extract Creative ID from the URL
                                    if "/creative/" in href:
                                        creative_id = href.split("creative/")[-1].split("?")[0]
                                    break
                            
                            if match_found and creative_id not in global_seen_ids:
                                global_seen_ids.add(creative_id)
                                found_new += 1
                                
                                # Find the actual image
                                img_tag = card.locator("img").first
                                img_url = img_tag.get_attribute("src")
                                
                                if img_url:
                                    res = requests.get(img_url, timeout=10)
                                    with open(f"data/Rimi/{creative_id}.png", "wb") as f:
                                        f.write(res.content)
                                    rimi_saved += 1
                                    log(f"    [MATCH] Saved Rimi Ad: {creative_id}")

                        except Exception: continue

                    if found_new == 0 and i > 5: break
                    
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(3)

            except Exception as e:
                log(f"    [ERROR] Range failed: {e}")

        browser.close()
        log(f"!!! DONE !!! Selver: {len(sel_ids)} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
