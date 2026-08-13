import os
import asyncio
import pandas as pd
import re
import shutil
import stat
from playwright.async_api import async_playwright
from datetime import datetime
import numpy as np
import base64


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_CSV_FILE = "meta_links.csv"
OUTPUT_CSV_FILE = "results.csv"

GITHUB_USER = "tanelneemoja"
GITHUB_REPO = "competitors_images"

BASE_DATA_DIR = "data"

META_CONCURRENCY = 15
GTC_TIMEOUT = 60000

# Set to 0 or None to process the full dataset
TEST_LIMIT = 0


# ============================================================
# LOGGING
# ============================================================

def log(msg):
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] {msg}",
        flush=True
    )


# ============================================================
# GENERAL HELPERS
# ============================================================

def sanitize_filename(name):
    return re.sub(
        r'[<>:"/\\|?*]',
        '',
        str(name or "Unknown")
    ).strip()


def get_case_insensitive_val(row, key_names, default=""):
    """
    Finds a column value regardless of header casing.
    Example:
        ID
        id
        Id
    """

    row_dict = {
        str(k).strip().lower(): v
        for k, v in row.items()
    }

    for key in key_names:

        key_lower = key.lower()

        if (
            key_lower in row_dict
            and pd.notna(row_dict[key_lower])
        ):

            val = str(row_dict[key_lower]).strip()

            if val:
                return val

    return default


def extract_id_from_url(url):
    """
    Fallback ID extractor from Meta URLs if CSV column fails.
    """

    match = re.search(
        r"(?:id=|creative/|sadbundle/|simgad/|ad_id=)([0-9]+)",
        str(url)
    )

    return match.group(1) if match else ""


def remove_readonly(func, path, exc_info):
    """
    Clear read-only file attributes if permission is denied
    during folder deletion.
    """

    os.chmod(path, stat.S_IWRITE)
    func(path)


# ============================================================
# DATA DIRECTORY
# ============================================================

def prepare_data_directory(shard_index):
    """
    Only clears the data directory on Shard 0
    (or single-shard runs) to avoid wiping peer output.
    """

    if not os.path.exists(BASE_DATA_DIR):

        os.makedirs(
            BASE_DATA_DIR,
            exist_ok=True
        )

        log(
            f"✨ Created fresh '{BASE_DATA_DIR}' directory."
        )

        return

    if shard_index == 0:

        log(
            f"🧹 [Shard 1 Init] "
            f"Clearing previous contents in "
            f"'{BASE_DATA_DIR}'..."
        )

        for item in os.listdir(BASE_DATA_DIR):

            item_path = os.path.join(
                BASE_DATA_DIR,
                item
            )

            try:

                if os.path.isdir(item_path):

                    shutil.rmtree(
                        item_path,
                        onerror=remove_readonly
                    )

                else:

                    os.chmod(
                        item_path,
                        stat.S_IWRITE
                    )

                    os.remove(item_path)

            except Exception as e:

                log(
                    f"⚠️ Could not delete "
                    f"{item_path}: {e}"
                )

        log(
            f"✨ Clean '{BASE_DATA_DIR}' directory ready."
        )


# ============================================================
# GITHUB ACTIONS SUMMARY
# ============================================================

