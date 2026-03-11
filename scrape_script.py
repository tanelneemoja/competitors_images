import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING REFINED SEGMENTED CRAWLER !!!")
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
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER ---
        sel_ids = set()
        try:
            log("--- [STAGE 1] SELVER ---")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            for s in range(8):
                cards = page.locator("creative-preview").all()
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img_url = card.locator("img").first.get_attribute("src", timeout=500)
                            if img_url:
                                with open(f"data/Selver/{cid}.png", "wb") as f:
                                    f.write(requests.get(img_url).content)
                                sel_ids.add(cid)
                    except: continue
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(2)
            log(f"  Selver Done: {len(sel_ids)}")
        except Exception as e: log(f"Selver Err: {e}")

        # --- STAGE 2: RIMI ---
        log("--- [STAGE 2] RIMI ---")
        rimi_saved = 0
        # IMPORTANT: Fresh set for Rimi so Selver IDs don't cause skips
        rimi_seen = set() 

        for start_date, end_date in date_chunks:
            log(f"  [RANGE] {start_date} to {end_date}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(8)

                btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
                if btn.count() > 0:
                    btn.click()
                    time.sleep(8)

                for i in range(15):
                    all_cards = page.locator("creative-preview")
                    cards_list = all_cards.all()
                    
                    found_now = 0
                    for card in cards_list:
                        try:
                            h = card.locator("a").first.get_attribute("href", timeout=300)
                            if not h: continue
                            cid = h.split("creative/")[-1].split("?")[0]
                            
                            if cid in rimi_seen: continue
                            rimi_seen.add(cid)
                            
                            # Broadened check for Media House
                            name_el = card.locator(".advertiser-name")
                            if name_el.count() > 0:
                                adv_text = name_el.first.inner_text().lower()
                                if "media house" in adv_text:
                                    img = card.locator("img").first.get_attribute("src")
                                    if img:
                                        with open(f"data/Rimi/{cid}.png", "wb") as f:
                                            f.write(requests.get(img).content)
                                        rimi_saved += 1
                                        found_now += 1
                        except: continue
                    
                    if found_now > 0:
                        log(f"    Loop {i}: +{found_now} ads. (Total Rimi: {rimi_saved})")
                    
                    page.evaluate("window.scrollBy(0, 1200)")
                    time.sleep(3)
                    
                    # If we see 100+ ads in the DOM and found nothing new, move on
                    if i > 3 and found_now == 0:
                        break

            except Exception as e: continue

        browser.close()
        log(f"!!! FINISHED !!! Selver: {len(sel_ids)} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
