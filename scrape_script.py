import os
import requests
import time
from playwright.sync_api import sync_playwright

def run_rimi_robust_scraper():
    if not os.path.exists('data/Rimi'): os.makedirs('data/Rimi', exist_ok=True)

    # URL showing the "Multiple Advertisers" grid for rimi.ee
    TARGET_URL = "https://adstransparency.google.com/?region=EE&domain=rimi.ee"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a real User Agent to avoid being flagged
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"\n--- [START] Deep-Scan: Rimi (Media House OÜ) ---")
        page.goto(TARGET_URL, wait_until="networkidle")
        time.sleep(5)

        # DEBUG: Check if we even see the grid
        grid_count = page.locator("creative-grid").count()
        print(f"[DEBUG] Found {grid_count} creative-grid elements on page.")

        seen_ids = set()
        
        for i in range(40):
            # Find all preview cards using the generic tag name (more stable than classes)
            cards = page.locator("creative-preview").all()
            
            if i == 0:
                print(f"[DEBUG] Initial batch: {len(cards)} total cards detected (all advertisers).")

            for card in cards:
                try:
                    # 1. FILTER BY ADVERTISER NAME
                    # We look for the div containing the text "Media House OÜ"
                    adv_element = card.locator(".advertiser-name")
                    if adv_element.count() == 0:
                        continue
                        
                    adv_name = adv_element.inner_text()
                    
                    # LOGGING: Only log if it's NOT Media House so we know what we are skipping
                    if "Media House" not in adv_name:
                        # Optional: print(f"  [SKIP] Found {adv_name}, skipping...")
                        continue

                    # 2. GET CREATIVE ID
                    link = card.locator("a[href*='creative/']").first
                    href = link.get_attribute("href")
                    cr_id = href.split("creative/")[-1].split("?")[0]

                    if cr_id not in seen_ids:
                        # 3. GET IMAGE (Look for any img inside the card)
                        img_element = card.locator("img").first
                        if img_element.count() > 0:
                            img_src = img_element.get_attribute("src")
                            
                            if img_src and "http" in img_src:
                                response = requests.get(img_src, timeout=10)
                                with open(f"data/Rimi/{cr_id}.png", "wb") as f:
                                    f.write(response.content)
                                
                                seen_ids.add(cr_id)
                                print(f"  [SUCCESS] Saved Rimi Ad: {cr_id} (Total: {len(seen_ids)})")
                except Exception as e:
                    # Silence individual card errors to keep logs clean, 
                    # but keep the scroll logs active
                    continue

            # Scroll and Wait
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2.5) 
            
            if i % 5 == 0:
                print(f"--- [PROGRESS] Scroll {i}/40 | Rimi Ads Captured: {len(seen_ids)} ---")

        browser.close()
        print(f"\n--- [FINISHED] Captured {len(seen_ids)} Rimi ads. ---")

if __name__ == "__main__":
    run_rimi_robust_scraper()
