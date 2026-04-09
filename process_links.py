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
    if await page.locator(".empty-results").first.is_visible():
        return "terminal"
    if await page.locator("html-renderer, .creative-si, iframe, .ad-container").count() > 0:
        return "alive"
    return "retry"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # 1. Format Filter (Unchanged)
    properties = page.locator("div.property")
    for i in range(await properties.count()):
        try:
            text = await properties.nth(i).inner_text()
            if any(x in text for x in ["Video", "Format: Text"]):
                return "skipped_format"
        except: continue

    # 2. Forced Progressive Wait
    # We wait 5s immediately, then poll for up to 30s.
    await asyncio.sleep(5.0)

    # 3. High-Precision Shadow-Piercing Selectors
    locators = [
        "html-renderer >> iframe[src*='googlesyndication.com']",
        "html-renderer >> .html-container >> iframe",
        "fletch-renderer >> iframe",
        "creative-sub-container:not(.hidden) >> html-renderer >> img",
        "html-renderer >> img"
    ]

    target = None
    
    # 4. Deep Polling Loop (Up to 30 Attempts)
    for attempt in range(30):
        for selector in locators:
            try:
                # First, check if the locator even exists
                loc = page.locator(selector).first
                if await loc.count() > 0:
                    # For iframes, check if the source is loaded (not about:blank)
                    if "iframe" in selector:
                        src = await loc.get_attribute("src")
                        if not src or "about:blank" in src:
                            continue

                    # Check for physical presence
                    box = await loc.bounding_box()
                    if box and box['width'] > 10 and box['height'] > 10:
                        target = loc
                        print(f"    ✅ [Seq {seq_num}] Found: {selector} ({int(box['width'])}x{int(box['height'])}) at attempt {attempt}")
                        break
            except: continue
        
        if target: break
        await asyncio.sleep(1.0) # Wait 1s between retries

    if not target:
        print(f"    ❌ [Seq {seq_num}] EXHAUSTED - Ad frame did not populate in 30s.")
        return "broken"

    # 5. Final Paint Buffer
    # Crucial: Finding the iframe is only half the battle. 
    # We must wait for the "sadbundle" content to paint.
    await asyncio.sleep(4.0) 
    
    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    try:
        # We increase the screenshot timeout for these heavy bundles
        await target.screenshot(path=file_path, scale='css', timeout=15000)
        return "success"
    except Exception as e:
        print(f"    ❌ [Seq {seq_num}] Screenshot Error: {str(e)[:40]}")
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
                    status = await check_page_status(page)
                    if status == "alive":
                        res = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                        if res == "success":
                            log(f"    ✅ [Seq: {seq_num}] SAVED: {ad_id}.png ({region}) | {url}")
                            await page.close(); return
                        elif res == "skipped_video":
                            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video | {url}")
                            await page.close(); return
                        elif res == "skipped_text":
                            log(f"    📝 [Seq: {seq_num}] SKIPPED: Text Ad | {url}")
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
