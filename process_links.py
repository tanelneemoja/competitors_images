import os
import asyncio
import pandas as pd
import re
import shutil
import stat
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np
import base64

# --- CONFIGURATION ---
CSV_FILE = "meta_links.csv"
BASE_DATA_DIR = "data"
META_CONCURRENCY = 15
GTC_TIMEOUT = 60000
TEST_LIMIT = 0  # Set to None or 0 to process the full dataset

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def get_case_insensitive_val(row, key_names, default=""):
    """Finds a column value regardless of header casing (e.g., 'ID', 'id', 'Id')."""
    row_dict = {str(k).strip().lower(): v for k, v in row.items()}
    for key in key_names:
        key_lower = key.lower()
        if key_lower in row_dict and pd.notna(row_dict[key_lower]):
            val = str(row_dict[key_lower]).strip()
            if val:
                return val
    return default

def extract_id_from_url(url):
    """Fallback ID extractor from Meta URLs if CSV column fails."""
    match = re.search(r"(?:id=|creative/|sadbundle/|simgad/|ad_id=)([0-9]+)", str(url))
    return match.group(1) if match else ""

def remove_readonly(func, path, exc_info):
    """Clear read-only file attributes if permission is denied during folder deletion."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def prepare_data_directory(shard_index):
    """Only clears the data directory on Shard 0 (or single-shard runs) to avoid wiping peer output."""
    if not os.path.exists(BASE_DATA_DIR):
        os.makedirs(BASE_DATA_DIR, exist_ok=True)
        log(f"✨ Created fresh '{BASE_DATA_DIR}' directory.")
        return

    if shard_index == 0:
        log(f"🧹 [Shard 1 Init] Clearing previous contents in '{BASE_DATA_DIR}'...")
        for item in os.listdir(BASE_DATA_DIR):
            item_path = os.path.join(BASE_DATA_DIR, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path, onerror=remove_readonly)
                else:
                    os.chmod(item_path, stat.S_IWRITE)
                    os.remove(item_path)
            except Exception as e:
                log(f"⚠️ Could not delete {item_path}: {e}")
        log(f"✨ Clean '{BASE_DATA_DIR}' directory ready.")

def append_to_github_summary(file_path, ad_id, seq_num, shard_tag):
    """Appends an embedded thumbnail directly into the GitHub Actions Job Summary UI."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file or not os.path.exists(file_path):
        return

    try:
        with open(file_path, "rb") as img_f:
            encoded = base64.b64encode(img_f.read()).decode("utf-8")

        markdown_block = (
            f"<details><summary><b>[{shard_tag} | Seq: {seq_num}] Ad ID: {ad_id}</b></summary>\n\n"
            f'<img src="data:image/jpeg;base64,{encoded}" width="350"/>\n'
            f"</details>\n\n"
        )
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(markdown_block)
    except Exception:
        pass

