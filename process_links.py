import os
import requests
import pandas as pd
import re
import time
from playwright.sync_api import sync_playwright

# --- CONFIG ---
CSV_FILE = "meta_google_ads_links(in).csv"
BASE_DATA_DIR = "data"

def sanitize_filename(name):
    """Removes characters that aren't allowed in folder/file names."""
    return re.sub(r'[<>:"/\\|?*]', '', str(name)).strip()

def extract_id_from_url(url, platform):
    """Extracts the unique Ad ID from the URL."""
    if "facebook.com" in url:
        match = re.search(r"id=(\d+)", url)
        return match.group(1) if match else "meta_unknown"
    elif "adstransparency.google.com" in url:
        match = re.search(r"creative/(CR\d+)", url)
        return match.group(1) if match else "gtc_unknown"
    return "unknown"

def download_image(url, folder, filename):
    """Downloads an image and saves it to the specified folder."""
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            path = os.path.join(folder, f"{filename}.png")
            with open(path, "wb") as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"   ⚠️ Download failed: {e}")
    return False

def process_ads():
    if not os.path.exists(CSV_FILE):
        print(f"❌ Error: {CSV_FILE} not found.")
        return

    # Load CSV
    df = pd.read_csv(CSV_FILE)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a real user agent to avoid bot detection on Meta
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for index, row in df.iterrows():
            platform = row['platform']
            advertiser = sanitize_filename(row['advertiser_name'])
            url = row['creative_page_url']
            ad_id = extract_id_from_url(url, platform)
            
            # Create advertiser directory
            advertiser_dir = os.path.join(BASE_DATA_DIR, advertiser)
            os.makedirs(advertiser_dir, exist_ok=True)
            
            # Skip if file already exists
            if os.path.exists(os.path.join(advertiser_dir, f"{ad_id}.png")):
                print(f"⏩ Skipping {ad_id} (Already exists)")
                continue

            print(f"🔎 Processing {index+1}/{len(df)}: {advertiser} ({platform})")
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                img_src = None

                if "Meta" in platform:
                    # Meta Ads Library selector
                    # We wait for the image tag with the specific FB CDN source
                    page.wait_for_selector('img[src*="fbcdn.net"]', timeout=20000)
                    img_src = page.locator('img[src*="fbcdn.net"]').first.get_attribute("src")
                
                else:
                    # Google Transparency Center selector
                    # Google uses <html-renderer> for image ads
                    page.wait_for_selector('html-renderer img', timeout=20000)
                    img_src = page.locator('html-renderer img').first.get_attribute("src")

                if img_src:
                    if download_image(img_src, advertiser_dir, ad_id):
                        print(f"   ✅ Saved: {ad_id}.png")
                else:
                    print(f"   ❌ Could not find image for {ad_id}")

            except Exception as e:
                print(f"   ❌ Error processing {ad_id}: {e}")
            
            # Small delay to be polite to servers
            time.sleep(1)

        browser.close()

if __name__ == "__main__":
    process_ads()
