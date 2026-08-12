import os
import asyncio
import pandas as pd
import re
import shutil
import stat
import urllib.parse
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np
import base64

# --- CONFIGURATION ---
CSV_FILE = "BALLZY_Table.csv"
BASE_DATA_DIR = "data"
META_CONCURRENCY = 15
GTC_TIMEOUT = 60000
ROW_LIMIT = 10  # 👈 Process only the first 10 rows for testing

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '', str(name or "Unknown")).strip()

def extract_id_from_url(url):
    """Extracts numeric ad ID from Meta archive/render URLs or standard library URLs."""
    match = re.search(r"(?:id=|creative/|sadbundle/|simgad/)([0-9]+)", str(url))
    return match.group(1) if match else "unknown"

def remove_readonly(func, path, exc_info):
    """Clear read-only file attributes if permission is denied during folder deletion."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def reset_data_directory():
    """Safely wipes all subdirectories and files inside 'data/' without breaking locks."""
    if not os.path.exists(BASE_DATA_DIR):
        os.makedirs(BASE_DATA_DIR, exist_ok=True)
        log(f"✨ Created fresh '{BASE_DATA_DIR}' directory.")
        return

    log(f"🧹 Clearing previous contents in '{BASE_DATA_DIR}'...")
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
            f"<details open><summary><b>[{shard_tag} | Seq: {seq_num}] Ad ID: {ad_id}</b></summary>\n\n"
            f'<img src="data:image/png;base64,{encoded}" width="350"/>\n'
            f"</details>\n\n"
        )
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(markdown_block)
    except Exception:
        pass

async def process_meta_link(context, row, seq_num, meta_sem, shard_tag):
    raw_url = str(row.get('creative_page_url', ''))
    ad_id = extract_id_from_url(raw_url)
    advertiser = sanitize_filename(row.get('advertiser', 'Unknown'))
    advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
    
    os.makedirs(advertiser_dir, exist_ok=True)

    async with meta_sem:
        log(f"🔍 [{shard_tag} | Seq: {seq_num}] START META: {ad_id} | Advertiser: {advertiser}")
        page = await context.new_page()
        try:
            # 1. Navigate to ad link
            await page.goto(raw_url, wait_until="domcontentloaded", timeout=GTC_TIMEOUT)

            # 2. Wait for modal or structural ad element using stable identifiers
            try:
                await page.wait_for_selector(
                    "text=This ad is from a URL link, [role='dialog'], [role='article'], [data-testid='ad-library-dynamic-content-container']",
                    timeout=20000
                )
            except Exception:
                pass

            # 3. Wait out loading spinners
            try:
                await page.wait_for_selector("text=Loading...", state="detached", timeout=10000)
            except Exception:
                pass

            await page.wait_for_timeout(3500)

           # 4. Target the isolated ad creative card without depending on hashed class names
            card_locator = None
            
            # Selector 1: Stable, explicit data-testid attribute for the creative wrapper
            dynamic_container = page.locator("div[data-testid='ad-library-dynamic-content-container']")
            
            if await dynamic_container.count() > 0 and await dynamic_container.is_visible():
                card_locator = dynamic_container.first
            else:
                # Selector 2: Anchor to the 'Sponsored' text node and walk up to its main container box
                # Finds the ancestor container right below the <hr> divider / metadata section
                sponsored_node = page.locator("text='Sponsored'").first
                if await sponsored_node.count() > 0:
                    # XPath explanation:
                    # - Tries finding data-testid parent first
                    # - Fallback: steps up to the div immediately following the horizontal rule (<hr>)
                    card_locator = sponsored_node.locator(
                        "xpath=ancestor::div[@data-testid='ad-library-dynamic-content-container'] | "
                        "ancestor::hr/following-sibling::div[1]"
                    ).first

            save_path = os.path.join(advertiser_dir, f"{ad_id}.png")

            # 5. Capture screenshot
            if card_locator and await card_locator.is_visible():
                await card_locator.screenshot(path=save_path)
                append_to_github_summary(save_path, ad_id, seq_num, shard_tag)
                log(f"    📸 [{shard_tag} | Seq: {seq_num}] SAVED AD CARD: {save_path}")

        except Exception as e:
            log(f"    ❌ [{shard_tag} | Seq: {seq_num}] FAIL META: {str(e)[:60]} | {raw_url}")
        finally:
            await page.close()

async def main():
    if not os.path.exists(CSV_FILE): 
        log(f"❌ Input CSV file '{CSV_FILE}' not found.")
        return

    # 1. Reset local data directory at start
    reset_data_directory()

    # 2. Read CSV and filter ONLY Meta links
    full_df = pd.read_csv(CSV_FILE)
    
    meta_mask = full_df['creative_page_url'].astype(str).str.contains(
        r"facebook\.com/ads/(?:library|archive)", case=False, na=False
    )
    meta_df = full_df[meta_mask].copy()
    
    if len(meta_df) == 0:
        log("⚠️ No Meta links found matching 'facebook.com/ads/library' or 'facebook.com/ads/archive'. Exiting.")
        return

    # ------------------------------------------------------------------
    # 🧪 TEST LIMIT: Cap dataset to the first 10 Meta links before sharding
    # ------------------------------------------------------------------
    if len(meta_df) > ROW_LIMIT:
        log(f"🧪 APPLYING TEST LIMIT: Processing first {ROW_LIMIT} rows out of {len(meta_df)} total Meta links.")
        meta_df = meta_df.head(ROW_LIMIT).copy()

    # Assign persistent global index (1 to N)
    meta_df['global_seq'] = range(1, len(meta_df) + 1)

    # 3. Dynamic Sharding Logic
    shard_index = int(os.environ.get("SHARD_INDEX", 0))
    total_shards = int(os.environ.get("TOTAL_SHARDS", 6))

    if shard_index >= total_shards:
        total_shards = shard_index + 1

    shard_tag = f"Shard {shard_index + 1}/{total_shards}"
    
    if total_shards > 1:
        shards = np.array_split(meta_df, total_shards)
        df_to_process = shards[shard_index]
        
        if len(df_to_process) == 0:
            log(f"🧩 [{shard_tag}] No rows assigned to this shard for the {ROW_LIMIT}-row test batch.")
            return

        seq_min = df_to_process['global_seq'].min()
        seq_max = df_to_process['global_seq'].max()
        log(f"🧩 Running {shard_tag} ({len(df_to_process)} assigned | Range: Seq {seq_min} to {seq_max}).")
    else:
        df_to_process = meta_df
        log(f"🚀 Processing all {len(df_to_process)} test Meta links.")

    # 4. Launch Playwright
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
