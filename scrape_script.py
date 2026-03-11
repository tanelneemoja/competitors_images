import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING PROTECTED SEQUENCE !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # Safety configurations
    MAX_RELOADS = 3
    STALL_THRESHOLD = 5 # Loops with same count before reloading

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()
        
        # --- STAGE 1: SELVER ---
        try:
            log("--- [STAGE 1] SELVER ---")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(8)
            
            sel_ids = set()
            for s in range(15):
                cards = page.locator("creative-preview").all()
                found_in_loop = 0
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
                                found_in_loop += 1
                    except: continue
                
                log(f"  Loop {s}: +{found_in_loop} ads. Total: {len(sel_ids)}")
                page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(3)
        except Exception as e: log(f"Selver Err: {e}")

        # --- STAGE 2: RIMI ---
        try:
            log("--- [STAGE 2] RIMI ---")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(10)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                btn.click()
                time.sleep(10)

            rimi_saved = 0
            seen_ids = set()
            last_count = 0
            stall_counter = 0
            reload_count = 0

            for i in range(60):
                all_cards = page.locator("creative-preview")
                current_count = all_cards.count()
                
                log(f"  [RIMI] Loop {i}: {current_count} ads visible. (Stall: {stall_counter}/{STALL_THRESHOLD})")

                # Stall Detection Logic
                if current_count > 0 and current_count == last_count:
                    stall_counter += 1
                else:
                    stall_counter = 0
                
                last_count = current_count

                if stall_counter >= STALL_THRESHOLD:
                    if reload_count < MAX_RELOADS:
                        reload_count += 1
                        log(f"  [CRITICAL] Stall detected! Reloading ({reload_count}/{MAX_RELOADS})...")
                        page.reload(wait_until="networkidle")
                        time.sleep(10)
                        stall_counter = 0
                        continue
                    else:
                        log("  [HALT] Max reloads reached. Moving to final report.")
                        break

                if current_count == 0:
                    page.evaluate("window.scrollBy(0, 1500)")
                    time.sleep(5)
                    continue

                # Content Scan
                cards_list = all_cards.all()
                for card in cards_list:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid in seen_ids: continue
                        seen_ids.add(cid)
                        
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            if "Media House" in name_el.first.inner_text():
                                img = card.locator("img").first.get_attribute("src")
                                with open(f"data/Rimi/{cid}.png", "wb") as f:
                                    f.write(requests.get(img, timeout=5).content)
                                rimi_saved += 1
                                log(f"    >>> MATCH: {cid}")
                    except: continue

                page.evaluate("window.scrollBy(0, 1800)")
                time.sleep(4)

        except Exception as e: log(f"Rimi Err: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Selver: {len(sel_ids) if 'sel_ids' in locals() else 0} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
