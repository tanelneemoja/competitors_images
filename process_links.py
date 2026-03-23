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

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"

def normalize_url(url):
    if "region=" not in url:
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

async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.is_visible()

    # Locator priority: html-renderer first to catch text-based ads
    locators = [
        "html-renderer", 
        "fletch-renderer",
        "html-renderer img",
        "iframe[src*='sadbundle']",
        "iframe[src*='googlesyndication.com']",
        ".creative-sub-container:not(.hidden) .creative-container",
        ".creative-container"
    ]

    target = None
    for _ in range(5):
        for selector in locators:
            loc = page.locator(selector).first
            if await loc.is_visible():
                target = loc
                break
        if target:
            break
        await asyncio.sleep(2)

    if not target:
        log(f"    ❌ [Seq: {seq_num}] ERROR: Target missing in DOM | {url}")
        return "broken"

    if not has_variations:
        declared_h = await get_container_declared_height(page)
        if 0 < declared_h <= 2:
            log(f"    ⏭️ [Seq: {seq_num}] SKIPPED: Stub variation (height={declared_h}px) | {url}")
            return "broken"

        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await asyncio.sleep(5.0) 
        await target.screenshot(path=file_path)

        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                    log(f"    🗑️ [Seq: {seq_num}] DELETED: Blank Render Hash | {url}")
                    os.remove(file_path)
                    return "broken"

        log(f"    ✅ [Seq: {seq_num}] SAVED: {ad_id}.png | {url}")

    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        next_btn = page.locator(".variation-right-arrow").first

        log(f"    🎠 [Seq: {seq_num}] Found {total_vars} variations | {url}")

        for i in range(1, total_vars + 1):
            declared_h = await get_container_declared_height(page)
            if 0 < declared_h <= 2:
                log(f"    ⏭️ [Seq: {seq_num}] SKIPPED VAR {i}/{total_vars}: stub | {url}")
            else:
                current_target = page.locator(".creative-sub-container:not(.hidden)").first
                v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")

                await asyncio.sleep(4.0)
                await current_target.screenshot(path=v_path)
                log(f"    📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png | {url}")

            if i < total_vars:
                btn_class = await next_btn.get_attribute("class") or ""
                if "is-disabled" not in btn_class:
                    await next_btn.click()
                    await asyncio.sleep(3.0)
                else:
                    break

    return "success"

async def process_link(context, row, seq_num, sem):
    url = str(row.get('creative_page_url', ''))
    if "adstransparency.google.com" not in url:
        return

    url = normalize_url(url)

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            try:
                await page.wait_for_selector(".ad-container", timeout=20000)
            except Exception:
                pass

            if not await is_actually_dead(page, url, seq_num):
                await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)

        except Exception as e:
            log(f"    ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]} | {url}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE):
        log(f"❌ CSV file not found: {CSV_FILE}")
        return

    df = pd.read_csv(CSV_FILE)
    log(f"📋 Loaded {len(df)} rows from {CSV_FILE}")

    total_shards = int(os.environ.get("SHARD_COUNT", 1))
    shard_index = int(os.environ.get("SHARD_INDEX", 0))

    # --- UPDATED PRIORITY INJECTION (Multiple IDs) ---
    target_ids = ["CR14180549296201400321", "CR14981377662579113985"]
    
    priority_rows = []
    for tid in target_ids:
        mask = df['creative_page_url'].str.contains(tid, na=False)
        if mask.any():
            priority_rows.append(df[mask])
            df = df[~mask]
    
    if priority_rows:
        df = pd.concat(priority_rows + [df], ignore_index=True)
        log(f"🎯 Priority Injection: Moved {len(priority_rows)} target IDs to the top.")

    if total_shards > 1:
        shards = np.array_split(df, total_shards)
        df = shards[shard_index]
        log(f"🔀 Shard {shard_index+1}/{total_shards}: {len(df)} rows")

    log(f"⚙️  Concurrency={GTC_CONCURRENCY} | Region={REGION}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        sem = asyncio.Semaphore(GTC_CONCURRENCY)
        tasks = [
            process_link(context, row, i, sem)
            for i, (_, row) in enumerate(df.iterrows(), 1)
        ]
        await asyncio.gather(*tasks)
        await browser.close()
        log("✅ All tasks complete.")

if __name__ == "__main__":
    asyncio.run(main())
