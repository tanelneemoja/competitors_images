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
            
            # 1. LOAD
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            # Wait for the specific Meta error text or the Library ID to appear
            try:
                await page.wait_for_selector("body", timeout=10000)
            except:
                pass

            # 2. THE RIGID VISIBLE TEXT CHECK
            # inner_text only gets what a HUMAN sees on the screen
            visible_text = await page.inner_text("body")
            
            death_signals = [
                "This content isn't available right now",
                "it's been deleted",
                "changed who can see it"
            ]

            if any(signal in visible_text for signal in death_signals):
                log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Meta Error Page detected (Ad Deleted).")
                stats["broken"] += 1
                return

            # 3. TARGETING THE CARD
            # We strictly look for the container that actually holds the Library ID
            card_locator = page.locator(f"div:has-text('Library ID: {ad_id}')").locator("xpath=ancestor::div[contains(@class, '_8n-a')]").first
            
            # Fallback for Google GTC
            gtc_locator = page.locator(f"a[href*='{ad_id}']").first

            target = None
            if await card_locator.count() > 0:
                target = card_locator
            elif await gtc_locator.count() > 0:
                target = gtc_locator

            if not target:
                reason = "Live ad found, but specific ID container missing."
                log(f"   ⚠️ [Seq: {seq_num}] FAIL: {reason}")
                audit_log.append({"seq": seq_num, "id": ad_id, "reason": reason, "url": url})
                stats["failed"] += 1
                return

            # 4. CAPTURE & VERIFY
            file_name = f"{ad_id}.png"
            file_path = os.path.join(advertiser_dir, file_name)
            
            status = "REPLACED" if os.path.exists(file_path) else "ADDED"
            await target.screenshot(path=file_path)
            
            # Create a simple hash of the file to "see" if it's the same error image
            with open(file_path, "rb") as f:
                img_hash = hashlib.md5(f.read()).hexdigest()[:8]

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

    print("\n" + "="*30)
    print(f"✅ NEW:      {stats['new']}")
    print(f"🔄 REPLACED: {stats['replaced']}")
    print(f"⏩ BROKEN:   {stats['broken']} (Unavailable)")
    print(f"❌ FAILED:   {stats['failed']}")
    
    if audit_log:
        print("\n" + "!"*10 + " AUDIT LOG " + "!"*10)
        for f in audit_log:
            print(f"Seq {f['seq']} | {f['id']} | {f['reason']}\nURL: {f['url']}\n")

if __name__ == "__main__":
    asyncio.run(main())
