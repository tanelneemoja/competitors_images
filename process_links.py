import os
import asyncio
import pandas as pd
import re
import shutil
import httpx
from playwright.async_api import async_playwright
from datetime import datetime

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 10  # Increased for speed
GTC_TIMEOUT = 20000    # 20 seconds is plenty for a single ad page

stats = {"success": 0, "broken": 0, "timeout": 0, "no_img": 0, "exists": 0, "failed_download": 0, "screenshot": 0}

def log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url):
    if "facebook.com" in url:
        match = re.search(r"id=(\d+)", url)
        return match.group(1) if match else f"meta_{int(datetime.now().timestamp())}"
    elif "adstransparency.google.com" in url:
        match = re.search(r"creative/([A-Z0-9]+)", url)
        return match.group(1) if match else f"gtc_{int(datetime.now().timestamp())}"
    return "unknown"

async def download_image(client, url, folder, filename):
    try:
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200:
            path = os.path.join(folder, f"{filename}.png")
            with open(path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception as e:
        log(f"      ⚠️ Download Error: {str(e)[:50]}")
    return False

async def process_link(context, row, index, total, semaphore, client):
    async with semaphore:
        platform_raw = str(row.get('platform', ''))
        platform_label = "META" if "Meta" in platform_raw else "GTC"
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        url = row.get('creative_page_url', '')
        ad_id = extract_id_from_url(url)
        
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)
        
        target_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        if os.path.exists(target_path):
            stats["exists"] += 1
            return

        page = await context.new_page()
        # BLOCK UNNECESSARY TRACKERS TO SAVE BANDWIDTH/TIME
        await page.route("**/*", lambda route: 
            route.abort() if route.request.resource_type in ["beacon", "csp_report", "media"] 
            else route.continue_())

        try:
            log(f"🚀 [{index}/{total}] [{platform_label}] {advertiser}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            if platform_label == "META":
                try:
                    # Wait for image or "Not Available"
                    target = await page.wait_for_selector('img[src*="fbcdn.net"], div:has-text("content isn\'t available")', timeout=12000)
                    content_text = await page.content()
                    
                    if "content isn't available" in content_text:
                        log(f"   ⏩ [{index}] SKIPPED: Meta ad expired/broken.")
                        stats["broken"] += 1
                    else:
                        img_elem = page.locator('img[src*="fbcdn.net"]').first
                        img_src = await img_elem.get_attribute("src")
                        if img_src and await download_image(client, img_src, advertiser_dir, ad_id):
                            log(f"   ✅ [{index}] SUCCESS: Meta Image saved.")
                            stats["success"] += 1
                except:
                    log(f"   ⏳ [{index}] TIMEOUT: Meta content didn't load.")
                    stats["timeout"] += 1
            
            else: # GOOGLE (GTC)
                try:
                    # Wait for any of the 3 types (Image, Video Renderer, or Container)
                    await page.wait_for_selector('html-renderer, fletch-renderer, .creative-container', timeout=15000)
                    
                    # ERROR CHECK: Violation or empty
                    if await page.locator(".policy-violation-banner, .empty-results").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: Policy violation or empty.")
                        stats["broken"] += 1
                        return

                    # TYPE 1: Direct Image (The fastest way)
                    img_loc = page.locator('html-renderer img').first
                    if await img_loc.is_visible():
                        img_src = await img_loc.get_attribute("src")
                        if img_src and "http" in img_src:
                            if await download_image(client, img_src, advertiser_dir, ad_id):
                                log(f"   ✅ [{index}] SUCCESS: GTC Image Downloaded.")
                                stats["success"] += 1
                                return

                    # TYPE 2: Video/Carousel/Text (Screenshot)
                    # We target the specific container to avoid UI buttons
                    container = page.locator('fletch-renderer, .creative-container, html-renderer').first
                    await container.screenshot(path=target_path)
                    log(f"   📸 [{index}] SUCCESS: GTC Screenshot captured (Video/Text).")
                    stats["success"] += 1
                    stats["screenshot"] += 1

                except Exception as e:
                    log(f"   ⏳ [{index}] TIMEOUT: GTC Ad Renderer failed.")
                    stats["timeout"] += 1

        except Exception as e:
            log(f"   ❌ [{index}] CRITICAL ERROR: {str(e)[:60]}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        log(f"ERROR: {CSV_FILE} not found!")
        return
        
    df = pd.read_csv(CSV_FILE)
    log(f"Starting process for {len(df)} links...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-gpu", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1200, 'height': 1000}
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient(follow_redirects=True, limits=httpx.Limits(max_connections=20)) as client:
            tasks = [process_link(context, row, i, len(df), semaphore, client) for i, (_, row) in enumerate(df.iterrows(), 1)]
            await asyncio.gather(*tasks)
            
        await browser.close()

    # FINAL LOGS
    log("-" * 30)
    log(f"FINISH SUMMARY:")
    log(f"   Total Successful: {stats['success']} (Downloads: {stats['success']-stats['screenshot']}, Screenshots: {stats['screenshot']})")
    log(f"   Already Existed:  {stats['exists']}")
    log(f"   Broken/Expired:   {stats['broken']}")
    log(f"   Timeouts:         {stats['timeout']}")
    log("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
