#!/usr/bin/env python3
"""
geo_self_rendered.py — GEO self-assessment from RENDERED HTML.

Το κρίσιμο κομμάτι που έλειπε από το GEO pipeline:

    ΠΡΙΝ:  site_scraper --geo-check → source code signals (67/100)
           geo_market_analysis.py   → rendered HTML signals (competitors)
           geo_gap_scorer.py        → ΣΥΓΚΡΙΣΗ source vs rendered = ΛΑΘΟΣ

    ΤΩΡΑ:  geo_self_rendered.py     → rendered HTML signals (εμάς)
           geo_market_analysis.py   → rendered HTML signals (competitors)
           geo_gap_scorer.py        → ΣΥΓΚΡΙΣΗ rendered vs rendered = ΣΩΣΤΟ

Pipeline:
    python tools/geo_self_rendered.py --output data/latest/geo_self_rendered.json
    python analysis/geo_gap_scorer.py --our-file data/latest/geo_self_rendered.json \\
        --market-file data/latest/geo_market.json --output data/latest/geo_gaps.json

Method:
    - Χρησιμοποιεί requests (όχι browser) — ίδια μέθοδος με geo_market_analysis
    - Περνάει το rendered HTML από lib/geo_scorer.extract_signals_from_html()
    - Παράγει output συμβατό με geo_gap_scorer.py --our-file
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import json
from datetime import datetime
from typing import Optional

import requests

from lib import geo_scorer

# ─── Constants ────────────────────────────────────────────────────────────

TARGET_URL = "https://aionai.gr/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15


# ─── Fetch rendered HTML ─────────────────────────────────────────────────

def fetch_rendered_html(url: str = TARGET_URL) -> Optional[str]:
    """
    Fetch rendered HTML of our site.

    Uses requests with a standard browser User-Agent (not Googlebot).
    This gives us the same view a no-JS crawler or AI engine would see.
    """
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        return None


# ─── Check llms.txt ──────────────────────────────────────────────────────

def check_llms_txt(domain: str = "aionai.gr") -> bool:
    """Check if llms.txt exists at the domain."""
    try:
        resp = requests.get(
            f"https://{domain}/llms.txt",
            timeout=REQUEST_TIMEOUT,
        )
        return resp.status_code == 200 and len(resp.text) > 20
    except requests.exceptions.RequestException:
        return False


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="geo_self_rendered.py — GEO self-assessment from rendered HTML."
    )
    parser.add_argument("--url", type=str, default=TARGET_URL,
                        help=f"URL to analyze (default: {TARGET_URL})")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON path")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()

    if args.verbose:
        print(f"[verbose] Fetching rendered HTML from {args.url}...", file=sys.stderr)

    # Step 1: Fetch rendered HTML
    html = fetch_rendered_html(args.url)
    if not html:
        print(f"Error: Failed to fetch {args.url}", file=sys.stderr)
        return 1

    if args.verbose:
        body_preview = html[:200].replace("\n", " ")
        print(f"[verbose] Received {len(html)} bytes", file=sys.stderr)
        print(f"[verbose] Preview: {body_preview}...", file=sys.stderr)

    # Step 2: Extract GEO signals from rendered HTML (UNIFIED method)
    signals = geo_scorer.extract_signals_from_html(html, domain="aionai.gr")

    # Step 3: Check llms.txt separately
    signals["has_llms_txt"] = check_llms_txt()

    # Step 4: Score it (same as competitors)
    scored = geo_scorer.score_geo_readiness(signals)

    # Step 5: Basic page info
    word_count = signals.get("word_count", 0)
    ul_count = signals.get("ul_count", 0)
    ol_count = signals.get("ol_count", 0)
    table_count = signals.get("table_count", 0)
    external_links = signals.get("external_link_count", 0)
    citation_kw = signals.get("citation_keyword_count", 0)
    stat_count = signals.get("stat_count", 0)

    # Step 6: Build output compatible with geo_gap_scorer.py --our-file
    # The expected format: {"signals": {name: bool, ...}} OR {"geo_signals": {...}}
    # geo_gap_scorer reads signals like "has_faq_schema", "has_faq_text", etc.
    # from either "signals" or "geo_signals" key

    output_signals = {name: signals.get(name, False)
                     for name, _, _ in geo_scorer.GEO_SIGNALS}

    report = {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": "geo_self_rendered.py",
        "url": args.url,
        "method": "requests + lib/geo_scorer (rendered HTML, same as competitors)",
        "html_size_bytes": len(html),
        "basic_stats": {
            "word_count": word_count,
            "ul_count": ul_count,
            "ol_count": ol_count,
            "table_count": table_count,
            "external_links": external_links,
            "citation_keywords": citation_kw,
            "stat_count": stat_count,
        },
        "geo_score": scored["score"],
        "geo_level": scored["level"],
        "max_geo_score": scored["max_score"],
        "signals": output_signals,              # <-- για geo_gap_scorer --our-file
        "geo_signals": output_signals,           # <-- και για το fallback format
        "signal_details": scored["signals"],     # full breakdown with scores
        "gaps": scored["gaps"],
        "summary": (
            f"GEO self (rendered): {scored['score']}/100 ({scored['level']}) | "
            f"words={word_count} | gaps={len(scored['gaps'])}"
        ),
    }

    # Output
    json_str = json.dumps(report, ensure_ascii=False, indent=2)
    print(json_str)

    if args.output:
        Path(args.output).write_text(json_str, "utf-8")
        if args.verbose:
            print(f"[verbose] Saved to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
