import os
import asyncio
import pandas as pd
import re
import shutil
import stat
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
META_CONCURRENCY = 15
GTC_TIMEOUT = 60000

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    """Extracts numeric ad ID from Meta archive/render URLs or standard library URLs."""
    match = re.search(r"(?:id=|creative/|sadbundle/|simgad/)([0-9]+)", str(url))
    return match.group(1) if match else "unknown"

def remove_readonly(func, path, exc_info):
    """Clear read-only file attributes if permission is denied during folder deletion."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def reset_data_directory():
    """Safely wipes all subdirectories and files inside 'data/' without breaking locks."""
    if not os.path.exists(BASE_DATA_DIR):
        os.makedirs(BASE_DATA_DIR, exist_ok=True)
        log(f"✨ Created fresh '{BASE_DATA_DIR}' directory.")
        return

    log(f"🧹 Removing existing contents from '{BASE_DATA_DIR}'...")
    for item in os.listdir(BASE_DATA_DIR):
        item_path = os.path.join(BASE_DATA_DIR, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, onerror=remove_readonly)
            else:
                os.chmod(item_path, stat.S_IWRITE)
                os.remove(item_path)
        except Exception as e:
            log(f"⚠️ Could not delete {item_path}: {e}")

    log(f"✨ Clean '{BASE_DATA_DIR}' directory ready.")

async def process_meta_link(context, row, seq_num, meta_sem):
    raw_url = str(row.get('creative_page_url', ''))
    ad_id = extract_id_from_url(raw_url)
    advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
    advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
    
    os.makedirs(advertiser_dir, exist_ok=True)

    async with meta_sem:
        log(f"🔍 [Seq: {seq_num}] START META: {ad_id} | Advertiser: {advertiser}")
        page = await context.new_page()
        try:
            await page.goto(raw_url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            
            # Wait for main ad container or body elements to load
            try:
                await page.wait_for_selector("div[role='article'], ._8n-a, body", timeout=15000)
            except Exception:
                pass
            
            meta_target = page.locator("div[role='article'], ._8n-a").first
            if await meta_target.count() > 0:
                save_path = os.path.join(advertiser_dir, f"{ad_id}.png")
                await meta_target.screenshot(path=save_path)
                log(f"    📸 [Seq: {seq_num}] SAVED META: {save_path}")
            else:
                # Fallback: capture full page screenshot if target card element isn't isolated
                save_path = os.path.join(advertiser_dir, f"{ad_id}_full.png")
                await page.screenshot(path=save_path)
                log(f"    📸 [Seq: {seq_num}] SAVED FULL PAGE FALLBACK: {save_path}")
        except Exception as e:
            log(f"    ❌ [Seq: {seq_num}] FAIL META: {str(e)[:60]} | {raw_url}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        log(f"❌ Input CSV file '{CSV_FILE}' not found.")
        return

    # 1. Reset data directory at start
    reset_data_directory()

    # 2. Read CSV and filter ONLY Meta links (supports both library and archive/render URLs)
    full_df = pd.read_csv(CSV_FILE)
    
    # Matches facebook.com/ads/library OR facebook.com/ads/archive
    meta_mask = full_df['creative_page_url'].astype(str).str.contains(
        r"facebook\.com/ads/(?:library|archive)", case=False, na=False
    )
    meta_df = full_df[meta_mask].copy()
    
    log(f"📊 CSV Summary: {len(full_df)} total rows loaded | {len(meta_df)} Meta links identified.")

    if len(meta_df) == 0:
        log("⚠️ No Meta links found matching 'facebook.com/ads/library' or 'facebook.com/ads/archive'. Exiting.")
        return

    # 3. Apply Sharding specifically to Meta links
    total_shards = int(os.environ.get("TOTAL_SHARDS", 1))
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    
    if total_shards > 1:
        shards = np.array_split(meta_df, total_shards)
        df_to_process = shards[shard_index]
        log(f"🧩 Running Shard {shard_index + 1}/{total_shards} ({len(df_to_process)} Meta links assigned).")
    else:
        df_to_process = meta_df
        log(f"🚀 Single run processing all {len(df_to_process)} Meta links.")

    # 4. Launch Playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
        meta_sem = asyncio.Semaphore(META_CONCURRENCY)
        
        tasks = [
            process_meta_link(context, row, i, meta_sem) 
            for i, (_, row) in enumerate(df_to_process.iterrows(), 1)
        ]
        await asyncio.gather(*tasks)
        await browser.close()
        
    log("🏁 PROCESSING COMPLETE.")

if __name__ == "__main__":
    asyncio.run(main())
