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
    region_map = {"EE": "Estonia", "FI": "Finland", "LV": "Latvia", "LT": "Lithuania"}
    target_name = region_map.get(target_region_code, "Estonia")

    try:
        # 1. Look for the "Clear/Close" button (the 'X') to reset sticky state
        # In your HTML this is: expand-scope-button-test
        clear_button = page.locator(".expand-scope-button, .close-icon, material-icon[icon='close']").first
        if await clear_button.is_visible():
            await clear_button.click()
            await asyncio.sleep(1.5) # Wait for reset

        # 2. Check current state - if it's already correct, we are done
        chip_text_locator = page.locator(".button-text").first
        if await chip_text_locator.count() > 0:
            current_text = await chip_text_locator.inner_text()
            if target_name.lower() in current_text.lower():
                return "alive"

        # 3. Perform the click/search if we aren't in the right region
        selector = page.locator(".region-selector, .region-switch, .button-text").first
        if await selector.is_visible():
            await selector.click()
            
            # Use a more specific selector for the search input
            search_input = page.locator("input[aria-label*='Region'], input[placeholder*='location'], input[role='combobox']").first
            await search_input.wait_for(state="visible", timeout=7000)
            await search_input.fill(target_name)
            await asyncio.sleep(1)
            await page.keyboard.press("Enter")
            
            # CRITICAL: Wait longer for the ad renderer to actually swap/load
            await asyncio.sleep(5) 

        # Final check for content
        if await page.locator("html-renderer, fletch-renderer, .creative-si").count() > 0:
            return "alive"
            
    except Exception as e:
        log(f"    ⚠️ Interaction failed for {target_name}: {str(e)[:50]}")

    # Final "Hail Mary" check
    if await page.locator("html-renderer, fletch-renderer, iframe[src*='google']").count() > 0:
        return "alive"

    if await page.locator(".empty-results").first.is_visible():
        return "terminal"
        
    return "retry"

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    # 1. Format Filter: Skip non-image ads early
    properties = page.locator("div.property")
    for i in range(await properties.count()):
        try:
            text = await properties.nth(i).inner_text()
            if any(x in text for x in ["Video", "Format: Text"]):
                return "skipped_format"
        except: 
            continue

    # 2. Region Guard: Stop the loop if ad is not available (e.g., Seq 200)
    # We check for the specific 'empty-results' class from your logs
    if await page.locator("div.empty-results").count() > 0:
        print(f"   ❌ [Seq: {seq_num}] Region Lock: Ad not available. Skipping.")
        return "skipped_region_unavailable"

    # 3. Targeted Selection: Carousel (221) vs Standard (211)
    # Check if this is a carousel-style page
    is_carousel = await page.locator("div.creative-carousel").count() > 0
    containers = page.locator("div[class*='creative-sub-container']:not(.hidden)")
    target = None

    if is_carousel:
        # Loop through containers to find the one with actual content height
        for i in range(await containers.count()):
            curr = containers.nth(i).locator("div.creative-container").first
            box = await curr.bounding_box()
            if box and box['height'] > 10:
                target = curr
                break
    
    # If not a carousel, or if the carousel loop found nothing, take the first visible container
    if not target:
        target = containers.first.locator("div.creative-container").first

    # 4. Hydration Check: The "5px" Guard (Worked for 211)
    # We wait up to 8 seconds for the container to expand/hydrate
    is_hydrated = False
    for _ in range(8):
        if await target.count() > 0:
            box = await target.bounding_box()
            if box and box['height'] > 10:
                is_hydrated = True
                break
        await asyncio.sleep(1.0)

    # Final check for Region Wall if hydration failed (sometimes Google is slow to show the error)
    if not is_hydrated:
        if await page.locator("div.empty-results").count() > 0:
            return "skipped_region_unavailable"
        return "broken_5px_render"

    # 5. Stabilization Sleep (Worked for 211)
    await asyncio.sleep(4.0)

    # 6. Screenshot: Target the container directly as per your suggestion
    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    try:
        # Use a strict 5s timeout and disable animations to prevent exhaustion
        await target.screenshot(
            path=file_path, 
            scale='css', 
            timeout=5000,
            animations="disabled"
        )
        return "success"
    except Exception:
        # Emergency Fallback: If the container fails, try to snap the whole active block
        try:
            await containers.first.screenshot(path=file_path, timeout=3000)
            return "success_fallback"
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
