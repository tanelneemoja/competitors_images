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
    """Debug log — prints only if DEBUG_CREATIVE_ID matches, or is None (log all)."""
    if DEBUG_CREATIVE_ID is None or (ad_id and DEBUG_CREATIVE_ID in str(ad_id)):
        print(f"[{datetime.now().strftime('%H:%M:%S')}]   🔬 [Seq: {seq_num}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    match = re.search(r"(?:creative/|id=)([A-Z0-9\d]+)", str(url))
    return match.group(1) if match else "unknown"


async def wait_for_fletch_iframe_ready(page, container_selector, seq_num, ad_id, timeout=20.0):
    """
    Waits until the fletch iframe inside the container has:
    - height > 10px (layout done)
    - AND its contentDocument has real content (ad loaded)

    Falls back gracefully if cross-origin blocks document access —
    in that case, height > 10 is treated as sufficient (the iframe
    is sandboxed so cross-origin access is expected and normal).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    poll = 0
    while asyncio.get_event_loop().time() < deadline:
        poll += 1
        try:
            result = await page.eval_on_selector(
                f"{container_selector} fletch-renderer iframe",
                """el => ({
                    height: el.getBoundingClientRect().height,
                    width: el.getBoundingClientRect().width,
                    src: el.getAttribute('src') || '',
                    hasContent: (() => {
                        try {
                            return el.contentDocument &&
                                   el.contentDocument.body &&
                                   el.contentDocument.body.innerHTML.length > 50;
                        } catch(e) {
                            return el.getBoundingClientRect().height > 10;
                        }
                    })(),
                    sandboxed: el.hasAttribute('sandbox')
                })"""
            )
            dlog(
                f"iframe poll #{poll}: "
                f"height={result['height']}px width={result['width']}px "
                f"hasContent={result['hasContent']} sandboxed={result['sandboxed']} "
                f"src={result['src'][:40]}",
                seq_num, ad_id
            )
            if result['height'] > 10 and result['hasContent']:
                dlog(f"iframe ready after {poll} poll(s)", seq_num, ad_id)
                return True
        except Exception as e:
            dlog(f"iframe poll #{poll} exception: {str(e)[:80]}", seq_num, ad_id)
        await asyncio.sleep(1.0)

    log(f"   ⏱️ [Seq: {seq_num}] Timed out waiting for fletch iframe content to load")
    return False


async def safe_screenshot(target, path, seq_num, ad_id, timeout=10000):
    """
    Takes a screenshot with an explicit short timeout so we fail fast
    instead of hanging for Playwright's default 30s.
    Returns True on success, False on failure.
    """
    dlog(f"attempting screenshot -> {os.path.basename(path)}", seq_num, ad_id)
    try:
        await target.screenshot(path=path, timeout=timeout)
        size_kb = os.path.getsize(path) / 1024 if os.path.exists(path) else 0
        dlog(f"screenshot OK: {os.path.basename(path)} ({size_kb:.1f} KB)", seq_num, ad_id)
        return True
    except Exception as e:
        log(f"   ⚠️ [Seq: {seq_num}] Screenshot failed: {str(e)[:80]}")
        return False


async def log_page_state(page, seq_num, ad_id, label=""):
    """Full DOM snapshot of key selectors — only emitted for debug creatives."""
    try:
        state = await page.evaluate("""() => {
            const allSubs = document.querySelectorAll('.creative-sub-container');
            const visibleSubs = document.querySelectorAll('.creative-sub-container:not(.hidden)');
            const iframes = document.querySelectorAll('fletch-renderer iframe');
            const indicator = document.querySelector('.variation-index-indicator');
            const emptyResults = document.querySelector('.empty-results');
            const policyBanner = document.querySelector('.policy-violation-banner');
            const adContainer = document.querySelector('.ad-container');

            return {
                totalSubContainers: allSubs.length,
                visibleSubContainers: visibleSubs.length,
                totalIframes: iframes.length,
                iframeDetails: Array.from(iframes).map((el, i) => ({
                    index: i,
                    height: el.getBoundingClientRect().height,
                    width: el.getBoundingClientRect().width,
                    src: (el.getAttribute('src') || '').slice(0, 60),
                    sandboxed: el.hasAttribute('sandbox'),
                    hidden: el.closest('.hidden') !== null
                })),
                variationIndicator: indicator ? indicator.innerText.trim() : null,
                hasEmptyResults: !!emptyResults,
                emptyResultsVisible: emptyResults ? emptyResults.offsetParent !== null : false,
                emptyResultsText: emptyResults ? emptyResults.innerText.trim().slice(0, 80) : null,
                hasPolicyBanner: !!policyBanner,
                policyBannerVisible: policyBanner ? policyBanner.offsetParent !== null : false,
                policyBannerText: policyBanner ? policyBanner.innerText.trim().slice(0, 80) : null,
                hasAdContainer: !!adContainer,
                pageTitle: document.title.slice(0, 60),
                pageUrl: window.location.href.slice(0, 100)
            };
        }""")

        prefix = f"[{label}] " if label else ""
        dlog(f"{prefix}--- page state ---", seq_num, ad_id)
        dlog(f"  title        : {state['pageTitle']}", seq_num, ad_id)
        dlog(f"  url          : {state['pageUrl']}", seq_num, ad_id)
        dlog(f"  adContainer  : {state['hasAdContainer']}", seq_num, ad_id)
        dlog(f"  subContainers: total={state['totalSubContainers']} visible={state['visibleSubContainers']}", seq_num, ad_id)
        dlog(f"  iframes      : total={state['totalIframes']}", seq_num, ad_id)
        for iframe in state['iframeDetails']:
            dlog(
                f"    iframe[{iframe['index']}]: {iframe['width']}x{iframe['height']}px "
                f"hidden={iframe['hidden']} sandboxed={iframe['sandboxed']} src={iframe['src']}",
                seq_num, ad_id
            )
        dlog(f"  variation    : {state['variationIndicator']}", seq_num, ad_id)
        dlog(f"  emptyResults : visible={state['emptyResultsVisible']} text={state['emptyResultsText']}", seq_num, ad_id)
        dlog(f"  policyBanner : visible={state['policyBannerVisible']} text={state['policyBannerText']}", seq_num, ad_id)
        dlog(f"  --- end state ---", seq_num, ad_id)

    except Exception as e:
        dlog(f"log_page_state [{label}] failed: {str(e)[:80]}", seq_num, ad_id)


async def is_actually_dead(page, url, seq_num, ad_id):
    """
    Surgical check.
    - If a non-hidden creative-sub-container with fletch-renderer exists -> NOT dead.
    - Only mark dead if truly empty-results or a policy-violation banner
      is visible AND there is NO live fletch-renderer container.
    """
    live_count = await page.locator(
        ".creative-sub-container:not(.hidden) fletch-renderer"
    ).count()
    dlog(f"is_actually_dead: live fletch containers = {live_count}", seq_num, ad_id)

    if live_count > 0:
        return False

    global_fletch = await page.locator("fletch-renderer").count()
    dlog(f"is_actually_dead: global fletch-renderer count = {global_fletch}", seq_num, ad_id)
    if global_fletch > 0:
        return False

    empty = page.locator(".empty-results").first
    policy = page.locator(".policy-violation-banner").first

    empty_visible = await empty.is_visible()
    policy_visible = await policy.is_visible()
    dlog(f"is_actually_dead: empty-results visible={empty_visible} | policy-banner visible={policy_visible}", seq_num, ad_id)

    if empty_visible or policy_visible:
        await asyncio.sleep(5.0)

    if await empty.is_visible():
        text = (await empty.inner_text()).lower()
        dlog(f"is_actually_dead: empty-results text = '{text[:80]}'", seq_num, ad_id)
        if "no ads" in text or "can't find" in text:
            log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Truly Empty | {url}")
            return True

    if await policy.is_visible():
        text = (await policy.inner_text()).lower()
        dlog(f"is_actually_dead: policy-banner text = '{text[:80]}'", seq_num, ad_id)
        if "removed" in text or "violation" in text:
            log(f"   ⚠️ [Seq: {seq_num}] SKIPPED: Policy Violation | {url}")
            return True

    return False


async def get_visible_sub_container(page):
    """
    Returns the locator for the currently-visible creative-sub-container.
    Uses nth-match on non-hidden containers — more reliable than is_visible()
    on Angular custom elements.
    """
    loc = page.locator(".creative-sub-container:not(.hidden)").first
    count = await loc.count()
    if count > 0:
        return loc
    return None


async def handle_google_variations(page, advertiser_dir, ad_id, seq_num, url):
    indicator = page.locator(".variation-index-indicator").first
    has_variations = await indicator.count() > 0
    dlog(f"has_variations={has_variations}", seq_num, ad_id)

    target = None
    for attempt in range(8):
        target = await get_visible_sub_container(page)
        if target and await target.count() > 0:
            dlog(f"sub-container found on attempt {attempt+1}", seq_num, ad_id)
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
            await log_page_state(page, seq_num, ad_id, label="no-target")
            return "broken"

    if not has_variations:
        await log_page_state(page, seq_num, ad_id, label="before-iframe-wait")

        loaded = await wait_for_fletch_iframe_ready(
            page, ".creative-sub-container:not(.hidden)", seq_num, ad_id
        )
        if not loaded:
            log(f"   ⚠️ [Seq: {seq_num}] WARNING: Iframe content may not be ready, attempting screenshot anyway")

        await log_page_state(page, seq_num, ad_id, label="after-iframe-wait")

        file_path = os.path.join(advertiser_dir, f"{ad_id}.png")
        ok = await safe_screenshot(target, file_path, seq_num, ad_id)
        if not ok:
            await log_page_state(page, seq_num, ad_id, label="screenshot-fail")
            return "broken"

        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                file_hash = hashlib.md5(f.read()).hexdigest()[:8]
                dlog(f"file hash: {file_hash} (bad={BAD_HASH})", seq_num, ad_id)
                if file_hash == BAD_HASH:
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
        await log_page_state(page, seq_num, ad_id, label="variations-start")

        for i in range(1, total_vars + 1):
            dlog(f"--- variation {i}/{total_vars} ---", seq_num, ad_id)

            try:
                result = await page.eval_on_selector(
                    ".creative-sub-container:not(.hidden) fletch-renderer iframe",
                    """el => ({
                        height: el.getBoundingClientRect().height,
                        width: el.getBoundingClientRect().width,
                        hasContent: (() => {
                            try {
                                return el.contentDocument &&
                                       el.contentDocument.body &&
                                       el.contentDocument.body.innerHTML.length > 50;
                            } catch(e) {
                                return el.getBoundingClientRect().height > 10;
                            }
                        })()
                    })"""
                )
                iframe_height = result['height']
                iframe_has_content = result['hasContent']
                dlog(
                    f"var {i}: iframe {result['width']}x{iframe_height}px "
                    f"hasContent={iframe_has_content}",
                    seq_num, ad_id
                )
            except Exception as e:
                iframe_height = 0
                iframe_has_content = False
                dlog(f"var {i}: iframe eval failed: {str(e)[:60]}", seq_num, ad_id)

            if iframe_height <= 10 or not iframe_has_content:
                log(f"   ⏭️ [Seq: {seq_num}] SKIPPED VAR {i}/{total_vars}: "
                    f"height={iframe_height}px hasContent={iframe_has_content} | {url}")
                if i < total_vars:
                    btn_class = await next_btn.get_attribute("class") or ""
                    dlog(f"var {i}: next-btn class='{btn_class[:60]}'", seq_num, ad_id)
                    if "is-disabled" not in btn_class:
                        await next_btn.click()
                        await asyncio.sleep(3.5)
                continue

            current_target = page.locator(".creative-sub-container:not(.hidden)").first
            v_path = os.path.join(advertiser_dir, f"{ad_id}_{i}.png")

            ok = await safe_screenshot(current_target, v_path, seq_num, ad_id)
            if not ok:
                log(f"   💔 [Seq: {seq_num}] Screenshot failed for var {i}, skipping")
                await log_page_state(page, seq_num, ad_id, label=f"var{i}-screenshot-fail")
                if i < total_vars:
                    btn_class = await next_btn.get_attribute("class") or ""
                    if "is-disabled" not in btn_class:
                        await next_btn.click()
                        await asyncio.sleep(3.5)
                continue

            if os.path.exists(v_path):
                with open(v_path, "rb") as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()[:8]
                    dlog(f"var {i} hash: {file_hash} (bad={BAD_HASH})", seq_num, ad_id)
                    if file_hash == BAD_HASH:
                        log(f"   🗑️ [Seq: {seq_num}] DELETED VAR {i}: Blank Hash | {url}")
                        os.remove(v_path)
                    else:
                        log(f"   📸 [Seq: {seq_num}] SAVED VAR {i}/{total_vars}: {ad_id}_{i}.png")

            if i < total_vars:
                btn_class = await next_btn.get_attribute("class") or ""
                dlog(f"var {i}: next-btn class='{btn_class[:60]}'", seq_num, ad_id)
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
            dlog(f"advertiser='{advertiser}' dir={advertiser_dir}", seq_num, ad_id)

            await page.goto(url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)
            dlog("domcontentloaded fired", seq_num, ad_id)

            # Wait for Angular to settle and render the ad container
            try:
                await page.wait_for_selector(".ad-container", timeout=20000)
                dlog(".ad-container appeared in DOM", seq_num, ad_id)
            except Exception:
                dlog(".ad-container never appeared (20s timeout)", seq_num, ad_id)

            # Increased sleep: fletch content.js is async and needs time to
            # inject ad content into the sandboxed iframe after Angular settles
            dlog("sleeping 5s for fletch content.js to fire...", seq_num, ad_id)
            await asyncio.sleep(5.0)

            await log_page_state(page, seq_num, ad_id, label="after-initial-load")

            dead = await is_actually_dead(page, url, seq_num, ad_id)
            dlog(f"is_actually_dead={dead}", seq_num, ad_id)

            if not dead:
                result = await handle_google_variations(page, advertiser_dir, ad_id, seq_num, url)
                dlog(f"handle_google_variations result={result}", seq_num, ad_id)
                if result == "broken":
                    log(f"   💔 [Seq: {seq_num}] BROKEN: {ad_id} | {url}")

        except Exception as e:
            log(f"   ❌ [Seq: {seq_num}] FAIL: {str(e)[:100]} | {url}")
            dlog(f"exception full detail: {str(e)}", seq_num, ad_id)
            await log_page_state(page, seq_num, ad_id, label="exception")
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
        f"Debug={'ALL creatives' if DEBUG_CREATIVE_ID is None else DEBUG_CREATIVE_ID}")

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
