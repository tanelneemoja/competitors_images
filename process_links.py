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
GTC_CONCURRENCY = 5
GTC_TIMEOUT = 60000
DEFAULT_REGION = "EE"
FALLBACK_REGIONS = ["FI", "LV", "LT"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

def normalize_url(url, target_region):
    if "adstransparency.google.com" not in url:
        return url
    # Force replacement of ANY existing region parameter
    url = re.sub(r'([\?&])region=[^&]*', r'\1', url).rstrip('?&')
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}region={target_region}"

async def check_page_status(page, url, seq_num):
    """
    Categorizes the page state to decide whether to proceed, 
    try a new region, or stop entirely.
    """
    # 1. SUCCESS: Ad content or grid found
    if await page.locator("fletch-renderer, html-renderer, .html-container, creative-preview, .creative-grid, .creative-si").count() > 0:
        return "alive"
    
    # 2. TERMINAL: Google explicitly says the ID/Advertiser is gone
    empty_results = page.locator(".empty-results").first
    if await empty_results.is_visible():
        text = (await empty_results.inner_text()).lower()
        if any(phrase in text for phrase in ["id was not found", "can't find ad", "can't find advertiser"]):
            log(f"    🛑 [Seq: {seq_num}] TERMINAL: ID/Advertiser not found. Stopping cycle. | {url}")
            return "terminal"
        return "retry"

    # 3. TERMINAL: Policy Violation
    if await page.locator(".policy-violation-banner").is_visible():
        log(f"    🛑 [Seq: {seq_num}] TERMINAL: Policy Violation. Stopping cycle. | {url}")
        return "terminal"

    return "retry"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # Skip if Video
    format_locator = page.locator("div.property")
    for i in range(await format_locator.count()):
        if "Video" in (await format_locator.nth(i).inner_text()):
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video Format | {url}")
            return "skipped"

    # Priority Locators including the new 'Text/SI' format containers
    locators = [
        "creative.creative-si", 
        ".html-container", 
        "html-renderer img", 
        ".creative-container > div", 
        "fletch-renderer",
        ".creative-container"
    ]

    target = None
    for _ in range(5):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if box and box['width'] > 10 and box['height'] > 10:
                    target = loc
                    break
        if target: break
        await asyncio.sleep(2)

    if not target:
        return "broken"

    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    await asyncio.sleep(5.0) # Settle animations/fonts
    
    try:
        await target.screenshot(path=file_path)
        log(f"    ✅ [Seq: {seq_num}] GOOGLE SAVED: {ad_id}.png | {url}")
        return "success"
    except Exception:
        # Final emergency fallback: screenshot the sub-container
        try:
            await page.locator(".creative-sub-container").first.screenshot(path=file_path)
            log(f"    📸 [Seq: {seq_num}] SAVED via Sub-Container Fallback | {url}")
            return "success"
        except Exception as e:
            log(f"    ❌ [Seq: {seq_num}] Screenshot Failed: {str(e)[:30]}")
            return "failed"

async def process_link(context, row, seq_num, sem):
    raw_url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in raw_url
    is_meta = "facebook.com/ads/library" in raw_url
    ad_id = extract_id_from_url(raw_url)
    advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
    advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
    os.makedirs(advertiser_dir, exist_ok=True)

    async with sem:
        regions = [DEFAULT_REGION] + FALLBACK_REGIONS if is_google else [None]
        
        for region in regions:
            url = normalize_url(raw_url, region) if is_google else raw_url
            page = await context.new_page()
            try:
                log(f"🚀 [Seq: {seq_num}] PROBING ({region if region else 'Meta'}): {ad_id}")
                await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
                
                if is_google:
                    await asyncio.sleep(2.0)
                    status = await check_page_status(page, url, seq_num)
                    
                    if status == "alive":
                        result = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                        if result in ["success", "skipped"]:
                            await page.close()
                            return
                    elif status == "terminal":
                        await page.close()
                        return # Kill this URL
                    
                    log(f"    ℹ️ [Seq: {seq_num}] {region} empty, trying next...")
                
                elif is_meta:
                    await asyncio.sleep(5)
                    meta_target = page.locator("img.xfn06ss, video.xat24cr, .x1ll56u3 img").first
                    if await meta_target.count() > 0:
                        await meta_target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                        log(f"    ✅ [Seq: {seq_num}] META SAVED | {url}")
                    await page.close()
                    return

            except Exception as e:
                log(f"    ❌ [Seq: {seq_num}] Error: {str(e)[:40]}")
            finally:
                await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    full_df = pd.read_csv(CSV_FILE)
    total_shards = 6
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    df = np.array_split(full_df, total_shards)[shard_index]
    
    log(f"📋 SHARD {shard_index+1}/6 | {len(df)} rows")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1400})
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
