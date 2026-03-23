import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime
import hashlib

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 2 
GTC_TIMEOUT = 45000    
# We know this hash is the 'Content Unavailable' screen
BAD_HASH = "f1813cb9" 

stats = {"new": 0, "replaced": 0, "broken": 0, "failed": 0}
audit_log = []

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=|id=)([A-Z0-9\d]+)", str(url))
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
            log(f"🔍 [Seq: {seq_num}] Target ID: {ad_id}")
            
            # 1. LOAD & WAIT
            await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
            await page.wait_for_timeout(3000) # Hard wait for Meta's late-loading error states

            # 2. IMMEDIATE TEXT/BUTTON SCAN
            content = await page.content()
            error_btn = page.locator('a[aria-label="Go to Feed"]').first
            
            if "This content isn't available" in content or await error_btn.is_visible():
                log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad dead (Text/Button Detection).")
                stats["broken"] += 1
                return

            # 3. TARGETING
            # Look for the Library ID specific card
            meta_card = page.locator(f"div:has-text('Library ID: {ad_id}')").locator("xpath=ancestor::div[contains(@class, '_8n-a')]").first
            gtc_ad = page.locator(f"a[href*='{ad_id}']").first

            target = None
            if await meta_card.count() > 0:
                target = meta_card
            elif await gtc_ad.count() > 0:
                target = gtc_ad
            else:
                # If we can't find the specific card, but the page didn't show an error, 
                # we fallback to the whole body to see what's actually there.
                target = page.locator("body") 

            # 4. CAPTURE & HASH VALIDATION
            file_name = f"{ad_id}.png"
            file_path = os.path.join(advertiser_dir, file_name)
            
            # Temporary save to check hash
            await target.screenshot(path=file_path)
            
            with open(file_path, "rb") as f:
                img_hash = hashlib.md5(f.read()).hexdigest()[:8]

            # THE HASH SHIELD: If it matches the known error hash, delete it.
            if img_hash == BAD_HASH:
                os.remove(file_path)
                log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad dead (Hash Detection {img_hash}).")
                stats["broken"] += 1
                return

            status = "REPLACED" if os.path.exists(file_path) else "ADDED"
            log(f"   📸 [Seq: {seq_num}] {status}: {file_name} [Hash:{img_hash}]")
            log(f"      URL: {url}")
            
            if status == "REPLACED": stats["replaced"] += 1
            else: stats["new"] += 1

        except Exception as e:
            err = str(e).split('\n')[0][:60]
            log(f"   ❌ [Seq: {seq_num}] ERROR: {err}")
            audit_log.append({"seq": seq_num, "id": ad_id, "reason": err, "url": url})
            stats["failed"] += 1
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        tasks = [process_link(context, row, i, len(df), semaphore) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

    print("\n" + "="*40)
    print(f"✅ NEW:      {stats['new']}")
    print(f"🔄 REPLACED: {stats['replaced']}")
    print(f"⏩ BROKEN:   {stats['broken']} (Unavailable)")
    print(f"❌ FAILED:   {stats['failed']}")
    
    if audit_log:
        print("\n" + "!"*15 + " FAILURE AUDIT " + "!"*15)
        for f in audit_log:
            print(f"Seq {f['seq']} | {f['id']}\nURL: {f['url']}\nReason: {f['reason']}\n" + "-"*30)

if __name__ == "__main__":
    asyncio.run(main())
