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
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 1000})
        page = context.new_page()
        
        # --- SELVER (Keep it fast) ---
        try:
            log("Stage 1: Selver")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            sel_ids = set()
            for _ in range(5):
                cards = page.locator("creative-preview").all()
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
                log(f"  Selver: {len(sel_ids)} ads.")
        except Exception as e: log(f"Selver Err: {e}")

        # --- RIMI (The Loop Breaker) ---
        try:
            log("Stage 2: Rimi (Media House Search)")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(8)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                btn.click()
                log("Expanded Grid. Waiting for load...")
                time.sleep(10)

            rimi_saved = 0
            seen_this_session = set()

            for i in range(60):
                all_cards = page.locator("creative-preview")
                count = all_cards.count()
                log(f"  [RIMI] Loop {i}: {count} ads on screen.")

                if count < 5:
                    log("  [PULSE] Page empty or stale. Teleporting scroll...")
                    page.evaluate("window.scrollBy(0, 2000)")
                    time.sleep(5)
                    continue

                cards_list = all_cards.all()
                for card in cards_list:
                    try:
                        # Get ID first to see if we've already "deleted" this one
                        h = card.locator("a").first.get_attribute("href", timeout=500)
                        cid = h.split("creative/")[-1].split("?")[0]
                        
                        if cid in seen_this_session:
                            page.evaluate("(el) => el.remove()", card.element_handle())
                            continue
                        
                        seen_this_session.add(cid)
                        
                        # Check for Media House
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            adv = name_el.first.inner_text().strip()
                            if "Media House" in adv:
                                if not os.path.exists(f"data/Rimi/{cid}.png"):
                                    img = card.locator("img").first.get_attribute("src")
                                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                                        f.write(requests.get(img).content)
                                    rimi_saved += 1
                                    log(f"    !!! SAVED MEDIA HOUSE: {cid}")

                        # FORCE REMOVAL via CSS + Remove (The One-Two Punch)
                        page.evaluate("(el) => { el.style.display = 'none'; el.remove(); }", card.element_handle())
                    except: continue

                # After clearing a batch, jump deep
                page.evaluate("window.scrollBy(0, 1200)")
                time.sleep(2)

        except Exception as e: log(f"Rimi Err: {e}")

        browser.close()
        log(f"COMPLETE. Selver: {len(sel_ids)} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
