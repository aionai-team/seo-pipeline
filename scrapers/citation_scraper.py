#!/usr/bin/env python3
"""
citation_scraper.py — GEO Citation Gap Analysis.

Ελέγχει αν το aionai.gr εμφανίζεται σε αποτελέσματα αναζήτησης για Greek AI queries
(proxy για citation checking σε AI engines όπως ChatGPT, Perplexity, Gemini).

Στρατηγική anti-detection (ίδια με serp_scraper.py):
  1. Playwright με πλήρες stealth (webdriver hiding, chrome runtime, canvas noise)
  2. Geolocation Αθήνα, Ελλάδα
  3. Greek locale (el-GR)
  4. Random viewport, user-agent, delays
  5. Cookie session persistence
  6. Retry me exponential backoff

Logic:
  - Input: keywords απο τη λίστα Greek AI queries
  - Για κάθε keyword: search Google → extract top URLs
  - Ελέγχει: υπάρχει το aionai.gr; Ποιοι εμφανίζονται αντί για εμάς;
  - Output: citation_gap_report.json με scores και recommendations

Usage:
    python scrapers/citation_scraper.py --keywords "ai agents Ελλάδα" "automation Αθήνα" --max 3 --verbose
    python scrapers/citation_scraper.py --input data/keywords.json --output data/latest/citation_report.json
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
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, quote

from playwright.async_api import async_playwright
from lib import url_utils


# ─── Randomizers ──────────────────────────────────────────────────────────

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
    {"width": 1600, "height": 900},
    {"width": 1680, "height": 1050},
]

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

SESSION_DIR = Path(__file__).resolve().parent.parent / ".serp_session"  # reuse same session


def random_delay(min_s: float = 1.0, max_s: float = 3.0) -> float:
    return random.uniform(min_s, max_s)


def jitter(value: int, amount: int = 20) -> int:
    return value + random.randint(-amount, amount)


# ─── Our domain to check ──────────────────────────────────────────────────

OUR_DOMAIN = "aionai.gr"
OUR_URL = "https://www.aionai.gr"

# Keywords that match our services — used for matching
OUR_KEYWORDS = [
    "ai agent", "ai automation", "τεχνητή νοημοσύνη", "αυτοματοποίηση",
    "ai consulting", "ai για επιχειρήσεις", "ai solutions", "ai agents",
    "aionAI", "aionai", "aionai.gr",
]


# ─── Browser setup (από serp_scraper.py) ──────────────────────────────────

async def create_browser_context(p, headless: bool = True):
    """Create a stealth browser context with randomized fingerprint."""
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

    # Stealth init scripts (ίδιο με serp_scraper.py)
    await context.add_init_script("""
        // ── WebDriver hiding ──
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        if (navigator.__proto__) delete navigator.__proto__.webdriver;

        // ── Chrome runtime ──
        window.chrome = {
            runtime: { connect: () => {}, sendMessage: () => {} },
            loadTimes: function() { return {}; },
            csi: function() { return {}; },
            app: { isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
            },
            webstore: { onInstallStageChanged: {}, onDownloadProgress: {} },
        };

        // ── Plugin spoofing ──
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1},
                {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1},
                {name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2},
                {name: 'Widevine Content Decryption Module', filename: 'widevinecdm.dll', description: '', length: 1},
            ]
        });

        // ── Language & platform ──
        Object.defineProperty(navigator, 'languages', {get: () => ['el-GR', 'el', 'en-GB', 'en']});
        Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
        Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});

        // ── WebGL vendor spoofing ──
        const gpProxy = {
            apply: function(target, thisArg, args) {
                const param = args[0];
                if (param === 37445) return 'Google Inc. (Intel)';
                if (param === 37446) return 'Intel Iris OpenGL Engine';
                return Reflect.apply(target, thisArg, args);
            }
        };
        if (HTMLCanvasElement.prototype.getContext) {
            const orig = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(...args) {
                const ctx = orig.apply(this, args);
                if (ctx && ctx.getParameter) ctx.getParameter = new Proxy(ctx.getParameter, gpProxy);
                return ctx;
            };
        }

        // ── Canvas fingerprint noise ──
        const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(...args) {
            const dataUrl = origToDataURL.apply(this, args);
            if (dataUrl.startsWith('data:image/png') && Math.random() > 0.5) {
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

async def search_google(page, keyword: str, max_results: int = 10) -> list[dict]:
    """Search Google and return organic results. Human-like behavior."""
    await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(random_delay(1.5, 3.0))

    # Handle cookie consent
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

    # Type search query
    search_box = await page.query_selector("textarea[name='q'], input[name='q']")
    if not search_box:
        return []

    await search_box.click()
    await asyncio.sleep(random_delay(0.2, 0.5))
    await search_box.fill("")
    await asyncio.sleep(random_delay(0.1, 0.3))

    # Get search box position for mouse movement
    try:
        sb_bbox = await search_box.bounding_box()
        sb_pos = sb_bbox if sb_bbox else {"x": 300, "y": 300}
    except Exception:
        sb_pos = {"x": 300, "y": 300}

    await search_box.type(keyword, delay=random.uniform(30, 80))
    await asyncio.sleep(random_delay(0.5, 1.5))

    # Random mouse movement
    try:
        await page.mouse.move(random.randint(100, 500), random.randint(200, 600), steps=random.randint(5, 15))
        await asyncio.sleep(random_delay(0.2, 0.6))
    except Exception:
        pass

    await asyncio.sleep(random_delay(0.1, 0.3))

    # Submit search
    if random.random() > 0.5:
        await search_box.press("Enter")
    else:
        try:
            search_btn = await page.query_selector(
                "button[aria-label='Αναζήτηση Google'], button[aria-label='Google Search'], "
                "input[value='Αναζήτηση Google'], input[value='Google Search']"
            )
            if search_btn:
                await search_btn.click()
            else:
                await page.keyboard.press("Enter")
        except Exception:
            await page.keyboard.press("Enter")

    await asyncio.sleep(random_delay(2.5, 4.0))

    # Check for CAPTCHA
    if "sorry" in page.url:
        await asyncio.sleep(random_delay(5.0, 8.0))
        if "sorry" in page.url:
            return []

    # Extract organic results
    urls = await page.evaluate("""(max) => {
        const results = [];
        const selectors = ['div.g', 'div[data-hveid]', 'div[data-sokoban-container]'];
        const seen = new Set();
        for (const sel of selectors) {
            const items = document.querySelectorAll(sel);
            items.forEach(item => {
                const link = item.querySelector('a[href^="http"]');
                const h3 = item.querySelector('h3');
                if (link && h3 && !seen.has(link.href)) {
                    seen.add(link.href);
                    // Extract snippet text if available
                    const snippetDiv = item.querySelector('div[data-sncf], span.aCOpRe, div.VwiC3b');
                    const snippet = snippetDiv ? snippetDiv.textContent.trim() : '';
                    results.push({
                        position: results.length + 1,
                        title: h3.textContent.trim(),
                        url: link.href,
                        snippet: snippet
                    });
                }
            });
        }
        return results.slice(0, max);
    }""", max_results)

    return urls


# ─── Analysis functions ───────────────────────────────────────────────────

def check_our_visibility(results: list[dict]) -> dict:
    """
    Check if aionai.gr appears in search results.
    Returns detailed visibility analysis.
    """
    found = False
    our_position = None
    our_entry = None
    competitors_found = []

    for item in results:
        url = item.get("url", "")
        domain = url_utils.extract_domain(url)
        title = item.get("title", "")

        # Check if it's us
        if OUR_DOMAIN in domain or OUR_DOMAIN in url:
            found = True
            our_position = item.get("position")
            our_entry = item
        else:
            # Classify the competitor
            ctype = url_utils.classify_url(url, title)
            competitors_found.append({
                "position": item.get("position"),
                "domain": domain,
                "url": url,
                "title": title[:100],
                "type": ctype,
                "snippet": item.get("snippet", "")[:150],
            })

    return {
        "us_found": found,
        "our_position": our_position,
        "our_entry": our_entry,
        "total_results": len(results),
        "competitors": competitors_found,
        "citation_gap": not found,  # True = WE'RE NOT VISIBLE = gap
    }


def calculate_citation_gap_score(keyword_visibilities: list[dict]) -> dict:
    """
    Calculate overall citation gap score (0-100).
    100 = perfect visibility (us in all queries).
    0 = zero visibility (us nowhere).
    """
    total_queries = len(keyword_visibilities)
    if total_queries == 0:
        return {"score": 0, "level": "NO_DATA"}

    found_count = sum(1 for v in keyword_visibilities if v.get("us_found"))
    visibility_ratio = found_count / total_queries

    # Average position if found
    positions = [v.get("our_position", 999) for v in keyword_visibilities if v.get("us_found")]
    avg_position = sum(positions) / len(positions) if positions else 999

    # Score: 0-100 based on visibility ratio and position
    # Base: visibility_ratio * 60
    # Bonus: if avg_position <= 3, +20; if <= 5, +10; if <= 10, +5
    base_score = visibility_ratio * 60
    position_bonus = 0
    if positions:
        if avg_position <= 3:
            position_bonus = 20
        elif avg_position <= 5:
            position_bonus = 10
        elif avg_position <= 10:
            position_bonus = 5

    # Bonus if we appear with our brand name
    brand_queries = [v for v in keyword_visibilities if "aionai" in v.get("keyword", "").lower()]
    brand_found = sum(1 for v in brand_queries if v.get("us_found"))
    brand_bonus = 10 if brand_queries and brand_found == len(brand_queries) else 0

    score = min(100, base_score + position_bonus + brand_bonus)

    # Level classification
    if score >= 80:
        level = "GOOD"
    elif score >= 50:
        level = "MODERATE"
    elif score >= 20:
        level = "POOR"
    else:
        level = "CRITICAL"

    return {
        "score": round(score, 1),
        "level": level,
        "found_in_queries": found_count,
        "total_queries": total_queries,
        "visibility_ratio": round(visibility_ratio, 3),
        "avg_position_when_found": round(avg_position, 1) if positions else None,
        "position_bonus": position_bonus,
        "brand_bonus": brand_bonus,
    }


def get_top_competitors(keyword_visibilities: list[dict]) -> list[dict]:
    """
    Aggregate all competitors found across queries and return ranked list.
    """
    from collections import Counter, defaultdict

    domain_stats = defaultdict(lambda: {"count": 0, "total_position": 0, "queries": [], "types": set(), "titles": []})

    for kw_result in keyword_visibilities:
        keyword = kw_result.get("keyword", "")
        for comp in kw_result.get("competitors", []):
            domain = comp.get("domain", "")
            if not domain:
                continue
            domain_stats[domain]["count"] += 1
            domain_stats[domain]["total_position"] += comp.get("position", 10)
            domain_stats[domain]["queries"].append(keyword)
            domain_stats[domain]["types"].add(comp.get("type", "UNKNOWN"))
            domain_stats[domain]["titles"].append(comp.get("title", ""))

    # Rank: most appearances first, then best avg position
    ranked = []
    for domain, stats in domain_stats.items():
        ranked.append({
            "domain": domain,
            "appearances": stats["count"],
            "avg_position": round(stats["total_position"] / stats["count"], 1),
            "queries": list(set(stats["queries"])),
            "types": list(stats["types"]),
            "sample_title": stats["titles"][0][:80] if stats["titles"] else "",
        })

    ranked.sort(key=lambda x: (-x["appearances"], x["avg_position"]))
    return ranked[:20]


# ─── Default keyword sets ─────────────────────────────────────────────────

DEFAULT_KEYWORDS_EL = [
    "AI automation ελλάδα",
    "AI agents επιχειρήσεις",
    "τεχνητή νοημοσύνη συμβουλευτική",
    "αυτοματοποίηση επιχειρήσεων ai",
    "AI consulting αθήνα",
    "ποιος βοηθά επιχειρήσεις με AI στην Ελλάδα",
    "καλύτερη ai εταιρεία ελλάδα",
    "ai for small business greece",
    "ai automation consultant greece",
    "best ai agency athens",
    "ai solutions for sme greece",
    "εφαρμογή τεχνητής νοημοσύνης σε επιχειρήσεις",
    "λογισμικό ai για επιχειρήσεις",
    "ai assistant ελληνική αγορά",
    "ai αυτοματισμοί 2026",
]

# Brand-specific — should ALWAYS find us
DEFAULT_KEYWORDS_BRAND = [
    "aionAI",
    "aionai.gr",
    "aionAI automation",
    "aionAI Ελλάδα",
]


# ─── Main logic ───────────────────────────────────────────────────────────

async def run_citation_check(keywords: list[str], max_results: int = 10,
                              delay_range: tuple = (20.0, 35.0), verbose: bool = False) -> dict:
    """
    Run citation check for all keywords.
    Returns full report.
    """
    # Limit to 6 searches per run to avoid CAPTCHA
    if len(keywords) > 6:
        if verbose:
            print(f"[warn] Limiting to 6 keywords per run (got {len(keywords)})", file=sys.stderr)
        keywords = keywords[:6]

    keyword_visibilities = []

    async with async_playwright() as p:
        browser, context = await create_browser_context(p, headless=True)
        page = await context.new_page()

        if verbose:
            print("[verbose] Browser session initialized ✓", file=sys.stderr)

        for idx, keyword in enumerate(keywords):
            kw_result = {
                "keyword": keyword,
                "status": "pending",
                "us_found": False,
                "our_position": None,
                "total_results": 0,
                "competitors": [],
            }

            if verbose:
                print(f"\n[{idx+1}/{len(keywords)}] '{keyword[:60]}'", file=sys.stderr)

            try:
                results = await search_google(page, keyword, max_results=max_results)
            except Exception as e:
                kw_result["status"] = f"error: {e}"
                keyword_visibilities.append(kw_result)
                if verbose:
                    print(f"  ✗ ERROR: {e}", file=sys.stderr)
                continue

            if not results:
                kw_result["status"] = "blocked"
                if verbose:
                    print(f"  ✗ BLOCKED (CAPTCHA or no results)", file=sys.stderr)
            else:
                vis = check_our_visibility(results)
                kw_result["status"] = "success"
                kw_result["us_found"] = vis["us_found"]
                kw_result["our_position"] = vis["our_position"]
                kw_result["total_results"] = vis["total_results"]
                kw_result["competitors"] = vis["competitors"]

                if vis["us_found"]:
                    if verbose:
                        print(f"  ✓ FOUND at position #{vis['our_position']} 🎯", file=sys.stderr)
                else:
                    # Show top 3 competitors
                    top_comps = vis["competitors"][:3]
                    if verbose:
                        print(f"  ✗ NOT FOUND — top results:", file=sys.stderr)
                        for c in top_comps:
                            print(f"     #{c['position']} {c['domain']} — {c['title'][:60]}", file=sys.stderr)

            keyword_visibilities.append(kw_result)

            # Variable delay between searches
            if idx < len(keywords) - 1:
                delay = random.uniform(*delay_range)
                if verbose:
                    print(f"  ~ waiting {delay:.0f}s...", file=sys.stderr)
                await asyncio.sleep(delay)

        # Save session
        await save_session(context)
        await browser.close()

    # Calculate overall scores
    gap_score = calculate_citation_gap_score(keyword_visibilities)
    top_competitors = get_top_competitors(keyword_visibilities)

    # Find direct competitor domains (not directories/news)
    direct_competitors = [c for c in top_competitors if "DIRECTORY" not in c.get("types", [])
                          and "NEWS" not in c.get("types", [])
                          and "SOCIAL" not in c.get("types", [])]

    report = {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": "citation_scraper.py",
        "our_domain": OUR_DOMAIN,
        "keywords_checked": len(keywords),
        "successful": sum(1 for r in keyword_visibilities if r["status"] == "success"),
        "blocked": sum(1 for r in keyword_visibilities if r["status"] == "blocked"),
        "citation_gap_score": gap_score,
        "top_competitors_all": top_competitors[:10],
        "top_direct_competitors": direct_competitors[:10],
        "keyword_results": keyword_visibilities,
        "summary": (
            f"GEO citation gap: {gap_score['level']} ({gap_score['score']}/100). "
            f"Found in {gap_score['found_in_queries']}/{gap_score['total_queries']} queries. "
            f"Top competitor: {top_competitors[0]['domain'] if top_competitors else 'none'} "
            f"({top_competitors[0]['appearances']} appearances)" if top_competitors else ""
        ),
    }

    return report


def main():
    parser = argparse.ArgumentParser(
        description="citation_scraper.py — GEO Citation Gap Analysis for aionAI."
    )
    parser.add_argument("--keywords", nargs="+", default=None,
                        help="Keywords to check (space-separated). Default: Greek AI queries")
    parser.add_argument("--include-brand", action="store_true",
                        help="Also check brand queries (aionAI, aionai.gr)")
    parser.add_argument("--max", type=int, default=6,
                        help="Max keywords per run (default: 6, max: 8)")
    parser.add_argument("--max-results", type=int, default=10,
                        help="Max results per keyword (default: 10)")
    parser.add_argument("--output", default=None,
                        help="Output JSON file path")
    parser.add_argument("--min-delay", type=float, default=20.0,
                        help="Min seconds between searches (default: 20)")
    parser.add_argument("--max-delay", type=float, default=35.0,
                        help="Max seconds between searches (default: 35)")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()

    # Build keyword list
    keywords = args.keywords or DEFAULT_KEYWORDS_EL.copy()
    if args.include_brand:
        keywords = DEFAULT_KEYWORDS_BRAND + keywords

    if len(keywords) > args.max:
        if args.verbose:
            print(f"[warn] Limiting to {args.max} keywords (use --max to change)", file=sys.stderr)
        keywords = keywords[:args.max]

    if args.verbose:
        print(f"[verbose] Citation check for {len(keywords)} keywords", file=sys.stderr)
        for i, kw in enumerate(keywords):
            print(f"  {i+1}. {kw}", file=sys.stderr)

    # Run
    report = asyncio.run(run_citation_check(
        keywords,
        max_results=args.max_results,
        delay_range=(args.min_delay, args.max_delay),
        verbose=args.verbose,
    ))

    # Output
    json_str = json.dumps(report, ensure_ascii=False, indent=2)
    print(json_str)

    if args.output:
        Path(args.output).write_text(json_str, "utf-8")
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
