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

async def check_page_status(page, target_region_code):
    # Mapping for validation
    region_map = {"EE": "Estonia", "FI": "Finland", "LV": "Latvia", "LT": "Lithuania"}
    target_name = region_map.get(target_region_code, "")

    # Wait for the specific regional chip to appear (from your provided HTML)
    try:
        # 1. Wait for the 'blue-chip' or the region text to show it's filtered
        await page.wait_for_selector(".button-text", timeout=5000)
        chip_text = await page.locator(".button-text").first.inner_text()
        
        # If still says 'anywhere', it hasn't loaded the regional filter yet
        if "anywhere" in chip_text.lower() and target_name:
            await asyncio.sleep(3.5)
            chip_text = await page.locator(".button-text").first.inner_text()

        # Check if ad container or fletch-renderer exists
        if await page.locator("fletch-renderer, html-renderer, .creative-si").count() > 0:
            return "alive"
            
        # If the chip explicitly says the country but no renderer, it's empty for that region
        if target_name in chip_text and await page.locator("fletch-renderer").count() == 0:
            return "terminal"

    except:
        pass

    if await page.locator(".empty-results").first.is_visible():
        return "terminal"
        
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

    # 2. Render Type Detection
    is_html_bundle = await page.locator("html-renderer").count() > 0
    is_fletch = await page.locator("fletch-renderer").count() > 0

    # Wait for iframe content to actually mount
    await asyncio.sleep(7.0) 

    target = None
    if is_html_bundle:
        target = page.locator("html-renderer >> iframe[src*='googlesyndication.com']").first
    elif is_fletch:
        target = page.locator("fletch-renderer >> iframe").first

    if not target or await target.count() == 0:
        target = page.locator(".creative-sub-container:not(.hidden) >> img").first

    # Ensure the target is actually rendered and visible
    for _ in range(4):
        if await target.count() > 0:
            box = await target.bounding_box()
            if box and box['width'] > 2 and box['height'] > 2:
                break 
        await asyncio.sleep(2.0)

    if await target.count() == 0:
        return "broken"

    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    try:
        # Added a tiny buffer for the fletch script to finish its callback
        await asyncio.sleep(1.5)
        await target.screenshot(path=file_path, scale='css', timeout=15000)
        return "success"
    except:
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
            log(f"🚀 [Seq: {seq_num}] Probing GTC {ad_id} | {raw_url}")
            regions = [DEFAULT_REGION] + FALLBACK_REGIONS
            for region in regions:
                url = normalize_url(raw_url, region)
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
                    status = await check_page_status(page, region)
                    if status == "alive":
                        res = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                        if res == "success":
                            log(f"    ✅ [Seq: {seq_num}] SAVED: {ad_id}.png ({region}) | {url}")
                            await page.close(); return
                        elif res == "skipped_format":
                            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Format (Video/Text) | {url}")
                            await page.close(); return
                    elif status == "terminal":
                        log(f"    🛑 [Seq: {seq_num}] REGION EMPTY: {region} | {url}")
                except: pass
                finally: await page.close()
            log(f"    ⚠️ [Seq: {seq_num}] EXHAUSTED: {ad_id} | {raw_url}")

    elif is_meta:
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
    if not os.path.exists(CSV_FILE): return
    full_df = pd.read_csv(CSV_FILE)
    total_shards = 6 
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    df = np.array_split(full_df, total_shards)[shard_index]
    
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
