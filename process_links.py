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
GTC_TIMEOUT = 60000  
BAD_HASH = "f1813cb9"

PROCESS_META = False 
PROCESS_GOOGLE = True

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def is_actually_dead(page, url, seq_num):
    if await page.locator(".empty-results").first.is_visible():
        log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Empty Results | {url}")
        return True
    if await page.locator(".policy-violation-banner").first.is_visible():
        log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Policy Violation | {url}")
        return True
    if await page.locator(".visibility-section").first.is_visible():
        log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Hidden/Restricted | {url}")
        return True
    return False

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    """
    ONLY MODIFIED: Targeted locators for Swedbank/Rademar/Eesti Energia.
    Everything else (Hash check, logic flow) is kept exactly as provided.
    """
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()
    
    # CHANGED: Replaced the old target line with a robust check for HTML5/Nested Imgs
    target = None
    locators = [
        "html-renderer img",           # Eesti Energia (Img inside renderer)
        "html-renderer",               # Swedbank / Rademar (HTML5)
        "iframe[src*='sadbundle']",    # Direct banking iFrames
        ".creative-sub-container:not(.hidden)", 
        "fletch-renderer", 
        ".creative-container"
    ]
    
    for _ in range(5):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.is_visible():
                target = loc
                break
        if target: break
        await asyncio.sleep(2)

    if not target:
        log(f"   ❌ [Seq: {seq_num}] ERROR: Target missing in DOM | {url}")
        return "broken"

    if not has_variations:
        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        # CHANGED: Increased sleep to 6.0 for HTML5 iFrame painting stability
        await asyncio.sleep(6.0) 
        await target.screenshot(path=file_path)
        
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                    log(f"   🗑️ [Seq: {seq_num}] DELETED: Blank Render Hash | {url}")
                    os.remove(file_path)
                    return "broken"
        
        log(f"   ✅ [Seq: {seq_num}] SAVED: {ad_id}.png | {url}")
    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        
        next_btn = page.locator(".variation-right-arrow").first
        
        for i in range(1, total_vars + 1):
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            # CHANGED: Increased to 4.5 for iFrame variation stability
            await asyncio.sleep(4.5) 
            await target.screenshot(path=v_path)
            log(f"   📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png | {url}")
            
            if i < total_vars:
                btn_class = await next_btn.get_attribute("class") or ""
                if "is-disabled" not in btn_class:
                    await next_btn.click()
                    await asyncio.sleep(2.0)
                else:
                    log(f"   🛑 [Seq: {seq_num}] WARN: Next button stuck at {i} | {url}")
                    break
    return "success"

async def process_link(context, row, seq_num, sem):
    url = str(row.get('creative_page_url', ''))
    if "adstransparency.google.com" not in url:
        return 

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            # CHANGED: Using networkidle to ensure iFrames/Assets start loading
            await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
            
            try:
                await page.wait_for_selector(".creative-container, .empty-results, .policy-violation-banner", timeout=25000)
            except:
                pass

            if not await is_actually_dead(page, url, seq_num):
                await asyncio.sleep(2) 
                await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)

        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]} | {url}")
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

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1400}, # Increased height for 300x600 ads
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
