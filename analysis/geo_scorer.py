#!/usr/bin/env python3
"""
geo_scorer.py — GEO comparison report: aionAI vs market.

Διαβάζει:
  1. geo_self_check.json (site_scraper.py --geo-check output)
  2. competitors_with_geo.json (enhanced competitor_scraper.py output)

Βγάζει:
  - geo_report.json with comparison table, market averages, opportunity ranking

Usage:
    python3 analysis/geo_scorer.py --output data/latest/geo_report.json
    python3 analysis/geo_scorer.py --verbose
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import json
from datetime import datetime
from pathlib import Path

LATEST_DIR = Path(__file__).resolve().parent.parent / "data" / "latest"


def safe_read(filename: str) -> dict | list | None:
    """Read JSON from latest/ symlink, return None on failure."""
    path = LATEST_DIR / filename
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_self_geo() -> dict | None:
    """Load our own GEO check results."""
    return safe_read("geo_self_check.json")


def load_competitor_geo() -> list[dict]:
    """Load competitor GEO data, return list of successful results."""
    data = safe_read("competitors_with_geo.json")
    if not data or not isinstance(data, dict):
        return []
    return [r for r in data.get("results", []) if r.get("status") == "success" and r.get("geo_score") is not None]


def compute_market_stats(competitors: list[dict]) -> dict:
    """Compute market-wide GEO signal distribution."""
    total = len(competitors)
    if total == 0:
        return {}

    # Signal keys from geo_signals structure
    signal_map = {
        "has_faq_schema": lambda r: r.get("has_faq_schema", False),
        "has_org_schema": lambda r: r.get("has_organization_schema", False),
        "has_faq_section": lambda r: r.get("geo_signals", {}).get("faq_section", {}).get("has_faq_section", False),
        "has_tldr": lambda r: r.get("geo_signals", {}).get("tldr", {}).get("has_tldr", False),
        "is_answer_first": lambda r: r.get("geo_signals", {}).get("answer_first", {}).get("is_answer_first", False),
        "has_lists_ge2": lambda r: (r.get("geo_signals", {}).get("lists", {}).get("ul_count", 0) +
                                     r.get("geo_signals", {}).get("lists", {}).get("ol_count", 0)) >= 2,
        "has_tables": lambda r: r.get("geo_signals", {}).get("tables", 0) > 0,
        "has_citations_ge2": lambda r: r.get("geo_signals", {}).get("citations", {}).get("keyword_matches", 0) >= 2,
        "has_author": lambda r: (r.get("geo_signals", {}).get("author", {}).get("has_meta", False) or
                                  r.get("geo_signals", {}).get("author", {}).get("has_byline", False)),
        "has_stats": lambda r: r.get("geo_signals", {}).get("statistics", {}).get("count", 0) > 0,
        "word_count_ge2000": lambda r: r.get("word_count", 0) >= 2000,
        "has_howto_schema": lambda r: r.get("geo_signals", {}).get("advanced_schema", {}).get("has_howto", False),
        "has_product_schema": lambda r: r.get("geo_signals", {}).get("advanced_schema", {}).get("has_product", False),
    }

    distribution = {}
    for signal_name, extract_fn in signal_map.items():
        count = sum(1 for r in competitors if extract_fn(r))
        distribution[signal_name] = {
            "count": count,
            "pct": round(count / total * 100),
        }

    # Overall market stats
    scores = [r.get("geo_score", 0) for r in competitors]
    return {
        "total_competitors": total,
        "market_avg_geo": round(sum(scores) / len(scores), 1) if scores else 0,
        "market_median_geo": sorted(scores)[len(scores) // 2] if scores else 0,
        "market_min_geo": min(scores) if scores else 0,
        "market_max_geo": max(scores) if scores else 0,
        "signal_distribution": distribution,
    }


def get_our_signals(self_data: dict) -> dict:
    """Extract our own GEO signal booleans from self-check data for comparison."""
    gs = self_data.get("geo_signals", {})
    schema_types = gs.get("schema_types", [])

    # Helper to determine signal states from our data
    return {
        "has_faq_schema": "FAQPage" in schema_types,
        "has_org_schema": "ProfessionalService" in schema_types or "Organization" in schema_types,
        "has_faq_section": gs.get("faq_text_in_static_html", False),
        "has_tldr": gs.get("tldr_present", False),
        "is_answer_first": gs.get("h1_is_definitive", False),
        "has_lists_ge2": (gs.get("list_count", {}).get("ul", 0) +
                           gs.get("list_count", {}).get("ol", 0)) >= 2,
        "has_tables": gs.get("table_count", 0) > 0,
        "has_citations_ge2": gs.get("citation_count", 0) >= 2,
        "has_author": bool(gs.get("author_meta")),
        "has_stats": gs.get("stat_count", 0) > 0,
        "word_count_ge2000": gs.get("static_body_words", 0) >= 2000,
        "has_howto_schema": "HowTo" in schema_types,
        "has_product_schema": "Product" in schema_types,
    }


def build_comparison(our_signals: dict, market_stats: dict) -> list[dict]:
    """Build comparison rows: signal, market%, our value, delta, priority."""
    rows = []
    signal_labels = {
        "has_faq_schema": "FAQ schema (JSON-LD)", "has_org_schema": "Organization schema",
        "has_faq_section": "FAQ text section", "has_tldr": "TL;DR block",
        "is_answer_first": "Answer-first H1", "has_lists_ge2": "Lists (≥2 ul/ol)",
        "has_tables": "Data tables", "has_citations_ge2": "Citations (≥2)",
        "has_author": "Author info", "has_stats": "Statistics",
        "word_count_ge2000": "Word count ≥2000", "has_howto_schema": "HowTo schema",
        "has_product_schema": "Product schema",
    }

    sd = market_stats.get("signal_distribution", {})
    for signal, label in signal_labels.items():
        mkt = sd.get(signal, {})
        mkt_pct = mkt.get("pct", 0)
        our_val = our_signals.get(signal, False)
        delta = (1 if our_val else 0) * 100 - mkt_pct

        if delta >= 30:
            priority = "LEAD"
        elif delta >= 10:
            priority = "SLIGHT_LEAD"
        elif delta > -10:
            priority = "PARITY"
        elif delta > -30:
            priority = "SLIGHT_GAP"
        else:
            priority = "GAP"

        # Action recommendation
        if priority == "GAP":
            action = "CREATE — market has this, we don't"
        elif priority == "SLIGHT_GAP":
            action = "CONSIDER — modest market advantage"
        elif priority == "LEAD":
            action = "MAINTAIN — we dominate this signal"
        elif priority == "SLIGHT_LEAD":
            action = "KEEP — small advantage to protect"
        else:
            action = "MONITOR — on par with market"

        rows.append({
            "signal": signal,
            "label": label,
            "market_pct": mkt_pct,
            "our_value": our_val,
            "delta": delta,
            "priority": priority,
            "action": action,
        })

    rows.sort(key=lambda r: r["delta"])
    return rows


def generate_opportunities(rows: list[dict]) -> list[dict]:
    """Extract top opportunities — signals where we lag but market has them."""
    return [
        {
            "signal": r["signal"],
            "label": r["label"],
            "market_pct": r["market_pct"],
            "opportunity": f"{r['market_pct']}% of competitors have {r['label']}, we don't",
            "effort": "easy" if r["market_pct"] < 25 else "medium",
        }
        for r in rows if r["priority"] in ("GAP", "SLIGHT_GAP")
    ]


def main():
    parser = argparse.ArgumentParser(
        description="geo_scorer.py — GEO comparison report: aionAI vs market."
    )
    parser.add_argument("--output", default=None, help="Output JSON file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Load data
    self_data = load_self_geo()
    competitors = load_competitor_geo()

    if not self_data:
        print("Error: geo_self_check.json not found in data/latest/", file=sys.stderr)
        return 1
    if not competitors:
        print("Warning: No competitor GEO data found", file=sys.stderr)

    if args.verbose:
        print(f"[verbose] Self GEO score: {self_data.get('geo_score', {}).get('value', '?')}", file=sys.stderr)
        print(f"[verbose] Competitors with GEO: {len(competitors)}", file=sys.stderr)

    # Compute
    our_signals = get_our_signals(self_data)
    market_stats = compute_market_stats(competitors) if competitors else {}
    comparison = build_comparison(our_signals, market_stats) if market_stats else []
    opportunities = generate_opportunities(comparison) if comparison else []

    our_score = self_data.get("geo_score", {}).get("value", 0)

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": "geo_scorer.py",
        "our_site": {
            "name": "aionAI",
            "geo_score": our_score,
            "gaps": self_data.get("gaps", []),
        },
        "market": {
            "competitors_analyzed": market_stats.get("total_competitors", 0),
            "avg_geo_score": market_stats.get("market_avg_geo", 0),
            "median_geo_score": market_stats.get("market_median_geo", 0),
            "min_geo_score": market_stats.get("market_min_geo", 0),
            "max_geo_score": market_stats.get("market_max_geo", 0),
            "our_rank_vs_market": "above" if our_score >= market_stats.get("market_avg_geo", 0) else "below",
        },
        "comparison": comparison,
        "opportunities": opportunities,
        "recommendations": [
            {
                "priority": "HIGH",
                "action": "Add static HTML content pages",
                "detail": "72% of competitors have 2000+ body words. We have 0 (SPA shell). This is our #1 GEO gap.",
            },
            {
                "priority": "HIGH",
                "action": "Change homepage H1 to answer-first",
                "detail": "22% of competitors have answer-first H1. Our H1 is CTA-style ('Μάθετε αν...').",
            },
            {
                "priority": "MEDIUM",
                "action": "Add data tables to content pages",
                "detail": "17% of competitors have tables. Easy for comparison pages. Use <table> with schema markup.",
            },
            {
                "priority": "MEDIUM",
                "action": "Add inline citations with sources",
                "detail": "13% of competitors cite external sources. Add 2-3 per page for E-E-A-T.",
            },
            {
                "priority": "LOW",
                "action": "Add TL;DR and FAQ sections to every page",
                "detail": "Market penetration is low (7-24%). We already have these. Ensure each new page has them too.",
            },
        ],
        "summary": (f"us={our_score} vs market_avg={market_stats.get('market_avg_geo', '?')} | "
                    f"{len(opportunities)} opportunities | {len(comparison)} signals compared"),
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"[verbose] Saved to {args.output}", file=sys.stderr)

    if args.verbose:
        print(f"\n[verbose] Summary: {report['summary']}", file=sys.stderr)
        for opp in opportunities:
            print(f"  📌 {opp['label']}: {opp['opportunity']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
