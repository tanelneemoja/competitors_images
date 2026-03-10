import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_rimi_direct_check(limit=10):
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

        # --- STEP 1: SELVER (KEEPING YOUR WORKING CODE) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE&preset-date=Last+30+days", wait_until="networkidle")
            page.wait_for_selector("creative-preview", timeout=15000)
            ads = page.locator("creative-preview").all()
            for ad in ads[:limit]:
                link = ad.locator("a[href*='/creative/CR']").first
                if link.count() > 0:
                    cr_id = re.search(r"(CR\d+)", link.get_attribute("href")).group(1)
                    img = ad.locator("html-renderer img").first
                    if img.count() > 0:
                        data = requests.get(img.get_attribute("src")).content
                        with open(f"data/Selver/{cr_id}.png", "wb") as f: f.write(data)
                        print(f"  [SAVED] Selver: {cr_id}")
        except Exception as e: print(f"  [ERROR] Selver: {e}")

        # --- STEP 2: RIMI (ELEMENT-BASED DEEP VERIFICATION) ---
        print("\n--- [START] Processing Rimi (Deep Element Check) ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            page.wait_for_selector("creative-preview", timeout=20000)
            
            # Scroll a bit to load more than 4 cards (Standard Google Grid behavior)
            page.keyboard.press("End")
            time.sleep(5)
            
            ads = page.locator("creative-preview").all()
            print(f"  [LOG] Found {len(ads)} ads on grid. Checking details for Media House OÜ...")

            processed = 0
            for i, ad in enumerate(ads):
                if processed >= limit: break
                
                link_el = ad.locator("a[href*='/creative/CR']").first
                if link_el.count() == 0: continue
                
                href = link_el.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"
                
                # Create a new tab to check the detail page
                check_page = context.new_page()
                try:
                    check_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                    # Check for the specific 'advertiser-title' snippet you sent
                    # We look for the text "Media House OÜ" within that specific class
                    title_locator = check_page.locator(".advertiser-title:has-text('Media House OÜ')")
                    
                    if title_locator.count() > 0:
                        print(f"  [MATCH] Card {i+1} ({cr_id}) verified as Media House.")
                        
                        save_path = f"data/Rimi/{cr_id}.png"
                        img_el = ad.locator("html-renderer img").first
                        
                        if img_el.count() > 0:
                            src = img_el.get_attribute("src")
                            img_data = requests.get(src).content
                            with open(save_path, "wb") as f: f.write(img_data)
                            print(f"    -> Image Saved")
                        else:
                            ad.screenshot(path=save_path)
                            print(f"    -> Video/Complex Ad Saved via Screenshot")
                        
                        processed += 1
                    else:
                        print(f"  [SKIP] Card {i+1} ({cr_id}) belongs to another advertiser.")
                except Exception as inner_e:
                    print(f"    [WARN] Could not verify {cr_id}: {inner_e}")
                finally:
                    check_page.close()

        except Exception as e:
            print(f"  [ERROR] Rimi: {e}")

        browser.close()

if __name__ == "__main__":
    scrape_rimi_direct_check(limit=10)
