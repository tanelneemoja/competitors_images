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
GTC_TIMEOUT = 45000  
BAD_HASH = "f1813cb9"

PROCESS_META = False 
PROCESS_GOOGLE = True

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=|[a-z]_id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def auto_expand_container(page):
    await page.evaluate("""() => {
        const targets = document.querySelectorAll('.creative-container, .html-container, fletch-renderer, iframe, creative');
        targets.forEach(el => {
            el.style.setProperty('height', 'auto', 'important');
            el.style.setProperty('min-height', '300px', 'important');
            el.style.setProperty('visibility', 'visible', 'important');
            el.style.setProperty('display', 'block', 'important');
        });
    }""")

async def is_dead_or_restricted(page, url, seq_num):
    ad_id = extract_id_from_url(url)
    # We wait for the ad content OR the failure UI
    success_selector = ".creative-container:not(.hidden), html-renderer, fletch-renderer"
    failure_selector = ".policy-violation-banner, .visibility-section, .empty-results"

    try:
        # Initial wait for any state
        await page.wait_for_selector(f"{success_selector}, {failure_selector}", timeout=15000)
        
        # CRITICAL FIX: Only skip if the failure element is ACTUALLY visible
        # We use .locator().is_visible() which respects CSS 'display: none' or 'hidden' classes
        is_failure_visible = await page.locator(failure_selector).first.is_visible()
        
        if is_failure_visible:
            log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Confirmed Policy Violation | {url}")
            return True
        
        # If failure isn't visible, but we haven't seen the Ad ID in text yet, wait a bit longer
        content = await page.content()
        if ad_id != "unknown" and ad_id not in content:
            await asyncio.sleep(4) 
        
        return False
    except:
        return False # Default to trying to capture if we aren't sure

async def capture_creative(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    total_vars = 1
    if await indicator.is_visible():
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1

    next_btn = page.locator(".variation-right-arrow").first
    
    for i in range(1, total_vars + 1):
        suffix = f"_{i}" if total_vars > 1 else ""
        file_path = os.path.join(advertiser_dir, f"{ad_id}{suffix}.png")
        
        await auto_expand_container(page)
        target = page.locator("creative:not(.hidden), .creative-container:not(.hidden), ._7jyr").first
        
        if await target.count() > 0:
            await asyncio.sleep(3.5) # Increased buffer for stability
            await target.screenshot(path=file_path)
            
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                        log(f"   🗑️ [Seq: {seq_num}] DELETED: Blank Render | {url}")
                        os.remove(file_path)
                        return False

            log(f"   ✅ [Seq: {seq_num}] SAVED: {ad_id}{suffix}.png | {url}")
        else:
            log(f"   ❌ [Seq: {seq_num}] ERROR: Element missing in DOM | {url}")
            return False

        if i < total_vars and await next_btn.is_enabled():
            await next_btn.click()
            await asyncio.sleep(2.0)
    return True

async def process_link(context, row, seq_num, sem):
    url = str(row.get('creative_page_url', ''))
    platform = str(row.get('platform', row.iloc[0])).lower() 

    is_google = "google" in platform or "adstransparency" in url
    is_meta = "meta" in platform or "facebook" in url

    if is_google and not PROCESS_GOOGLE: return
    if is_meta and not PROCESS_META: return

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        await page.route("**/analytics/**", lambda route: route.abort())
        await page.route("**/gtm.js*", lambda route: route.abort())

        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            await page.goto(url, wait_until="commit", timeout=GTC_TIMEOUT)
            
            if is_google:
                if await is_dead_or_restricted(page, url, seq_num):
                    await page.close()
                    return

            await capture_creative(page, advertiser_dir, ad_id, seq_num, url)
                
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
            viewport={'width': 1366, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
