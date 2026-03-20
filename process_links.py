import os
import asyncio
import pandas as pd
import re
import shutil
import httpx
from playwright.async_api import async_playwright

# --- KONFIGURATSIOON ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
CONCURRENCY_LIMIT = 5 
GTC_TIMEOUT = 30000 

stats = {"success": 0, "broken": 0, "timeout": 0, "no_img": 0, "exists": 0, "failed_download": 0}

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
        else:
            log(f"      ⚠️ Pildi allalaadimine ebaõnnestus (HTTP {resp.status_code})")
    except Exception as e:
        log(f"      ⚠️ Allalaadimise viga: {str(e)[:50]}")
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
            await page.goto(url, wait_until="load", timeout=45000)

            if platform_label == "META":
                try:
                    # Ootame pilti või "pole saadaval" teadet
                    await page.wait_for_selector('img[src*="fbcdn.net"], :text("This content isn\'t available right now")', timeout=20000)
                    
                    if await page.get_by_text("This content isn't available right now").is_visible():
                        log(f"   ⏩ [{index}] SKIPPED: Reklaam pole enam aktiivne (Broken).")
                        stats["broken"] += 1
                    else:
                        img_elem = page.locator('img[src*="fbcdn.net"]').first
                        img_src = await img_elem.get_attribute("src")
                        if img_src:
                            if await download_image(client, img_src, advertiser_dir, ad_id):
                                log(f"   ✅ [{index}] SUCCESS: Pilt salvestatud.")
                                stats["success"] += 1
                            else:
                                stats["failed_download"] += 1
                        else:
                            log(f"   ❌ [{index}] ERROR: Pildi URL-i ei leitud.")
                            stats["no_img"] += 1
                except Exception:
                    log(f"   ⏳ [{index}] TIMEOUT: Meta pilti ei ilmub lehele.")
                    stats["timeout"] += 1
            
            else: # GOOGLE (GTC)
                try:
                    error_selectors = [".empty-results", ".policy-violation-banner", ":text('Can\'t find ad')"]
                    for err in error_selectors:
                        if await page.locator(err).is_visible():
                            log(f"   ⏩ [{index}] SKIPPED: Piirkondlik või poliitika piirang.")
                            stats["broken"] += 1
                            return

                    await page.wait_for_selector('html-renderer, fletch-renderer, creative, .creative-container', timeout=GTC_TIMEOUT)
                    await asyncio.sleep(2.5)

                    img_loc = page.locator('html-renderer img, .creative-container img').first
                    if await img_loc.count() > 0 and await img_loc.is_visible():
                        img_src = await img_loc.get_attribute("src")
                        if img_src and "http" in img_src:
                            if await download_image(client, img_src, advertiser_dir, ad_id):
                                log(f"   ✅ [{index}] SUCCESS: GTC otsepilt salvestatud.")
                                stats["success"] += 1
                                return

                    container = page.locator('creative, html-renderer, fletch-renderer, .creative-container').first
                    if await container.is_visible():
                        await container.screenshot(path=target_path)
                        log(f"   📸 [{index}] SUCCESS: GTC ekraanitõmmis tehtud.")
                        stats["success"] += 1
                    else:
                        log(f"   ❌ [{index}] ERROR: Element leiti, aga polnud nähtav.")
                        stats["no_img"] += 1

                except Exception as e:
                    log(f"   ⏳ [{index}] TIMEOUT: GTC sisu ei laadinud.")
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
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 1200}
        )
        
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            tasks = [process_link(context, row, i, len(df), semaphore, client) for i, (_, row) in enumerate(df.iterrows(), 1)]
            await asyncio.gather(*tasks)
        await browser.close()
    
    log(f"\n🏁 KOKKUVÕTE: Edukaid: {stats['success']} | Katkiseid: {stats['broken']} | Aegumisi: {stats['timeout']} | Allalaadimise vigu: {stats['failed_download']}")

if __name__ == "__main__":
    asyncio.run(main())