async def process_meta_link(context, row, seq_num, meta_sem, shard_tag):
    raw_url = get_case_insensitive_val(row, ['ad_snapshot_url', 'creative_page_url', 'url'])
    ad_id = get_case_insensitive_val(row, ['id', 'ad_id', 'library_id'])
    
    # Fallback to URL extraction if ID column is missing/empty
    if not ad_id or ad_id.lower() == "unknown":
        ad_id = extract_id_from_url(raw_url) or "unknown"

    advertiser_raw = get_case_insensitive_val(row, ['page_name', 'advertiser'], 'Unknown')
    advertiser = sanitize_filename(advertiser_raw)
    
    advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
    save_path = os.path.join(advertiser_dir, f"{ad_id}.jpg")

    # SKIP LOGIC
    if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
        log(f"⏩ [{shard_tag} | Seq: {seq_num}] SKIPPED (Already exists): {ad_id}")
        append_to_github_summary(save_path, ad_id, seq_num, shard_tag)
        return

    os.makedirs(advertiser_dir, exist_ok=True)

    async with meta_sem:
        log(f"🔍 [{shard_tag} | Seq: {seq_num}] START META: {ad_id} | Advertiser: {advertiser}")
        page = await context.new_page()
        try:
            await page.route(
                re.compile(r"(google-analytics|connect\.facebook\.net/.*signals|doubleclick|analytics)"), 
                lambda route: route.abort()
            )

            # 1. Navigation
            await page.goto(raw_url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            # 2. Dynamic wait for primary containers (Image or Video)
            try:
                await page.wait_for_selector(
                    "div[data-testid='ad-library-dynamic-content-container'], "
                    "div[data-testid='ad-content-body-video-container'], "
                    "[role='dialog'], [role='article']",
                    timeout=10000
                )
            except Exception:
                pass

            # 3. Wait for video poster / image assets to fully render
            await page.wait_for_timeout(3500)

           # 4. Check primary container testid first
            primary_locator = page.locator("div[data-testid='ad-library-dynamic-content-container']").first

            if await primary_locator.count() > 0 and await primary_locator.is_visible():
                await primary_locator.screenshot(path=save_path, type="jpeg", quality=80)
                append_to_github_summary(save_path, ad_id, seq_num, shard_tag)
                log(f"    📸 [{shard_tag} | Seq: {seq_num}] SAVED AD CARD (JPG): {save_path}")
            else:
                # 5. Robust Fallback: Locates full card parent wrapping Header, Video/Image & CTA
                card_locator = page.locator(
                    "xpath=//*[contains(text(), 'Library ID:')]/ancestor::div["
                    ".//video or .//div[@data-testid='ad-content-body-video-container'] or .//a[contains(@href, 'l.facebook.com')]"
                    "][last()]"
                ).first

                # Secondary fallback if [last()] ancestor evaluates too high
                if await card_locator.count() == 0 or not await card_locator.is_visible():
                    card_locator = page.locator("xpath=//*[contains(text(), 'Library ID:')]/ancestor::div[2]").first

                assets_heading = page.locator("xpath=//*[contains(text(), 'Additional assets from this ad')]").first

                if await card_locator.count() > 0 and await card_locator.is_visible():
                    card_box = await card_locator.bounding_box()

                    # Crop out "Additional assets" section if present
                    if assets_heading and await assets_heading.count() > 0 and await assets_heading.is_visible():
                        heading_box = await assets_heading.bounding_box()

                        if card_box and heading_box and heading_box['y'] > card_box['y']:
                            clip_height = max(100, heading_box['y'] - card_box['y'])
                            await page.screenshot(
                                path=save_path,
                                type="jpeg",
                                quality=80,
                                clip={
                                    'x': card_box['x'],
                                    'y': card_box['y'],
                                    'width': card_box['width'],
                                    'height': clip_height
                                }
                            )
                            append_to_github_summary(save_path, ad_id, seq_num, shard_tag)
                            log(f"    📸 [{shard_tag} | Seq: {seq_num}] SAVED CROPPED CARD (JPG): {save_path}")
                            return

                    # Full card screenshot
                    await card_locator.screenshot(path=save_path, type="jpeg", quality=80)
                    append_to_github_summary(save_path, ad_id, seq_num, shard_tag)
                    log(f"    📸 [{shard_tag} | Seq: {seq_num}] SAVED ANCHORED CARD (JPG): {save_path}")
                else:
                    # Final fallback to body element
                    await page.locator("body").screenshot(path=save_path, type="jpeg", quality=80)
                    append_to_github_summary(save_path, ad_id, seq_num, shard_tag)
                    log(f"    📸 [{shard_tag} | Seq: {seq_num}] SAVED BODY FALLBACK (JPG): {save_path}")

        except Exception as e:
            log(f"    ❌ [{shard_tag} | Seq: {seq_num}] FAIL META: {str(e)[:60]} | {raw_url}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        log(f"❌ Input CSV file '{CSV_FILE}' not found.")
        return

    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    total_shards = int(os.environ.get("TOTAL_SHARDS", 6))

    if shard_index >= total_shards:
        total_shards = shard_index + 1

    shard_tag = f"Shard {shard_index + 1}/{total_shards}"

    prepare_data_directory(shard_index)

    full_df = pd.read_csv(CSV_FILE)
    
    cols_lower = [str(c).strip().lower() for c in full_df.columns]
    url_col_name = None
    for target in ['ad_snapshot_url', 'creative_page_url', 'url']:
        if target in cols_lower:
            url_col_name = full_df.columns[cols_lower.index(target)]
            break

    if not url_col_name:
        log("❌ No valid snapshot URL column found in CSV headers.")
        return

    meta_mask = full_df[url_col_name].astype(str).str.contains(
        r"facebook\.com|fb\.me", case=False, na=False
    )
    meta_df = full_df[meta_mask].copy()
    
    if len(meta_df) == 0:
        log("⚠️ No Meta links found in dataset. Exiting.")
        return

    if TEST_LIMIT and TEST_LIMIT > 0:
        meta_df = meta_df.head(TEST_LIMIT)
        log(f"🧪 [TEST MODE ACTIVE] Restricted run to first {len(meta_df)} rows.")

    meta_df['global_seq'] = range(1, len(meta_df) + 1)
    total_rows = len(meta_df)

    if total_shards > 1:
        shards = np.array_split(meta_df, total_shards)
        df_to_process = shards[shard_index]
        
        if len(df_to_process) == 0:
            log(f"🧩 [{shard_tag}] No rows assigned to this shard.")
            return

        seq_min = df_to_process['global_seq'].min()
        seq_max = df_to_process['global_seq'].max()
        log(f"🧩 Running {shard_tag} ({len(df_to_process)} / {total_rows} assigned | Range: Seq {seq_min} to {seq_max}).")
    else:
        df_to_process = meta_df
        log(f"🚀 Processing all {total_rows} Meta links.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1280, 'height': 1200})
        meta_sem = asyncio.Semaphore(META_CONCURRENCY)
        
        tasks = [
            process_meta_link(context, row, int(row['global_seq']), meta_sem, shard_tag) 
            for _, row in df_to_process.iterrows()
        ]
        await asyncio.gather(*tasks)
        await browser.close()
        
    log(f"🏁 [{shard_tag}] PROCESSING COMPLETE.")

if __name__ == "__main__":
    asyncio.run(main())
