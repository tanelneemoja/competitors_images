import os
import asyncio
import pandas as pd
import re
import shutil
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
GTC_CONCURRENCY = 10 
META_CONCURRENCY = 15
GTC_TIMEOUT = 60000
DEFAULT_REGION = "EE"
FALLBACK_REGIONS = ["FI", "LV", "LT"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=|sadbundle/|simgad/)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

def reset_data_directory():
    """Removes all existing folders/files inside the BASE_DATA_DIR to start fresh."""
    if os.path.exists(BASE_DATA_DIR):
        log(f"🧹 Cleaning up existing '{BASE_DATA_DIR}' directory...")
        shutil.rmtree(BASE_DATA_DIR)
    os.makedirs(BASE_DATA_DIR, exist_ok=True)
    log(f"✨ Clean '{BASE_DATA_DIR}' folder initialized.")

async def process_link(context, row, seq_num, gtc_sem, meta_sem):
    raw_url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in raw_url
    is_meta = "facebook.com/ads/library" in raw_url
    ad_id = extract_id_from_url(raw_url)
    advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
    advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)

    # 1. GOOGLE DISABLED
    if is_google:
        log(f"⏭️ [Seq: {seq_num}] SKIPPED: Google Ads disabled for this run | {ad_id}")
        return

    # 2. META EXTRACTION (UNTOUCHED)
    elif is_meta:
        os.makedirs(advertiser_dir, exist_ok=True)
        async with meta_sem:
            log(f"🔍 [Seq: {seq_num}] START META: {ad_id} | {raw_url}")
            page = await context.new_page()
            try:
                await page.goto(raw_url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
                try:
                    await page.wait_for_selector("div[role='article'], ._8n-a", timeout=15000)
                except: pass
                
                meta_target = page.locator("div[role='article'], ._8n-a").first
                if await meta_target.count() > 0:
                    await meta_target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                    log(f"    📸 [Seq: {seq_num}] ADDED META: {ad_id}.png | {raw_url}")
                else:
                    log(f"    ⏩ [Seq: {seq_num}] SKIPPED: Meta Ad missing | {raw_url}")
            except Exception as e:
                log(f"    ❌ [Seq: {seq_num}] FAIL META: {str(e)[:50]} | {raw_url}")
            finally:
                await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        log(f"❌ Input CSV file '{CSV_FILE}' not found.")
        return

    # Wipe the data directory before starting execution
    reset_data_directory()

    full_df = pd.read_csv(CSV_FILE)
    total_shards = int(os.environ.get("TOTAL_SHARDS", 1)) # Default to 1 if testing locally without shards
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    
    if total_shards > 1:
        df = np.array_split(full_df, total_shards)[shard_index]
    else:
        df = full_df

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
        gtc_sem = asyncio.Semaphore(GTC_CONCURRENCY)
        meta_sem = asyncio.Semaphore(META_CONCURRENCY)
        
        tasks = [process_link(context, row, i, gtc_sem, meta_sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()
        
    log("🏁 SHARD PROCESSING COMPLETE.")

if __name__ == "__main__":
    asyncio.run(main())
