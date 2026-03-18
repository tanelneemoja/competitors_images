import os
import requests
import time
import re
from playwright.sync_api import sync_playwright
 
# --- SELVER CONFIG ---
# Direct link to Selver's verified advertiser page
SEARCH_URL = "https://adstransparency.google.com/advertiser/AR07386001844390559745?region=EE"
SAVE_PATH = "data/Selver"

def scrape_selver_fast():
    # Create folder if it doesn't exist
    os.makedirs(SAVE_PATH, exist_ok=True)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"🚀 Loading Selver Grid...")
            # Use 'domcontentloaded' for maximum speed
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
            
            # Wait for the ad counter to appear
            page.wait_for_selector(".ads-count", timeout=20000)
            count_text = page.locator(".ads-count").inner_text()
            max_ads = int(re.search(r"(\d+)", count_text).group(1))
            print(f"🎯 Target: {max_ads} ads. Starting rapid scroll...")

            # --- FAST SCROLL ---
            last_count = 0
            for _ in range(10): 
                page.keyboard.press("End")
                time.sleep(2) # Shortest stable wait for Google to pop new ads
                current_count = page.locator("creative-preview").count()
                print(f"📡 Loaded {current_count}/{max_ads}...")
                if current_count >= max_ads or current_count == last_count:
                    break
                last_count = current_count

            # --- GRID SCRAPE ---
            ads = page.locator("creative-preview").all()
            success_count = 0
            skipped_count = 0

            for i, ad in enumerate(ads):
                try:
                    # 1. Get the ID
                    link_element = ad.locator("a[href*='/creative/']").first
                    if link_element.count() == 0: continue
                    
                    href = link_element.get_attribute("href")
                    cr_id = re.search(r"(CR\d+)", href).group(1)
                    
                    file_name = f"{SAVE_PATH}/{cr_id}.png"
                    
                    # 2. Check if already downloaded
                    if os.path.exists(file_name):
                        skipped_count += 1
                        continue

                    # 3. Grab Image from the Grid
                    img_element = ad.locator("img").first
                    if img_element.count() > 0:
                        src = img_element.get_attribute("src")
                        if not src: continue
                        
                        img_data = requests.get(src, timeout=10).content
                        with open(file_name, "wb") as f:
                            f.write(img_data)
                        success_count += 1
                        print(f"✅ Saved ({i+1}): {cr_id}")

                except Exception:
                    continue 

            print(f"\n✨ DONE: {success_count} New | {skipped_count} Skipped | {len(ads)} Total Found")

        except Exception as e:
            print(f"❌ Scraper Error: {e}")
        
        browser.close()

if __name__ == "__main__":
    scrape_selver_fast()
