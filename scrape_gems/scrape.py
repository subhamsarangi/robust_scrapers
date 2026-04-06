"""
EduGems Scraper (Windows + Playwright)
----------------------------------------
1. Opens a browser for you to log in to Google manually
2. Visits each gem's copy page on Gemini
3. Extracts the "name" and "instructions" form fields
4. Saves to gems_output/001_lesson-plan.txt etc.
"""

import os
import re
import time
from playwright.sync_api import sync_playwright

HOME_URL = "https://www.edugems.ai/"
OUTPUT_DIR = "gems_output"
DEBUG_DIR = "gems_debug"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────


def get_gem_links(page):
    page.goto(HOME_URL)
    page.wait_for_load_state("networkidle")
    links = page.eval_on_selector_all("a[href*='/gem/']", "els => els.map(e => e.href)")
    seen = set()
    result = []
    for link in links:
        if link.startswith("https://www.edugems.ai/gem/") and link not in seen:
            seen.add(link)
            result.append(link)
    return sorted(result)


def get_copy_link(page, gem_url):
    page.goto(gem_url)
    page.wait_for_load_state("domcontentloaded")
    copy_link = page.evaluate(
        """
        () => {
            const anchors = [...document.querySelectorAll('a')];
            for (const a of anchors) {
                const parent = a.closest('p') || a.parentElement;
                if (parent && parent.textContent.includes('Make your own copy')) {
                    if (a.href.includes('gemini.google.com')) return a.href;
                }
            }
            return null;
        }
    """
    )
    return copy_link


def clean(text):
    """Return stripped text, or None if empty/whitespace."""
    if not text:
        return None
    stripped = str(text).strip()
    return stripped if stripped else None


def scrape_gemini_copy_page(page, copy_url, slug, index):
    page.goto(copy_url)
    page.wait_for_load_state("domcontentloaded")

    # Wait for any editable field to appear — don't use networkidle, Gemini never settles
    try:
        page.wait_for_selector(
            'textarea, [contenteditable="true"], [contenteditable=""], mat-form-field',
            timeout=15000,
        )
    except Exception:
        pass  # continue anyway and try to scrape what's there

    page.wait_for_timeout(2000)  # small extra pause for Angular to finish rendering

    # --- Strategy 1: standard input/textarea .value ---
    raw_name, raw_instructions = page.evaluate(
        """
        () => {
            function getVal(el) {
                if (!el) return null;
                return el.value || el.innerText || el.textContent || null;
            }

            // Try name
            let name = null;
            for (const sel of [
                'input[name="name"]', 'input[aria-label*="name" i]',
                'input[placeholder*="name" i]', 'textarea[name="name"]',
            ]) {
                const el = document.querySelector(sel);
                if (el && getVal(el)) { name = getVal(el).trim(); break; }
            }

            // Try instructions
            let instr = null;
            for (const sel of [
                'textarea[name="instructions"]',
                'textarea[aria-label*="instruction" i]',
                'textarea[placeholder*="instruction" i]',
            ]) {
                const el = document.querySelector(sel);
                if (el && getVal(el)) { instr = getVal(el).trim(); break; }
            }

            return [name, instr];
        }
    """
    )
    name = clean(raw_name)
    instructions = clean(raw_instructions)

    # --- Strategy 2: contenteditable divs (Angular Material / rich-text editors) ---
    if not instructions:
        instructions = clean(
            page.evaluate(
                """
            () => {
                const editables = [...document.querySelectorAll('[contenteditable="true"], [contenteditable=""]')];
                for (const el of editables) {
                    const text = el.innerText || el.textContent || '';
                    if (text.trim().length > 30) return text.trim();
                }
                return null;
            }
        """
            )
        )

    # --- Strategy 3: Angular Material mat-form-field labels → sibling inputs ---
    if not name or not instructions:
        name2, instructions2 = page.evaluate(
            """
            () => {
                let name = null, instr = null;
                document.querySelectorAll('mat-form-field, .mat-mdc-form-field').forEach(field => {
                    const label = field.querySelector('label, mat-label');
                    const labelText = label ? label.innerText.trim().toLowerCase() : '';
                    const input = field.querySelector('input, textarea, [contenteditable]');
                    if (!input) return;
                    const val = (input.value || input.innerText || '').trim();
                    if (!val) return;
                    if (labelText === 'name' && !name) name = val;
                    if (labelText.includes('instruction') && !instr) instr = val;
                });
                return [name, instr];
            }
        """
        )
        if not name:
            name = clean(name2)
        if not instructions:
            instructions = clean(instructions2)

    # --- Strategy 4: scan ALL visible text blocks, pick the longest as instructions ---
    if not instructions:
        instructions = clean(
            page.evaluate(
                """
            () => {
                const candidates = [];
                document.querySelectorAll('input, textarea, [contenteditable]').forEach(el => {
                    const text = (el.value || el.innerText || el.textContent || '').trim();
                    if (text.length > 30) candidates.push(text);
                });
                if (candidates.length === 0) return null;
                return candidates.sort((a, b) => b.length - a.length)[0];
            }
        """
            )
        )

    # --- Debug: always save HTML snapshot so you can inspect failures ---
    html = page.content()
    debug_path = os.path.join(DEBUG_DIR, f"{index:03d}_{slug}.html")
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(html)

    return name, instructions


