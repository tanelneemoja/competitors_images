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
REGION = "EE"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

def normalize_url(url):
    if "region=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}region={REGION}"
    return url

async def is_actually_dead(page, url, seq_num):
    if await page.locator("fletch-renderer, html-renderer, .creative-container").count() > 0:
        return False
    empty = page.locator(".empty-results").first
    policy = page.locator(".policy-violation-banner").first
    if await empty.is_visible() or await policy.is_visible():
        await asyncio.sleep(5.0)
    if await empty.is_visible():
        return True
    if await policy.is_visible():
        return True
    return False

async def get_container_declared_height(page):
    try:
        return await page.eval_on_selector(
            ".creative-sub-container:not(.hidden) .creative-container",
            "el => { const h = el.style.height; return h ? parseInt(h) : 0; }"
        )
    except Exception:
        return 0

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()

    locators = [
        "html-renderer", 
        "fletch-renderer",
        "iframe[src*='sadbundle']",
        "iframe[src*='googlesyndication.com']",
        ".creative-sub-container:not(.hidden) .creative-container",
        ".creative-container",
        "creative" # Broadest possible target
    ]

    target = None
    log(f"    🔍 [Seq: {seq_num}] Diagnostic: Probing DOM for {ad_id}...")
    
    # Check if the main wrapper even exists
    wrapper_count = await page.locator("creative-details").count()
    log(f"    🔍 [Seq: {seq_num}] Diagnostic: creative-details count: {wrapper_count}")

    for attempt in range(1, 6):
        for selector in locators:
            loc = page.locator(selector).first
            count = await loc.count()
            if count > 0:
                is_vis = await loc.is_visible()
                if is_vis:
                    log(f"    🎯 [Seq: {seq_num}] Found visible target: {selector} on attempt {attempt}")
                    target = loc
                    break
                else:
                    log(f"    ⚠️ [Seq: {seq_num}] Found {selector} but it is NOT visible in DOM.")
            
        if target:
            break
        await asyncio.sleep(2)

    if not target:
        # Final desperate check: is there ANY iframe we can grab?
        if await page.locator("iframe").count() > 0:
            log(f"    💡 [Seq: {seq_num}] Diagnostic: No standard target found, but iframes exist. Taking full page capture.")
            target = page.locator(".ad-container").first

    if not target:
        log(f"    ❌ [Seq: {seq_num}] ERROR: Target missing in DOM | {url}")
        return "broken"

    # Proceed with capture
    if not has_variations:
        declared_h = await get_container_declared_height(page)
        if 0 < declared_h <= 2:
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Stub (height={declared_h}px)")
            return "broken"

        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await asyncio.sleep(5.0) 
        await target.screenshot(path=file_path)
        log(f"    ✅ [Seq: {seq_num}] SAVED: {ad_id}.png")

    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        log(f"    Carousel: {total_vars} variations found.")
        
        next_btn = page.locator(".variation-right-arrow").first
        for i in range(1, total_vars + 1):
            current_target = page.locator(".creative-sub-container:not(.hidden)").first
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            await asyncio.sleep(4.0)
            await current_target.screenshot(path=v_path)
            log(f"    📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}")

            if i < total_vars:
                btn_class = await next_btn.get_attribute("class") or ""
                if "is-disabled" not in btn_class:
                    await next_btn.click()
                    await asyncio.sleep(3.0)
                else:
                    break
    return "success"

async def process_link(context, row, seq_num, sem):
    url = normalize_url(str(row.get('creative_page_url', '')))
    if "adstransparency.google.com" not in url: return

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            await asyncio.sleep(5) # Allow Angular to boot

            if not await is_actually_dead(page, url, seq_num):
                await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
        except Exception as e:
            log(f"    ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)

    # Priority Injection
    target_ids = ["CR14180549296201400321", "CR14981377662579113985"]
    priority_rows = [df[df['creative_page_url'].str.contains(tid, na=False)] for tid in target_ids]
    priority_rows = [r for r in priority_rows if not r.empty]
    
    if priority_rows:
        other_rows = df[~df['creative_page_url'].str.contains('|'.join(target_ids), na=False)]
        df = pd.concat(priority_rows + [other_rows], ignore_index=True)
        log(f"🎯 Priority Injection active for {len(priority_rows)} items.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1400})
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
