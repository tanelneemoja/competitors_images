import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime
import hashlib
import numpy as np

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
GTC_CONCURRENCY = 5  
GTC_TIMEOUT = 45000  # Back to 45s; if it takes longer, it's a dead end.

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # LOOK FOR THE AD IMMEDIATELY
    # Priority: The actual Fletch iframe, then the renderer, then the container
    locators = [
        "fletch-renderer iframe", 
        "iframe[src*='sadbundle']",
        "html-renderer img",
        "fletch-renderer",
        ".creative-container"
    ]
    
    target = None
    # Poll every 1 second for max 20 seconds
    for _ in range(20): 
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if box and box['width'] > 5 and box['height'] > 5:
                    target = loc
                    break
        if target: break
        await asyncio.sleep(1)

    if not target:
        log(f"   ❌ [Seq: {seq_num}] ERROR: Content Timeout | {url}")
        return "broken"

    # Check for Variations
    indicator = page.locator(".variation-index-indicator").first
    has_vars = await indicator.is_visible()
    
    if not has_vars:
        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await asyncio.sleep(4.0) # Minimal wait for asset load
        await target.screenshot(path=file_path)
        log(f"   ✅ [Seq: {seq_num}] SAVED: {ad_id}.png | {url}")
    else:
        text = await indicator.inner_text()
        total_vars = int(re.search(r"of (\d+)", text).group(1)) if "of" in text else 1
        next_btn = page.locator(".variation-right-arrow").first
        
        for i in range(1, total_vars + 1):
            # Target the non-hidden sub-container specifically
            v_target = page.locator(".creative-sub-container:not(.hidden)").first
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            await asyncio.sleep(4.0) 
            await v_target.screenshot(path=v_path)
            log(f"   📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png")
            
            if i < total_vars:
                await next_btn.click()
                await asyncio.sleep(2.0)
    return "success"

async def process_link(context, row, seq_num, sem):
    url = str(row.get('creative_page_url', ''))
    if "adstransparency.google.com" not in url: return 

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            
            # Use 'commit' - as soon as the URL starts loading, we begin our own polling
            await page.goto(url, wait_until="commit", timeout=GTC_TIMEOUT)
            
            # Start finding the ad content immediately while page loads
            await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                
        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:50]} | {url}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)

    total_shards = int(os.environ.get("SHARD_COUNT", 1))
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    if total_shards > 1:
        shards = np.array_split(df, total_shards)
        df = shards[shard_index]

    if shard_index == 0:
        target_id = "CR14180549296201400321"
        mask = df['creative_page_url'].str.contains(target_id, na=False)
        if mask.any():
            priority_row = df[mask]
            df = pd.concat([priority_row, df[~mask]], ignore_index=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1400})
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
