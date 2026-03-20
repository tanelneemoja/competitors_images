import os
import asyncio
import pandas as pd
import re
import shutil
import httpx
from playwright.async_api import async_playwright

# --- CONFIG ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 5 
GTC_TIMEOUT = 30000 # 30 seconds to find the ad element

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
        resp = await client.get(url, timeout=15)
        if resp.status_code == 200:
            path = os.path.join(folder, f"{filename}.png")
            with open(path, "wb") as f:
                f.write(resp.content)
            return True
    except:
        return False
    return False

async def process_link(context, row, index, total, semaphore, client):
    async with semaphore:
        platform_raw = row['platform']
        platform_label = "META" if "Meta" in platform_raw else "GTC"
        advertiser = sanitize_filename(row['advertiser_name'])
        url = row['creative_page_url']
        ad_id = extract_id_from_url(url, platform_raw)
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)
        
        target_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        if os.path.exists(target_path):
            stats["exists"] += 1
            return

        page = await context.new_page()
        try:
            log(f"🚀 [{index}/{total}] [{platform_label}] {advertiser}...")
            
            # Using 'load' instead of 'networkidle' to prevent infinite hangs
            await page.goto(url, wait_until="load", timeout=45000)

            if platform_label == "META":
                try:
                    await page.wait_for_selector('img[src*="fbcdn.net"], :text("This content isn\'t available right now")', timeout=15000)
                    if await page.get_by_text("This content isn't available right now").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: Meta expired.")
                        stats["broken"] += 1
                    else:
                        img_src = await page.locator('img[src*="fbcdn.net"]').first.get_attribute("src")
                        if img_src and await download_image(client, img_src, advertiser_dir, ad_id):
                            log(f"   ✅ [{index}] SUCCESS: Image saved.")
                            stats["success"] += 1
                except:
                    stats["timeout"] += 1
            
            else: # GOOGLE (GTC)
                try:
                    # 1. Check for immediate "Not Found" / Policy violations
                    error_selectors = [".empty-results", ".policy-violation-banner", ":text('Can\'t find ad')"]
                    for err in error_selectors:
                        if await page.locator(err).is_visible():
                            log(f"   ⏩ [{index}] SKIPPED: Regional/Policy block.")
                            stats["broken"] += 1
                            return

                    # 2. Wait for the Creative container to exist
                    # We wait for the specific 'creative' or 'renderer' tags
                    await page.wait_for_selector('html-renderer, fletch-renderer, creative, .creative-container', timeout=GTC_TIMEOUT)
                    
                    # 3. Small sleep to allow inner frames/images to actually render
                    await asyncio.sleep(2.5)

                    # 4. Try getting a high-res image first
                    img_loc = page.locator('html-renderer img, .creative-container img').first
                    if await img_loc.count() > 0 and await img_loc.is_visible():
                        img_src = await img_loc.get_attribute("src")
                        if img_src and "http" in img_src:
                            if await download_image(client, img_src, advertiser_dir, ad_id):
                                log(f"   ✅ [{index}] SUCCESS: Direct image saved.")
                                stats["success"] += 1
                                return

                    # 5. Screenshot Fallback (for Text, Video, HTML5)
                    # We target the 'creative' element directly for a clean crop
                    container = page.locator('creative, html-renderer, fletch-renderer, .creative-container').first
                    if await container.is_visible():
                        await container.screenshot(path=target_path)
                        log(f"   📸 [{index}] SUCCESS: Screenshot saved.")
                        stats["success"] += 1
                    else:
                        log(f"   ❌ [{index}] ERROR: Elements found but not visible.")
                        stats["no_img"] += 1

                except Exception as e:
                    log(f"   ⏳ [{index}] TIMEOUT: Ad content did not render in time.")
                    stats["timeout"] += 1

        except Exception as e:
            log(f"   ❌ [{index}] CRASH: {str(e)[:50]}")
        finally:
            await page.close()

async def main():
    if os.getenv("PURGE_DATA") == "true":
        if os.path.exists(BASE_DATA_DIR):
            shutil.rmtree(BASE_DATA_DIR)
        os.makedirs(BASE_DATA_DIR, exist_ok=True)

    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a real-looking User Agent to reduce Google throttling
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1200}
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            tasks = [process_link(context, row, i, len(df), semaphore, client) for i, (_, row) in enumerate(df.iterrows(), 1)]
            await asyncio.gather(*tasks)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
