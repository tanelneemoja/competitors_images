import os
import asyncio
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime
import hashlib
import numpy as np

# --- CONFIGURATION ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"
GTC_CONCURRENCY = 5
GTC_TIMEOUT = 60000

PROCESS_META = True
PROCESS_GOOGLE = True
REGION = "EE"

DIAGNOSTIC_TARGET_ID = "CR14981377662579113985"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

def normalize_url(url):
    if "adstransparency.google.com" in url and "region=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}region={REGION}"
    return url

async def is_actually_dead(page, url, seq_num):
    if await page.locator("fletch-renderer, html-renderer, .html-container").count() > 0:
        return False
    empty = page.locator(".empty-results").first
    policy = page.locator(".policy-violation-banner").first
    if await empty.is_visible() or await policy.is_visible():
        await asyncio.sleep(5.0)
    if await empty.is_visible():
        log(f"    ⚠️ [Seq: {seq_num}] SKIPPED: Truly Empty | {url}")
        return True
    if await policy.is_visible():
        log(f"    ⚠️ [Seq: {seq_num}] SKIPPED: Policy Violation | {url}")
        return True
    return False

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    is_diag = (ad_id == DIAGNOSTIC_TARGET_ID)
    
    # 1. SKIP CHECKS (Video & Render Failure)
    render_failed = page.locator(".render-failed-container, .render-failed").first
    if await render_failed.count() > 0:
        if "unable to show" in (await render_failed.inner_text()).lower():
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Render Failure | {url}")
            return "skipped"

    format_locator = page.locator("div.property")
    for i in range(await format_locator.count()):
        text = await format_locator.nth(i).inner_text()
        if "Format:" in text and "Video" in text:
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video Format | {url}")
            return "skipped"

    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()

    # 2. LOCATOR PROBING (Updated for .html-container)
    locators = [
        ".html-container",
        "html-renderer img", 
        "iframe[id*='fletch-render']", 
        "div[id*='fletch-render']",
        "fletch-renderer",
        "html-renderer",
        ".creative-container"
    ]

    target = None
    for attempt in range(1, 6):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                box = await loc.bounding_box()
                if await loc.is_visible() or (box and box['width'] > 5 and box['height'] > 5):
                    target = loc
                    break
        if target: break
        await asyncio.sleep(2)

    if not target:
        log(f"    ❌ [Seq: {seq_num}] ERROR: Target missing | {url}")
        return "broken"

    # 3. CAPTURE
    file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
    await asyncio.sleep(6.0)

    try:
        if not has_variations:
            try:
                await target.screenshot(path=file_path)
            except:
                await page.locator(".creative-container").first.screenshot(path=file_path)
            log(f"    ✅ [Seq: {seq_num}] GOOGLE SAVED: {ad_id}.png | {url}")
        else:
            text = await indicator.inner_text()
            total = int(re.search(r"of (\d+)", text).group(1)) if "of" in text else 1
            next_btn = page.locator(".variation-right-arrow").first
            for i in range(1, total + 1):
                v_fail = page.locator(".creative-sub-container:not(.hidden) .render-failed").first
                if await v_fail.count() > 0:
                    log(f"    ⏭️ [Seq: {seq_num}] SKIPPED VAR {i}/{total}: Render Failure | {url}")
                else:
                    v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
                    await asyncio.sleep(4.0)
                    await page.locator(".creative-sub-container:not(.hidden)").first.screenshot(path=v_path)
                    log(f"    📸 [Seq: {seq_num}] SAVED VAR {i}/{total}: {ad_id}_{i}.png | {url}")
                
                if i < total and "is-disabled" not in (await next_btn.get_attribute("class") or ""):
                    await next_btn.click()
                    await asyncio.sleep(3.0)
    except Exception as e:
        log(f"    ❌ [Seq: {seq_num}] Screenshot Failed: {str(e)[:50]} | {url}")
    return "success"

async def process_link(context, row, seq_num, sem):
    url = normalize_url(str(row.get('creative_page_url', '')))
    is_google = "adstransparency.google.com" in url
    is_meta = "facebook.com/ads/library" in url

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            if is_google:
                try: await page.wait_for_selector(".ad-container", timeout=20000)
                except: pass
                await asyncio.sleep(3.0) 

                if not await is_actually_dead(page, url, seq_num):
                    await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
            elif is_meta:
                await asyncio.sleep(5)
                target = page.locator("img.xfn06ss, video.xat24cr, .x1ll56u3 img").first
                if await target.count() > 0:
                    await target.screenshot(path=os.path.join(advertiser_dir, f"{ad_id}.png"))
                    log(f"    ✅ [Seq: {seq_num}] META SAVED | {url}")

        except Exception as e:
            log(f"    ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]} | {url}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    full_df = pd.read_csv(CSV_FILE)

    total_shards = 6
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    shards = np.array_split(full_df, total_shards)
    df = shards[shard_index]
    
    log(f"📋 SHARD {shard_index+1}/6 | {len(df)} rows")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1400})
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()
        log(f"✅ Shard {shard_index+1} Complete.")

if __name__ == "__main__":
    asyncio.run(main())
