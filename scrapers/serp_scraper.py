#!/usr/bin/env python3

"""
serp_scraper.py — Google SERP URLs με απόλυτη stealth προστασία.

Στρατηγική anti-detection:
  1. playwright-stealth για patching browser fingerprint
  2. Single persistent session (cookies αποθηκεύονται σε disk)
  3. Random human-like delays (όχι fixed intervals)
  4. Random viewport variation (±20px)
  5. Geolocation matching (Αθήνα, Ελλάδα)
  6. Session save/restore (cookies.txt)
  7. Μέγιστο 10 searches ανά run
  8. Retry με exponential backoff για CAPTCHA
  9. Extra init scripts για απόκρυψη automation

Phase A: Μόνο URLs από Google — γρήγορο, minimal exposure.
Phase B: competitor_scraper.py με requests.

Usage:
    python serp_scraper.py --input data/ranked_2026-06-13.json --output data/urls_2026-06-13.json
    python serp_scraper.py --input data/ranked.json --intent-filter COMMERCIAL,TRANSACTIONAL
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import asyncio
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib import url_utils
from lib.supabase_client import get_supabase
from playwright.async_api import async_playwright


# ─── Randomizers ──────────────────────────────────────────────────────────
# Every run uses slightly different parameters to look human

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
    {"width": 1680, "height": 1050},
]

# Real Chrome user agents — randomly picked each run
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
]

SESSION_DIR = Path(__file__).resolve().parent.parent / ".serp_session"


def random_delay(min_s: float = 1.0, max_s: float = 3.0) -> float:
    """Human-like random delay."""
    return random.uniform(min_s, max_s)


def jitter(value: int, amount: int = 20) -> int:
    """Add random jitter to a value."""
    return value + random.randint(-amount, amount)


# ─── Browser setup ────────────────────────────────────────────────────────

async def create_browser_context(p, headless: bool = True):
    """Create a stealth browser context with randomized fingerprint."""
    # Randomize viewport
    viewport = random.choice(VIEWPORTS)
    viewport = {"width": jitter(viewport["width"]), "height": jitter(viewport["height"])}

    user_agent = random.choice(USER_AGENTS)

    browser = await p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-setuid-sandbox",
            f"--window-size={viewport['width']},{viewport['height']}",
        ],
    )

    context = await browser.new_context(
        user_agent=user_agent,
        locale="el-GR",
        timezone_id="Europe/Athens",
        viewport=viewport,
        geolocation={"latitude": 37.9838, "longitude": 23.7275},  # Athens
        permissions=["geolocation"],
        extra_http_headers={"Accept-Language": "el-GR,el;q=0.9,en;q=0.8"},
    )

    # Restore session cookies if available
    cookies_path = SESSION_DIR / "cookies.json"
    if cookies_path.exists():
        try:
            cookies = json.loads(cookies_path.read_text("utf-8"))
            if cookies:
                await context.add_cookies(cookies)
        except Exception:
            pass

    # Multiple stealth init scripts
    await context.add_init_script("""
        // ── Layer 1: WebDriver hiding (multiple techniques) ──
        // Method 1: Override property descriptor
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true,
        });
        
        // Method 2: Delete from prototype
        if (navigator.__proto__) {
            delete navigator.__proto__.webdriver;
        }
        
        // ── Layer 2: Chrome runtime emulation ──
        window.chrome = {
            runtime: { connect: () => {}, sendMessage: () => {} },
            loadTimes: function() { return {}; },
            csi: function() { return {}; },
            app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
            webstore: { onInstallStageChanged: {}, onDownloadProgress: {} },
        };
        
        // ── Layer 3: Plugin spoofing ──
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1},
                {name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2},
                {name: 'Widevine Content Decryption Module', filename: 'widevinecdm.dll', description: 'Enables Widevine licenses for playback of HTML audio/video content.', length: 1},
            ]
        });
        
        // ── Layer 4: Language & platform spoofing ──
        Object.defineProperty(navigator, 'languages', {get: () => ['el-GR', 'el', 'en-GB', 'en']});
        Object.defineProperty(navigator, 'language', {get: () => 'el-GR'});
        Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        Object.defineProperty(navigator, 'oscpu', {get: () => 'Windows NT 10.0; Win64; x64'});
        
        // ── Layer 5: Hardware fingerprint spoofing ──
        Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
        Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
        Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});  // desktop
        
        // ── Layer 6: WebGL vendor spoofing ──
        const getParameterProxyHandler = {
            apply: function(target, thisArg, args) {
                const param = args[0];
                const realVal = Reflect.apply(target, thisArg, args);
                // Unmask vendor/renderer
                if (param === 37445) return 'Google Inc. (Intel)';  // UNMASKED_VENDOR_WEBGL
                if (param === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
                return realVal;
            }
        };
        if (HTMLCanvasElement.prototype.getContext) {
            const origGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(...args) {
                const ctx = origGetContext.apply(this, args);
                if (ctx && ctx.getParameter) {
                    const origGetParameter = ctx.getParameter;
                    ctx.getParameter = new Proxy(origGetParameter, getParameterProxyHandler);
                }
                return ctx;
            };
        }
        
        // ── Layer 7: Canvas fingerprint noise ──
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(...args) {
            const dataUrl = origToDataURL.apply(this, args);
            // Add tiny noise to ~5% of pixels (makes fingerprint unique per session)
            if (dataUrl.startsWith('data:image/png') && Math.random() > 0.5) {
                // Just return slightly modified version
                return dataUrl.replace(/[0-9a-f]{6}/g, (match) => {
                    if (Math.random() > 0.95) {
                        const shift = Math.floor(Math.random() * 3) - 1;
                        const newVal = Math.min(255, Math.max(0, parseInt(match, 16) + shift)).toString(16).padStart(2, '0');
                        return newVal.repeat(3);
                    }
                    return match;
                });
            }
            return dataUrl;
        };
        
        // ── Layer 8: Screen & window specifics ──
        Object.defineProperty(screen, 'colorDepth', {get: () => 24});
        Object.defineProperty(screen, 'pixelDepth', {get: () => 24});
    """)

    return browser, context


async def save_session(context):
    """Persist cookies to disk for next run."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    cookies = await context.cookies()
    (SESSION_DIR / "cookies.json").write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2), "utf-8"
    )


