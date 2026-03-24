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
BAD_HASH = "f1813cb9"

PROCESS_META = False
PROCESS_GOOGLE = True
REGION = "EE"

# The specific ID that needs deep diagnostics
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
    if await page.locator("fletch-renderer, html-renderer").count() > 0:
        return False
    empty = page.locator(".empty-results").first
    policy = page.locator(".policy-violation-banner").first
    if await empty.is_visible() or await policy.is_visible():
        await asyncio.sleep(5.0)
    if await empty.is_visible():
        text = (await empty.inner_text()).lower()
        if "no ads" in text or "can't find" in text:
            log(f"    ⚠️ [Seq: {seq_num}] SKIPPED: Truly Empty | {url}")
            return True
    if await policy.is_visible():
        text = (await policy.inner_text()).lower()
        if "removed" in text or "violation" in text:
            log(f"    ⚠️ [Seq: {seq_num}] SKIPPED: Policy Violation | {url}")
            return True
    return False

async def get_container_declared_height(page):
    try:
        return await page.eval_on_selector(
            ".creative-sub-container:not(.hidden) .creative-container",
            "el => { const h = el.style.height; return h ? parseInt(h) : 0; }"
        )
    except Exception:
        return 0

async def handle_meta_ad(page, advertiser_dir, ad_id, seq_num, url):
    try:
        target = page.locator("img.xfn06ss, video.xat24cr, .x1ll56u3 img").first
        if await target.count() == 0:
            target = page.locator("div[role='button'] img").first 

        if await target.count() > 0:
            file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
            await target.screenshot(path=file_path)
            log(f"    ✅ [Seq: {seq_num}] META SAVED: {ad_id}.png")
        else:
            log(f"    ❌ [Seq: {seq_num}] META ERROR: No creative found | {url}")
    except Exception as e:
        log(f"    ❌ [Seq: {seq_num}] META FAIL: {str(e)[:50]}")

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    is_diag = (ad_id == DIAGNOSTIC_TARGET_ID)
    
    # --- NEW: VIDEO FORMAT SKIP LOGIC ---
    # Looks for the property div containing "Format: Video"
    format_locator = page.locator("div.property")
    count = await format_locator.count()
    for i in range(count):
        text = await format_locator.nth(i).inner_text()
        if "Format:" in text and "Video" in text:
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Video Format Detected | {ad_id}")
            return "skipped_video"

    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()

    locators = [
        "html-renderer img", "html-renderer", "fletch-renderer",
        "iframe[src*='sadbundle']", "iframe[src*='googlesyndication.com']",
        ".creative-sub-container:not(.hidden)", ".creative-container"
    ]

    target = None
    if is_diag: log(f"    🔍 [DIAGNOSTIC] Probing DOM for {ad_id}...")

    for attempt in range(1, 4):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                is_vis = await loc.is_visible()
                box = await loc.bounding_box()
                if is_vis or (box and box['width'] > 5 and box['height'] > 5):
                    if is_diag: log(f"    🎯 [DIAGNOSTIC] Found target via {selector}")
                    target = loc
                    break
        if target: break
        await asyncio.sleep(2)

    if not target:
        log(f"    ❌ [Seq: {seq_num}] ERROR: Target missing | {url}")
        return "broken"

    if not has_variations:
        declared_h = await get_container_declared_height(page)
        if 0 < declared_h <= 5:
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Stub (height={declared_h}px)")
            return "broken"

        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await asyncio.sleep(6.0)
        await target.screenshot(path=file_path)
        log(f"    ✅ [Seq: {seq_num}] GOOGLE SAVED: {ad_id}.png")
    else:
        text = await indicator.inner_text()
        total_vars = int(re.search(r"of (\d+)", text).group(1)) if "of" in text else 1
        next_btn = page.locator(".variation-right-arrow").first
        for i in range(1, total_vars + 1):
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
            await asyncio.sleep(4.0)
            await page.locator(".creative-sub-container:not(.hidden)").first.screenshot(path=v_path)
            log(f"    📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}")
            if i < total_vars and "is-disabled" not in (await next_btn.get_attribute("class") or ""):
                await next_btn.click()
                await asyncio.sleep(3.0)
    return "success"

async def process_link(context, row, seq_num, sem):
    url = normalize_url(str(row.get('creative_page_url', '')))
    is_google = "adstransparency.google.com" in url
    is_meta = "facebook.com/ads/library" in url

    if (is_google and not PROCESS_GOOGLE) or (is_meta and not PROCESS_META): return

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            if is_google:
                if not await is_actually_dead(page, url, seq_num):
                    await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
            elif is_meta:
                await asyncio.sleep(4)
                await handle_meta_ad(page, advertiser_dir, ad_id, seq_num, url)

        except Exception as e:
            log(f"    ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): return
    df = pd.read_csv(CSV_FILE)

    target_ids = ["CR14180549296201400321", DIAGNOSTIC_TARGET_ID]
    priority = df[df['creative_page_url'].str.contains('|'.join(target_ids), na=False)]
    others = df[~df['creative_page_url'].str.contains('|'.join(target_ids), na=False)]
    df = pd.concat([priority, others], ignore_index=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1400})
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [process_link(context, row, i, sem) for i, (_, row) in enumerate(df.iterrows(), 1)]
        await asyncio.gather(*tasks)
        await browser.close()
        log("✅ All tasks complete.")

if __name__ == "__main__":
    asyncio.run(main())
