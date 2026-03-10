import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_with_logs(limit=10):
    # --- 1. CLEAN SLATE ---
    if os.path.exists('data'):
        shutil.rmtree('data')
    os.makedirs('data/Selver', exist_ok=True)
    os.makedirs('data/Rimi', exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1200},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # --- STEP 1: SELVER ---
        selver_url = "https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days"
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto(selver_url, wait_until="networkidle")
            page.wait_for_selector(".advertiser-name:has-text('Selver')", timeout=15000)
            
            ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(ads)} potential Selver cards.")
            
            for i, ad in enumerate(ads[:limit]):
                link = ad.locator("a[href*='/creative/CR']").first
                if link.count() > 0:
                    cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                    img = ad.locator("html-renderer img").first
                    if img.count() > 0:
                        data = requests.get(img.get_attribute("src")).content
                        with open(f"data/Selver/{cr_id}.png", "wb") as f: f.write(data)
                        print(f"  [SAVED] Selver: {cr_id}.png")
        except Exception as e:
            print(f"  [ERROR] Selver Step: {e}")

        # --- STEP 2: RIMI ---
        rimi_url = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto(rimi_url, wait_until="networkidle")
            
            print("  [LOG] Waiting for 'Media House OÜ' to appear in the DOM...")
            page.wait_for_selector(".advertiser-name:has-text('Media House OÜ')", timeout=30000)
            
            # Give it a moment to stabilize all 40 cards
            time.sleep(5)
            
            ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(ads)} total cards on Rimi domain page.")
            
            processed = 0
            for i, ad in enumerate(ads):
                if processed >= limit: break

                # Locate the specific advertiser name for THIS card
                name_tag = ad.locator(".advertiser-name")
                
                if name_tag.count() > 0:
                    current_name = name_tag.inner_text().strip()
                    
                    if "Media House OÜ" in current_name:
                        link = ad.locator("a[href*='/creative/CR']").first
                        if link.count() == 0: continue
                        
                        cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                        img = ad.locator("html-renderer img").first
                        save_path = f"data/Rimi/{cr_id}.png"
                        
                        if img.count() > 0:
                            src = img.get_attribute("src")
                            img_data = requests.get(src).content
                            with open(save_path, "wb") as f: f.write(img_data)
                            print(f"  [MATCH] Card {i+1}: Found Media House -> Saved {cr_id}")
                            processed += 1
                        else:
                            ad.screenshot(path=save_path)
                            print(f"  [SCREENSHOT] Card {i+1}: Found Media House (Renderer) -> Saved {cr_id}")
                            processed += 1
                    else:
                        # This log will show you exactly what it's skipping
                        print(f"  [SKIP] Card {i+1}: Advertiser is '{current_name}'")
                else:
                    print(f"  [WARN] Card
