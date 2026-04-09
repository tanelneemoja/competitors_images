import os
import asyncio
import pandas as pd
import re
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

def normalize_url(url, target_region):
    if "adstransparency.google.com" not in url: return url
    url = re.sub(r'([\?&])region=[^&]*', r'\1', url).rstrip('?&')
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}region={target_region}"

async def check_page_status(page):
    # Check for empty results first
    if await page.locator(".empty-results").first.is_visible():
        return "terminal"
    # Check for any valid ad renderer
    if await page.locator("html-renderer, fletch-renderer, .creative-si, .ad-container").count() > 0:
        return "alive"
    return "retry"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # 1. Format Filter
    properties = page.locator("div.property")
    for i in range(await properties.count()):
        try:
            text = await properties.nth(i).inner_text()
            if any(x in text for x in ["Video", "Format: Text"]):
                return "skipped_format"
        except: continue

    # 2. Format Detection
    is_html_bundle = await page.locator("html-renderer").count() > 0
    is_fletch = await page.locator("fletch-renderer").count() > 0

    # 3. Targeted Waiting
    if is_html_bundle:
        await asyncio.sleep(10.0) # 211 needs time for redirect
    else:
        await asyncio.sleep(7.0)  # 221 needs time for carousel init

    target = None

    # --- PATH A: THE 211 FIX ---
    if is_html_bundle:
        target = page.locator("html-renderer >> iframe[src*='googlesyndication.com']").first
        
    # --- PATH B: THE 221 FIX (Based on your provided HTML) ---
    elif is_fletch:
        # We find the fletch-renderer inside the container that is NOT hidden
        target = page.locator(".creative-sub-container:not(.hidden) fletch-renderer >> iframe").first

    # --- FALLBACK ---
    if not target or await target.count() == 0:
        target = page.locator(".creative-sub-container:not(.hidden) >> img").first

    # 4. Dimension Validation (The "Inflation" Check)
    for _ in range(3):
        if await target.count() > 0:
            box = await target.bounding_box()
            if box and box['width'] > 10 and box['height'] > 10:
                break 
        await asyncio.sleep(3.0)

    if await target.count() == 0:
        return "broken"

    # 5. Capture
    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    try:
        await asyncio.sleep(2.0)
        await target.screenshot(path=file_path, scale='css', timeout=15000)
        return "success"
    except Exception as e:
        print(f"    ❌ [Seq {seq_num}] Capture Error: {str(e)[:40]}")
        return "failed"
        
async def process_link(context, row, seq_num, gtc_sem, meta_sem):
    raw_url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in raw_url
    is_meta = "facebook.com/ads/library" in raw_url
    ad_id = extract_id_from_url(raw_url)
    advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
    advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
    os.makedirs(advertiser_dir, exist_ok=True)

    if is_google:
        async with gtc_sem:
            log(f"🚀 [Seq: {seq_num}] Probing GTC {ad_id}")
            regions = [DEFAULT_REGION] + FALLBACK_REGIONS
            for region in regions:
                url = normalize_url(raw_url, region)
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
                    
                    # URL Guard: Ensure region wasn't stripped
                    if f"region={region}" not in page.url:
                        await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
                        await asyncio.sleep(2)

                    status = await check_page_status(page)
                    if status == "alive":
                        res = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                        if res == "success":
                            log(f"    ✅ [Seq: {seq_num}] SAVED ({region})")
                            await page.close(); return
                        elif res == "skipped_format":
                            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Format")
                            await page.close(); return
                    elif status == "terminal":
                        log(f"    🛑 [Seq: {seq_num}] REGION EMPTY: {region}")
                except: pass
                finally: await page.close()
            log(f"    ⚠️ [Seq: {seq_num}] EXHAUSTED: {ad_id}")

    elif is_meta:
        async with meta_sem:
            page = await context.new_page()
            try:
                await page.goto(raw_url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
                meta_target = page.locator("div[role='article'], ._8n-a").first
                if await meta_target.count() > 0:
                    await meta_target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                    log(f"    📸 [Seq: {seq_num}] ADDED META")
            except: pass
            finally: await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    full_df = pd.read_csv(CSV_FILE)
    
    total_shards = 6 # REVERTED TO 6
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    
    shards = np.array_split(full_df, total_shards)
    df = shards[shard_index]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        gtc_sem = asyncio.Semaphore(GTC_CONCURRENCY)
        meta_sem = asyncio.Semaphore(META_CONCURRENCY)
        
        tasks = [process_link(context, row, i, gtc_sem, meta_sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()
    log("🏁 SHARD PROCESSING COMPLETE.")

if __name__ == "__main__":
    asyncio.run(main())
