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
    stats = {"harvested": 0, "skipped": 0, "success": 0, "failed": 0}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        page.set_default_timeout(60000)

        print(f"📡 Navigating to {DOMAIN}...")
        try:
            page.goto(f"https://adstransparency.google.com/?region=EE&domain={DOMAIN}", wait_until="domcontentloaded")
            time.sleep(8) # Critical wait for grid rendering

            # Expand grid if possible
            expand_btn = page.get_by_role("button", name="See all ads")
            if expand_btn.is_visible():
                expand_btn.click()
                time.sleep(4)

            # Hydrate the list
            for _ in range(3):
                page.mouse.wheel(0, 2000)
                time.sleep(2)

            # Collect IDs
            links = page.locator('a[href*="/creative/"]').all()
            found_ids = {link.get_attribute("href").split("/creative/")[1].split("?")[0] for link in links if link.get_attribute("href")}
            stats["harvested"] = len(found_ids)

            print(f"✅ Found {stats['harvested']} total ads for Selver.")

            # Process IDs
            for cid in list(found_ids):
                local_file = f"{SAVE_PATH}/{cid}.jpg"
                
                if os.path.exists(local_file):
                    stats["skipped"] += 1
                    continue

                try:
                    # Direct Detail Page
                    detail_url = f"https://adstransparency.google.com/advertiser/{SELVER_AR_ID}/creative/{cid}?region=EE"
                    page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                    
                    img_el = page.locator("html-renderer img, fletch-renderer img").first
                    img_url = img_el.get_attribute("src")

                    if img_url:
                        final_url = img_url if img_url.startswith('http') else f"https:{img_url}"
                        res = requests.get(final_url, timeout=15)
                        if res.status_code == 200:
                            with open(local_file, "wb") as f:
                                f.write(res.content)
                            stats["success"] += 1
                    else:
                        stats["failed"] += 1
                    
                    time.sleep(1)
                except:
                    stats["failed"] += 1

        except Exception as e:
            print(f"❌ Critical Error during navigation: {e}")

        browser.close()

    # --- FINAL REPORT ---
    print("\n" + "="*30)
    print(f"🏁 SELVER SYNC COMPLETE")
    print(f"📦 Total Harvested: {stats['harvested']}")
    print(f"⏩ Already in Library: {stats['skipped']}")
    print(f"✨ New Downloads: {stats['success']}")
    if stats["failed"] > 0:
        print(f"⚠️ Failed/Missing: {stats['failed']}")
    print("="*30)

if __name__ == "__main__":
    run_selver_sync()
