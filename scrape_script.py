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
        
        # --- STAGE 1: SELVER ---
        try:
            log("--- [STAGE 1] SELVER ---")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            sel_ids = set()
            for s in range(5):
                cards = page.locator("creative-preview").all()
                log(f"  Loop {s}: Processing {len(cards)} cards.")
                for card in cards:
                    try:
                        h = card.locator("a").first.get_attribute("href")
                        cid = h.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img = card.locator("img").first.get_attribute("src")
                            with open(f"data/Selver/{cid}.png", "wb") as f:
                                f.write(requests.get(img).content)
                            sel_ids.add(cid)
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(2)
            log(f"  Selver Complete: {len(sel_ids)} ads saved.")
        except Exception as e: log(f"Selver Err: {e}")

        # --- STAGE 2: RIMI ---
        try:
            log("--- [STAGE 2] RIMI (The Loop Breaker) ---")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(8)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                log("  [ACTION] Clicking 'See all ads'...")
                btn.click()
                time.sleep(10)

            rimi_saved = 0
            seen_this_session = set()

            for i in range(60):
                all_cards = page.locator("creative-preview")
                count = all_cards.count()
                
                # HEARTBEAT
                log(f"  [RIMI] Loop {i}: {count} ads detected on page.")

                if count < 5:
                    log("  [STATUS] Page looks empty. Triggering Deep Teleport (2500px)...")
                    page.evaluate("window.scrollBy(0, 2500)")
                    time.sleep(5)
                    continue

                cards_list = all_cards.all()
                processed_in_loop = 0
                
                for card in cards_list:
                    try:
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        
                        # ANTI-LOOP CHECK
                        if cid in seen_this_session:
                            page.evaluate("(el) => el.remove()", card.element_handle())
                            continue
                        
                        seen_this_session.add(cid)
                        processed_in_loop += 1
                        
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            adv = name_el.first.inner_text().strip()
                            if "Media House" in adv:
                                if not os.path.exists(f"data/Rimi/{cid}.png"):
                                    img = card.locator("img").first.get_attribute("src")
                                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                                        f.write(requests.get(img).content)
                                    rimi_saved += 1
                                    log(f"    >>> FOUND MEDIA HOUSE: {cid} (Total: {rimi_saved})")
                            else:
                                # Detailed log so you know it's not "stuck"
                                if processed_in_loop % 15 == 0:
                                    log(f"    (Filtering: skipping {adv}...)")

                        # NUCLEAR REMOVAL
                        page.evaluate("(el) => { el.style.display = 'none'; el.remove(); }", card.element_handle())
                    except: continue

                log(f"  [RIMI] Loop {i} finished. Processed {processed_in_loop} new items.")
                page.evaluate("window.scrollBy(0, 1200)")
                time.sleep(2)

        except Exception as e: log(f"Rimi Err: {e}")

        browser.close()
        log(f"!!! FINISHED !!! Selver: {len(sel_ids) if 'sel_ids' in locals() else 0} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
