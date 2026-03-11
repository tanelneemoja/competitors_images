import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING HIGH-VISIBILITY CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        log("Launching Browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1200})
        page = context.new_page()
        
        # --- STAGE 1: SELVER ---
        try:
            log("--- [STAGE 1] SELVER ---")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            sel_ids = set()
            for s in range(12):
                cards = page.locator("creative-preview").all()
                new_in_loop = 0
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
                                new_in_loop += 1
                    except: continue
                log(f"  Loop {s}: Found {new_in_loop} new ads. (Total: {len(sel_ids)})")
                page.evaluate("window.scrollBy(0, 1500)")
                time.sleep(2)
        except Exception as e: log(f"Selver Error: {e}")

        # --- STAGE 2: RIMI ---
        try:
            log("--- [STAGE 2] RIMI (Deep Scan) ---")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(10)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                log("[ACTION] Clicking 'See all ads' to initialize 800-ad grid...")
                btn.click()
                time.sleep(10)

            rimi_saved = 0
            seen_ids = set()
            last_count = 0
            stall_count = 0

            # 250 loops to ensure we cover the 800 ads at a safe pace
            for i in range(250):
                all_cards = page.locator("creative-preview")
                current_count = all_cards.count()
                
                # STATUS LOG
                log(f"  [RIMI] Loop {i}: {current_count} ads in DOM | Target: ~800 | Saved: {rimi_saved}")

                if current_count == last_count and current_count > 0:
                    stall_count += 1
                else:
                    stall_count = 0
                last_count = current_count

                # THE KICK (To bypass the 218 wall)
                if stall_count >= 4:
                    log(f"  [ATTENTION] Stall detected ({stall_count}/10). Performing Scroll-Kick...")
                    page.evaluate("window.scrollBy(0, -1200)") # Kick Up
                    time.sleep(1)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)") # Kick Down
                    time.sleep(7) # Extra time for the loader to respond
                    
                    if stall_count >= 12:
                        log("  [HALT] Loader stopped responding. Ending Rimi stage.")
                        break

                cards_list = all_cards.all()
                processed_this_loop = 0
                
                for card in cards_list:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=300)
                        if not h: continue
                        cid = h.split("creative/")[-1].split("?")[0]
                        
                        if cid in seen_ids: 
                            continue # Skip ads we've already checked
                        
                        seen_ids.add(cid)
                        processed_this_loop += 1
                        
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            adv_name = name_el.first.inner_text().strip()
                            if "Media House" in adv_name:
                                img = card.locator("img").first.get_attribute("src")
                                if img and "http" in img:
                                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                                        f.write(requests.get(img, timeout=5).content)
                                    rimi_saved += 1
                                    log(f"    *** MATCH: Saved Media House Ad ({cid}) ***")
                    except: continue

                if processed_this_loop > 0:
                    log(f"    (Scan: {processed_this_loop} new ads checked this loop)")

                # Steady, incremental scrolling
                page.evaluate("window.scrollBy(0, 1100)")
                time.sleep(3)

        except Exception as e: log(f"Rimi Error: {e}")

        browser.close()
        log("--- FINAL SCRAPER REPORT ---")
        log(f"Selver Ads: {len(sel_ids) if 'sel_ids' in locals() else 0}")
        log(f"Rimi (Media House) Ads: {rimi_saved}")
        log("!!! PROCESS COMPLETE !!!")

if __name__ == "__main__":
    run_scraper()
