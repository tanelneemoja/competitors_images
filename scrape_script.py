import os
import requests
import json
import time
import re
from playwright.sync_api import sync_playwright

def run_rimi_network_deep_scan():
    for folder in ['data/Selver', 'data/Rimi']:
        if not os.path.exists(folder): os.makedirs(folder, exist_ok=True)

    # The domain-specific search that identifies Rimi via Media House
    RIMI_DOMAIN_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"
    TARGET_MEDIA_HOUSE_ID = "AR17608295264152453121"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        # INTERNAL TRACKING
        stats = {"total_requests": 0, "ads_in_network": 0, "saved": 0}

        # NETWORK LOGGING: Watch what Google is actually sending back
        def handle_response(response):
            if "SearchAds" in response.url:
                stats["total_requests"] += 1
                status = response.status
                try:
                    # Logging the raw response size to see if Google is still sending data
                    size = len(response.body())
                    print(f"  [NETWORK] Request #{stats['total_requests']} | Status: {status} | Size: {size} bytes")
                except:
                    pass

        page.on("response", handle_response)

        print(f"\n--- [START] Deep Network Scan: Rimi (Media House) ---")
        page.goto(RIMI_DOMAIN_URL, wait_until="load")
        time.sleep(5)

        # 1. Expand the grid
        try:
            expand_btn = page.get_by_role("button", name=re.compile("See all ads", re.IGNORECASE))
            if expand_btn.count() > 0:
                expand_btn.first.click()
                print("  [UI] 'See all ads' clicked. Starting deep scroll...")
                time.sleep(4)
        except:
            pass

        # 2. Pumping Scroll to force the 178 limit
        last_height = 0
        stuck_cycles = 0
        seen_creatives = set()

        while stuck_cycles < 15:
            # Pumping: Down -> Up slightly -> Down hard
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            page.evaluate("window.scrollBy(0, -1000)")
            time.sleep(0.5)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight + 500)")
            time.sleep(2)

            # Check UI Growth
            current_ads = page.locator("creative-preview").all()
            new_height = page.evaluate("document.body.scrollHeight")
            
            print(f"  [SCROLL] Height: {new_height} | Ads in DOM: {len(current_ads)}")

            if new_height == last_height:
                stuck_cycles += 1
                print(f"  [WARN] No growth. Stuck cycle {stuck_cycles}/15...")
            else:
                stuck_cycles = 0
                last_height = new_height

            # Process visible ads to avoid missing them if Google clears memory
            for ad in current_ads:
                try:
                    href = ad.locator("a").first.get_attribute("href")
                    if not href: continue
                    
                    # Ensure it is the Rimi Advertiser (Media House)
                    if TARGET_MEDIA_HOUSE_ID not in href: continue

                    cr_id = href.split("creative/")[-1].split("?")[0]
                    if cr_id not in seen_creatives:
                        seen_creatives.add(cr_id)
                        
                        img_tag = ad.locator("img").first
                        img_src = img_tag.get_attribute("src")
                        
                        if img_src and "google" in img_src:
                            save_path = f"data/Rimi/{cr_id}.png"
                            img_data = requests.get(img_src).content
                            with open(save_path, "wb") as f:
                                f.write(img_data)
                            stats["saved"] += 1
                            if stats["saved"] % 20 == 0:
                                print(f"    [SAVED] {stats['saved']} Rimi ads captured...")
                except:
                    continue

        browser.close()
        
        print(f"\n--- [FINISHED] ---")
        print(f"Final Count of Rimi (Media House) ads: {stats['saved']}")
        print(f"Total Unique Ad IDs encountered: {len(seen_creatives)}")
        print(f"Total Network Data Requests: {stats['total_requests']}")

if __name__ == "__main__":
    run_rimi_network_deep_scan()
