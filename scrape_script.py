import os
import requests
import time
import re
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
TARGETS = {
    "Rimi": {
        "domain": "rimi.ee",
        "ar_id": "AR17608295264152453121"
    },
    "Selver": {
        "domain": "selver.ee",
        "ar_id": "AR07386001844390559745"
    }
}

BASE_SAVE_PATH = "data"

def run_unified_sync():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using a more recent User-Agent to stay under the radar
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        
        for name, info in TARGETS.items():
            print(f"\n--- 🚀 Starting {name} ({info['domain']}) ---")
            save_path = os.path.join(BASE_SAVE_PATH, name)
            os.makedirs(save_path, exist_ok=True)
            
            found_ids = set()
            page = context.new_page()
            # Set a long default timeout for slow Google pages
            page.set_default_timeout(60000) 

            # 1. THE LISTENER: Scans all traffic for ID patterns
            def handle_response(response):
                if "SearchAds" in response.url and response.status == 200:
                    try:
                        text = response.text()
                        # Extract all Creative IDs (CR...) found in the network packet
                        c_ids = re.findall(r'CR\d{15,25}', text)
                        if info['ar_id'] in text:
                            for cid in c_ids:
                                found_ids.add(cid)
                    except: pass

            page.on("response", handle_response)

            # 2. NAVIGATION: Use 'commit' to get in, then wait manually
            try:
                print(f"📡 Navigating to Transparency Center...")
                page.goto(f"https://adstransparency.google.com/?region=EE&domain={info['domain']}", wait_until="domcontentloaded")
                time.sleep(5) # Allow JS to boot up

                # 3. INTERACTION: Trigger the "See all ads" to dump the IDs into traffic
                expand_selectors = ["text='See all ads'", "button:has-text('See all ads')", ".see-all-button"]
                for selector in expand_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=5000):
                            btn.click()
                            print("✅ Clicked 'See all ads' button.")
                            break
                    except: continue

                # Scroll to ensure the API keeps sending data
                for i in range(5):
                    page.mouse.wheel(0, 2000)
                    time.sleep(2)

            except Exception as e:
                print(f"⚠️ Navigation/Interaction issue: {e}")

            print(f"📊 {name} Results: Harvested {len(found_ids)} unique IDs.")

            # 4. DOWNLOADER: Direct Asset Retrieval
            for i, cid in enumerate(list(found_ids)):
                local_file = os.path.join(save_path, f"{cid}.jpg")
                if os.path.exists(local_file): continue

                try:
                    # Visit the ad detail page directly
                    detail_url = f"https://adstransparency.google.com/advertiser/{info['ar_id']}/creative/{cid}?region=EE"
                    page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                    
                    # Wait for image to appear
                    page.wait_for_selector("html-renderer img, fletch-renderer img", timeout=10000)
                    img_el = page.locator("html-renderer img, fletch-renderer img").first
                    img_url = img_el.get_attribute("src")

                    if img_url:
                        final_url = img_url if img_url.startswith('http') else f"https:{img_url}"
                        res = requests.get(final_url, timeout=15)
                        if res.status_code == 200:
                            with open(local_file, "wb") as f:
                                f.write(res.content)
                            print(f"   [{i+1}/{len(found_ids)}] Saved: {cid}")
                    
                    time.sleep(1)
                except:
                    print(f"   ❌ Skip {cid} (Detail page timeout/missing img)")

            page.close()

        browser.close()

if __name__ == "__main__":
    run_unified_sync()
