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
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    date_chunks = [
        ("2026-03-01", "2026-03-11"),
        ("2026-02-01", "2026-02-28"),
        ("2026-01-01", "2026-01-31"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # --- STAGE 1: SELVER (Working Direct Link) ---
        log("--- [STAGE 1] SELVER (Direct Scan) ---")
        sel_ids = set()
        try:
            # Selver uses a direct advertiser ID link which is more stable
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            
            for s in range(10): # Scroll 10 times to capture the history
                cards = page.locator("creative-preview").all()
                new_sel_this_scroll = 0
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
                                new_sel_this_scroll += 1
                    except: continue
                
                log(f"  Scroll {s}: Found {new_sel_this_scroll} new Selver ads. (Total: {len(sel_ids)})")
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(2)
        except Exception as e: 
            log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI ---
        log("--- [STAGE 2] RIMI (Brute-Force Matcher) ---")
        rimi_total_saved = 0
        global_seen_ids = set()
        
        TARGET_ID = "AR17608295264152453121" 
        TARGET_NAME = "media house"

        for start_date, end_date in date_chunks:
            log(f"  [STARTING RANGE] {start_date} to {end_date}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(8)

                # Expansion Logic for Rimi's "See all ads" gatekeeper
                expand_btn = page.get_by_text("See all ads", exact=True)
                if expand_btn.count() > 0 and expand_btn.is_visible():
                    log("    [ACTION] Clicking 'See all ads'...")
                    expand_btn.click()
                    time.sleep(5)

                count_el = page.locator(".ads-count").first
                target_total = 0
                if count_el.count() > 0:
                    target_total = int(re.sub(r'\D', '', count_el.inner_text()))
                    log(f"    [INFO] Range Target: {target_total} ads.")

                for i in range(25): 
                    cards = page.locator("creative-preview").all()
                    analyzed_this_loop = 0
                    matches_this_loop = 0
                    
                    for card in cards:
                        try:
                            h_elem = card.locator("a").first
                            href = h_elem.get_attribute("href")
                            if not href: continue
                            cid = href.split("creative/")[-1].split("?")[0]
                            
                            if cid not in global_seen_ids:
                                global_seen_ids.add(cid)
                                analyzed_this_loop += 1
                                
                                card_content = card.inner_html().lower()
                                if (TARGET_ID in href) or (TARGET_NAME in card_content):
                                    img_url = card.locator("img").first.get_attribute("src")
                                    if img_url:
                                        res = requests.get(img_url, timeout=10)
                                        with open(f"data/Rimi/{cid}.png", "wb") as f:
                                            f.write(res.content)
                                        rimi_total_saved += 1
                                        matches_this_loop += 1
                        except: continue

                    log(f"    Loop {i}: Analyzed {analyzed_this_loop} new. Saved: {matches_this_loop}. (Total: {len(global_seen_ids)})")
                    
                    if target_total > 0 and len(global_seen_ids) >= target_total:
                        break

                    page.evaluate("window.scrollBy(0, 800)")
                    time.sleep(3)

            except Exception as e:
                log(f"    [ERROR] Range failed: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Selver: {len(sel_ids)} | Rimi: {rimi_total_saved}")

if __name__ == "__main__":
    run_scraper()
