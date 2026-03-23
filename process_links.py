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

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"


async def wait_for_fletch_iframe_height(page, container_selector, seq_num, timeout=15.0):
    """
    Polls until the fletch-renderer iframe inside the given container
    has a real height (> 10px), indicating the ad has actually rendered.
    Returns True if loaded, False if timed out.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            # Evaluate JS to get the iframe height inside the visible sub-container
            height = await page.eval_on_selector(
                f"{container_selector} fletch-renderer iframe",
                "el => el.getBoundingClientRect().height"
            )
            if height and height > 10:
                return True
        except Exception:
            pass
        await asyncio.sleep(1.0)
    log(f"   ⏱️ [Seq: {seq_num}] Timed out waiting for fletch iframe to load")
    return False


async def is_actually_dead(page, url, seq_num):
    """
    Surgical check. 
    - If a non-hidden creative-sub-container with fletch-renderer exists → NOT dead.
    - Only mark dead if truly empty-results or a policy-violation banner
      is visible AND there is NO live fletch-renderer container.
    """
    # If ANY non-hidden sub-container with fletch exists → alive
    live_count = await page.locator(
        ".creative-sub-container:not(.hidden) fletch-renderer"
    ).count()
    if live_count > 0:
        return False

    # Fallback: global fletch-renderer (non-variation pages)
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


async def get_visible_sub_container(page):
    """
    Returns the locator for the currently-visible creative-sub-container.
    Uses JS evaluation to bypass Playwright's strict visibility model
    on Angular custom elements.
    """
    # Use nth-match on non-hidden containers — more reliable than is_visible()
    loc = page.locator(".creative-sub-container:not(.hidden)").first
    count = await loc.count()
    if count > 0:
        return loc
    return None


async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.count() > 0
 
    target = None
    for attempt in range(8):
        target = await get_visible_sub_container(page)
        if target and await target.count() > 0:
            break
        log(f"   🔄 [Seq: {seq_num}] Waiting for sub-container (attempt {attempt+1}/8)...")
        await asyncio.sleep(2.5)
 
    if not target or await target.count() == 0:
        fallback = page.locator("fletch-renderer").first
        if await fallback.count() > 0:
            target = fallback
            log(f"   ℹ️ [Seq: {seq_num}] Using fallback fletch-renderer target")
        else:
            log(f"   ❌ [Seq: {seq_num}] ERROR: No renderable target found | {url}")
            return "broken"
 
    if not has_variations:
        loaded = await wait_for_fletch_iframe_height(
            page, ".creative-sub-container:not(.hidden)", seq_num
        )
        if not loaded:
            log(f"   ⚠️ [Seq: {seq_num}] WARNING: Iframe may not be fully loaded, attempting screenshot anyway")
 
        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
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
            # ── NEW: Peek at the iframe height BEFORE doing anything expensive ──
            try:
                iframe_height = await page.eval_on_selector(
                    ".creative-sub-container:not(.hidden) fletch-renderer iframe",
                    "el => el.getBoundingClientRect().height"
                )
            except Exception:
                iframe_height = 0
 
            if iframe_height <= 10:
                log(f"   ⏭️ [Seq: {seq_num}] SKIPPED VAR {i}/{total_vars}: iframe height={iframe_height}px (not rendered) | {url}")
                # Still try to advance to the next variation
                if i < total_vars:
                    btn_class = await next_btn.get_attribute("class") or ""
                    if "is-disabled" not in btn_class:
                        await next_btn.click()
                        await asyncio.sleep(3.5)
                continue
            # ── END NEW ──
 
            current_target = page.locator(".creative-sub-container:not(.hidden)").first
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")
 
            await current_target.screenshot(path=v_path)
 
            if os.path.exists(v_path):
                with open(v_path, "rb") as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()[:8]
                    if file_hash == BAD_HASH:
                        log(f"   🗑️ [Seq: {seq_num}] DELETED VAR {i}: Blank Hash | {url}")
                        os.remove(v_path)
                    else:
                        log(f"   📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png")
 
            if i < total_vars:
                btn_class = await next_btn.get_attribute("class") or ""
                if "is-disabled" not in btn_class:
                    await next_btn.click()
                    await asyncio.sleep(3.5)
                else:
                    log(f"   ⏹️ [Seq: {seq_num}] Next button disabled at var {i}, stopping")
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
            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            # Wait for Angular to settle and render the ad container
            try:
                await page.wait_for_selector(".ad-container", timeout=20000)
            except Exception:
                pass

            # Extra wait for fletch script to execute and inject iframe height
            await asyncio.sleep(3.0)

            if not await is_actually_dead(page, url, seq_num):
                result = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                if result == "broken":
                    log(f"   💔 [Seq: {seq_num}] BROKEN: {ad_id} | {url}")

        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]} | {url}")
        finally:
            await page.close()


async def main():
    if not os.path.exists(CSV_FILE):
        return
    df = pd.read_csv(CSV_FILE)

    total_shards = int(os.environ.get("SHARD_COUNT", 1))
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    if total_shards > 1:
        shards = np.array_split(df, total_shards)
        df = shards[shard_index]

    if shard_index == 0:
        target_id = "CR14180549296201400321"
        mask = df['creative_page_url'].str.contains(target_id, na=False)
        if mask.any():
            priority_row = df[mask]
            df = pd.concat([priority_row, df[~mask]], ignore_index=True)
            log(f"🎯 Shard 0: Injected {target_id} as first priority.")

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


if __name__ == "__main__":
    asyncio.run(main())
