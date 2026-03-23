import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 15 
GTC_TIMEOUT = 30000    

# Global counters
stats = {"new": 0, "replaced": 0, "broken": 0, "failed": 0}
failed_ads = []

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def process_link(context, row, index, total, semaphore):
    async with semaphore:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        url = str(row.get('creative_page_url', ''))
        ad_id = extract_id_from_url(url)
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [{index}/{total}] Checking {advertiser} | ID: {ad_id}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            # 1. Check for Expired/Unavailable
            if await page.locator(":text('isn\\'t available'), :text('Can\\'t find ad'), .empty-results").first.is_visible():
                log(f"   ⏩ SKIP: Ad link is dead/expired.")
                stats["broken"] += 1
                return

            # 2. Find Ad Container
            container_selectors = [
                '[data-testid="ad-library-dynamic-content-container"]', 
                '[data-testid*="carousel"]',                           
                '.creative-container',                                 
                'fletch-renderer'                                      
            ]
            
            container = None
            for sel in container_selectors:
                loc = page.locator(sel).first
                if await loc.is_visible():
                    container = loc
                    break

            if not container:
                reason = "Container not found (Possible new UI layout)"
                log(f"   ⚠️ FAIL: {reason}")
                failed_ads.append({"id": ad_id, "adv": advertiser, "url": url, "reason": reason})
                stats["failed"] += 1
                return

            # 3. Handle Carousel vs Static Naming
            next_btn = page.locator('div[role="button"][aria-label*="Next"], button[aria-label*="Next"], .next-button').first
            is_carousel = await next_btn.is_visible()

            if is_carousel:
                slide_idx = 1
                while True:
                    file_name = f"{ad_id}_{slide_idx}.png"
                    file_path = os.path.join(advertiser_dir, file_name)
                    
                    action = "REPLACED" if os.path.exists(file_path) else "ADDED"
                    if action == "REPLACED": stats["replaced"] += 1
                    else: stats["new"] += 1

                    await container.screenshot(path=file_path)
                    log(f"   📸 {action}: {file_name} (Carousel)")

                    if await next_btn.is_visible():
                        is_disabled = await next_btn.get_attribute("aria-disabled") == "true"
                        if is_disabled: break
                        await next_btn.click()
                        await asyncio.sleep(1.2)
                        slide_idx += 1
                        if slide_idx > 15: break
                    else:
                        break
            else:
                # Static / Google Ad
                file_name = f"{ad_id}.png"
                file_path = os.path.join(advertiser_dir, file_name)
                
                action = "REPLACED" if os.path.exists(file_path) else "ADDED"
                if action == "REPLACED": stats["replaced"] += 1
                else: stats["new"] += 1

                await container.screenshot(path=file_path)
                log(f"   📸 {action}: {file_name}")

        except Exception as e:
            err = str(e).split('\n')[0][:70]
            log(f"   ❌ ERROR on {ad_id}: {err}")
            failed_ads.append({"id": ad_id, "adv": advertiser, "url": url, "reason": err})
            stats["failed"] += 1
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        await asyncio.gather(*[process_link(context, row, i, len(df), semaphore) for i, (_, row) in enumerate(df.iterrows(), 1)])
        await browser.close()

    # --- FINAL DETAILED REPORT ---
    print("\n" + "="*30)
    print("      SCRAPE STATISTICS")
    print("="*30)
    print(f"✅ NEW IMAGES ADDED:    {stats['new']}")
    print(f"🔄 IMAGES REPLACED:     {stats['replaced']}")
    print(f"⏩ EXPIRED ADS SKIPPED: {stats['broken']}")
    print(f"❌ TECHNICAL FAILURES:  {stats['failed']}")
    print("="*30)

    if failed_ads:
        print("\n" + "!"*10 + " FAILURE AUDIT LOG " + "!"*10)
        for f in failed_ads:
            print(f"ADVERTISER: {f['adv']}\nID:         {f['id']}\nWHY:        {f['reason']}\nURL:        {f['url']}\n" + "-"*30)

if __name__ == "__main__":
    asyncio.run(main())
