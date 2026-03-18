import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING PRIORITY-AWARE SCRAPER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    # Media House ID from your HTML
    TARGET_AR_ID = "AR17608295264152453121"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # --- [STAGE 1] SELVER (STAYS THE SAME) ---
        log("--- [STAGE 1] SELVER ---")
        sel_ids = set()
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            for _ in range(3):
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
        except Exception as e: log(f"Selver Error: {e}")

        # --- [STAGE 2] RIMI (UPDATED SELECTORS) ---
        log(f"--- [STAGE 2] RIMI (Targeting: {TARGET_AR_ID}) ---")
        
        # We use your specific date range URL
        rimi_url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date=2026-03-01&end-date=2026-03-18"
        page.goto(rimi_url, wait_until="networkidle")
        
        # Wait specifically for the elements in your HTML to appear
        log("Waiting for Priority Grid to load...")
        try:
            page.wait_for_selector("priority-creative-grid", timeout=15000)
        except:
            log("Priority grid not found, trying standard grid...")

        # Expansion logic
        expand = page.locator(".grid-expansion-button").first
        if expand.is_visible():
            log("Expanding 'See all ads'...")
            expand.click()
            time.sleep(5)

        # Collect ALL links matching the Advertiser ID anywhere on the page
        ad_links = page.locator(f"a[href*='{TARGET_AR_ID}']").all()
        detail_urls = []
        for link in ad_links:
            href = link.get_attribute("href")
            if href and "/creative/" in href:
                if href not in detail_urls:
                    detail_urls.append(href)
        
        log(f"Found {len(detail_urls)} unique Rimi ads in the grid.")

        # Process detail pages
        for rel_url in detail_urls:
            full_url = f"https://adstransparency.google.com{rel_url}"
            cid = rel_url.split("creative/")[-1].split("?")[0]
            
            log(f"  [RIMI] Inspecting {cid}")
            try:
                page.goto(full_url, wait_until="networkidle")
                time.sleep(6) # Essential for iframe rendering

                img_src = None
                for frame in page.frames:
                    if "/adframe" in frame.url or "google" in frame.url:
                        # 1. Try your specific marketing-image ID
                        img_el = frame.locator("#marketing-image")
                        if img_el.count() > 0:
                            img_src = img_el.get_attribute("src")
                        
                        # 2. Try the simgad archive fallback (seen in your HTML)
                        if not img_src:
                            simgad = frame.locator("img[src*='simgad']").first
                            if simgad.count() > 0:
                                img_src = simgad.get_attribute("src")
                        
                        if img_src: break

                if img_src:
                    r = requests.get(img_src, timeout=15)
                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                        f.write(r.content)
                    log(f"    >>> SUCCESS: Image saved.")
                else:
                    log(f"    [FAIL] No image found in frames.")

            except Exception as e:
                log(f"    [ERROR] {cid}: {e}")

        browser.close()
        log("DONE.")

if __name__ == "__main__":
    run_scraper()