def save_gem(index, slug, name, instructions, copy_url):
    filename = f"{index:03d}_{slug}.txt"
    path = os.path.join(OUTPUT_DIR, filename)
    # Normalize — treat whitespace-only as missing
    name_out = clean(name) or "N/A"
    instr_out = clean(instructions) or "NOT FOUND"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Name: {name_out}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Copy URL: {copy_url}\n\n")
        f.write("Instructions:\n")
        f.write("-" * 40 + "\n")
        f.write(instr_out)
        f.write("\n")
    return filename, name_out, instr_out


# Main


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="C:/scraper_chrome_profile",
            headless=False,
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        browser = context.browser
        page = context.new_page()

        # Step 1: manual Google login
        print("Opening browser... Please log in to your Google account.")
        page.goto("https://accounts.google.com")
        print("Waiting for login (up to 2 minutes)...")
        page.wait_for_url("https://myaccount.google.com/**", timeout=120000)
        print("Login detected! Continuing...\n")

        # Step 2: collect gem links
        print("Fetching gem list...")
        gem_links = get_gem_links(page)
        print(f"Found {len(gem_links)} gems.\n")

        # Step 3: scrape each gem
        failed = []
        skipped = []

        for i, gem_url in enumerate(gem_links, start=1):
            slug = gem_url.rstrip("/").split("/")[-1]

            # --- Resume: skip if already successfully scraped ---
            existing = os.path.join(OUTPUT_DIR, f"{i:03d}_{slug}.txt")
            if os.path.exists(existing):
                with open(existing, encoding="utf-8") as f:
                    content = f.read()
                if "NOT FOUND" not in content:
                    print(f"[{i:03d}] {slug} ... already done, skipping")
                    skipped.append(slug)
                    continue

            print(f"[{i:03d}] {slug}", end=" ... ", flush=True)

            # --- Get copy link (with retry) ---
            copy_url = None
            for attempt in range(2):
                try:
                    copy_url = get_copy_link(page, gem_url)
                    break
                except Exception as e:
                    print(
                        f"(copy link attempt {attempt+1} failed: {e})",
                        end=" ",
                        flush=True,
                    )
                    time.sleep(3)

            if not copy_url:
                print("no copy link found, skipping")
                failed.append((i, slug, "no copy link"))
                continue

            # --- Scrape with retry ---
            name, instructions = None, None
            for attempt in range(2):
                try:
                    name, instructions = scrape_gemini_copy_page(
                        page, copy_url, slug, i
                    )
                    break
                except Exception as e:
                    print(
                        f"(scrape attempt {attempt+1} failed: {e})", end=" ", flush=True
                    )
                    time.sleep(5)

            # Always save — even partial results are useful
            filename, saved_name, saved_instr = save_gem(
                i, slug, name, instructions, copy_url
            )

            if saved_instr == "NOT FOUND":
                print(
                    f"⚠  instructions EMPTY -> {filename}  (check gems_debug/{i:03d}_{slug}.html)"
                )
                failed.append((i, slug, "instructions empty"))
            elif saved_name == "N/A":
                print(f"⚠  name missing, instructions OK -> {filename}")
            else:
                print(f"✓  -> {filename}")

            # Random delay to avoid rate limiting (2-4 seconds)
            time.sleep(2 + (i % 3))

        browser.close()

        # --- Final summary ---
        print(f"\n{'='*60}")
        print(
            f"Done. {len(gem_links) - len(failed) - len(skipped)} scraped, "
            f"{len(skipped)} skipped (already done), {len(failed)} failed."
        )
        if failed:
            print("\nFailed gems (re-run script to retry):")
            for idx, s, reason in failed:
                print(f"  [{idx:03d}] {s} — {reason}")
        print(f"\nFiles saved to '{OUTPUT_DIR}/'")
        print(f"HTML snapshots saved to '{DEBUG_DIR}/' for any failures.")


if __name__ == "__main__":
    main()
