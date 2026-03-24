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
    if "adstransparency.google.com" not in url: return url
    url = re.sub(r'([\?&])region=[^&]*', r'\1', url).rstrip('?&')
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}region={target_region}"

async def check_page_status(page):
    # Presence check for any valid ad container
    if await page.locator("fletch-renderer, html-renderer, .html-container, .creative-si, .creative-carousel, iframe").count() > 0:
        # Only terminal if the violation banner is actually VISIBLE
        banner = page.locator(".policy-violation-banner").first
        if await banner.is_visible():
            return "terminal"
        return "alive"
    
    # Check for "Not Found" message
    empty_results = page.locator(".empty-results").first
    if await empty_results.is_visible():
        text = (await empty_results.inner_text()).lower()
        if any(phrase in text for phrase in ["id was not found", "can't find ad"]):
            return "terminal"
    return "retry"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num):
    # 1. Format Check (Video Skip)
    properties = page.locator("div.property")
    for i in range(await properties.count()):
        prop_text = await properties.nth(i).inner_text()
        if "Video" in prop_text:
            return "skipped"

    # 2. Universal Settlement Wait
    # We wait 4s for SI containers, iframes, and carousels to finish entry animations
    await asyncio.sleep(4.0) 

    # 3. Targeted Locators (Prioritizing the internal content of SI containers)
    locators = [
        "html-renderer iframe",       # Best for Text/HTML5 bundles (Seq 9)
        "html-renderer img",          # Standard Image ads
        ".creative-container img",    # Fallback image
        ".creative-sub-container-si", # The primary wrapper for About You ads
        "creative.creative-si",       # The variation host
        ".html-container"             # Final fallback
    ]

    target = None
    # 10 attempts to find a rendered element with valid dimensions
    for attempt in range(10):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                if await loc.is_hidden(): continue
                
                box = await loc.bounding_box()
                if box and box['width'] > 10 and box['height'] > 10:
                    target = loc
                    break
        if target: break
        await asyncio.sleep(1.0)

    if not target: return "broken"

    # 4. Final Stabilize
    await asyncio.sleep(2.0)
    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    
    try:
        await target.screenshot(path=file_path)
        return "success"
    except Exception:
        # Last ditch effort: snap the whole SI container if element-specific fails
        try:
            await page.locator(".creative-sub-container-si").first.screenshot(path=file_path)
            return "success"
        except:
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
        # Log start of sequence
        log(f"🚀 [Seq: {seq_num}] Probing {ad_id}")
        
        regions = [DEFAULT_REGION] + FALLBACK_REGIONS if is_google else [None]
        
        for region in regions:
            url = normalize_url(raw_url, region) if is_google else raw_url
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
                
                if is_google:
                    await asyncio.sleep(3.0)
                    status = await check_page_status(page)
                    
                    if status == "alive":
                        res = await handle_google_variations(page, advertiser_dir, ad_id, seq_num)
                        if res == "success":
                            log(f"    ✅ [Seq: {seq_num}] SAVED: {ad_id}.png ({region})")
                            await page.close(); return
                        elif res == "skipped":
                            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video Format ({region})")
                            await page.close(); return
                    elif status == "terminal":
                        log(f"    🛑 [Seq: {seq_num}] TERMINAL: Policy/Not Found ({region})")
                        await page.close(); return
                    
                    # If reach here, region failed; loop to next one silently
                
                elif is_meta:
                    await asyncio.sleep(5)
                    meta_target = page.locator("img.xfn06ss, video.xat24cr, .x1ll56u3 img").first
                    if await meta_target.count() > 0:
                        await meta_target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                        log(f"    ✅ [Seq: {seq_num}] SAVED: {ad_id}.png (Meta)")
                        await page.close(); return
                    else:
                        log(f"    ❌ [Seq: {seq_num}] FAILED: Meta selectors missing")
                        await page.close(); return

            except Exception:
                pass 
            finally:
                await page.close()
        
        # Only log one exhausted message if ALL regions failed
        if is_google:
            log(f"    ⚠️ [Seq: {seq_num}] EXHAUSTED: All regions failed for {ad_id}")

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
