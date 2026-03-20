import os
import asyncio
import pandas as pd
import re
import time
import httpx  # Faster than requests for async
from playwright.async_api import async_playwright

# --- CONFIG ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 5  # Number of tabs to run at once
TIMEOUT_MS = 10000     # 10 seconds max per page

# Stats for the final summary
stats = {"success": 0, "broken": 0, "timeout": 0, "exists": 0}

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
        pass
    return False

async def handle_route(route):
    """Blocks fonts and styles to save bandwidth."""
    if route.request.resource_type in ["font", "stylesheet", "media"]:
        await route.abort()
    else:
        await route.continue_()

async def process_link(context, row, index, total, semaphore, client):
    async with semaphore:
        platform = row['platform']
        advertiser = sanitize_filename(row['advertiser_name'])
        url = row['creative_page_url']
        ad_id = extract_id_from_url(url, platform)
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)
        
        if os.path.exists(os.path.join(advertiser_dir, f"{ad_id}.png")):
            stats["exists"] += 1
            return

        page = await context.new_page()
        # Intercept requests to speed up loading
        await page.route("**/*", handle_route)
        
        try:
            log(f"🚀 [{index}/{total}] Starting: {advertiser}")
            
            # Go to URL with a tighter timeout
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

            img_src = None
            if "Meta" in platform:
                # Wait for Image OR Error message
                try:
                    # Look for either the image or the "Content not available" text
                    # Using a 7s timeout for the internal element wait
                    await page.wait_for_selector('img[src*="fbcdn.net"], :text("This content isn\'t available right now")', timeout=7000)
                    
                    if await page.get_by_text("This content isn't available right now").is_visible():
                        log(f"   ⏩ [{index}] Broken Link.")
                        stats["broken"] += 1
                    else:
                        img_src = await page.locator('img[src*="fbcdn.net"]').first.get_attribute("src")
                except:
                    log(f"   ❌ [{index}] Timeout/Not found.")
                    stats["timeout"] += 1
            else:
                # Google
                await page.wait_for_selector('html-renderer img', timeout=TIMEOUT_MS)
                img_src = await page.locator('html-renderer img').first.get_attribute("src")

            if img_src:
                if await download_image(client, img_src, advertiser_dir, ad_id):
                    log(f"   ✅ [{index}] Saved.")
                    stats["success"] += 1
                
        except Exception as e:
            stats["timeout"] += 1
            log(f"   ❌ [{index}] Failed: {str(e)[:30]}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)
    total = len(df)
    
    log(f"📋 Processing {total} links with Concurrency={CONCURRENCY_LIMIT}...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a single context for all pages to save memory
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient() as client:
            tasks = []
            for i, (_, row) in enumerate(df.iterrows(), 1):
                tasks.append(process_link(context, row, i, total, semaphore, client))
            
            await asyncio.gather(*tasks)

        await browser.close()
    
    log(f"\n✨ FINISHED! \n✅ Success: {stats['success']} \n⏩ Broken: {stats['broken']} \n⌛ Timeouts: {stats['timeout']} \n📂 Existing: {stats['exists']}")

if __name__ == "__main__":
    asyncio.run(main())
