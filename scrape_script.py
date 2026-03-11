import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING FULL BRUTE-FORCE CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    date_chunks = [
        ("2026-03-01", "2026-03-11"),
        ("2026-02-01", "2026-02-28"),
        ("2026-01-01", "2026-01-31"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Larger viewport helps trigger more lazy-loading
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # --- STAGE 1: SELVER (Omitted for brevity, keep your existing logic) ---

        # --- STAGE 2: RIMI ---
        log("--- [STAGE 2] RIMI (Brute-Force Matcher) ---")
        rimi_total_saved = 0
        global_seen_ids = set()
        
        # Exact ID and Name from your HTML snippet
        TARGET_ID = "AR17608295264152453121" 
        TARGET_NAME = "media house"

        for start_date, end_date in date_chunks:
            log(f"  [STARTING RANGE] {start_date} to {end_date}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start_date}&end-date={end_date}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(8)

                # TRIGGER EXPANSION: This is why it stays at 16 ads
                # We search for the "See all ads" or any button that expands the view
                expand_btn = page.locator("button:has-text('See all ads')")
                if expand_btn.count() > 0:
                    log("    [ACTION] Expanding 'See all ads' grid...")
                    expand_btn.click()
                    time.sleep(5)

                # Re-verify total count after expansion
                count_el = page.locator(".ads-count").first
                target_count = 58 # Default fallback
                if count_el.count() > 0:
                    target_count = int(re.sub(r'\D', '', count_el.inner_text()))
                    log(f"    [INFO] Detected {target_count} ads in range.")

                for i in range(20): # Loop to scroll and capture
                    cards = page.locator("creative-preview").all()
                    analyzed_this_loop = 0
                    matches_this_loop = 0
                    
                    for card in cards:
                        try:
                            # Use href as unique ID
                            h_elem = card.locator("a").first
                            href = h_elem.get_attribute("href")
                            if not href: continue
                            
                            cid = href.split("creative/")[-1].split("?")[0]
                            
                            if cid not in global_seen_ids:
                                global_seen_ids.add(cid)
                                analyzed_this_loop += 1
                                
                                # CRITICAL: Wait for text/advertiser name to actually load
                                # Brute force check on the HTML content
                                card_html = card.inner_html().lower()
                                
                                if (TARGET_ID in href) or (TARGET_NAME in card_html):
                                    img_tag = card.locator("img").first
                                    img_url = img_tag.get_attribute("src")
                                    
                                    if img_url:
                                        r = requests.get(img_url, timeout=10)
                                        with open(f"data/Rimi/{cid}.png", "wb") as f:
                                            f.write(r.content)
                                        rimi_total_saved += 1
                                        matches_this_loop += 1
                        except: continue

                    log(f"    Loop {i}: Analyzed {analyzed_this_loop} new. Matched: {matches_this_loop}. (Range Total: {len(global_seen_ids)})")
                    
                    # If we found nothing new, scroll and wait
                    page.evaluate("window.scrollBy(0, 800)")
                    time.sleep(3)

                    # Break if we've processed roughly the target amount
                    if len(global_seen_ids) >= target_count and i > 5:
                        break

            except Exception as e:
                log(f"    [ERROR] Range failed: {e}")

        browser.close()
        log(f"!!! FINAL REPORT !!! Rimi (Matched Media House): {rimi_total_saved}")

if __name__ == "__main__":
    run_scraper()
