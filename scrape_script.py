import os
import requests
import time
import re
import sys
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING BOOT SEQUENCE !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        log("Launching Browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1000})
        page = context.new_page()
        
        # --- STAGE 1: SELVER (Optimized for 80+ Cards) ---
        try:
            log("--- [STAGE 1] SELVER ---")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            
            sel_ids = set()
            # Capture phase
            for s in range(3): # Fewer loops needed if 80 load at once
                cards = page.locator("creative-preview").all()
                log(f"  Loop {s}: Found {len(cards)} cards. Extracting metadata...")
                
                batch_to_download = []
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img_url = card.locator("img").first.get_attribute("src", timeout=500)
                            if img_url:
                                batch_to_download.append((cid, img_url))
                                sel_ids.add(cid)
                        # Remove from UI immediately to stop the hang
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue
                
                # Download phase (Faster outside the browser interaction)
                for cid, img_url in batch_to_download:
                    try:
                        with open(f"data/Selver/{cid}.png", "wb") as f:
                            f.write(requests.get(img_url, timeout=5).content)
                    except: continue
                
                log(f"  Saved {len(batch_to_download)} new Selver ads. Total: {len(sel_ids)}")
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(2)
        except Exception as e: log(f"Selver Err: {e}")

        # --- STAGE 2: RIMI (The Loop Breaker) ---
        try:
            log("--- [STAGE 2] RIMI ---")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(8)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                log("  [ACTION] Clicking 'See all ads'...")
                btn.click()
                time.sleep(10)

            rimi_saved = 0
            seen_ids = set()

            for i in range(50):
                all_cards = page.locator("creative-preview")
                count = all_cards.count()
                log(f"  [RIMI] Loop {i}: {count} ads on screen.")

                if count < 5:
                    log("  [STATUS] Triggering Deep Teleport...")
                    page.evaluate("window.scrollBy(0, 2500)")
                    time.sleep(5)
                    continue

                cards_list = all_cards.all()
                processed_this_loop = 0
                
                for card in cards_list:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        
                        if cid in seen_ids:
                            page.evaluate("(el) => el.remove()", card.element_handle())
                            continue
                        
                        seen_ids.add(cid)
                        processed_this_loop += 1
                        
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            adv = name_el.first.inner_text().strip()
                            if "Media House" in adv:
                                img = card.locator("img").first.get_attribute("src")
                                with open(f"data/Rimi/{cid}.png", "wb") as f:
                                    f.write(requests.get(img, timeout=5).content)
                                rimi_saved += 1
                                log(f"    >>> FOUND MEDIA HOUSE: {cid}")
                        
                        page.evaluate("(el) => { el.style.display = 'none'; el.remove(); }", card.element_handle())
                    except: continue

                log(f"  [RIMI] Loop {i} done. Processed {processed_this_loop} new items.")
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(2)

        except Exception as e: log(f"Rimi Err: {e}")

        browser.close()
        log(f"!!! FINISHED !!! Selver: {len(sel_ids)} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
