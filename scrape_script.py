import os
import requests
import time
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
# We use the specific AR IDs to filter out agency noise
TARGETS = {
    "Rimi": {
        "domain": "rimi.ee",
        "ar_id": "AR17608295264152453121" # Media House ID
    },
    "Selver": {
        "domain": "selver.ee",
        "ar_id": "AR07386001844390559745" # Selver AS Direct ID
    }
}

BASE_SAVE_PATH = "data"

def run_unified_sync():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Setting a standard user agent helps avoid basic bot blocks
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36")
        
        for name, info in TARGETS.items():
            print(f"\n--- Processing {name} ---")
            save_path = os.path.join(BASE_SAVE_PATH, name)
            os.makedirs(save_path, exist_ok=True)
            
            found_ids = set()
            page = context.new_page()

            # 1. THE LISTENER: Intercept IDs from the hidden API responses
            def handle_response(response):
                if "SearchAds" in response.url and response.status == 200:
                    try:
                        data = response.json()
                        for ad in data.get('ads', []):
                            if ad.get('advertiserId') == info['ar_id']:
                                found_ids.add(ad.get('creativeId'))
                    except: pass

            page.on("response", handle_response)

            # 2. TRIGGER: Load the search and force data packets to send
            print(f"📡 Harvesting IDs for {info['domain']}...")
            page.goto(f"https://adstransparency.google.com/?region=EE&domain={info['domain']}", wait_until="networkidle")
            
            try:
                # Trigger expansion
                expand = page.get_by_role("button", name="See all ads")
                if expand.is_visible(timeout=5000):
                    expand.click()
                    # Scroll to ensure Google's API sends the next batches of IDs
                    for _ in range(10): 
                        page.mouse.wheel(0, 4000)
                        time.sleep(1.5)
            except: pass

            print(f"✅ Found {len(found_ids)} unique IDs for {name}.")

            # 3. DOWNLOADER: Visit direct pages to get the clean images
            for i, cid in enumerate(list(found_ids)):
                local_file = os.path.join(save_path, f"{cid}.jpg")
                
                # Skip if we already have it
                if os.path.exists(local_file):
                    continue

                try:
                    # Direct Detail Page is the most stable way to get the source URL
                    detail_url = f"https://adstransparency.google.com/advertiser/{info['ar_id']}/creative/{cid}?region=EE"
                    page.goto(detail_url, wait_until="domcontentloaded")
                    
                    # Look for the image in either the static or video renderer
                    img_el = page.locator("html-renderer img, fletch-renderer img").first
                    img_url = img_el.get_attribute("src")

                    if img_url:
                        final_url = img_url if img_url.startswith('http') else f"https:{img_url}"
                        res = requests.get(final_url, timeout=15)
                        if res.status_code == 200:
                            with open(local_file, "wb") as f:
                                f.write(res.content)
                            print(f"   [{i+1}/{len(found_ids)}] Saved: {cid}")
                    
                    time.sleep(0.5) # Gentle pause
                except Exception as e:
                    print(f"   ❌ Error on {cid}: {e}")

            page.close()

        browser.close()

if __name__ == "__main__":
    run_unified_sync()
