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
    url = re.sub(r'([\?&])region=[^&]*', r'\1', url).rstrip('?&')
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}region={target_region}"

async def check_page_status(page, url, seq_num):
    # Check for presence of ad content
    if await page.locator("fletch-renderer, html-renderer, .html-container, .creative-si, .creative-carousel, iframe").count() > 0:
        # Check for VISIBLE policy violation
        banner = page.locator(".policy-violation-banner").first
        if await banner.is_visible():
            log(f"    🛑 [Seq: {seq_num}] TERMINAL: Policy Violation confirmed | {url}")
            return "terminal"
        return "alive"
    
    empty_results = page.locator(".empty-results").first
    if await empty_results.is_visible():
        text = (await empty_results.inner_text()).lower()
        if any(phrase in text for phrase in ["id was not found", "can't find ad"]):
            log(f"    🛑 [Seq: {seq_num}] TERMINAL: Ad ID not found | {url}")
            return "terminal"
        return "retry"

    return "retry"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # Detect Video Skip
    properties = page.locator("div.property")
    for i in range(await properties.count()):
        prop_text = await properties.nth(i).inner_text()
        if "Video" in prop_text:
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video detected | {url}")
            return "skipped"

    # Detect if it's a carousel variation (Needs more wait)
    is_carousel = await page.locator(".variation-index-indicator, .creative-carousel").count() > 0
    if is_carousel:
        await asyncio.sleep(2.0) # Extra time for carousel animation

    # Expanded locators based on your "About You" HTML
    locators = [
        ".creative-sub-container-si creative", # Specific to About You Carousel
        "html-renderer iframe", 
        "creative.creative-si", 
        ".creative-carousel .creative-container",
        "html-renderer img",
        ".html-container"
    ]

    target = None
    for attempt in range(1, 6):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                # Force visibility check
                if await loc.is_hidden(): continue
                
                box = await loc.bounding_box()
                if box and box['width'] > 5 and box['height'] > 5:
                    target = loc
                    break
        if target: break
        await asyncio.sleep(2)

    if not target:
        log(f"    ❌ [Seq: {seq_num}] FAILED: No valid container found | {url}")
        return "broken"

    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    await asyncio.sleep(4.0) # Final settling time
    
    try:
        await target.screenshot(path=file_path)
        log(f"    ✅ [Seq: {seq_num}] GOOGLE SAVED: {ad_id}.png | {url}")
        return "success"
    except Exception as e:
        log(f"    ❌ [Seq: {seq_num}] Screenshot Error: {str(e)[:30]}")
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
                    await asyncio.sleep(4.0) 
                    status = await check_page_status(page, url, seq_num)
                    
                    if status == "alive":
                        result = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                        if result in ["success", "skipped"]:
                            await page.close()
                            return 
                    elif status == "terminal":
                        await page.close()
                        return 
                    
                    log(f"    ℹ️ [Seq: {seq_num}] {region} empty/retry, trying next...")
                
                elif is_meta:
                    await asyncio.sleep(5)
                    # Reverting to your exact Meta selectors
                    meta_target = page.locator("img.xfn06ss, video.xat24cr, .x1ll56u3 img").first
                    if await meta_target.count() > 0:
                        await meta_target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                        log(f"    ✅ [Seq: {seq_num}] META SAVED | {url}")
                    await page.close()
                    return

            except Exception as e:
                log(f"    ❌ [Seq: {seq_num}] Error on {region}: {str(e)[:40]}")
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
        context = await browser.new_context(viewport={'width': 1280, 'height': 1400})
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
