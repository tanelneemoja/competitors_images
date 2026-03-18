import os
import requests
import time
from playwright.sync_api import sync_playwright

# CONFIG
TARGET_AR = "AR17608295264152453121" # Media House / Rimi
DOMAIN = "rimi.ee"
SAVE_PATH = "data/Rimi"

def run_task():
    os.makedirs(SAVE_PATH, exist_ok=True)
    found_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Listen for Google's API response containing the IDs
        def handle_response(response):
            if "SearchAds" in response.url and response.status == 200:
                try:
                    data = response.json()
                    for ad in data.get('ads', []):
                        if ad.get('advertiserId') == TARGET_AR:
                            found_ids.add(ad.get('creativeId'))
                except: pass

        page.on("response", handle_response)

        # 2. Trigger the load
        print(f"📡 Requesting ads for {DOMAIN}...")
        page.goto(f"https://adstransparency.google.com/?region=EE&domain={DOMAIN}", wait_until="networkidle")
        
        # Click 'See all' and scroll a few times to force API to send all batches
        try:
            page.get_by_role("button", name="See all ads").click()
            for _ in range(5):
                page.mouse.wheel(0, 2000)
                time.sleep(2)
        except: pass

        print(f"✅ Harvested {len(found_ids)} unique Rimi Creative IDs.")

        # 3. Download phase: Visit each ID's direct page (Static & Stable)
        for i, cid in enumerate(found_ids):
            try:
                # Direct URL bypasses the messy grid
                direct_url = f"https://adstransparency.google.com/advertiser/{TARGET_AR}/creative/{cid}?region=EE"
                page.goto(direct_url, wait_until="domcontentloaded")
                
                img_el = page.locator("html-renderer img, fletch-renderer img").first
                img_url = img_el.get_attribute("src")

                if img_url:
                    final_url = img_url if img_url.startswith('http') else f"https:{img_url}"
                    res = requests.get(final_url, timeout=10)
                    with open(f"{SAVE_PATH}/{cid}.jpg", "wb") as f:
                        f.write(res.content)
                    print(f"   [{i+1}/{len(found_ids)}] Saved: {cid}")
            except Exception as e:
                print(f"   ⚠️ Failed on {cid}: {e}")

        browser.close()

if __name__ == "__main__":
    run_task()