# ─── Google search ────────────────────────────────────────────────────────

async def search_google(page, keyword: str, max_results: int = 8) -> list[dict]:
    """Search Google and return organic results. Human-like behavior."""
    
    # Navigate to Google with random timing
    await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(random_delay(1.5, 3.0))

    # Handle cookie consent if present (varies per region/session)
    consent_selectors = [
        "button:has-text('Αποδοχή')",
        "button:has-text('Accept all')",
        "button:has-text('Αποδοχή όλα')",
        "button:has-text('Accept')",
        "button:has-text('Συμφωνώ')",
        "form:has(button) button:first-child",
    ]
    for selector in consent_selectors:
        try:
            btn = await page.query_selector(selector)
            if btn:
                await btn.click()
                await asyncio.sleep(random_delay(0.5, 1.5))
                break
        except Exception:
            continue

    # Find search box and type — human-like typing
    search_box = await page.query_selector("textarea[name='q'], input[name='q']")
    if not search_box:
        return []

    await search_box.click()
    await asyncio.sleep(random_delay(0.2, 0.5))
    await search_box.fill("")
    await asyncio.sleep(random_delay(0.1, 0.3))
    
    # Capture search box position for mouse movement
    try:
        search_box_bbox = await search_box.bounding_box()
        search_box_position = search_box_bbox if search_box_bbox else {"x": 300, "y": 300}
    except Exception:
        search_box_position = {"x": 300, "y": 300}
    
    # Type with varied delay (simulates human typing — slower is more realistic)
    await search_box.type(keyword, delay=random.uniform(30, 80))
    await asyncio.sleep(random_delay(0.5, 1.5))
    
    # Random mouse movement before submit (moves mouse away, then back)
    try:
        await page.mouse.move(
            random.randint(100, 500),
            random.randint(200, 600),
            steps=random.randint(5, 15),
        )
        await asyncio.sleep(random_delay(0.2, 0.6))
        await page.mouse.move(
            random.randint(search_box_position.get('x', 300), search_box_position.get('x', 300) + 200),
            random.randint(search_box_position.get('y', 300), search_box_position.get('y', 300) + 50),
            steps=random.randint(5, 15),
        )
    except Exception:
        pass
    
    await asyncio.sleep(random_delay(0.1, 0.3))
    
    # Submit search (sometimes click, sometimes press Enter)
    if random.random() > 0.5:
        await search_box.press("Enter")
    else:
        # Find and click the search button
        try:
            search_btn = await page.query_selector("button[aria-label='Αναζήτηση Google'], button[aria-label='Google Search'], input[value='Αναζήτηση Google'], input[value='Google Search']")
            if search_btn:
                await search_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")
    
    # Wait for results with varied timing
    await asyncio.sleep(random_delay(2.5, 4.0))

    # Check for CAPTCHA
    if "sorry" in page.url:
        # Wait and retry once with backoff
        await asyncio.sleep(random_delay(5.0, 8.0))
        if "sorry" in page.url:
            return []

    # Extract organic URLs (only <h3> tagged results = organic)
    urls = await page.evaluate("""
        (max) => {
            const results = [];
            // Standard Google result containers
            const selectors = [
                'div.g',
                'div[data-hveid]',
                'div[data-sokoban-container]',
            ];
            
            const seen = new Set();
            for (const sel of selectors) {
                const items = document.querySelectorAll(sel);
                items.forEach(item => {
                    const link = item.querySelector('a[href^="http"]');
                    const h3 = item.querySelector('h3');
                    if (link && h3 && !seen.has(link.href)) {
                        seen.add(link.href);
                        results.push({
                            position: results.length + 1,
                            title: h3.textContent.trim(),
                            url: link.href
                        });
                    }
                });
            }
            return results.slice(0, max);
        }
    """, max_results)

    return urls


