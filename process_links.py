import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime
import hashlib
import numpy as np
import random

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
GTC_CONCURRENCY = 2  # Lowered concurrency to reduce bot detection
GTC_TIMEOUT = 90000  # Increased to 90s
BAD_HASH = "f1813cb9"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def is_actually_dead(page, url, seq_num):
    # Life signals: fletch, creative, or any iframe inside the main content
    if await page.locator("fletch-renderer, .creative-container, iframe[src*='adframe']").count() > 0:
        return False

    empty = page.locator(".empty-results").first
    policy = page.locator(".policy-violation-banner").first
    
    if await empty.is_visible() or await policy.is_visible():
        await asyncio.sleep(2.0)
        # Check if they are truly blocking the view
        if await empty.is_visible():
            is_hidden = await page.evaluate("(el) => !!el.closest('.hidden')", await empty.element_handle())
            if not is_hidden: return True
        if await policy.is_visible():
            is_hidden = await page.evaluate("(el) => !!el.closest('.hidden')", await policy.element_handle())
            if not is_hidden: return True
    return False

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()
    
    locators = [
        "fletch-renderer iframe", 
        "div.creative-container iframe",
        "html-renderer img",
        "fletch-renderer",
        ".ad-container"
    ]
    
    target = None
    for _ in range(12): # 12 retries (24 seconds total)
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if box and box['width'] > 5 and box['height'] > 5:
                    target = loc
                    break
        if target: break
        await asyncio.sleep(2)

    if not target:
        log(f"   ❌ [Seq: {seq_num}] ERROR: Ad content never rendered | {url}")
        return "broken"

    if not has_variations:
        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await asyncio.sleep(10.0) # Maximum patience for Fletch
        await target.screenshot(path=file_path)
        log(f"   ✅ [Seq: {seq_num}] SAVED: {ad_id}.png | {url}")
    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        next_btn = page.locator(".variation-right-arrow").first
        
        for i in range(1, total_vars + 1):
            current_target = page.locator(".creative-sub-container:not(.hidden)").first
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            await asyncio.sleep(7.0) 
            await current_target.screenshot(path=v_path)
            log(f"   📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png | {url}")
            
            if i < total_vars:
                await next_btn.click()
                await asyncio.sleep(4.0)
    return "success"

async def process_link(context, row, seq_num, sem):
    url = str(row.get('creative_page_url', ''))
    if "adstransparency.google.com" not in url: return 

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            
            # 1. Load page
            await page.goto(url, wait_until="networkidle", timeout=GTC_TIMEOUT)
            
            # 2. Mimic "Human" presence
            await page.mouse.wheel(0, 500)
            await asyncio.sleep(random.uniform(1.0, 3.0))
            
            # 3. Wait for structural container with longer timeout
            try:
                await page.wait_for_selector(".ad-container", timeout=45000)
            except:
                log(f"   🕒 [Seq: {seq_num}] Slow load warning: Proceeding anyway...")

            # 4. Process
            if not await is_actually_dead(page, url, seq_num):
                await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                
        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:60]} | {url}")
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

    if shard_index == 0:
        target_id = "CR14180549296201400321"
        mask = df['creative_page_url'].str.contains(target_id, na=False)
        if mask.any():
            priority_row = df[mask]
            df = pd.concat([priority_row, df[~mask]], ignore_index=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a more realistic context
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
