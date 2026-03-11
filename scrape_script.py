import os
import requests
import time
import re
import sys
from playwright.sync_api import sync_playwright

# FORCES immediate log visibility in GitHub Actions
def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! SCRIPT STARTING !!!")
    
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)
        log(f"Verified directory: {folder}")

    with sync_playwright() as p:
        log("Launching Headless Chromium...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        # --- SECTION 1: SELVER ---
        try:
            log("Navigating to Selver (Direct ID)...")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            
            selver_ids = set()
            for s in range(10):
                cards = page.locator("creative-preview").all()
                log(f"  [SELVER] Loop {s}: Found {len(cards)} cards on screen.")
                
                for card in cards:
                    try:
                        href = card.locator("a").first.get_attribute("href", timeout=1000)
                        cr_id = href.split("creative/")[-1].split("?")[0]
                        if cr_id not in selver_ids:
                            img = card.locator("img").first.get_attribute("src", timeout=1000)
                            if img:
                                with open(f"data/Selver/{cr_id}.png", "wb") as f:
                                    f.write(requests.get(img, timeout=10).content)
                                selver_ids.add(cr_id)
                                log(f"    + Saved Selver Ad: {cr_id}")
                        
                        # Remove to keep DOM clean
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue
                
                page.evaluate("window.scrollBy(0, 1000)")
                log(f"  [SELVER] Total so far: {len(selver_ids)}")
                time.sleep(2)
        except Exception as e:
            log(f"Selver Stage Error: {e}")

        # --- SECTION 2: RIMI ---
        try:
            log("Navigating to Rimi (Domain Search)...")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(8)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                log("[ACTION] Clicking 'See all ads' to expand Rimi grid...")
                btn.click()
                time.sleep(10) 
            else:
                log("[WARN] 'See all ads' button missing. Page might be blank or auto-expanded.")

            rimi_saved = 0
            total_processed = 0

            for i in range(50): # 50 loops to ensure we find Media House ads
                all_cards = page.locator("creative-preview")
                card_count = all_cards.count()
                
                # HEARTBEAT: Always log, even if 0 ads
                log(f"  [RIMI] Loop {i}/50: {card_count} ads currently visible.")

                if card_count == 0:
                    log("    (No ads visible. Scrolling to trigger load...)")
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(4)
                    if i == 5: # Screenshot if stuck at 0
                        page.screenshot(path="data/rimi_empty_debug.png")
                        log("    [DEBUG] Captured 'rimi_empty_debug.png' because grid is empty.")
                    continue

                cards_list = all_cards.all()
                for card in cards_list[:15]: 
                    total_processed += 1
                    try:
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            adv_name = name_el.first.inner_text().strip()
                            
                            if "Media House" in adv_name:
                                href = card.locator("a").first.get_attribute("href")
                                cr_id = href.split("creative/")[-1].split("?")[0]
                                
                                if not os.path.exists(f"data/Rimi/{cr_id}.png"):
                                    img_src = card.locator("img").first.get_attribute("src")
                                    with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                        f.write(requests.get(img_src, timeout=10).content)
                                    rimi_saved += 1
                                    log(f"    MATCH: Saved Media House Ad {cr_id}")
                            else:
                                # Log occasionally so you know it's working
                                if total_processed % 20 == 0:
                                    log(f"    (Skipping ad by: {adv_name})")

                        # PURGE: Delete from DOM to prevent "Again and Again"
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue

                page.evaluate("window.scrollBy(0, 600)")
                time.sleep(2)

        except Exception as e:
            log(f"Rimi Stage Error: {e}")

        browser.close()
        log("!!! SCRIPT FINISHED !!!")
        log(f"Final Count -> Selver: {len(selver_ids) if 'selver_ids' in locals() else 0} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