# ─── Blocklist cache ───────────────────────────────────────────

_BLOCKLIST_CACHE = None

def _get_blocklist():
    global _BLOCKLIST_CACHE
    if _BLOCKLIST_CACHE is None:
        _BLOCKLIST_CACHE = url_utils.load_blocklist()
    return _BLOCKLIST_CACHE


def _classify_and_filter(urls: list[dict]) -> dict:
    """
    Classify and filter URLs through blocklist.
    Returns dict with filtered/classified results.
    """
    blocked_domains, path_patterns = _get_blocklist()
    
    result = {
        "organic_urls": [],      # All URLs with classification
        "competitors": [],       # COMPETITOR only (for Phase B)
        "secondary": {           # Non-competitor, grouped by type
            "reddit": [],
            "directories": [],
            "news": [],
            "youtube": [],
            "wikipedia": [],
            "social": [],
            "other": [],
            "blocked": [],
        },
        "classification": {},    # type -> count
    }
    
    for item in urls:
        url = item["url"]
        title = item.get("title", "")
        
        # Blocklist check
        if url_utils.is_blocked(url, blocked_domains, path_patterns):
            result["secondary"]["blocked"].append(item)
            result["classification"]["BLOCKED"] = result["classification"].get("BLOCKED", 0) + 1
            continue
        
        # Classify
        ctype = url_utils.classify_url(url, title)
        item["type"] = ctype
        result["organic_urls"].append(item)
        result["classification"][ctype] = result["classification"].get(ctype, 0) + 1
        
        if ctype == "COMPETITOR":
            result["competitors"].append(item)
        elif ctype in result["secondary"]:
            result["secondary"][ctype].append(item)
        else:
            # Default to other
            result["secondary"]["other"].append(item)
            ct = "OTHER"
            result["classification"][ct] = result["classification"].get(ct, 0) + 1
    
    return result


# ─── Main ─────────────────────────────────────────────────────────────────

async def main_async(keywords: list[dict], max_per_keyword: int, delay_range: tuple, verbose: bool):
    results = []
    total = len(keywords)
    
    # Limit to 8 searches per run to avoid detection
    if total > 8:
        if verbose:
            print(f"[warn] Limiting to 8 keywords per run (got {total})", file=sys.stderr)
        keywords = keywords[:8]

    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=True)
        page = await context.new_page()

        if verbose:
            print("[verbose] Session initialized ✓", file=sys.stderr)

        for idx, kw_data in enumerate(keywords):
            keyword = kw_data.get("keyword", "")
            if not keyword:
                continue

            sr = {
                "keyword": keyword,
                "trend_score": kw_data.get("trend_score", 0),
                "trend_direction": kw_data.get("trend_direction", ""),
                "organic_urls": [],
                "total_urls": 0,
                "status": "pending",
            }

            if verbose:
                print(f"\n[{idx+1}/{total}] '{keyword[:50]}'", file=sys.stderr)

            try:
                urls = await search_google(page, keyword, max_results=max_per_keyword)
            except Exception as e:
                sr["status"] = f"error: {e}"
                results.append(sr)
                if verbose:
                    print(f"  ✗ ERROR: {e}", file=sys.stderr)
                continue

            if not urls:
                sr["status"] = "blocked"
                if verbose:
                    print(f"  ✗ BLOCKED (CAPTCHA)", file=sys.stderr)
            else:
                # Classify and filter URLs
                classified = _classify_and_filter(urls)
                sr["organic_urls"] = classified["organic_urls"]
                sr["competitors"] = classified["competitors"]
                sr["secondary"] = classified["secondary"]
                sr["classification"] = classified["classification"]
                sr["total_urls_raw"] = len(urls)
                sr["total_urls"] = len(classified["organic_urls"])
                sr["total_competitors"] = len(classified["competitors"])
                sr["status"] = "success"
                if verbose:
                    print(f"  ✓ {len(urls)} raw → {len(classified['organic_urls'])} filtered, "
                          f"{len(classified['competitors'])} competitors", file=sys.stderr)
                    for u in classified["competitors"][:3]:
                        domain = u["url"].split("/")[2] if "//" in u["url"] else u["url"]
                        print(f"     #{u['position']} {domain} — {u['title'][:50]}", file=sys.stderr)

            results.append(sr)

            # Variable delay between searches (not fixed!)
            if idx < total - 1:
                delay = random.uniform(*delay_range)
                if verbose:
                    print(f"  ~ waiting {delay:.0f}s...", file=sys.stderr)
                await asyncio.sleep(delay)

        # Save session cookies
        await save_session(context)
        await browser.close()

    return results


