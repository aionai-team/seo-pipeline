#!/usr/bin/env python3
"""
geo_market_analysis.py — GEO Market Analysis.

Μετράει το GEO readiness των competitors από RENDERED HTML
χρησιμοποιώντας το UNIFIED geo_scorer (ίδια κριτήρια για όλους).

Αρχιτεκτονική (όπως το SEO pipeline):
    serp_scraper.py → competitor_scraper.py (υπάρχον)
    geo_market_analysis.py (ΝΕΟ) → παίρνει competitors URLs και μετράει GEO

Pipeline:
    python3 analysis/geo_market_analysis.py --input data/latest/serp.json --output data/latest/geo_market.json
    python3 analysis/geo_market_analysis.py --urls "https://aiagency.gr" "https://digibot.gr" --output data/latest/geo_market.json

Output:
    - Per-competitor GEO score (0-100) από rendered HTML
    - Market average, median, max
    - Signal-by-signal market comparison
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from lib import geo_scorer
from lib import url_utils
from lib.supabase_client import get_supabase


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
REQUEST_DELAY = 1.5  # seconds between requests


def fetch_page(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[str]:
    """Fetch a page's rendered HTML. Returns None on failure."""
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        return None


def extract_competitor_urls_from_serp(serp_data: dict) -> list[dict]:
    """
    Extract competitor URLs from serp_scraper.py output.
    
    Handles both formats:
    - New: {"results": [{"competitors": [{"url": "...", "title": "..."}]}]}
    - Old: [{"competitors": [{"url": "...", "title": "..."}]}]
    """
    competitors = []
    
    # Normalize to list of result objects
    results = []
    if isinstance(serp_data, list):
        results = serp_data
    elif isinstance(serp_data, dict):
        results = serp_data.get("results", [])
        if not results and "organic_urls" in serp_data:
            # Single keyword result
            results = [serp_data]
    
    for r in results:
        keyword = r.get("keyword", "")
        comps = r.get("competitors", [])
        for c in comps:
            url = c.get("url", "")
            if url and url_utils.is_competitor_candidate(url, c.get("title", "")):
                domain = url_utils.extract_domain(url)
                competitors.append({
                    "url": url,
                    "domain": domain,
                    "keyword": keyword,
                    "title": c.get("title", ""),
                })
    
    # Deduplicate by domain (keep first occurrence)
    seen_domains = set()
    unique = []
    for c in competitors:
        if c["domain"] not in seen_domains:
            seen_domains.add(c["domain"])
            unique.append(c)
    
    return unique


def analyze_competitor(url: str, domain: str = "") -> dict:
    """
    Full GEO analysis of a single competitor.
    
    1. Fetch rendered HTML
    2. Extract GEO signals via geo_scorer
    3. Calculate unified score
    """
    html = fetch_page(url)
    if not html:
        return {
            "url": url,
            "domain": domain or url_utils.extract_domain(url),
            "status": "error",
            "fetch_error": True,
        }
    
    signals = geo_scorer.extract_signals_from_html(html, domain=domain)
    scored = geo_scorer.score_geo_readiness(signals)
    
    # Extract basic page info for reference
    title_match = re.search(r'<title>(.*?)</title>', html, re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""
    
    # Word count from rendered HTML
    body = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL)
    body_text = re.sub(r'<[^>]+>', ' ', body)
    body_text = re.sub(r'\s+', ' ', body_text).strip()
    word_count = len(body_text.split())
    
    return {
        "url": url,
        "domain": domain or url_utils.extract_domain(url),
        "title": title[:120],
        "word_count": word_count,
        "status": "success",
        "geo_score": scored["score"],
        "geo_level": scored["level"],
        "signals": {k: v["status"] for k, v in scored["signals"].items()},
        "signal_scores": {k: v["score"] for k, v in scored["signals"].items()},
        "gaps": scored["gaps"],
    }


