#!/usr/bin/env python3
"""
geo_gap_scorer.py — GEO Gap Analysis: us vs market.

Συγκρίνει το GEO score μας (από rendered HTML, ίδια κριτήρια)
με το market average και βρίσκει συγκεκριμένα gaps.

Αρχιτεκτονική (όπως το SEO gap_scorer.py):
    serp_scraper → competitor_scraper → gap_scorer (SEO)
    geo_market_analysis → geo_gap_scorer (GEO)

Pipeline:
    # Βήμα 1: Μετράμε εμάς (rendered HTML)
    python3 scrapers/citation_scraper.py --health-check
    
    # Βήμα 2: Μετράμε την αγορά
    python3 analysis/geo_market_analysis.py --input data/latest/serp.json --output data/latest/geo_market.json
    
    # Βήμα 3: Βρίσκουμε gaps (αυτό το script)
    python3 analysis/geo_gap_scorer.py --our-score 0 --market-file data/latest/geo_market.json --output data/latest/geo_gaps.json

Usage:
    python3 analysis/geo_gap_scorer.py --our-score 0 --market-file data/latest/geo_market.json
    python3 analysis/geo_gap_scorer.py --our-file data/latest/geo_self.json --market-file data/latest/geo_market.json
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

from lib import geo_scorer
from lib.supabase_client import get_supabase


# ─── Gap priority based on weight + market advantage ─────────────────────

def calculate_gap_priority(signal_name: str, weight: int, we_have_it: bool,
                            market_presence_pct: float) -> dict:
    """
    Calculate gap priority based on:
    - How important the signal is (weight)
    - Do we have it? (we_have_it)
    - How many competitors have it? (market_presence_pct)
    
    Priority matrix:
        HIGH weight + we DON'T have + market HAS it = CRITICAL/HIGH gap
        HIGH weight + we DON'T have + market doesn't either = MEDIUM (everyone's gap)
        LOW weight + we DON'T have = LOW/ignorable
        we HAVE it = no gap (regardless of market)
    """
    if we_have_it:
        return {"is_gap": False, "priority": "NONE", "score": 0}
    
    # We don't have it — how bad is it?
    if weight >= 10:  # High-impact signals
        if market_presence_pct >= 50:
            # Market has it, we don't → CRITICAL gap
            priority = "CRITICAL"
            score = weight * 2
        elif market_presence_pct >= 20:
            priority = "HIGH"
            score = weight * 1.5
        else:
            # Market doesn't have it either → everyone's gap
            priority = "MEDIUM"
            score = weight * 0.5
    elif weight >= 6:  # Medium-impact signals
        if market_presence_pct >= 50:
            priority = "HIGH"
            score = weight
        elif market_presence_pct >= 20:
            priority = "MEDIUM"
            score = weight * 0.7
        else:
            priority = "LOW"
            score = weight * 0.3
    else:  # Low-impact signals
        if market_presence_pct >= 50:
            priority = "MEDIUM"
            score = weight * 0.5
        else:
            priority = "LOW"
            score = weight * 0.2
    
    return {"is_gap": True, "priority": priority, "score": round(score, 1)}


def run_gap_analysis(our_signals: dict, market_stats: dict) -> dict:
    """
    Compare our GEO signals against the market.
    
    Args:
        our_signals: dict of signal_name -> bool for our site
        market_stats: market_summary from geo_market_analysis.py
    
    Returns:
        dict with gap analysis
    """
    signal_market = market_stats.get("signal_market_analysis", {})
    
    gaps = []
    opportunities = []
    our_strengths = []
    
    for name, weight, desc in geo_scorer.GEO_SIGNALS:
        we_have_it = our_signals.get(name, False)
        market_info = signal_market.get(name, {})
        market_pct = market_info.get("market_presence_pct", 0)
        competitors_have = market_info.get("competitors_with_signal", 0)
        total_analyzed = market_info.get("total_analyzed", 1)
        
        gap_result = calculate_gap_priority(name, weight, we_have_it, market_pct)
        
        entry = {
            "signal": name,
            "description": desc,
            "weight": weight,
            "we_have_it": we_have_it,
            "market_presence_pct": market_pct,
            "competitors_with_signal": competitors_have,
            "total_competitors_analyzed": total_analyzed,
        }
        entry.update(gap_result)
        
        if we_have_it and market_pct < 30:
            # We have something few competitors have → competitive advantage
            our_strengths.append(entry)
        elif we_have_it:
            pass  # Table stakes — no gap, no advantage
        elif not we_have_it and market_pct >= 20:
            gaps.append(entry)
        elif not we_have_it:
            opportunities.append(entry)
    
    # Sort gaps by priority then weight
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    gaps.sort(key=lambda g: (priority_order.get(g["priority"], 99), -g["weight"]))
    opportunities.sort(key=lambda o: -o["weight"])
    our_strengths.sort(key=lambda s: -s["weight"])
    
    # Calculate overall gap score (0-100, higher = bigger overall gap)
    total_possible_gap = sum(w * 2 for _, w, _ in geo_scorer.GEO_SIGNALS)
    actual_gap_score = sum(g.get("score", 0) for g in gaps)
    gap_score_pct = round((actual_gap_score / total_possible_gap) * 100) if total_possible_gap > 0 else 0
    
    return {
        "summary": {
            "total_gaps": len(gaps),
            "critical_gaps": sum(1 for g in gaps if g["priority"] == "CRITICAL"),
            "high_gaps": sum(1 for g in gaps if g["priority"] == "HIGH"),
            "medium_gaps": sum(1 for g in gaps if g["priority"] == "MEDIUM"),
            "low_gaps": sum(1 for g in gaps if g["priority"] == "LOW"),
            "our_strengths": len(our_strengths),
            "market_opportunities": len(opportunities),
            "gap_intensity_score": gap_score_pct,
        },
        "gaps": gaps,
        "opportunities": opportunities,
        "our_strengths": our_strengths,
        "recommendations": generate_recommendations(gaps, our_strengths, our_signals),
    }


def generate_recommendations(gaps: list, strengths: list, our_signals: dict) -> list:
    """Generate actionable recommendations from gaps."""
    recs = []
    
    for gap in gaps:
        signal = gap["signal"]
        priority = gap["priority"]
        
        if signal == "has_tldr":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add TL;DR block (40-80 words) visible in rendered HTML at top of content",
                "effort": "Low",
                "impact": "High",
            })
        elif signal == "has_faq_text":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Move FAQ text from JSON-LD only to visible HTML elements",
                "effort": "Medium",
                "impact": "High",
            })
        elif signal == "is_answer_first":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Restructure H1 + first paragraph to answer a question directly",
                "effort": "Low",
                "impact": "High",
            })
        elif signal == "word_count_ge1500":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add substantial visible content (currently SPA shell gives 0 words)",
                "effort": "High",
                "impact": "Critical",
            })
        elif signal == "has_lists_ge2":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add structured lists (services, features, benefits) in visible HTML",
                "effort": "Low",
                "impact": "Medium",
            })
        elif signal == "has_tables":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add comparison/data tables in visible content",
                "effort": "Medium",
                "impact": "Medium",
            })
        elif signal == "has_citations_ge2":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add inline citations with links to authoritative sources",
                "effort": "Medium",
                "impact": "Medium",
            })
        elif signal == "has_statistics":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add statistics/percentages with cited sources",
                "effort": "Medium",
                "impact": "Medium",
            })
        elif signal == "has_author_name":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Add author byline with credentials in visible content",
                "effort": "Low",
                "impact": "Low",
            })
        elif signal == "has_llms_txt":
            recs.append({
                "priority": priority,
                "signal": signal,
                "action": "Create/update llms.txt with structured domain overview",
                "effort": "Low",
                "impact": "Medium",
            })
    
    return recs


def main():
    parser = argparse.ArgumentParser(
        description="geo_gap_scorer.py — GEO Gap Analysis: us vs market."
    )
    parser.add_argument("--our-score", type=int, default=None,
                        help="Our GEO score (0-100) from --googlebot check")
    parser.add_argument("--our-file", type=str, default=None,
                        help="JSON file with our GEO signals")
    parser.add_argument("--market-file", type=str, required=True,
                        help="geo_market_analysis.py output JSON")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON path")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Pipeline run ID for Supabase tracking")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()
    
    # Read market data
    market_raw = json.loads(Path(args.market_file).read_text("utf-8"))
    market_stats = market_raw.get("market_summary", {})
    competitors = market_raw.get("competitors", [])
    
    # Determine our signals
    our_signals = {}
    
    if args.our_file:
        our_data = json.loads(Path(args.our_file).read_text("utf-8"))
        # Try to extract signals from our data
        if "signals" in our_data:
            our_signals = our_data.get("signals", {})
        elif "geo_signals" in our_data:
            # From site_scraper --geo-check
            gs = our_data.get("geo_signals", {})
            our_signals = {
                "has_faq_schema": gs.get("faq_schema_in_static_html", False),
                "has_faq_text": gs.get("faq_text_in_static_html", False),
                "has_org_schema": "ProfessionalService" in str(our_data.get("json_ld", {})),
                "has_tldr": gs.get("tldr_present", False),
                "is_answer_first": gs.get("h1_is_definitive", False),
                "word_count_ge1500": gs.get("static_body_words", 0) >= 1500,
                "has_lists_ge2": gs.get("list_count", {}).get("ul", 0) + gs.get("list_count", {}).get("ol", 0) >= 2,
                "has_tables": gs.get("table_count", 0) > 0,
                "has_citations_ge2": gs.get("citation_count", 0) >= 2 or gs.get("citation_keyword_mentions", 0) >= 2,
                "has_author_name": bool(gs.get("author_meta", "")),
                "has_statistics": gs.get("stat_count", 0) > 0,
                "has_llms_txt": gs.get("llms_txt", {}).get("exists", False),
            }
    elif args.our_score is not None:
        # If we only have a score, infer signals based on score level
        # This is a fallback — better to provide our-file
        if args.verbose:
            print("[warn] No signal data provided. Using score-based inference.", file=sys.stderr)
        our_signals = {
            "has_faq_schema": args.our_score >= 15,
            "has_faq_text": args.our_score >= 25,
            "has_org_schema": True,
            "has_tldr": args.our_score >= 35,
            "is_answer_first": args.our_score >= 45,
            "word_count_ge1500": args.our_score >= 50,
            "has_lists_ge2": args.our_score >= 55,
            "has_tables": args.our_score >= 60,
            "has_citations_ge2": args.our_score >= 65,
            "has_author_name": args.our_score >= 70,
            "has_statistics": args.our_score >= 75,
            "has_llms_txt": args.our_score >= 80,
        }
    else:
        # Default: we have nothing (Googlebot sees 0 words)
        if args.verbose:
            print("[warn] No signal data. Assuming zero GEO score (CRITICAL).", file=sys.stderr)
        our_signals = {name: False for name, _, _ in geo_scorer.GEO_SIGNALS}
        # We DO have FAQ schema and org schema in static HTML
        our_signals["has_faq_schema"] = True
        our_signals["has_org_schema"] = True
        our_signals["has_llms_txt"] = True
        our_signals["has_author_name"] = True
    
    # Run gap analysis
    gap_report = run_gap_analysis(our_signals, market_stats)
    
    # Calculate our score from signals
    our_scored = geo_scorer.score_geo_readiness(our_signals)
    
    # Build final report
    report = {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": "geo_gap_scorer.py",
        "our_geo_score": our_scored["score"],
        "our_geo_level": our_scored["level"],
        "market_avg_geo": market_stats.get("avg_score", 0),
        "market_max_geo": market_stats.get("max_score", 0),
        "market_median_geo": market_stats.get("median_score", 0),
        "competitors_analyzed": market_stats.get("competitors_analyzed", 0),
        "gap_analysis": gap_report,
        "summary": (
            f"Our GEO: {our_scored['score']}/100 ({our_scored['level']}) | "
            f"Market: {market_stats.get('avg_score', 0)} avg, "
            f"{market_stats.get('max_score', 0)} max | "
            f"Gaps: {gap_report['summary']['critical_gaps']}C + "
            f"{gap_report['summary']['high_gaps']}H + "
            f"{gap_report['summary']['medium_gaps']}M | "
            f"Strengths: {gap_report['summary']['our_strengths']}"
        ),
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
            for gap in gap_report.get("gaps", []):
                supabase.table("geo_gaps").insert({
                    "run_id": args.run_id,
                    "signal": gap["signal"],
                    "weight": gap["weight"],
                    "we_have_it": gap["we_have_it"],
                    "market_presence_pct": gap["market_presence_pct"],
                    "priority": gap["priority"],
                    "score": gap["score"],
                }).execute()
            if args.verbose:
                print(f"[verbose] Written {len(gap_report.get('gaps', []))} gaps to Supabase geo_gaps table", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to write to Supabase: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
