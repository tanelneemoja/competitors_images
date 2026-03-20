import os
import requests
import pandas as pd
import re
import time
import sys
from playwright.sync_api import sync_playwright

# --- CONFIG ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"

def log(msg):
    """Prints and flushes immediately for live GitHub logs."""
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

def download_image(url, folder, filename):
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            path = os.path.join(folder, f"{filename}.png")
            with open(path, "wb") as f:
                f.write(response.content)
            return True
    except Exception as e:
        log(f"   ⚠️ Download failed: {e}")
    return False

def process_ads():
    if not os.path.exists(CSV_FILE):
        log(f"❌ Error: {CSV_FILE} not found.")
        return

    df = pd.read_csv(CSV_FILE)
    log(f"📋 Loaded {len(df)} links. Starting engine...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for index, row in df.iterrows():
            platform = row['platform']
            advertiser = sanitize_filename(row['advertiser_name'])
            url = row['creative_page_url']
            ad_id = extract_id_from_url(url, platform)
            
            advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
            os.makedirs(advertiser_dir, exist_ok=True)
            
            if os.path.exists(os.path.join(advertiser_dir, f"{ad_id}.png")):
                log(f"⏩ [{index+1}/{len(df)}] Skipping {ad_id} (Exists)")
                continue

            log(f"🚀 [{index+1}/{len(df)}] {advertiser} | {platform}")
            
            try:
                # Go to URL
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # --- NEW: META BROKEN LINK CHECK ---
                if "Meta" in platform:
                    # Check for "Content not available" message
                    unavailable_msg = page.get_by_text("This content isn't available right now")
                    if unavailable_msg.is_visible():
                        log(f"   ⏩ Link Broken/Expired. Skipping immediately.")
                        continue

                img_src = None

                if "Meta" in platform:
                    log(f"   ⏳ Locating Meta Image...")
                    # Small wait for the actual ad content to render
                    page.wait_for_selector('img[src*="fbcdn.net"]', timeout=15000)
                    img_src = page.locator('img[src*="fbcdn.net"]').first.get_attribute("src")
                
                else:
                    log(f"   ⏳ Locating Google Image...")
                    page.wait_for_selector('html-renderer img', timeout=20000)
                    img_src = page.locator('html-renderer img').first.get_attribute("src")

                if img_src:
                    if download_image(img_src, advertiser_dir, ad_id):
                        log(f"   ✅ Saved: {ad_id}.png")
                else:
                    log(f"   ❌ No image found.")

            except Exception as e:
                # Check if it was just a timeout on an already identified broken page
                if "timeout" in str(e).lower() and "Meta" in platform:
                     log(f"   ❌ Timeout (Page likely restricted or broken).")
                else:
                     log(f"   ❌ Failed: {str(e)[:50]}...")
            
            time.sleep(1)

        browser.close()

if __name__ == "__main__":
    process_ads()
