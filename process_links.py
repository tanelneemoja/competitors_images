import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime
import hashlib

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
GTC_CONCURRENCY = 5      
META_CONCURRENCY = 15    
GTC_TIMEOUT = 60000     
BAD_HASH = "f1813cb9"  

stats = {"new": 0, "broken": 0, "failed": 0}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def is_actually_dead(page, url):
    if await page.locator(".empty-results, .policy-violation-banner").first.is_visible():
        return True
    if await page.locator(".visibility-section").first.is_visible():
        return True
    if "adstransparency.google.com" in url:
        ad_id = extract_id_from_url(url)
        content = await page.content()
        if ad_id != "unknown" and ad_id not in content:
            return True
    return False

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num):
    # This logic is kept intact but won't be called in this run
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()
    
    target = page.locator(".creative-sub-container:not(.hidden)").first
    if await target.count() == 0:
        target = page.locator("html-renderer, fletch-renderer, .creative-container").first

    if await target.count() == 0 or not await target.is_visible():
        return "broken"

    if not has_variations:
        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await target.screenshot(path=file_path)
        with open(file_path, "rb") as f:
            if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                os.remove(file_path)
                return "broken"
        log(f"   📸 [Seq: {seq_num}] ADDED: {ad_id}.png")
        stats["new"] += 1
    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        next_btn = page.locator(".variation-right-arrow").first
        for i in range(1, total_vars + 1):
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            await asyncio.sleep(1.5) 
            await target.screenshot(path=v_path)
            log(f"   📸 [Seq: {seq_num}] VARIATION: {ad_id}_{i}.png")
            stats["new"] += 1
            if i < total_vars and await next_btn.is_enabled():
                await next_btn.click()
    return "success"

async def process_link(context, row, seq_num, gtc_sem, meta_sem):
    url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in url
    
    # --- TEMPORARY SKIP FOR GTC ---
    if is_google:
        # log(f"   ⏭️ [Seq: {seq_num}] SKIPPING GTC (Testing Meta Only)")
        return 

    semaphore = meta_sem # Forced to meta_sem for this logic
    
    async with semaphore:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🔍 [Seq: {seq_num}] START META: {ad_id}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            
            # Wait for Meta's specific container
            try:
                await page.wait_for_selector("div[role='article'], ._8n-a", timeout=15000)
            except:
                pass

            if await is_actually_dead(page, url):
                log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Meta Ad dead/missing.")
                stats["broken"] += 1
            else:
                meta_target = page.locator("div[role='article'], ._8n-a").first
                if await meta_target.is_visible():
                    await meta_target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                    log(f"   📸 [Seq: {seq_num}] ADDED: {ad_id}.png")
                    stats["new"] += 1

        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:50]}")
            stats["failed"] += 1
        
        await page.close()

async def main():
    if not os.path.exists(CSV_FILE):
        log(f"Error: {CSV_FILE} not found.")
        return
    df = pd.read_csv(CSV_FILE)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
        gtc_sem = asyncio.Semaphore(GTC_CONCURRENCY)
        meta_sem = asyncio.Semaphore(META_CONCURRENCY)
        
        tasks = [process_link(context, row, i, gtc_sem, meta_sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()
    
    print(f"\n✅ META RUN DONE. IMAGES: {stats['new']} | SKIPPED: {stats['broken']} | FAIL: {stats['failed']}")

if __name__ == "__main__":
    asyncio.run(main())
