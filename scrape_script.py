import os
import requests
import time
from playwright.sync_api import sync_playwright

def run_rimi_verified_scraper():
    if not os.path.exists('data/Rimi'): os.makedirs('data/Rimi', exist_ok=True)

    # The domain search you provided that shows 778 ads
    TARGET_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        print("\n--- [START] Scraping Rimi via Media House OÜ ---")
        page.goto(TARGET_URL, wait_until="networkidle")
        time.sleep(5)

        # 1. Expand the grid if 'See all ads' appears
        try:
            expand = page.get_by_role("button", name="See all ads")
            if expand.count() > 0:
                expand.first.click()
                time.sleep(4)
        except: pass

        seen_creatives = set()
        rimi_saved = 0
        
        # 2. Deep Scroll Loop
        for i in range(50): # High range to reach the 778 limit
            # Get all preview cards currently loaded
            cards = page.locator("creative-preview").all()
            
            for card in cards:
                try:
                    # CHECK ADVERTISER NAME: Only proceed if it says 'Media House OÜ'
                    adv_name_element = card.locator(".advertiser-name")
                    if adv_name_element.count() == 0: continue
                    
                    adv_name = adv_name_element.inner_text()
                    if "Media House" not in adv_name:
                        continue # Skip Henkel or others

                    # GET CREATIVE ID (CR...)
                    link_element = card.locator("a").first
                    href = link_element.get_attribute("href")
                    if not href or "creative/" not in href: continue
                    
                    cr_id = href.split("creative/")[-1].split("?")[0]

                    # IF NEW, SAVE IMAGE
                    if cr_id not in seen_creatives:
                        img_element = card.locator("img").first
                        img_src = img_element.get_attribute("src")
                        
                        if img_src and "google" in img_src:
                            img_data = requests.get(img_src).content
                            with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                f.write(img_data)
                            
                            seen_creatives.add(cr_id)
                            rimi_saved += 1
                            if rimi_saved % 10 == 0:
                                print(f"  [LOG] Found {rimi_saved} Rimi ads...")

                except Exception:
                    continue

            # Scroll down to load the next batch
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            # Monitoring progress
            current_height = page.evaluate("document.body.scrollHeight")
            if i % 5 == 0:
                print(f"  [SCROLL {i}] Height: {current_height} | Unique Rimi Ads: {rimi_saved}")

        browser.close()
        print(f"\n--- [FINISHED] ---")
        print(f"Final Count of Rimi ads saved: {rimi_saved}")

if __name__ == "__main__":
    run_rimi_verified_scraper()
