import os
import requests
import time
import re
import cv2
import numpy as np
import easyocr
from playwright.sync_api import sync_playwright

# Initialize OCR Reader (Estonian + English)
# gpu=False is required for standard GitHub Runners
reader = easyocr.Reader(['et', 'en'], gpu=False)

def check_image_for_rimi(img_bytes):
    """Performs OCR on the image pixels to find the word 'Rimi'"""
    try:
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        # detail=0 returns just the detected text strings
        results = reader.readtext(img, detail=0)
        full_text = " ".join(results).lower()
        return "rimi" in full_text
    except Exception as e:
        print(f"OCR Error: {e}")
        return False

def scrape_ads():
    # Configuration: Selver is direct, Rimi requires OCR filtering
    targets = [
        {"name": "Selver", "id": "AR08638735883022893057", "use_ocr": False},
        {"name": "Rimi", "id": "AR17608295264152453121", "use_ocr": True}
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        for target in targets:
            print(f"\n🚀 Starting {target['name']}...")
            save_dir = f"data/{target['name']}"
            os.makedirs(save_dir, exist_ok=True)

            page = context.new_page()
            url = f"https://adstransparency.google.com/advertiser/{target['id']}?region=EE"
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_selector(".ads-count", timeout=30000)
                
                count_text = page.locator(".ads-count").inner_text()
                max_ads = int(re.search(r"(\d+)", count_text).group(1))
                print(f"Targeting {max_ads} ads for {target['name']}.")

                # --- Fast Scroll ---
                last_count = 0
                for _ in range(12):
                    page.keyboard.press("End")
                    time.sleep(3)
                    current_count = page.locator("creative-preview").count()
                    print(f"Discovered {current_count}/{max_ads}...")
                    if current_count >= max_ads or current_count == last_count:
                        break
                    last_count = current_count

                # --- Scrape and Filter ---
                ads = page.locator("creative-preview").all()
                saved_count = 0

                for i, ad in enumerate(ads):
                    link_el = ad.locator("a[href*='/creative/CR']").first
                    if link_el.count() == 0: continue
                    
                    cr_id = re.search(r"(CR\d+)", link_el.get_attribute("href")).group(1)
                    file_path = f"{save_dir}/{cr_id}.png"

                    # Skip if already exists
                    if os.path.exists(file_path):
                        saved_count += 1
                        continue

                    img_el = ad.locator("html-renderer img").first
                    if img_el.count() > 0:
                        src = img_el.get_attribute("src")
                        img_res = requests.get(src, timeout=10)
                        
                        if img_res.status_code == 200:
                            if target['use_ocr']:
                                # Rimi Logic: Only save if OCR 'sees' Rimi
                                if check_image_for_rimi(img_res.content):
                                    with open(file_path, "wb") as f:
                                        f.write(img_res.content)
                                    print(f"✅ Saved Rimi: {cr_id}")
                                    saved_count += 1
                            else:
                                # Selver Logic: Save everything
                                with open(file_path, "wb") as f:
                                    f.write(img_res.content)
                                print(f"✅ Saved Selver: {cr_id}")
                                saved_count += 1

            except Exception as e:
                print(f"Error on {target['name']}: {e}")
            
            page.close()

        browser.close()

if __name__ == "__main__":
    scrape_ads()
