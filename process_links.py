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
CONCURRENCY_LIMIT = 10
META_TIMEOUT = 10000
GTC_TIMEOUT = 22000 # Increased slightly for better screenshot stability

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
            # Using a generous navigation timeout for slow GTC loads
            await page.goto(url, wait_until="domcontentloaded", timeout=50000)

            if platform_label == "META":
                try:
                    await page.wait_for_selector('img[src*="fbcdn.net"], :text("This content isn\'t available right now")', timeout=META_TIMEOUT)
                    if await page.get_by_text("This content isn't available right now").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: Meta content expired/unavailable.")
                        stats["broken"] += 1
                    else:
                        img_src = await page.locator('img[src*="fbcdn.net"]').first.get_attribute("src")
                        if img_src and await download_image(client, img_src, advertiser_dir, ad_id):
                            log(f"   ✅ [{index}] SUCCESS: Saved {ad_id}.png")
                            stats["success"] += 1
                except:
                    log(f"   ⏳ [{index}] TIMEOUT: Meta ad failed to load.")
                    stats["timeout"] += 1
            
            else: # GOOGLE (GTC)
                try:
                    # RACE: Wait for Ad content OR one of the Error messages
                    # 1. "Can't find ad" (Regional restriction)
                    # 2. "Removed for policy violation"
                    # 3. The actual ad container
                    await page.wait_for_selector('fletch-renderer, .creative-container, :text("Can\'t find ad"), .policy-violation-banner', timeout=GTC_TIMEOUT)

                    if await page.get_by_text("Can't find ad").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: Not found in region.")
                        stats["broken"] += 1
                        return
                    
                    if await page.locator(".policy-violation-banner").is_visible() or await page.get_by_text("Sorry, we're not able to show you this ad").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: Policy violation.")
                        stats["broken"] += 1
                        return

                    # Try to find high-res Image source first
                    img_elem = page.locator('html-renderer img').first
                    if await img_elem.is_visible():
                        img_src = await img_elem.get_attribute("src")
                        if img_src and await download_image(client, img_src, advertiser_dir, ad_id):
                            log(f"   ✅ [{index}] SUCCESS: Image downloaded.")
                            stats["success"] += 1
                            return

                    # FALLBACK: Screenshot for Video/HTML5/Animation
                    ad_container = page.locator('fletch-renderer, .creative-container').first
                    if await ad_container.is_visible():
                        # Give it 1 extra second to settle (animations)
                        await asyncio.sleep(1)
                        await ad_container.screenshot(path=target_path)
                        log(f"   📸 [{index}] SUCCESS: Screenshot captured (Video/HTML5).")
                        stats["success"] += 1
                    else:
                        log(f"   ❌ [{index}] ERROR: No ad element found.")
                        stats["no_img"] += 1

                except Exception as e:
                    log(f"   ⏳ [{index}] TIMEOUT: GTC failed to render ad content.")
                    stats["timeout"] += 1

        except Exception as e:
            log(f"   ❌ [{index}] CRASH: {str(e)[:40]}")
        finally:
            await page.close()

async def main():
    # --- ONE-TIME PURGE LOGIC ---
    if os.getenv("PURGE_DATA") == "true":
        if os.path.exists(BASE_DATA_DIR):
            log("🧹 PURGE_DATA is true: Emptying data folder...")
            shutil.rmtree(BASE_DATA_DIR)
        os.makedirs(BASE_DATA_DIR, exist_ok=True)

    if not os.path.exists(CSV_FILE):
        log(f"❌ {CSV_FILE} not found!")
        return
        
    df = pd.read_csv(CSV_FILE)
    log(f"📋 Starting (Concurrency: {CONCURRENCY_LIMIT})\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Larger viewport ensures we don't miss elements
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            viewport={'width': 1600, 'height': 1200} 
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            tasks = [process_link(context, row, i, len(df), semaphore, client) for i, (_, row) in enumerate(df.iterrows(), 1)]
            await asyncio.gather(*tasks)

        await browser.close()
    
    log(f"\n" + "="*30)
    log(f"🏁 FINAL SUMMARY")
    log(f"✅ Saved:   {stats['success']}")
    log(f"📂 Exists:  {stats['exists']}")
    log(f"⏩ Broken:  {stats['broken']} (Link dead/Regional)")
    log(f"⌛ Timeout: {stats['timeout']}")
    log(f"❌ No Img:  {stats['no_img']}")
    log("="*30)

if __name__ == "__main__":
    asyncio.run(main())
