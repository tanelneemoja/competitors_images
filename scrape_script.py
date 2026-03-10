import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_rimi_final_logic(limit=10):
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

        # --- STEP 1: SELVER (STABLE) ---
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="domcontentloaded")
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

        # --- STEP 2: RIMI (BREADCRUMB VERIFICATION) ---
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="domcontentloaded")
            
            # Click the expansion button (the fix you found)
            try:
                page.locator(".grid-expansion-button").click()
                print("  [ACTION] Expanded Grid.")
                time.sleep(4)
            except: pass

            # Scroll once to ensure the first batch of Rimi ads are loaded
            page.evaluate("window.scrollBy(0, 2500)")
            time.sleep(3)
            
            ads = page.locator("creative-preview").all()
            print(f"  [LOG] Analyzing {len(ads)} ads found in the grid...")

            processed = 0
            for i, ad in enumerate(ads):
                if processed >= limit: break
                
                link_el = ad.locator("a[href*='/creative/CR']").first
                if link_el.count() == 0: continue
                
                href = link_el.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"
                
                # Verification Step
                v_page = context.new_page()
                try:
                    v_page.goto(detail_url, wait_until="domcontentloaded", timeout=25000)
                    
                    # TARGET: Breadcrumb button content (Highest reliable element)
                    # From your snippet: <div buttoncontent="" class="_ngcontent-awb-2">Media House OÜ</div>
                    breadcrumb = v_page.locator("breadcrumbs .advertiser-scope-button .content div[buttoncontent]")
                    
                    if breadcrumb.count() > 0 and "Media House OÜ" in breadcrumb.inner_text():
                        print(f"  [VERIFIED] Ad {cr_id} belongs to Media House OÜ.")
                        
                        save_path = f"data/Rimi/{cr_id}.png"
                        
                        # IMAGE EXTRACTION
                        # Checking html-renderer (images) and fletch-renderer (YouTube/HTML5)
                        img_src = None
                        img_el = v_page.locator("html-renderer img, fletch-renderer img").first
                        
                        if img_el.count() > 0:
                            img_src = img_el.get_attribute("src")
                            img_data = requests.get(img_src).content
                            with open(save_path, "wb") as f: f.write(img_data)
                            print(f"    -> Image Saved.")
                        else:
                            # If no direct image, screenshot the ad area
                            v_page.locator("creative").first.screenshot(path=save_path)
                            print(f"    -> Screenshot Captured.")
                            
                        processed += 1
                except:
                    continue
                finally:
                    v_page.close()

        except Exception as e: print(f"  [ERROR] Rimi: {e}")

        browser.close()

if __name__ == "__main__":
    scrape_rimi_final_logic(limit=10)