def calculate_market_stats(competitor_results: list[dict]) -> dict:
    """Calculate market-wide GEO statistics from individual results."""
    scores = [c["geo_score"] for c in competitor_results if c.get("status") == "success"]
    
    if not scores:
        return {
            "competitors_analyzed": 0,
            "avg_score": 0,
            "median_score": 0,
            "max_score": 0,
            "min_score": 0,
        }
    
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    
    # Signal-level aggregation
    signal_aggregation = {}
    for name, weight, desc in geo_scorer.GEO_SIGNALS:
        present_count = sum(
            1 for c in competitor_results
            if c.get("status") == "success" and c.get("signals", {}).get(name) == "✅"
        )
        signal_aggregation[name] = {
            "market_presence_pct": round((present_count / n) * 100),
            "competitors_with_signal": present_count,
            "total_analyzed": n,
            "weight": weight,
        }
    
    return {
        "competitors_analyzed": n,
        "total_fetched": len(competitor_results),
        "failed": sum(1 for c in competitor_results if c.get("status") != "success"),
        "avg_score": round(sum(scores) / n, 1),
        "median_score": sorted_scores[n // 2] if n % 2 == 1
                        else round((sorted_scores[n//2 - 1] + sorted_scores[n//2]) / 2, 1),
        "max_score": max(scores),
        "min_score": min(scores),
        "scores_distribution": {
            "EXCELLENT": sum(1 for s in scores if s >= 80),
            "GOOD": sum(1 for s in scores if 60 <= s < 80),
            "MODERATE": sum(1 for s in scores if 40 <= s < 60),
            "POOR": sum(1 for s in scores if 20 <= s < 40),
            "CRITICAL": sum(1 for s in scores if s < 20),
        },
        "signal_market_analysis": signal_aggregation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="geo_market_analysis.py — GEO Market Analysis (unified scoring)."
    )
    parser.add_argument("--input", type=str, default=None,
                        help="SERP JSON or competitor list JSON (with competitors key)")
    parser.add_argument("--urls", nargs="+", default=None,
                        help="Direct competitor URLs to analyze")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON path")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY,
                        help=f"Delay between requests (default: {REQUEST_DELAY}s)")
    parser.add_argument("--max", type=int, default=20,
                        help="Max competitors to analyze (default: 20)")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Pipeline run ID for Supabase tracking")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()
    
    # Collect competitor URLs
    competitors = []
    if args.input:
        raw = json.loads(Path(args.input).read_text("utf-8"))
        competitors = extract_competitor_urls_from_serp(raw)
        if args.verbose:
            print(f"[verbose] Extracted {len(competitors)} competitors from {args.input}", file=sys.stderr)
    
    if args.urls:
        for url in args.urls:
            domain = url_utils.extract_domain(url)
            competitors.append({
                "url": url,
                "domain": domain,
                "keyword": "",
                "title": "",
            })
    
    if not competitors:
        print("Error: No competitors found. Provide --input or --urls.", file=sys.stderr)
        return 1
    
    # Limit
    if len(competitors) > args.max:
        if args.verbose:
            print(f"[verbose] Limiting to {args.max} competitors (got {len(competitors)})", file=sys.stderr)
        competitors = competitors[:args.max]
    
    if args.verbose:
        print(f"[verbose] Analyzing {len(competitors)} competitors...", file=sys.stderr)
    
    # Analyze each competitor
    results = []
    for i, comp in enumerate(competitors):
        url = comp["url"]
        domain = comp.get("domain", "")
        if args.verbose:
            print(f"  [{i+1}/{len(competitors)}] {domain or url}", file=sys.stderr)
        
        result = analyze_competitor(url, domain=domain)
        result["keyword"] = comp.get("keyword", "")
        results.append(result)
        
        if args.verbose and result.get("status") == "success":
            print(f"      GEO: {result['geo_score']}/100 ({result['geo_level']})", file=sys.stderr)
        elif args.verbose and result.get("status") == "error":
            print(f"      ✗ FETCH ERROR", file=sys.stderr)
        
        # Delay between requests
        if i < len(competitors) - 1:
            time.sleep(args.delay)
    
    # Calculate market stats
    market_stats = calculate_market_stats(results)
    
    # Build report
    report = {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": "geo_market_analysis.py",
        "methodology": (
            "Unified GEO scoring via lib/geo_scorer.py — "
            "all competitors scored from rendered HTML with identical criteria"
        ),
        "competitors_analyzed": len(results),
        "market_summary": market_stats,
        "competitors": sorted(results, key=lambda x: x.get("geo_score", 0) if x.get("status") == "success" else 0, reverse=True),
    }
    
    # Output
    json_str = json.dumps(report, ensure_ascii=False, indent=2)
    print(json_str)
    
    if args.output:
        Path(args.output).write_text(json_str, "utf-8")
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)

    # Write to Supabase if run_id provided
    if args.run_id:
        try:
            supabase = get_supabase()
            supabase.table("geo_market").insert({
                "run_id": args.run_id,
                "competitors_analyzed": market_stats["competitors_analyzed"],
                "avg_score": market_stats["avg_score"],
                "median_score": market_stats["median_score"],
                "max_score": market_stats["max_score"],
                "min_score": market_stats["min_score"],
                "score_distribution": market_stats.get("scores_distribution", {}),
                "signal_analysis": market_stats.get("signal_market_analysis", {}),
            }).execute()
            if args.verbose:
                print(f"[verbose] Written to Supabase geo_market table", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to write to Supabase: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