def append_to_github_summary(
    file_path,
    ad_id,
    seq_num,
    shard_tag
):
    """
    Appends an embedded thumbnail directly into
    the GitHub Actions Job Summary UI.
    """

    summary_file = os.environ.get(
        "GITHUB_STEP_SUMMARY"
    )

    if (
        not summary_file
        or not os.path.exists(file_path)
    ):
        return

    try:

        with open(file_path, "rb") as img_f:

            encoded = base64.b64encode(
                img_f.read()
            ).decode("utf-8")

        markdown_block = (
            f"<details>"
            f"<summary>"
            f"<b>[{shard_tag} | Seq: {seq_num}] "
            f"Ad ID: {ad_id}</b>"
            f"</summary>\n\n"

            f'<img '
            f'src="data:image/jpeg;base64,{encoded}" '
            f'width="350"/>\n'

            f"</details>\n\n"
        )

        with open(
            summary_file,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(markdown_block)

    except Exception:
        pass


# ============================================================
# CREATIVE DETECTION
# ============================================================

async def creative_exists_in_element(element):
    """
    Checks whether an element contains an actual Meta
    creative rather than only layout/text.
    """

    try:

        return await element.evaluate(
            """
            (el) => {

                const selectors = [
                    'img[src*="s600x600"]',
                    'img[src*="s720x720"]',
                    'img[src*="s1080x1080"]',
                    'img[src*="scontent"]',
                    'img[src*="fbcdn.net"]',
                    'video',
                    '[data-testid="ad-library-ad-carousel-container"]',
                    '[data-testid="ad-content-body-video-container"]'
                ];

                return selectors.some(
                    selector => el.querySelector(selector)
                );
            }
            """
        )

    except Exception:
        return False


# ============================================================
# FIND META AD CARD
# ============================================================

async def get_ad_card(page):
    """
    Finds the actual Meta Ad Library card.

    Strategy:

        Library ID
             +
        creative
             +
        reasonable dimensions
             ↓
        smallest valid ancestor

    This deliberately avoids Facebook generated CSS classes.
    """

    # --------------------------------------------------------
    # STEP 1
    # Find an element containing an actual Library ID.
    #
    # Using innerText rather than exact text nodes makes this
    # more tolerant of Meta's nested markup.
    # --------------------------------------------------------

    library_candidates = page.locator(
        """
        xpath=//*[contains(
            normalize-space(.),
            'Library ID:'
        )]
        """
    )

    library_count = await library_candidates.count()

    if library_count == 0:

        log(
            "    ⚠️ No 'Library ID:' element found."
        )

        return None

    # --------------------------------------------------------
    # STEP 2
    # Examine each Library ID candidate.
    # Usually the first/visible one is the relevant one.
    # --------------------------------------------------------

    for library_index in range(library_count):

        library = library_candidates.nth(
            library_index
        )

        try:

            if not await library.is_visible():
                continue

        except Exception:
            continue

        # ----------------------------------------------------
        # STEP 3
        # Find every DIV ancestor containing a creative.
        #
        # We intentionally do NOT use [1] here.
        #
        # We want to inspect all ancestors and choose the
        # smallest useful container ourselves.
        # ----------------------------------------------------

        candidates = library.locator(
            """
            xpath=ancestor::div[
                .//img[contains(@src, 's600x600')]
                or
                .//img[contains(@src, 's720x720')]
                or
                .//img[contains(@src, 's1080x1080')]
                or
                .//img[contains(@src, 'scontent')]
                or
                .//img[contains(@src, 'fbcdn.net')]
                or
                .//video
                or
                .//*[@data-testid='ad-library-ad-carousel-container']
                or
                .//*[@data-testid='ad-content-body-video-container']
            ]
            """
        )

        candidate_count = await candidates.count()

        if candidate_count == 0:
            continue

        best_candidate = None
        best_area = None

        # ----------------------------------------------------
        # STEP 4
        # Examine every candidate.
        # ----------------------------------------------------

        for i in range(candidate_count):

            candidate = candidates.nth(i)

            try:

                if not await candidate.is_visible():
                    continue

                box = await candidate.bounding_box()

                if not box:
                    continue

                width = box["width"]
                height = box["height"]

                # --------------------------------------------
                # Ignore tiny elements.
                # --------------------------------------------

                if width < 250:
                    continue

                if height < 250:
                    continue

                # --------------------------------------------
                # Reject page-level containers.
                #
                # Your viewport is 1400px wide, so anything
                # approaching the entire viewport is almost
                # certainly not the ad card.
                # --------------------------------------------

                if width > 1200:
                    continue

                # --------------------------------------------
                # Reject huge page sections.
                # --------------------------------------------

                if height > 3000:
                    continue

                # --------------------------------------------
                # Make absolutely sure this candidate actually
                # contains a creative.
                # --------------------------------------------

                has_creative = await creative_exists_in_element(
                    candidate
                )

                if not has_creative:
                    continue

                # --------------------------------------------
                # Make sure it still contains Library ID.
                # --------------------------------------------

                contains_library_id = await candidate.evaluate(
                    """
                    (el) => {
                        return /Library ID:\\s*\\d+/i.test(
                            el.innerText || ''
                        );
                    }
                    """
                )

                if not contains_library_id:
                    continue

                area = width * height

                # --------------------------------------------
                # Smallest valid container wins.
                # --------------------------------------------

                if (
                    best_candidate is None
                    or area < best_area
                ):

                    best_candidate = candidate
                    best_area = area

            except Exception:
                continue

        if best_candidate is not None:

            box = await best_candidate.bounding_box()

            if box:

                log(
                    f"    🎯 Found ad card: "
                    f"{box['width']:.0f}x"
                    f"{box['height']:.0f}"
                )

            return best_candidate

    log(
        "    ⚠️ Could not identify a valid ad card."
    )

    return None


# ============================================================
# CLEAN AD CARD VISUALLY BEFORE SCREENSHOT
# ============================================================

async def prepare_card_for_screenshot(card):
    """
    Forces the actual ad card to have a clean white
    background and removes visual effects that could
    introduce surrounding page/background artifacts.
    """

    try:

        await card.evaluate(
            """
            (el) => {

                el.style.background = '#ffffff';
                el.style.backgroundColor = '#ffffff';

                el.style.boxShadow = 'none';

                el.style.borderRadius = '0';

                el.style.margin = '0';

                el.style.backgroundImage = 'none';

                el.style.overflow = 'visible';
            }
            """
        )

    except Exception as e:

        log(
            f"    ⚠️ Could not prepare card styling: {e}"
        )


# ============================================================
# WAIT FOR CREATIVE
# ============================================================

async def wait_for_creative(page):
    """
    Waits for a real creative to appear.

    Supports:
        - standard images
        - Meta CDN images
        - video
        - carousel
    """

    selectors = (
        'img[src*="s600x600"], '
        'img[src*="s720x720"], '
        'img[src*="s1080x1080"], '
        'img[src*="scontent"], '
        'img[src*="fbcdn.net"], '
        'video, '
        '[data-testid="ad-library-ad-carousel-container"], '
        '[data-testid="ad-content-body-video-container"]'
    )

    try:

        await page.wait_for_selector(
            selectors,
            timeout=15000
        )

        return True

    except Exception:

        return False


# ============================================================
# SCREENSHOT AD CARD
# ============================================================

async def screenshot_ad_card(
    page,
    card,
    save_path
):
    """
    Takes the screenshot of the actual ad card.

    If 'Additional assets from this ad' exists below
    the card, crop before that section.
    """

    await prepare_card_for_screenshot(card)

    card_box = await card.bounding_box()

    if not card_box:

        raise Exception(
            "Ad card has no bounding box."
        )

    # --------------------------------------------------------
    # Find Additional assets section.
    # --------------------------------------------------------

    assets_heading = page.locator(
        """
        xpath=//*[contains(
            normalize-space(.),
            'Additional assets from this ad'
        )]
        """
    ).first

    if (
        await assets_heading.count() > 0
        and await assets_heading.is_visible()
    ):

        heading_box = await assets_heading.bounding_box()

        if heading_box:

            crop_height = (
                heading_box["y"]
                - card_box["y"]
            )

            # Only use the crop if it makes sense.
            if (
                crop_height > 100
                and crop_height < card_box["height"]
            ):

                await page.screenshot(
                    path=save_path,
                    type="jpeg",
                    quality=90,
                    clip={
                        "x": card_box["x"],
                        "y": card_box["y"],
                        "width": card_box["width"],
                        "height": crop_height
                    }
                )

                return "FULL AD CARD / CROPPED"

    # --------------------------------------------------------
    # Normal element screenshot.
    # --------------------------------------------------------

    await card.screenshot(
        path=save_path,
        type="jpeg",
        quality=90,
        animations="disabled"
    )

    return "FULL AD CARD"


# ============================================================
# FALLBACK CREATIVE SCREENSHOT
# ============================================================

async def screenshot_creative_fallback(
    page,
    save_path
):
    """
    Last useful fallback:
    screenshot the largest visible creative.
    """

    creative_candidates = page.locator(
        """
        img[src*="s600x600"],
        img[src*="s720x720"],
        img[src*="s1080x1080"],
        img[src*="scontent"],
        img[src*="fbcdn.net"],
        video
        """
    )

    count = await creative_candidates.count()

    best = None
    best_area = 0

    for i in range(count):

        candidate = creative_candidates.nth(i)

        try:

            if not await candidate.is_visible():
                continue

            box = await candidate.bounding_box()

            if not box:
                continue

            width = box["width"]
            height = box["height"]

            area = width * height

            if area > best_area:

                best = candidate
                best_area = area

        except Exception:
            continue

    if best is None:
        return False

    await best.screenshot(
        path=save_path,
        type="jpeg",
        quality=90,
        animations="disabled"
    )

    return True


# ============================================================
# PROCESS ONE META LINK
# ============================================================

async def process_meta_link(
    context,
    row,
    seq_num,
    meta_sem,
    shard_tag,
    output_rows
):

    raw_url = get_case_insensitive_val(
        row,
        [
            "ad_snapshot_url",
            "creative_page_url",
            "url"
        ]
    )

    ad_id = get_case_insensitive_val(
        row,
        [
            "id",
            "ad_id",
            "library_id"
        ]
    )

    # --------------------------------------------------------
    # Fallback ID extraction
    # --------------------------------------------------------

    if (
        not ad_id
        or ad_id.lower() == "unknown"
    ):

        ad_id = (
            extract_id_from_url(raw_url)
            or "unknown"
        )

    advertiser_raw = get_case_insensitive_val(
        row,
        [
            "page_name",
            "advertiser"
        ],
        "Unknown"
    )

    advertiser = sanitize_filename(
        advertiser_raw
    )

    advertiser_dir = os.path.join(
        BASE_DATA_DIR,
        advertiser
    )

    file_name = f"{ad_id}.jpg"

    save_path = os.path.join(
        advertiser_dir,
        file_name
    )

    # --------------------------------------------------------
    # GitHub Pages URL
    # --------------------------------------------------------

    github_pages_url = (
        f"https://{GITHUB_USER}.github.io/"
        f"{GITHUB_REPO}/"
        f"{BASE_DATA_DIR}/"
        f"{advertiser}/"
        f"{file_name}"
    )

    os.makedirs(
        advertiser_dir,
        exist_ok=True
    )

    # ========================================================
    # FORCE OVERWRITE OLD FILE
    # ========================================================

    if os.path.exists(save_path):

        try:

            os.remove(save_path)

            log(
                f"🗑️ [{shard_tag} | Seq: {seq_num}] "
                f"Removed old image: {file_name}"
            )

        except Exception as e:

            log(
                f"⚠️ Could not remove old image "
                f"{save_path}: {e}"
            )

    # ========================================================
    # SEMAPHORE
    # ========================================================

    async with meta_sem:

        log(
            f"🔍 [{shard_tag} | Seq: {seq_num}] "
            f"START META: {ad_id} | "
            f"Advertiser: {advertiser}"
        )

        page = await context.new_page()

        try:

            # ------------------------------------------------
            # Block unnecessary tracking requests
            # ------------------------------------------------

            await page.route(
                re.compile(
                    r"(google-analytics|"
                    r"connect\.facebook\.net/.*signals|"
                    r"doubleclick|"
                    r"analytics)"
                ),
                lambda route: route.abort()
            )

            # ------------------------------------------------
            # Open Meta Ad Library
            # ------------------------------------------------

            await page.goto(
                raw_url,
                wait_until="domcontentloaded",
                timeout=GTC_TIMEOUT
            )

            # ------------------------------------------------
            # Give React time to hydrate
            # ------------------------------------------------

            await page.wait_for_timeout(2500)

            # ------------------------------------------------
            # Wait for creative
            # ------------------------------------------------

            creative_found = await wait_for_creative(
                page
            )

            if not creative_found:

                log(
                    f"    ⚠️ [{shard_tag} | Seq: {seq_num}] "
                    f"No obvious creative selector found. "
                    f"Continuing with Library ID detection."
                )

            # ------------------------------------------------
            # Extra wait for lazy-loaded creatives
            # ------------------------------------------------

            await page.wait_for_timeout(2000)

            # ------------------------------------------------
            # Find actual ad card
            # ------------------------------------------------

            card = await get_ad_card(page)

            # =================================================
            # PRIMARY:
            # FULL ACTUAL AD CARD
            # =================================================

            if card is not None:

                screenshot_type = (
                    await screenshot_ad_card(
                        page,
                        card,
                        save_path
                    )
                )

                append_to_github_summary(
                    save_path,
                    ad_id,
                    seq_num,
                    shard_tag
                )

                log(
                    f"    📸 "
                    f"[{shard_tag} | Seq: {seq_num}] "
                    f"SAVED {screenshot_type}: "
                    f"{save_path}"
                )

            # =================================================
            # FALLBACK 1:
            # LARGEST CREATIVE
            # =================================================

            else:

                log(
                    f"    ⚠️ "
                    f"[{shard_tag} | Seq: {seq_num}] "
                    f"Ad card not found. "
                    f"Trying creative fallback..."
                )

                creative_saved = (
                    await screenshot_creative_fallback(
                        page,
                        save_path
                    )
                )

                if creative_saved:

                    append_to_github_summary(
                        save_path,
                        ad_id,
                        seq_num,
                        shard_tag
                    )

                    log(
                        f"    📸 "
                        f"[{shard_tag} | Seq: {seq_num}] "
                        f"SAVED CREATIVE FALLBACK: "
                        f"{save_path}"
                    )

                # =============================================
                # FALLBACK 2:
                # WHOLE PAGE
                # =============================================

                else:

                    log(
                        f"    ⚠️ "
                        f"[{shard_tag} | Seq: {seq_num}] "
                        f"Creative fallback failed. "
                        f"Saving full page..."
                    )

                    await page.screenshot(
                        path=save_path,
                        full_page=True,
                        type="jpeg",
                        quality=80
                    )

                    append_to_github_summary(
                        save_path,
                        ad_id,
                        seq_num,
                        shard_tag
                    )

                    log(
                        f"    📸 "
                        f"[{shard_tag} | Seq: {seq_num}] "
                        f"SAVED PAGE FALLBACK: "
                        f"{save_path}"
                    )

            # =================================================
            # SAVE OUTPUT ROW
            # =================================================

            output_rows.append({
                "Ad ID": ad_id,
                "Advertiser": advertiser,
                "Image": github_pages_url
            })

        except Exception as e:

            log(
                f"    ❌ "
                f"[{shard_tag} | Seq: {seq_num}] "
                f"FAIL META: "
                f"{str(e)[:200]} | "
                f"{raw_url}"
            )

        finally:

            await page.close()


# ============================================================
# MAIN
# ============================================================

async def main():

    shard_index = int(
        os.environ.get(
            "SHARD_INDEX",
            0
        )
    )

    total_shards = int(
        os.environ.get(
            "TOTAL_SHARDS",
            6
        )
    )

    if shard_index >= total_shards:

        total_shards = (
            shard_index + 1
        )

    shard_tag = (
        f"Shard "
        f"{shard_index + 1}/"
        f"{total_shards}"
    )

    # --------------------------------------------------------
    # Prepare data directory
    # --------------------------------------------------------

    prepare_data_directory(
        shard_index
    )

    # --------------------------------------------------------
    # Ensure results.csv exists immediately
    # --------------------------------------------------------

    if not os.path.exists(
        OUTPUT_CSV_FILE
    ):

        pd.DataFrame(
            columns=[
                "Ad ID",
                "Advertiser",
                "Image"
            ]
        ).to_csv(
            OUTPUT_CSV_FILE,
            index=False
        )

    # --------------------------------------------------------
    # Load input CSV
    # --------------------------------------------------------

    if not os.path.exists(
        INPUT_CSV_FILE
    ):

        log(
            f"❌ Input file "
            f"'{INPUT_CSV_FILE}' not found."
        )

        return

    try:

        log(
            f"📥 Loading data from "
            f"'{INPUT_CSV_FILE}'..."
        )

        full_df = pd.read_csv(
            INPUT_CSV_FILE
        )

        log(
            f"✅ Successfully loaded "
            f"{len(full_df)} rows from "
            f"{INPUT_CSV_FILE}."
        )

    except Exception as e:

        log(
            f"❌ Failed to read "
            f"'{INPUT_CSV_FILE}': {e}"
        )

        return

    # --------------------------------------------------------
    # Find URL column
    # --------------------------------------------------------

    cols_lower = [
        str(c).strip().lower()
        for c in full_df.columns
    ]

    url_col_name = None

    for target in [
        "ad_snapshot_url",
        "creative_page_url",
        "url"
    ]:

        if target in cols_lower:

            url_col_name = (
                full_df.columns[
                    cols_lower.index(target)
                ]
            )

            break

    if not url_col_name:

        log(
            "❌ No valid snapshot URL "
            "column found in CSV headers."
        )

        return

    # --------------------------------------------------------
    # Filter Meta links
    # --------------------------------------------------------

    meta_mask = (
        full_df[url_col_name]
        .astype(str)
        .str.contains(
            r"facebook\.com|fb\.me",
            case=False,
            na=False
        )
    )

    meta_df = full_df[
        meta_mask
    ].copy()

    if len(meta_df) == 0:

        log(
            "⚠️ No Meta links found "
            "in dataset. Exiting."
        )

        return

    # --------------------------------------------------------
    # Test limit
    # --------------------------------------------------------

    if (
        TEST_LIMIT
        and TEST_LIMIT > 0
    ):

        meta_df = meta_df.head(
            TEST_LIMIT
        )

        log(
            f"🧪 [TEST MODE ACTIVE] "
            f"Restricted run to first "
            f"{len(meta_df)} rows."
        )

    # --------------------------------------------------------
    # Global sequence numbers
    # --------------------------------------------------------

    meta_df["global_seq"] = range(
        1,
        len(meta_df) + 1
    )

    total_rows = len(meta_df)

    # --------------------------------------------------------
    # Sharding
    # --------------------------------------------------------

    if total_shards > 1:

        shards = np.array_split(
            meta_df,
            total_shards
        )

        df_to_process = shards[
            shard_index
        ]

        if len(df_to_process) == 0:

            log(
                f"🧩 [{shard_tag}] "
                f"No rows assigned to this shard."
            )

            return

        seq_min = (
            df_to_process["global_seq"]
            .min()
        )

        seq_max = (
            df_to_process["global_seq"]
            .max()
        )

        log(
            f"🧩 Running {shard_tag} "
            f"({len(df_to_process)} / "
            f"{total_rows} assigned | "
            f"Range: Seq {seq_min} "
            f"to {seq_max})."
        )

    else:

        df_to_process = meta_df

        log(
            f"🚀 Processing all "
            f"{total_rows} Meta links."
        )

    # ========================================================
    # PLAYWRIGHT
    # ========================================================

    output_rows = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=True
        )

        context = await browser.new_context(
            viewport={
                "width": 1400,
                "height": 1600
            },
            device_scale_factor=1.5
        )

        meta_sem = asyncio.Semaphore(
            META_CONCURRENCY
        )

        tasks = [
            process_meta_link(
                context,
                row,
                int(row["global_seq"]),
                meta_sem,
                shard_tag,
                output_rows
            )
            for _, row
            in df_to_process.iterrows()
        ]

        await asyncio.gather(
            *tasks
        )

        await browser.close()

    # ========================================================
    # SAVE RESULTS
    # ========================================================

    if output_rows:

        results_df = pd.DataFrame(
            output_rows
        )

        header_needed = (
            not os.path.exists(
                OUTPUT_CSV_FILE
            )
            or
            os.path.getsize(
                OUTPUT_CSV_FILE
            ) == 0
        )

        results_df.to_csv(
            OUTPUT_CSV_FILE,
            mode="a",
            header=header_needed,
            index=False
        )

        log(
            f"🎉 Appended "
            f"{len(output_rows)} rows "
            f"to '{OUTPUT_CSV_FILE}'!"
        )

    else:

        log(
            f"⚠️ No rows were processed "
            f"or captured for "
            f"'{OUTPUT_CSV_FILE}'."
        )

    log(
        f"🏁 [{shard_tag}] "
        f"PROCESSING COMPLETE."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
