import os
import requests
import time
import re
import sys
from playwright.sync_api import sync_playwright

# Forces logs to show up in GitHub Actions immediately
def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! SCRIPT STARTING !!!")
    
    # Create directories
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)
        log(f"Directory ready: {folder}")

    with sync_playwright() as p:
        log("Launching Browser...")
        browser = p.chromium.launch(headless=True)
        # Use a standard user agent to avoid bot detection
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.set_default_timeout(60000)

        # --- SECTION 1: SELVER (Stable ID) ---
        try:
            log("Navigating to Selver...")
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            
            selver_ids = set()
            for s in range(8):
                cards = page.locator("creative-preview").all()
                for card in cards:
                    try:
                        href = card.locator("a").first.get_attribute("href", timeout=1000)
                        cr_id = href.split("creative/")[-1].split("?")[0]
                        if cr_id not in selver_ids:
                            img = card.locator("img").first.get_attribute("src", timeout=1000)
                            if img and "http" in img:
                                resp = requests.get(img, timeout=10)
                                with open(f"data/Selver/{cr_id}.png", "wb") as f:
                                    f.write(resp.content)
                                selver_ids.add(cr_id)
                        # Delete to keep page light
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except: continue
                page.evaluate("window.scrollBy(0, 1000)")
                log(f"Selver Progress: {len(selver_ids)} ads saved.")
                time.sleep(2)
        except Exception as e:
            log(f"Selver Error: {e}")

        # --- SECTION 2: RIMI (Media House OÜ) ---
        try:
            log("Navigating to Rimi (Domain Search)...")
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            time.sleep(8)

            # Click the gatekeeper button
            btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if btn.count() > 0:
                log("Clicking 'See all ads' button...")
                btn.click()
                time.sleep(10) # Heavy wait for the grid to populate
            else:
                log("Warning: 'See all ads' button not found. It might have auto-expanded.")

            rimi_saved = 0
            for i in range(40): # 40 loops to go deep
                all_cards_locator = page.locator("creative-preview")
                count = all_cards_locator.count()
                
                # HEARTBEAT LOG
                log(f"Rimi Loop {i}/40: Browser sees {count} ads on screen.")

                if count == 0:
                    if i == 5: # If still nothing after 5 loops, take a diagnostic screenshot
                        page.screenshot(path="rimi_error.png")
                        log("Created rimi_error.png for debugging.")
                    
                    page.evaluate("window.scrollBy(0, 1000)")
                    time.sleep(4)
                    continue

                # Process a batch
                cards = all_cards_locator.all()
                for card in cards[:15]: 
                    try:
                        # Check advertiser name
                        name_el = card.locator(".advertiser-name")
                        if name_el.count() > 0:
                            adv_name = name_el.first.inner_text()
                            
                            if "Media House" in adv_name:
                                href = card.locator("a").first.get_attribute("href")
                                cr_id = href.split("creative/")[-1].split("?")[0]
                                
                                if not os.path.exists(f"data/Rimi/{cr_id}.png"):
                                    img_src = card.locator("img").first.get_attribute("src")
                                    if img_src and "http" in img_src:
                                        with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                            f.write(requests.get(img_src, timeout=10).content)
                                        rimi_saved += 1
                                        log(f" >> [MATCH] Saved Media House Ad: {cr_id}")

                        # PURGE: Always delete the element to force the next batch to load
                        page.evaluate("(el) => el.remove()", card.element_handle())
                    except:
                        continue

                # Gentle scroll to trigger lazy loading
                page.evaluate("window.scrollBy(0, 600)")
                time.sleep(2)

        except Exception as e:
            log(f"Rimi Error: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!!")
        log(f"Selver: {len(selver_ids) if 'selver_ids' in locals() else 0} ads")
        log(f"Rimi (Media House): {rimi_saved} ads")

if __name__ == "__main__":
    run_scraper()
