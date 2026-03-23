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
    # Restored full detailed logging
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

async def capture_creative(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    total_vars = 1
    if await indicator.is_visible():
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1

    for i in range(1, total_vars + 1):
        suffix = f"_{i}" if total_vars > 1 else ""
        file_path = os.path.join(advertiser_dir, f"{ad_id}{suffix}.png")
        
        await auto_expand_container(page)
        
        # Target only visible creatives
        target = page.locator("creative:not(.hidden), .creative-container:not(.hidden):not(.creative-carousel), ._7jyr").first
        
        if await target.count() > 0:
            # Check for iframe (HTML5 ads) and wait for source
            iframe = target.locator("iframe").first
            if await iframe.count() > 0:
                try:
                    await iframe.wait_for(state="attached", timeout=5000)
                except: pass

            await asyncio.sleep(4.0) # Safety buffer for rendering
            
            try:
                await target.screenshot(path=file_path, timeout=15000)
                
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                            log(f"   🗑️ [Seq: {seq_num}] DELETED: Blank Render | {url}")
                            os.remove(file_path)
                            return False
                log(f"   ✅ [Seq: {seq_num}] SAVED: {ad_id}{suffix}.png | {url}")
            except Exception as e:
                log(f"   ❌ [Seq: {seq_num}] SCREENSHOT TIMEOUT (Retrying later) | {url}")
                return False
        else:
            log(f"   ❌ [Seq: {seq_num}] ERROR: No visible target | {url}")
            return False

        if i < total_vars:
            next_btn = page.locator(".variation-right-arrow").first
            if await next_btn.is_visible() and "is-disabled" not in (await next_btn.get_attribute("class") or ""):
                await next_btn.click()
                await asyncio.sleep(2.0)
            else:
                break 
    return True

async def process_link(context, row, seq_num, sem):
    url = str(row.get('creative_page_url', ''))
    # Use column 'platform' to skip Meta for now
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
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            
            # Wait for any main content to appear
            await page.wait_for_selector(".creative-details, .ad-container", timeout=15000)
            
            # Simplified Check: only skip if the violation banner is ACTUALLY visible
            banner = page.locator(".policy-violation-banner").first
            if await banner.is_visible():
                log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Violation Visible | {url}")
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
