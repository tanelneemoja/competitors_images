import os
import asyncio
import pandas as pd
import re
import time
import httpx
from playwright.async_api import async_playwright

# --- CONFIG ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 5  # Number of tabs at once
TIMEOUT_MS = 12000     # 12 seconds per page

stats = {"success": 0, "broken": 0, "timeout": 0, "no_img": 0, "exists": 0}

def log(msg):
    print(msg, flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url, platform):
    if "facebook.com" in url:
        match = re.search(r"id=(\d+)", url)
        return match.group(1) if match else "meta_unknown"
    elif "adstransparency.google.com" in url:
        match = re.search(r"creative/(CR\d+)", url)
        return match.group(1) if match else "gtc_unknown"
    return "unknown"

async def download_image(client, url, folder, filename):
    try:
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200:
            path = os.path.join(folder, f"{filename}.png")
            with open(path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception:
        return False
    return False

async def handle_route(route):
    if route.request.resource_type in ["font", "stylesheet", "media"]:
        await route.abort()
    else:
        await route.continue_()

async def process_link(context, row, index, total, semaphore, client):
    async with semaphore:
        platform = "META" if "Meta" in row['platform'] else "GTC"
        advertiser = sanitize_filename(row['advertiser_name'])
        url = row['creative_page_url']
        ad_id = extract_id_from_url(url, row['platform'])
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)
        
        if os.path.exists(os.path.join(advertiser_dir, f"{ad_id}.png")):
            stats["exists"] += 1
            return

        page = await context.new_page()
        await page.route("**/*", handle_route)
        
        try:
            # Start Log
            log(f"🚀 [{index}/{total}] [{platform}] {advertiser}...")
            
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            img_src = None

            if platform == "META":
                try:
                    # Check for "Not Available" vs Image race
                    await page.wait_for_selector('img[src*="fbcdn.net"], :text("This content isn\'t available right now")', timeout=8000)
                    
                    if await page.get_by_text("This content isn't available right now").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: URL content no longer available (Broken/Expired)")
                        stats["broken"] += 1
                    else:
                        img_src = await page.locator('img[src*="fbcdn.net"]').first.get_attribute("src")
                        if not img_src:
                            log(f"   ⚠️ [{index}] FAILED: Element found but img src is empty")
                            stats["no_img"] += 1
                except:
                    log(f"   ⏳ [{index}] TIMEOUT: Meta page took too long or ad is restricted")
                    stats["timeout"] += 1
            
            else: # GTC (Google)
                try:
                    await page.wait_for_selector('html-renderer img', timeout=TIMEOUT_MS)
                    img_src = await page.locator('html-renderer img').first.get_attribute("src")
                except:
                    log(f"   ⏳ [{index}] TIMEOUT: Google page failed to render image")
                    stats["timeout"] += 1

            if img_src:
                if await download_image(client, img_src, advertiser_dir, ad_id):
                    log(f"   ✅ [{index}] SUCCESS: Image saved as {ad_id}.png")
                    stats["success"] += 1
                else:
                    log(f"   ❌ [{index}] ERROR: Download failed (Network error)")
                    stats["no_img"] += 1
                
        except Exception as e:
            log(f"   ❌ [{index}] CRASH: {str(e)[:40]}")
            stats["timeout"] += 1
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE):
        log(f"❌ {CSV_FILE} not found!")
        return
    
    df = pd.read_csv(CSV_FILE)
    total = len(df)
    log(f"📋 Starting high-speed processing for {total} links...\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient() as client:
            tasks = [process_link(context, row, i, total, semaphore, client) for i, (_, row) in enumerate(df.iterrows(), 1)]
            await asyncio.gather(*tasks)

        await browser.close()
    
    log(f"\n" + "="*30)
    log(f"🏁 FINAL SUMMARY")
    log(f"✅ Saved:   {stats['success']}")
    log(f"📂 Exists:  {stats['exists']}")
    log(f"⏩ Broken:  {stats['broken']} (Meta link expired)")
    log(f"⌛ Timeout: {stats['timeout']} (Page didn't load)")
    log(f"❌ No Img:  {stats['no_img']} (Download failed)")
    log("="*30)

if __name__ == "__main__":
    asyncio.run(main())
