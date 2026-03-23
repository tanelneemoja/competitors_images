import os
import asyncio
import pandas as pd
import re
import httpx
from playwright.async_api import async_playwright
from datetime import datetime

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 8  # Balanced for speed and iframe stability
GTC_TIMEOUT = 25000    

stats = {"success": 0, "broken": 0, "timeout": 0, "overwritten": 0, "screenshot": 0}

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url):
    # Extract ID for both Meta and GTC
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else f"ad_{int(datetime.now().timestamp())}"

async def download_image(client, url, folder, filename):
    try:
        # Ignore small icons/logos by checking URL patterns or sizes
        if "icon" in url.lower() or ".svg" in url.lower():
            return False
            
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200 and len(resp.content) > 5000: # Skip files < 5KB (usually logos)
            path = os.path.join(folder, f"{filename}.png")
            with open(path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception:
        pass
    return False

async def process_link(context, row, index, total, semaphore, client):
    async with semaphore:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        url = row.get('creative_page_url', '')
        ad_id = extract_id_from_url(url)
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)
        target_path = os.path.join(advertiser_dir, f"{ad_id}.png")

        page = await context.new_page()
        
        # SPEED: Abort SVG/GIF to avoid capturing logos as the main image
        await page.route("**/*.{svg,gif}", lambda route: route.abort())

        try:
            log(f"🚀 [{index}/{total}] [{advertiser}]")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            # --- 1. THE "CAN'T FIND" FAST EXIT ---
            # Checks for the specific GTC error state you provided
            error_check = page.locator(".empty-results, :text('Can\\'t find ad'), :text('isn\\'t available')")
            if await error_check.count() > 0 and await error_check.first.is_visible():
                log(f"   ⏩ SKIPPED: Ad not found/available.")
                stats["broken"] += 1
                return

            # --- 2. THE IFRAME/SADBUNDLE CHECK ---
            # We want the ACTUAL image inside the ad, not a screenshot of the wrapper
            try:
                await page.wait_for_selector('html-renderer, fletch-renderer', timeout=10000)
                
                iframe_loc = page.locator("iframe[src*='sadbundle'], iframe[src*='adframe']").first
                if await iframe_loc.count() > 0:
                    frame = await iframe_loc.content_frame()
                    if frame:
                        # Find the largest image in the frame
                        inner_img = frame.locator("img").first
                        inner_src = await inner_img.get_attribute("src")
                        if inner_src and await download_image(client, inner_src, advertiser_dir, ad_id):
                            log(f"   ✅ SUCCESS: Extracted high-res from Iframe.")
                            stats["success"] += 1
                            return

                # --- 3. STANDARD RENDERER ---
                img_loc = page.locator('html-renderer img, .creative-container img').first
                if await img_loc.count() > 0:
                    img_src = await img_loc.get_attribute("src")
                    if img_src and await download_image(client, img_src, advertiser_dir, ad_id):
                        log(f"   ✅ SUCCESS: Direct Image Overwritten.")
                        stats["success"] += 1
                        return

                # --- 4. SCREENSHOT FALLBACK (Video/Complex) ---
                container = page.locator('.creative-container, fletch-renderer').first
                await container.screenshot(path=target_path)
                log(f"   📸 SUCCESS: Captured Screenshot.")
                stats["screenshot"] += 1
                stats["success"] += 1

            except Exception:
                log(f"   ⏳ TIMEOUT: Content failed to render.")
                stats["timeout"] += 1

        except Exception as e:
            log(f"   ❌ ERROR: {str(e)[:50]}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
            viewport={'width': 1200, 'height': 900}
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            tasks = [process_link(context, row, i, len(df), semaphore, client) for i, (_, row) in enumerate(df.iterrows(), 1)]
            await asyncio.gather(*tasks)
            
        await browser.close()
    log(f"FINISH: Success: {stats['success']} | Broken/Skipped: {stats['broken']}")

if __name__ == "__main__":
    asyncio.run(main())
