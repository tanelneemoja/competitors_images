import os
import requests
import time
from playwright.sync_api import sync_playwright

# --- SELVER CONFIG ---
SELVER_AR_ID = "AR07386001844390559745"
DOMAIN = "selver.ee"
SAVE_PATH = "data/Selver"

def run_selver_sync():
    os.makedirs(SAVE_PATH, exist_ok=True)
    
    with sync_playwright() as p:
        # Launching with a slower, more stable profile
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        # Increased timeout for Selver's heavy page
        page.set_default_timeout(60000)

        print(f"📡 Navigating to Selver Ads...")
        # Use 'domcontentloaded' to avoid the 30s networkidle timeout
        page.goto(f"https://adstransparency.google.com/?region=EE&domain={DOMAIN}", wait_until="domcontentloaded")
        
        # Give the JS 5 seconds to actually render the grid
        time.sleep(5)

        # 1. Expand the grid
        try:
            expand_btn = page.get_by_role("button", name="See all ads")
            if expand_btn.is_visible():
                expand_btn.click()
                print("✅ Expanded ad grid.")
                time.sleep(3)
        except:
            print("ℹ️ No 'See all' button found, continuing...")

        # 2. Collect IDs from the page
        # We scroll a few times to hydrate the list
        for _ in range(5):
            page.mouse.wheel(0, 2000)
            time.sleep(2)

        # Get all ad links (these contain the Creative IDs)
        links = page.locator('a[href*="/creative/"]').all()
        found_ids = set()
        for link in links:
            href = link.get_attribute("href")
            if href:
                # Extract the CR... ID from the URL
                cid = href.split("/creative/")[1].split("?")[0]
                found_ids.add(cid)

        print(f"✅ Found {len(found_ids)} Selver IDs.")

        # 3. Download Images
        for i, cid in enumerate(list(found_ids)):
            local_file = f"{SAVE_PATH}/{cid}.jpg"
            if os.path.exists(local_file):
                continue

            try:
                # Direct link to the ad detail
                page.goto(f"https://adstransparency.google.com/advertiser/{SELVER_AR_ID}/creative/{cid}?region=EE", wait_until="domcontentloaded")
                
                # Simple selector for the ad image
                img_el = page.locator("html-renderer img, fletch-renderer img").first
                img_url = img_el.get_attribute("src")

                if img_url:
                    final_url = img_url if img_url.startswith('http') else f"https:{img_url}"
                    res = requests.get(final_url, timeout=15)
                    with open(local_file, "wb") as f:
                        f.write(res.content)
                    print(f"   [{i+1}/{len(found_ids)}] Saved: {cid}")
                
                time.sleep(1)
            except:
                print(f"   ❌ Failed to download {cid}")

        browser.close()

if __name__ == "__main__":
    run_selver_sync()
