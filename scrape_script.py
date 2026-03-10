import os
import requests
import time
import re
import shutil
from playwright.sync_api import sync_playwright

def scrape_ads_refined(limit=10):
    # Clean and setup directories
    for folder in ['data/Selver', 'data/Rimi']:
        if os.path.exists(folder):
            shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Using a realistic User-Agent to prevent bot detection
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        # --- PART 1: SELVER (Direct Advertiser Page) ---
        page = context.new_page()
        print("\n--- [START] Processing Selver ---")
        try:
            page.goto("https://adstransparency.google.com/advertiser/AR08638735883022893057?region=EE", wait_until="networkidle")
            page.wait_for_selector("creative-preview", timeout=10000)
            ads = page.locator("creative-preview").all()
            for i, ad in enumerate(ads[:limit]):
                cr_link = ad.locator("a[href*='/creative/CR']").first
                cr_id = re.search(r"(CR\d+)", cr_link.get_attribute("href")).group(1)
                img = ad.locator("html-renderer img").first
                if img.count() > 0:
                    img_url = img.get_attribute("src")
                    data = requests.get(img_url).content
                    with open(f"data/Selver/{cr_id}.png", "wb") as f: f.write(data)
                    print(f"  [SAVED] Selver: {cr_id}")
        except Exception as e: print(f"  [ERROR] Selver: {e}")

        # --- PART 2: RIMI (Domain Search + Deep Verification) ---
        print("\n--- [START] Processing Rimi ---")
        try:
            page.goto("https://adstransparency.google.com/?region=EE&domain=rimi.ee", wait_until="networkidle")
            
            # 1. Expand the grid to see all ads
            try:
                expand_btn = page.locator(".grid-expansion-button")
                if expand_btn.is_visible():
                    expand_btn.click()
                    print("  [ACTION] Grid expanded.")
                    time.sleep(3)
            except: pass

            # 2. Deep Scroll to find Media House ads (often buried)
            print("  [LOG] Scrolling to load ad grid...")
            for _ in range(10):
                page.evaluate("window.scrollBy(0, 2000)")
                time.sleep(1)

            grid_ads = page.locator("creative-preview").all()
            print(f"  [LOG] Analyzing {len(grid_ads)} ads found in grid...")

            processed_count = 0
            for ad in grid_ads:
                if processed_count >= limit: break
                
                # Get the detail URL from the grid
                link_el = ad.locator("a[href*='/creative/CR']").first
                if link_el.count() == 0: continue
                href = link_el.get_attribute("href")
                cr_id = re.search(r"(CR\d+)", href).group(1)
                detail_url = f"https://adstransparency.google.com{href}"

                # 3. GO INSIDE THE URL (The "Deep Check")
                ad_page = context.new_page()
                try:
                    ad_page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                    
                    # VERIFY: Check breadcrumbs for "Media House OÜ"
                    breadcrumb = ad_page.locator("breadcrumbs .advertiser-scope-button div[buttoncontent]")
                    if breadcrumb.count() > 0 and "Media House OÜ" in breadcrumb.inner_text():
                        
                        print(f"  [MATCH] Found Rimi/Media House Ad: {cr_id}")
                        
                        # Target the "Big Element": ad-container
                        container = ad_page.locator(".ad-container").first
                        ad_page.wait_for_selector(".ad-container", timeout=5000)

                        # Check for Image in html-renderer or fletch-renderer
                        img_tag = container.locator("html-renderer img, fletch-renderer img").first
                        
                        if img_tag.count() > 0:
                            src = img_tag.get_attribute("src")
                            img_data = requests.get(src).content
                            with open(f"data/Rimi/{cr_id}.png", "wb") as f: f.write(img_data)
                            print(f"    -> Image Saved.")
                        else:
                            # Fallback: High-quality screenshot of the ad box
                            container.screenshot(path=f"data/Rimi/{cr_id}.png")
                            print(f"    -> Screenshot Saved (No <img> tag).")

                        # 4. Handle Variations (Next Slide)
                        next_arrow = ad_page.locator(".variation-right-arrow:not([disabled])")
                        if next_arrow.count() > 0:
                            next_arrow.click()
                            time.sleep(1)
                            container.screenshot(path=f"data/Rimi/{cr_id}_var2.png")
                            print(f"    -> Saved variation 2.")

                        processed_count += 1
                except Exception as e:
                    print(f"  [SKIP] Error checking {cr_id}")
                finally:
                    ad_page.close()

        except Exception as e: print(f"  [ERROR] Rimi: {e}")

        browser.close()
        print("\n--- [FINISHED] Check 'data' folder for results. ---")

if __name__ == "__main__":
    scrape_ads_refined(limit=10)
