import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING COMBINED SCRAPER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    TARGET_AR_ID = "AR17608295264152453121"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # --- [STAGE 1] SELVER (UNTOUCHED - AS REQUESTED) ---
        log("--- [STAGE 1] SELVER ---")
        sel_ids = set()
        try:
            # Using your existing Selver link/logic
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            for _ in range(5):
                for card in page.locator("creative-preview").all():
                    try:
                        href = card.locator("a").first.get_attribute("href")
                        cid = href.split("creative/")[-1].split("?")[0]
                        if cid not in sel_ids:
                            img = card.locator("img").first.get_attribute("src")
                            if img:
                                r = requests.get(img, timeout=10)
                                with open(f"data/Selver/{cid}.png", "wb") as f:
                                    f.write(r.content)
                                sel_ids.add(cid)
                                log(f"  [SELVER] Saved: {cid}")
                    except: continue
                page.evaluate("window.scrollBy(0, 1000)")
                time.sleep(2)
        except Exception as e: 
            log(f"Selver Error: {e}")

        # --- [STAGE 2] RIMI (NEW IFRAME-PIERCING LOGIC) ---
        log(f"--- [STAGE 2] RIMI (Targeting: {TARGET_AR_ID}) ---")
        
        # 1. Collect the URLs from the grid first
        log("Accessing Rimi grid to collect ad URLs...")
        page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
        time.sleep(8)

        expand = page.locator(".grid-expansion-button").first
        if expand.is_visible():
            expand.click()
            time.sleep(4)

        ad_links = page.locator(f"a[href*='{TARGET_AR_ID}']").all()
        detail_urls = list(set([link.get_attribute("href") for link in ad_links if "/creative/" in link.get_attribute("href")]))
        log(f"Found {len(detail_urls)} Rimi ads to inspect individually.")

        # 2. Visit each detail page and pierce the iframe
        for rel_url in detail_urls:
            full_url = f"https://adstransparency.google.com{rel_url}"
            cid = rel_url.split("creative/")[-1].split("?")[0]
            
            log(f"  [INSPECTING RIMI] {cid}")
            try:
                page.goto(full_url, wait_until="networkidle")
                time.sleep(5) # Wait for the 'Fletch' script to build the iframe

                img_src = None
                for frame in page.frames:
                    if "/adframe" in frame.url:
                        # Specifically targeting the element you found
                        img_element = frame.locator("#marketing-image")
                        try:
                            img_element.wait_for(state="attached", timeout=3000)
                            img_src = img_element.get_attribute("src")
                            if img_src: break
                        except:
                            # Fallback to any simgad image in the frame
                            fallback = frame.locator("img[src*='simgad']").first
                            if fallback.count() > 0:
                                img_src = fallback.get_attribute("src")
                                break

                if img_src:
                    r = requests.get(img_src, timeout=10)
                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                        f.write(r.content)
                    log(f"    >>> Saved high-res image for {cid}")
                else:
                    log(f"    [SKIP] Could not find image in frames for {cid}")

            except Exception as e:
                log(f"    [ERROR] Failed Rimi ad {cid}: {e}")

        browser.close()
        log("DONE. Check data/Selver and data/Rimi folders.")

if __name__ == "__main__":
    run_scraper()
