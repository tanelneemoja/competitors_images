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
CONCURRENCY_LIMIT = 2 
GTC_TIMEOUT = 60000    # 60s for Google
META_TIMEOUT = 30000   # 30s for Meta
BAD_HASH = "f1813cb9" 
MAX_GTC_RETRIES = 2    # Only Google gets retries

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

async def process_link(context, row, seq_num, total, semaphore):
    async with semaphore:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        url = str(row.get('creative_page_url', ''))
        ad_id = extract_id_from_url(url)
        is_google = "adstransparency.google.com" in url
        
        max_attempts = (MAX_GTC_RETRIES + 1) if is_google else 1
        timeout = GTC_TIMEOUT if is_google else META_TIMEOUT

        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        for attempt in range(max_attempts):
            page = await context.new_page()
            try:
                attempt_pfx = f" (Attempt {attempt+1})" if attempt > 0 else ""
                log(f"🔍 [Seq: {seq_num}] Target ID: {ad_id}{attempt_pfx}")
                
                # Use domcontentloaded to prevent hanging on background trackers
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                
                # Specifically wait for GTC ad components to initialize
                if is_google:
                    try:
                        await page.wait_for_selector("fletch-renderer, html-renderer, .creative-container", timeout=15000)
                    except:
                        pass # Continue to check for death signals
                
                await page.wait_for_timeout(5000) 

                content = await page.content()
                visible_text = await page.inner_text("body")
                
                death_signals = [
                    "This content isn't available right now", 
                    "it's been deleted",                      
                    "An ad with this ID was not found",
                    "Removed for a policy violation",
                    "Sorry, we're not able to show you this ad"
                ]
                
                if any(signal in visible_text or signal in content for signal in death_signals):
                    log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad is unavailable.")
                    log(f"      URL: {url}")
                    stats["broken"] += 1
                    await page.close()
                    return

                # --- PERSISTENT SELECTOR SUITE ---
                target = None
                if is_google:
                    # All known GTC containers restored
                    gtc_selectors = ["fletch-renderer", "html-renderer", ".creative-container"]
                    for selector in gtc_selectors:
                        loc = page.locator(selector).first
                        if await loc.count() > 0:
                            target = loc
                            break
                else:
                    # Meta Targeting
                    meta_card = page.locator(f"div:has-text('Library ID: {ad_id}')").locator("xpath=ancestor::div[contains(@class, '_8n-a')]").first
                    if await meta_card.count() > 0:
                        target = meta_card
                
                if target:
                    file_name = f"{ad_id}.png"
                    file_path = os.path.join(advertiser_dir, file_name)
                    exists_before = os.path.exists(file_path)
                    
                    await target.screenshot(path=file_path)
                    
                    with open(file_path, "rb") as f:
                        img_hash = hashlib.md5(f.read()).hexdigest()[:8]

                    if img_hash == BAD_HASH:
                        os.remove(file_path)
                        log(f"   ⏩ [Seq: {seq_num}] SKIPPED: Ad dead (Hash Detection {img_hash}).")
                        log(f"      URL: {url}")
                        stats["broken"] += 1
                        await page.close()
                        return

                    status = "REPLACED" if exists_before else "ADDED"
                    log(f"   📸 [Seq: {seq_num}] {status}: {file_name} [Hash:{img_hash}]")
                    log(f"      URL: {url}") # Deep logging for success
                    
                    if status == "REPLACED": stats["replaced"] += 1
                    else: stats["new"] += 1
                    await page.close()
                    return 
                
                else:
                    raise Exception("No valid ad container found")

            except Exception as e:
                err_msg = str(e).split('\n')[0][:60]
                if is_google and attempt < MAX_GTC_RETRIES:
                    log(f"   ⚠️ [Seq: {seq_num}] {err_msg}. Retrying...")
                    await page.close()
                    await asyncio.sleep(3) 
                    continue
                else:
                    log(f"   ❌ [Seq: {seq_num}] FAIL: {err_msg}")
                    log(f"      URL: {url}") # Deep logging for failure
                    audit_log.append({"seq": seq_num, "id": ad_id, "reason": err_msg, "url": url})
                    stats["failed"] += 1
            
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        print(f"Error: {CSV_FILE} not found.")
        return
    df = pd.read_csv(CSV_FILE)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Using a standard viewport and UA to avoid bot-detection blocking
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        tasks = [process_link(context, row, i, len(df), semaphore) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()

    print("\n" + "="*40)
    print(f"RUN COMPLETE - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*40)
    print(f"✅ NEW:      {stats['new']}")
    print(f"🔄 REPLACED: {stats['replaced']}")
    print(f"⏩ BROKEN:   {stats['broken']}")
    print(f"❌ FAILED:   {stats['failed']}")
    
    if audit_log:
        print("\n" + "!"*15 + " FAILURE SUMMARY " + "!"*15)
        for f in audit_log:
            print(f"Row {f['seq']} | ID: {f['id']} | {f['reason']}")
            print(f"URL: {f['url']}")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
