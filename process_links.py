import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 3  # Lowered slightly for better stability on GTC
GTC_TIMEOUT = 45000    # GTC can be slow to render specific CR blocks

stats = {"new": 0, "replaced": 0, "broken": 0, "failed": 0}
audit_log = []

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def process_link(context, row, seq_num, total, semaphore):
    async with semaphore:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        url = str(row.get('creative_page_url', ''))
        ad_id = extract_id_from_url(url)
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🔍 [Seq: {seq_num}] Starting ID: {ad_id} ({advertiser})")
            await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)

            # 1. Check for Expired/Broken Links
            expired_selectors = [":text('isn\\'t available')", ":text('Can\\'t find ad')", ".empty-results"]
            is_expired = False
            for sel in expired_selectors:
                if await page.locator(sel).first.is_visible():
                    is_expired = True
                    break
            
            if is_expired:
                log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad expired/unavailable at URL: {url}")
                stats["broken"] += 1
                return

            # 2. TARGETING LOGIC: Find the element matching the ID from the URL
            # We look for an anchor tag (<a>) that contains the Ad ID in its href
            specific_ad_locator = page.locator(f"a[href*='{ad_id}']").first
            
            # Fallback selectors if the direct ID-link isn't found (Meta vs Google)
            containers = [
                specific_ad_locator,
                page.locator('[data-testid="ad-library-dynamic-content-container"]').first,
                page.locator('.creative-container').first,
                page.locator('fletch-renderer').first
            ]

            target_element = None
            for loc in containers:
                if await loc.count() > 0 and await loc.is_visible():
                    target_element = loc
                    break

            if not target_element:
                reason = "Target element not found on page"
                log(f"   ⚠️ [Seq: {seq_num}] FAIL: {reason} | URL: {url}")
                audit_log.append({"seq": seq_num, "id": ad_id, "reason": reason, "url": url})
                stats["failed"] += 1
                return

            # 3. CAROUSEL CHECK (Meta Only)
            next_btn = page.locator('div[role="button"][aria-label*="Next"], button[aria-label*="Next"]').first
            is_carousel = await next_btn.is_visible()

            if is_carousel:
                slide_idx = 1
                while True:
                    file_name = f"{ad_id}_{slide_idx}.png"
                    file_path = os.path.join(advertiser_dir, file_name)
                    
                    status = "REPLACED" if os.path.exists(file_path) else "ADDED"
                    if status == "REPLACED": stats["replaced"] += 1
                    else: stats["new"] += 1

                    await target_element.screenshot(path=file_path)
                    log(f"   📸 [Seq: {seq_num}] {status}: {file_name}")

                    if await next_btn.is_visible():
                        is_disabled = await next_btn.get_attribute("aria-disabled") == "true"
                        if is_disabled: break
                        await next_btn.click()
                        await asyncio.sleep(1.5)
                        slide_idx += 1
                        if slide_idx > 10: break # Safety cap
                    else:
                        break
            else:
                # Static Image / GTC Ad
                file_name = f"{ad_id}.png"
                file_path = os.path.join(advertiser_dir, file_name)
                
                status = "REPLACED" if os.path.exists(file_path) else "ADDED"
                if status == "REPLACED": stats["replaced"] += 1
                else: stats["new"] += 1

                await target_element.screenshot(path=file_path)
                log(f"   📸 [Seq: {seq_num}] {status}: {file_name}")

        except Exception as e:
            err_short = str(e).split('\n')[0][:60]
            log(f"   ❌ [Seq: {seq_num}] ERROR: {err_short}")
            audit_log.append({"seq": seq_num, "id": ad_id, "reason": err_short, "url": url})
            stats["failed"] += 1
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found.")
        return

    df = pd.read_csv(CSV_FILE)
    total_ads = len(df)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a realistic User Agent to help GTC load properly
        context = await browser.new_context(
            viewport={'width': 1440, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        tasks = []
        for i, (_, row) in enumerate(df.iterrows(), 1):
            tasks.append(process_link(context, row, i, total_ads, semaphore))
        
        await asyncio.gather(*tasks)
        await browser.close()

    # --- FINAL REPORT ---
    print("\n" + "="*40)
    print(f"SCRAPE FINISHED | TOTAL PROCESSED: {total_ads}")
    print("="*40)
    print(f"✅ NEW:      {stats['new']}")
    print(f"🔄 REPLACED: {stats['replaced']}")
    print(f"⏩ EXPIRED:  {stats['broken']}")
    print(f"❌ FAILED:   {stats['failed']}")
    
    if audit_log:
        print("\n" + "!"*15 + " FAILURE AUDIT " + "!"*15)
        for item in audit_log:
            print(f"Row {item['seq']} | ID: {item['id']}\nReason: {item['reason']}\nURL: {item['url']}\n" + "-"*30)

if __name__ == "__main__":
    asyncio.run(main())