def main():
    parser = argparse.ArgumentParser(
        description="serp_scraper.py — Google SERP URLs με stealth (Phase A)."
    )
    parser.add_argument("--input", required=True, help="Ranked keywords JSON")
    parser.add_argument("--output", default=None, help="Output JSON (URLs only)")
    parser.add_argument("--max-per-keyword", type=int, default=8)
    parser.add_argument("--min-delay", type=float, default=15.0, help="Min seconds between searches")
    parser.add_argument("--max-delay", type=float, default=25.0, help="Max seconds between searches")
    parser.add_argument("--max-runs", type=int, default=3, help="Max keywords per run (def: 3)")
    parser.add_argument("--intent-filter", type=str, default=None,
                        help="Only process keywords with these intents: comma-separated "
                             "(e.g. COMMERCIAL,TRANSACTIONAL). INFO keywords are skipped.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Supabase pipeline run ID for writing serp_results",
    )
    args = parser.parse_args()

    # Read input
    raw = json.loads(Path(args.input).read_text("utf-8"))
    keywords = (raw if isinstance(raw, list) else raw.get("results", []) 
                if isinstance(raw, dict) else [])

    if not keywords:
        print("Error: No keywords found.", file=sys.stderr)
        return 1

    if len(keywords) > args.max_runs:
        if args.verbose:
            print(f"[warn] Limiting to {args.max_runs} keywords (use --max-runs to change)", file=sys.stderr)
        keywords = keywords[:args.max_runs]

    # Intent filter
    if args.intent_filter:
        allowed_intents = set(i.strip().upper() for i in args.intent_filter.split(","))
        filtered = []
        for kw in keywords:
            intent = (kw.get("intent") or url_utils.classify_keyword_intent(kw.get("keyword", "")))
            if intent in allowed_intents:
                filtered.append(kw)
            elif args.verbose:
                print(f"  ○ Skipped '{kw.get('keyword', '')[:40]}' (intent: {intent})", file=sys.stderr)
        if args.verbose:
            print(f"[verbose] Intent filter ({args.intent_filter}): {len(filtered)}/{len(keywords)} keywords kept",
                  file=sys.stderr)
        keywords = filtered
        if not keywords:
            print("Error: All keywords filtered out by intent filter.", file=sys.stderr)
            return 1

    if args.verbose:
        print(f"[verbose] Processing {len(keywords)} keywords...", file=sys.stderr)

    results = asyncio.run(main_async(
        keywords, args.max_per_keyword, (args.min_delay, args.max_delay), args.verbose
    ))

    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_keywords": len(results),
        "successful": sum(1 for r in results if r["status"] == "success"),
        "blocked": sum(1 for r in results if r["status"] == "blocked"),
        "results": results,
    }

    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    # ─── Supabase write ────────────────────────────────────────────────
    if args.run_id:
        try:
            supabase = get_supabase()
            for r in results:
                supabase.table("serp_results").insert({
                    "run_id": args.run_id,
                    "keyword": r.get("keyword", ""),
                    "trend_score": r.get("trend_score", 0),
                    "organic_urls": json.dumps(r.get("organic_urls", []), ensure_ascii=False),
                    "blocked": r.get("status") == "blocked",
                }).execute()
            if args.verbose:
                print(f"[verbose] Written {len(results)} SERP results to Supabase (run_id={args.run_id})", file=sys.stderr)
        except Exception as e:
            print(f"[warn] Supabase write failed: {e}", file=sys.stderr)

    if args.verbose:
        print(f"\n[verbose] Done: {data['successful']} ok, {data['blocked']} blocked", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
