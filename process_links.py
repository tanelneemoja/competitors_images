import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 2 
GTC_TIMEOUT = 45000    

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
            await asyncio.sleep(1.5) # Give Meta a moment to flip to the 'Unavailable' state

            # 2. THE RIGID CONTENT CHECK
            # We check the actual visible text of the body tag
            body_text = await page.inner_text("body")
            
            # Specific strings that indicate the ad is gone
            is_unavailable = any(x in body_text for x in [
                "This content isn't available right now",
                "it's been deleted",
                "changed who can see it",
                "isn't available"
            ])

            if is_unavailable:
                log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad is confirmed DEAD/UNAVAILABLE. ID: {ad_id}")
                stats["broken"] += 1
                return

            # 3. TARGETING LOGIC
            # If the ad is live, we look for the Library ID inside the card
            meta_id_locator = page.locator(f"div:has-text('Library ID: {ad_id}')").locator("xpath=ancestor::div[contains(@class, '_8n-a')]").first
            gtc_href_locator = page.locator(f"a[href*='{ad_id}']").first
            
            target_element = None
            if await meta_id_locator.count() > 0:
                target_element = meta_id_locator
            elif await gtc_href_locator.count() > 0:
                target_element = gtc_href_locator

            if not target_element:
                reason = "Valid ad container not found on live page"
                log(f"   ⚠️ [Seq: {seq_num}] FAIL: {reason}")
                audit_log.append({"seq": seq_num, "id": ad_id, "reason": reason, "url": url})
                stats["failed"] += 1
                return

            # 4. CAPTURE & LOG PREVIEW
            file_name = f"{ad_id}.png"
            file_path = os.path.join(advertiser_dir, file_name)
            abs_path = os.path.abspath(file_path) # Get full path for the log
            
            status = "REPLACED" if os.path.exists(file_path) else "ADDED"
            
            await target_element.screenshot(path=file_path)
            
            # NEW: Log shows exactly where it was saved so you can check it
            log(f"   📸 [Seq: {seq_num}] {status}: {file_name}")
            log(f"      ↳ Saved to: {abs_path}")
            
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

    # --- FINAL AUDIT LOG ---
    print("\n" + "="*40)
    print(f"✅ NEW:      {stats['new']}")
    print(f"🔄 REPLACED: {stats['replaced']}")
    print(f"⏩ BROKEN:   {stats['broken']}")
    print(f"❌ FAILED:   {stats['failed']}")
    
    if audit_log:
        print("\n" + "!"*15 + " FAILURE AUDIT LIST " + "!"*15)
        for f in audit_log:
            print(f"Row {f['seq']} | ID: {f['id']} | {f['reason']}\nURL: {f['url']}\n" + "-"*30)

if __name__ == "__main__":
    asyncio.run(main())
