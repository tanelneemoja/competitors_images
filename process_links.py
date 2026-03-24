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
    """Returns 'alive', 'empty' (try next region), or 'terminal' (stop entirely)."""
    
    # If these exist, the page is definitely ALIVE.
    if await page.locator("fletch-renderer, html-renderer, .html-container, creative-preview, .creative-grid").count() > 0:
        return "alive"
    
    empty_title_loc = page.locator(".empty-results .title").first
    policy_banner = page.locator(".policy-violation-banner").first
    
    if await empty_title_loc.is_visible():
        text = (await empty_title_loc.inner_text()).lower()
        # If the ID itself is not found, it's a dead link. Don't check other regions.
        if "can't find" in text or "not found" in text:
            log(f"    ⚠️ [Seq: {seq_num}] TERMINAL: Ad/Advertiser ID not found | {url}")
            return "terminal"
        return "empty"

    if await policy_banner.is_visible():
        log(f"    ⚠️ [Seq: {seq_num}] TERMINAL: Policy Violation | {url}")
        return "terminal"

    return "empty"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # Skip if Video
    format_locator = page.locator("div.property")
    for i in range(await format_locator.count()):
        if "Video" in (await format_locator.nth(i).inner_text()):
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video Format | {url}")
            return "skipped"

    # Identify Target
    locators = [".html-container", "html-renderer img", "fletch-renderer", ".creative-container"]
    target = None
    for _ in range(5):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if await loc.is_visible() or (box and box['width'] > 5):
                    target = loc
                    break
        if target: break
        await asyncio.sleep(2)

    if not target:
        log(f"    ❌ [Seq: {seq_num}] ERROR: Target missing | {url}")
        return "broken"

    # Capture
    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    await asyncio.sleep(5.0)
    try:
        await target.screenshot(path=file_path)
        log(f"    ✅ [Seq: {seq_num}] GOOGLE SAVED: {ad_id}.png | {url}")
        return "success"
    except Exception as e:
        log(f"    ❌ [Seq: {seq_num}] Screenshot Failed: {str(e)[:30]} | {url}")
        return "failed"

async def process_link(context, row, seq_num, sem):
    raw_url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in raw_url
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
                log(f"🚀 [Seq: {seq_num}] PROBING ({region}): {ad_id} | {url}")
                await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
                
                # Wait for content or error
                try: await page.wait_for_selector(".ad-container, .empty-results, creative-preview", timeout=10000)
                except: pass

                status = await check_page_status(page, url, seq_num)
                
                if status == "alive":
                    result = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                    if result in ["success", "skipped"]:
                        await page.close()
                        return
                elif status == "terminal":
                    await page.close()
                    return # Stop entirely for this URL
                
                # If status is 'empty', loop continues to next region...
            except Exception as e:
                log(f"    ❌ [Seq: {seq_num}] Region {region} error: {str(e)[:50]}")
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
