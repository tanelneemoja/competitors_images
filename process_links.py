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
GTC_CONCURRENCY = 3      # Lowered slightly for better observation during debugging
GTC_TIMEOUT = 60000     
BAD_HASH = "f1813cb9"  

stats = {"new": 0, "broken": 0, "failed": 0, "variations": 0}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

async def is_actually_dead(page, url, seq_num):
    """Logs specific reasons for skipping."""
    if await page.locator(".empty-results").first.is_visible():
        log(f"   ⚠️ [Seq: {seq_num}] Reason: Empty Results grid.")
        return True
    if await page.locator(".policy-violation-banner").first.is_visible():
        log(f"   ⚠️ [Seq: {seq_num}] Reason: Policy Violation Banner.")
        return True
    if await page.locator(".visibility-section").first.is_visible():
        log(f"   ⚠️ [Seq: {seq_num}] Reason: Visibility Section (Hidden Ad).")
        return True
    
    ad_id = extract_id_from_url(url)
    content = await page.content()
    if ad_id != "unknown" and ad_id not in content:
        log(f"   ⚠️ [Seq: {seq_num}] Reason: ID Mismatch (Ad ID {ad_id} not in source).")
        return True

    return False

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num):
    log(f"   🧐 [Seq: {seq_num}] Scanning for variations...")
    
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()
    
    # Identify the specific sub-container to avoid screenshotting the whole UI
    target = page.locator(".creative-sub-container:not(.hidden)").first
    if await target.count() == 0:
        log(f"   🔍 [Seq: {seq_num}] Falling back to general renderer locator.")
        target = page.locator("html-renderer, fletch-renderer, .creative-container").first

    if await target.count() == 0 or not await target.is_visible():
        log(f"   ❌ [Seq: {seq_num}] No visible ad target found in DOM.")
        return "broken"

    if not has_variations:
        log(f"   📄 [Seq: {seq_num}] Single ad detected.")
        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await target.screenshot(path=file_path)
        
        with open(file_path, "rb") as f:
            if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                log(f"   🗑️ [Seq: {seq_num}] Deleted: Matches BAD_HASH (blank render).")
                os.remove(file_path)
                return "broken"
        
        log(f"   ✅ [Seq: {seq_num}] Saved: {ad_id}.png")
        stats["new"] += 1
    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        log(f"   🔄 [Seq: {seq_num}] Carousel detected: {total_vars} variations found.")
        
        next_btn = page.locator(".variation-right-arrow").first
        
        for i in range(1, total_vars + 1):
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            log(f"   ⏳ [Seq: {seq_num}] Rendering variation {i}/{total_vars}...")
            
            # Wait for internal iframes to settle
            await asyncio.sleep(2.0) 
            await target.screenshot(path=v_path)
            log(f"   📸 [Seq: {seq_num}] Captured: {ad_id}_{i}.png")
            stats["new"] += 1
            stats["variations"] += 1
            
            if i < total_vars:
                if await next_btn.is_enabled():
                    log(f"   🖱️ [Seq: {seq_num}] Clicking 'Next'...")
                    await next_btn.click()
                else:
                    log(f"   🛑 [Seq: {seq_num}] 'Next' button disabled before end of count.")
                    break
                
    return "success"

async def process_link(context, row, seq_num, gtc_sem):
    url = str(row.get('creative_page_url', ''))
    is_google = "adstransparency.google.com" in url
    
    # --- SKIP META ---
    if not is_google:
        return 

    async with gtc_sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] START GTC: {ad_id}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            
            # Wait for Angular shell to fetch the data
            log(f"   ⏳ [Seq: {seq_num}] Waiting for Angular content load...")
            try:
                await page.wait_for_selector(".creative-container, .empty-results, .policy-violation-banner", timeout=20000)
            except:
                log(f"   ⏰ [Seq: {seq_num}] Timeout waiting for primary selectors.")
                pass

            if await is_actually_dead(page, url, seq_num):
                stats["broken"] += 1
            else:
                # Extra heartbeat for the heavy HTML5 animations
                await asyncio.sleep(2) 
                res = await handle_google_variations(page, advertiser_dir, ad_id, seq_num)
                if res == "broken":
                    stats["broken"] += 1

        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] CRITICAL FAIL: {str(e)}")
            stats["failed"] += 1
        
        await page.close()
        log(f"🏁 [Seq: {seq_num}] FINISHED: {ad_id}")

async def main():
    if not os.path.exists(CSV_FILE):
        log(f"Error: {CSV_FILE} not found.")
        return
        
    df = pd.read_csv(CSV_FILE)
    log(f"📊 CSV Loaded. Total rows: {len(df)}. Filtering for GTC links...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Using a standard Desktop UA to avoid mobile-redirects on GTC
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        gtc_sem = asyncio.Semaphore(GTC_CONCURRENCY)
        
        tasks = [process_link(context, row, i, gtc_sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()
    
    print(f"\n✅ GTC DEBUG RUN DONE.")
    print(f"   📂 Total Images/Vars: {stats['new']}")
    print(f"   ⏩ Skipped (Dead/Policy): {stats['broken']}")
    print(f"   ❌ Failed: {stats['failed']}")

if __name__ == "__main__":
    asyncio.run(main())
