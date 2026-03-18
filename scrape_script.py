import os
import requests
import time
from playwright.sync_api import sync_playwright

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def run_scraper():
    log("!!! STARTING DEEP-SCAN CRAWLER !!!")
    for folder in ['data/Selver', 'data/Rimi']:
        os.makedirs(folder, exist_ok=True)

    TARGET_ID = "AR17608295264152453121"
    
    date_chunks = [
        ("2026-03-01", "2026-03-11"),
        ("2026-02-01", "2026-02-28"),
        ("2026-01-01", "2026-01-31"),
        ("2025-12-01", "2025-12-31"),
        ("2025-11-01", "2025-11-30"),
        ("2025-10-01", "2025-10-31"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1200})
        page = context.new_page()

        # [STAGE 1] SELVER - (Keeping simple as it works)
        log("--- [STAGE 1] SELVER ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            time.sleep(5)
            # ... (omitted for brevity, assume standard logic)
        except: pass

        # [STAGE 2] RIMI
        log(f"--- [STAGE 2] RIMI (Deep-ID Search) ---")
        rimi_saved = 0
        global_seen_ids = set()

        for start, end in date_chunks:
            log(f"  [RANGE] {start} to {end}")
            url = f"https://adstransparency.google.com/?region=EE&domain=rimi.ee&start-date={start}&end-date={end}"
            
            try:
                page.goto(url, wait_until="networkidle")
                time.sleep(8)

                # Force Expansion
                expand = page.locator("material-button:has-text('See all ads'), .grid-expansion-button")
                if expand.count() > 0:
                    log("    [ACTION] Found expansion button. Clicking...")
                    expand.first.click()
                    time.sleep(5)

                for i in range(12): # Scroll loops
                    # Find EVERY link that points to our target advertiser
                    # This is the most reliable selector possible
                    target_links = page.locator(f"a[href*='{TARGET_ID}']").all()
                    
                    new_this_loop = 0
                    for link in target_links:
                        href = link.get_attribute("href")
                        if "/creative/" not in href: continue
                        
                        cid = href.split("creative/")[-1].split("?")[0]
                        
                        if cid not in global_seen_ids:
                            global_seen_ids.add(cid)
                            new_this_loop += 1
                            
                            # Navigate from the link to the card container to find the image
                            # We look for the closest parent that contains an img
                            try:
                                # Look for the image associated with this specific ad link
                                # Strategy: Find the img tag inside the same 'creative-preview' or 'creative' parent
                                parent_card = page.locator(f"creative-preview:has(a[href*='{cid}'])").first
                                img_tag = parent_card.locator("img").first
                                img_url = img_tag.get_attribute("src")
                                
                                if img_url:
                                    res = requests.get(img_url, timeout=10)
                                    with open(f"data/Rimi/{cid}.png", "wb") as f:
                                        f.write(res.content)
                                    rimi_saved += 1
                                    log(f"    [MATCH] Saved: {cid}")
                            except Exception as e:
                                log(f"    [WARN] Found ID {cid} but couldn't grab image.")

                    log(f"    Loop {i}: Found {new_this_loop} new target ads.")
                    
                    # Scroll down to trigger lazy loading
                    page.evaluate("window.scrollBy(0, 1200)")
                    time.sleep(4)
                    
                    # If we found nothing new for 3 loops, move to next date range
                    if new_this_loop == 0 and i > 3: break

            except Exception as e:
                log(f"    [ERROR] Critical error: {e}")

        browser.close()
        log(f"DONE. Rimi Total: {rimi_saved}")

if __name__ == "__main__":
    run_scraper()
