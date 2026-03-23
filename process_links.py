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

# Set to a creative ID string to enable extra diagnostic logging for that creative only.
# Set to None to apply debug logging to ALL creatives.
DEBUG_CREATIVE_ID = "CR14180549296201400321"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def dlog(msg, seq_num, ad_id):
    """Debug log — only prints for DEBUG_CREATIVE_ID, or all if None."""
    if DEBUG_CREATIVE_ID is None or (ad_id and DEBUG_CREATIVE_ID in str(ad_id)):
        print(f"[{datetime.now().strftime('%H:%M:%S')}]   🔬 [Seq: {seq_num}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"


async def is_actually_dead(page, url, seq_num):
    """
    Original logic from doc4 — untouched.
    If fletch is present, it is NOT dead. Ignore the banners.
    """
    if await page.locator("fletch-renderer").count() > 0:
        return False

    empty = page.locator(".empty-results").first
    policy = page.locator(".policy-violation-banner").first

    if await empty.is_visible() or await policy.is_visible():
        await asyncio.sleep(5.0)

    if await empty.is_visible():
        text = (await empty.inner_text()).lower()
        if "no ads" in text or "can't find" in text:
            log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Truly Empty | {url}")
            return True

    if await policy.is_visible():
        text = (await policy.inner_text()).lower()
        if "removed" in text or "violation" in text:
            log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Policy Violation | {url}")
            return True

    return False


async def get_container_declared_height(page):
    """
    Read the CSS height declared on the visible .creative-container div
    (set by Angular via inline style). Returns 0 if not found.
    height=5px means a stub/placeholder variation — skip it.
    """
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

    # Original locator fallback chain from doc4 — untouched
    locators = [
        "html-renderer img",
        "html-renderer",
        "iframe[src*='sadbundle']",
        "fletch-renderer",
        "iframe[src*='googlesyndication.com']",
        ".creative-sub-container:not(.hidden)",
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
        log(f"   ❌ [Seq: {seq_num}] ERROR: Target missing in DOM | {url}")
        return "broken"

    if not has_variations:
        # NEW: skip stub variations declared at 5px by Angular
        declared_h = await get_container_declared_height(page)
        dlog(f"declared container height={declared_h}px", seq_num, ad_id)
        if 0 < declared_h <= 5:
            log(f"   ⏭️ [Seq: {seq_num}] SKIPPED: Stub variation (declared height={declared_h}px) | {url}")
            return "broken"

        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        await asyncio.sleep(7.0)
        await target.screenshot(path=file_path)

        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                if hashlib.md5(f.read()).hexdigest()[:8] == BAD_HASH:
                    log(f"   🗑️ [Seq: {seq_num}] DELETED: Blank Render Hash | {url}")
                    os.remove(file_path)
                    return "broken"

        log(f"   ✅ [Seq: {seq_num}] SAVED: {ad_id}.png | {url}")

    else:
        text = await indicator.inner_text()
        match = re.search(r"of (\d+)", text)
        total_vars = int(match.group(1)) if match else 1
        next_btn = page.locator(".variation-right-arrow").first

        log(f"   🎠 [Seq: {seq_num}] Found {total_vars} variations | {url}")

        for i in range(1, total_vars + 1):
            # NEW: skip stub variations declared at 5px by Angular
            declared_h = await get_container_declared_height(page)
            dlog(f"var {i}: declared container height={declared_h}px", seq_num, ad_id)
            if 0 < declared_h <= 5:
                log(f"   ⏭️ [Seq: {seq_num}] SKIPPED VAR {i}/{total_vars}: stub (declared height={declared_h}px) | {url}")
                if i < total_vars:
                    btn_class = await next_btn.get_attribute("class") or ""
                    if "is-disabled" not in btn_class:
                        await next_btn.click()
                        await asyncio.sleep(3.0)
                continue

            current_target = page.locator(".creative-sub-container:not(.hidden)").first
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")

            await asyncio.sleep(5.0)
            await current_target.screenshot(path=v_path)
            log(f"   📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png | {url}")

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

    async with sem:
        advertiser = sanitize_filename(row.get('advertiser_name', 'Unknown'))
        ad_id = extract_id_from_url(url)
        advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
        os.makedirs(advertiser_dir, exist_ok=True)

        page = await context.new_page()
        try:
            log(f"🚀 [Seq: {seq_num}] STARTING: {ad_id} | {url}")
            dlog(f"advertiser='{advertiser}' dir={advertiser_dir}", seq_num, ad_id)

            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            dlog("domcontentloaded fired", seq_num, ad_id)

            try:
                await page.wait_for_selector(".ad-container", timeout=20000)
                dlog(".ad-container appeared in DOM", seq_num, ad_id)
            except Exception:
                dlog(".ad-container never appeared (20s timeout)", seq_num, ad_id)

            if not await is_actually_dead(page, url, seq_num):
                await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)

        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]} | {url}")
            dlog(f"exception detail: {str(e)}", seq_num, ad_id)
        finally:
            await page.close()
            dlog("page closed", seq_num, ad_id)


async def main():
    if not os.path.exists(CSV_FILE):
        log(f"❌ CSV file not found: {CSV_FILE}")
        return

    df = pd.read_csv(CSV_FILE)
    log(f"📋 Loaded {len(df)} rows from {CSV_FILE}")

    total_shards = int(os.environ.get("SHARD_COUNT", 1))
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    if total_shards > 1:
        shards = np.array_split(df, total_shards)
        df = shards[shard_index]
        log(f"🔀 Shard {shard_index+1}/{total_shards}: {len(df)} rows")

    if shard_index == 0:
        target_id = "CR14180549296201400321"
        mask = df['creative_page_url'].str.contains(target_id, na=False)
        if mask.any():
            priority_row = df[mask]
            df = pd.concat([priority_row, df[~mask]], ignore_index=True)
            log(f"🎯 Shard 0: Injected {target_id} as first priority.")
        else:
            log(f"⚠️  Priority creative {target_id} not found in this shard's rows")

    log(f"⚙️  Concurrency={GTC_CONCURRENCY} | "
        f"Debug={'ALL' if DEBUG_CREATIVE_ID is None else DEBUG_CREATIVE_ID}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 1400},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
