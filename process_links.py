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

# Concurrency settings
GTC_CONCURRENCY = 5     
META_CONCURRENCY = 15   

GTC_TIMEOUT = 60000    
META_TIMEOUT = 30000   
BAD_HASH = "f1813cb9" 
MAX_GTC_RETRIES = 2    

stats = {"new": 0, "replaced": 0, "broken": 0, "failed": 0}
audit_log = []

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def is_actually_dead(page):
    """
    Surgical check for GTC death states.
    Uses .is_visible() and .inner_text() to ignore hidden 'policy violation' divs.
    """
    # 1. Check for the 'Can't find ad' block from your HTML dump
    error_block = page.locator(".empty-results")
    if await error_block.is_visible():
        return True

    # 2. Check for visible text only
    death_signals = [
        "Can't find ad",
        "ad with this ID was not found",
        "This content isn't available right now",
        "Removed for a policy violation"
    ]
    
    visible_text = await page.inner_text("body")
    if any(signal in visible_text for signal in death_signals):
        await asyncio.sleep(3) 
        visible_text_retry = await page.inner_text("body")
        return any(signal in visible_text_retry for signal in death_signals)
    
    return False

async def process_link(context, row, seq_num, gtc_sem, meta_sem):
    url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in url
    semaphore = gtc_sem if is_google else meta_sem
    
    async with semaphore:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        max_attempts = (MAX_GTC_RETRIES + 1) if is_google else 1
        timeout = GTC_TIMEOUT if is_google else META_TIMEOUT
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        for attempt in range(max_attempts):
            page = await context.new_page()
            try:
                # --- START LOG ---
                log(f"🔍 [Seq: {seq_num}] START: {ad_id} | {url}")
                
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                
                if is_google:
                    try:
                        await page.wait_for_selector("html-renderer img, fletch-renderer, .empty-results", timeout=25000)
                    except:
                        pass 

                # Check if actually dead (Visible only)
                if await is_actually_dead(page):
                    log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad dead/unavailable.")
                    log(f"      URL: {url}")
                    stats["broken"] += 1
                    await page.close()
                    return

                await page.wait_for_timeout(5000) 

                target = None
                if is_google:
                    for selector in ["html-renderer", "fletch-renderer", ".creative-container"]:
                        loc = page.locator(selector).first
                        if await loc.count() > 0:
                            target = loc
                            break
                else:
                    meta_card = page.locator(f"div:has-text('Library ID: {ad_id}')").locator("xpath=ancestor::div[contains(@class, '_8n-a')]").first
                    if await meta_card.count() > 0:
                        target = meta_card
                
                if target:
                    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
                    exists_before = os.path.exists(file_path)
                    await target.screenshot(path=file_path)
                    
                    with open(file_path, "rb") as f:
                        img_hash = hashlib.md5(f.read()).hexdigest()[:8]

                    if img_hash == BAD_HASH:
                        os.remove(file_path)
                        log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Dead Hash ({img_hash}).")
                        log(f"      URL: {url}")
                        stats["broken"] += 1
                        await page.close()
                        return

                    status = "REPLACED" if exists_before else "ADDED"
                    log(f"   📸 [Seq: {seq_num}] {status}: {ad_id}.png [Hash:{img_hash}]")
                    log(f"      URL: {url}")
                    
                    if status == "REPLACED": stats["replaced"] += 1
                    else: stats["new"] += 1
                    await page.close()
                    return 
                
                else:
                    raise Exception("Container not found after wait.")

            except Exception as e:
                err_msg = str(e).split('\n')[0][:60]
                if is_google and attempt < MAX_GTC_RETRIES:
                    log(f"   ⚠️ [Seq: {seq_num}] {err_msg}. Retrying GTC...")
                    await page.close()
                    await asyncio.sleep(2)
                    continue
                else:
                    log(f"   ❌ [Seq: {seq_num}] FAIL: {err_msg}")
                    log(f"      URL: {url}")
                    audit_log.append({"seq": seq_num, "id": ad_id, "reason": err_msg, "url": url})
                    stats["failed"] += 1
            
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        print(f"Error: {CSV_FILE} not found.")
        return
    df = pd.read_csv(CSV_FILE)
    start_time = datetime.now()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        gtc_sem = asyncio.Semaphore(GTC_CONCURRENCY)
        meta_sem = asyncio.Semaphore(META_CONCURRENCY)
        
        tasks = [process_link(context, row, i, gtc_sem, meta_sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

    duration = datetime.now() - start_time
    print("\n" + "="*40)
    print(f"FINISHED IN: {str(duration).split('.')[0]}")
    print(f"✅ NEW: {stats['new']} | 🔄 REPLACED: {stats['replaced']} | ⏩ SKIPPED: {stats['broken']} | ❌ FAIL: {stats['failed']}")
    print("="*40)

if __name__ == "__main__":
    asyncio.run(main())
