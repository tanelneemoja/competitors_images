import os
import requests
import time
import re
import sys # Added for flushing
from playwright.sync_api import sync_playwright

# Custom print function to ensure GitHub Actions shows logs IMMEDIATELY
def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_live_log_scraper():
    log("!!! SCRIPT STARTING !!!")
    
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
            log(f"Created directory: {folder}")

    with sync_playwright() as p:
        log("Launching Browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()
        page.set_default_timeout(60000) # 60s timeout for slow GitHub runners

        # --- SELVER SECTION ---
        try:
            log("Navigating to Selver...")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            
            selver_ids = set()
            for s in range(5):
                cards = page.locator("creative-preview").all()
                for card in cards:
                    try:
                        href = card.locator("a").first.get_attribute("href", timeout=500)
                        cr_id = href.split("creative/")[-1].split("?")[0]
                        if cr_id not in selver_ids:
                            img = card.locator("img").first.get_attribute("src", timeout=500)
                            if img:
                                with open(f"data/Selver/{cr_id}.png", "wb") as f:
                                    f.write(requests.get(img, timeout=10).content)
                                selver_ids.add(cr_id)
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue
                page.evaluate("window.scrollBy(0, 1000)")
                log(f"Selver Progress: {len(selver_ids)} ads saved.")
                time.sleep(2)
        except Exception as e:
            log(f"Selver Error: {e}")

        # --- RIMI SECTION ---
        try:
            log("Navigating to Rimi...")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(7)

            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                log("Clicking 'See all ads'...")
                btn.click()
                time.sleep(5)

            rimi_saved = 0
            # Reduced to 30 loops to ensure it finishes within GitHub's typical window
            for i in range(30):
                cards = page.locator("creative-preview").all()
                if not cards:
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(3)
                    continue

                for card in cards:
                    try:
                        name_el = card.locator(".advertiser-name")
                        # Real-time check for Media House
                        if name_el.count() > 0 and "Media House" in name_el.inner_text():
                            href = card.locator("a").first.get_attribute("href")
                            cr_id = href.split("creative/")[-1].split("?")[0]
                            img = card.locator("img").first.get_attribute("src")
                            with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                f.write(requests.get(img, timeout=10).content)
                            rimi_saved += 1
                            log(f"FOUND: Media House Ad {cr_id}")

                        # PURGE: Delete from DOM to prevent "Again and Again"
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue

                log(f"Rimi Loop {i}/30 - Cleared batch. Total Media House: {rimi_saved}")
                page.evaluate("window.scrollBy(0, 500)")
                time.sleep(1)

        except Exception as e:
            log(f"Rimi Error: {e}")

        browser.close()
        log(f"FINAL REPORT - Selver: {len(selver_ids)} | Rimi: {rimi_saved}")

if __name__ == "__main__":
    run_live_log_scraper()
