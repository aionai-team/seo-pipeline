#!/usr/bin/env python3

"""
gap_scorer.py — Keyword White Space Detection (Gap Score).

Συνδυάζει trend_score (από trend_validator) + SERP classification (από serp_scraper)
για να υπολογίσει το Gap Score κάθε keyword.

Gap Score = trend_score × (1 / (agency_in_top_10 + 1)) × publisher_penalty × mismatch_bonus

  - agency_in_top_10: πόσοι COMPETITOR URLs εμφανίζονται στις θέσεις 1-10
  - publisher_penalty: 1.5x αν κυριαρχούν Wikipedia/News (όχι agencies) = uncontested
  - mismatch_bonus: 1.0–2.0x αν το intent του keyword ΔΕΝ ταιριάζει με τα SERP results
    (π.χ. COMMERCIAL keyword αλλά τα top 3 είναι blog posts = nobody built the right page)
  - Υψηλό Gap Score = trending keyword + λίγοι competitors + intent mismatch → γρήγορο ranking

Output: ranked keywords by Gap Score (descending).

Usage:
    python gap_scorer.py --trends data/ranked_2026-06-14.json \\
        --serp data/urls_2026-06-14.json \\
        --output data/gaps_2026-06-14.json
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.supabase_client import get_supabase


# ─── Intent Mismatch Detection ─────────────────────────────────

def detect_intent_mismatch(intent: str, organic_urls: list[dict]) -> dict:
    """
    Συγκρίνει το intent του keyword με τα actual SERP results.
    
    Αν το keyword είναι COMMERCIAL/TRANSACTIONAL αλλά τα top URLs είναι
    INFO content (blog posts, Wikipedia, Reddit) → nobody built the right page → opportunity.
    
    Returns:
        mismatch_score: 0-100 (0=perfect match, 100=total mismatch)
        mismatch_type: description of the mismatch
        mismatch_bonus: 1.0–2.0 multiplier for gap score
    """
    if not organic_urls:
        return {"mismatch_score": 0, "mismatch_type": "NO_SERP_DATA", "mismatch_bonus": 1.0}
    
    # Get top 5 results sorted by position
    top5 = sorted(organic_urls[:5], key=lambda x: x.get("position", 99))
    top3 = top5[:3]
    top1_type = top5[0].get("type", "UNKNOWN") if top5 else "UNKNOWN"
    
    # Types of results in top 3
    top3_types = [item.get("type", "UNKNOWN") for item in top3]
    comp_count = sum(1 for t in top3_types if t == "COMPETITOR")
    info_count = sum(1 for t in top3_types if t in ("REDDIT", "NEWS", "WIKIPEDIA", "FORUM"))
    dir_count = sum(1 for t in top3_types if t == "DIRECTORY")
    
    mismatch_score = 0
    mismatch_type = "MATCH"
    
    if intent == "COMMERCIAL":
        # Commercial intent: user wants to find/hire an agency
        # Ideal: COMPETITOR pages in top 3
        # Mismatch: info/news/wiki/reddit in top 3
        
        if comp_count == 0:
            # Zero agencies in top 3 — strong mismatch
            if info_count >= 2:
                mismatch_score = 90
                mismatch_type = "COMMERCIAL_INTENT_INFO_RESULTS"
            elif top1_type in ("WIKIPEDIA", "NEWS"):
                mismatch_score = 80
                mismatch_type = "COMMERCIAL_INTENT_NON_AGENCY_TOP"
            else:
                mismatch_score = 60
                mismatch_type = "COMMERCIAL_INTENT_NO_AGENCIES"
        elif comp_count == 1:
            # Only 1 agency in top 3 — moderate mismatch
            if info_count >= 2:
                mismatch_score = 50
                mismatch_type = "COMMERCIAL_INTENT_PARTIAL_MISMATCH"
            else:
                mismatch_score = 20
                mismatch_type = "COMMERCIAL_INTENT_WEAK_MISMATCH"
        else:
            # 2+ agencies in top 3 — good match
            mismatch_score = 0
            mismatch_type = "COMMERCIAL_MATCH"
    
    elif intent == "TRANSACTIONAL":
        # Transactional: user wants pricing, comparison, buy
        # Ideal: pricing/comparison/agency pages
        # Mismatch: info content, Wikipedia, Reddit
        
        if comp_count == 0:
            if info_count >= 2:
                mismatch_score = 85
                mismatch_type = "TRANSACTIONAL_INTENT_INFO_RESULTS"
            else:
                mismatch_score = 70
                mismatch_type = "TRANSACTIONAL_INTENT_NO_PRICING"
        elif comp_count <= 1 and info_count >= 1:
            mismatch_score = 45
            mismatch_type = "TRANSACTIONAL_INTENT_PARTIAL"
        else:
            mismatch_score = 10
            mismatch_type = "TRANSACTIONAL_MATCH"
    
    elif intent == "INFO":
        # Info: user wants to learn
        # Ideal: guides, articles, Wikipedia (any info content)
        # Mismatch: mostly agency/commercial pages
        
        if comp_count >= 2:
            mismatch_score = 30
            mismatch_type = "INFO_INTENT_COMMERCIAL_RESULTS"
        else:
            mismatch_score = 0
            mismatch_type = "INFO_MATCH"
    
    elif intent == "NAVIGATIONAL":
        # Navigational: user looks for specific brand
        mismatch_score = 0
        mismatch_type = "NAVIGATIONAL_MATCH"
    
    # Convert mismatch score to bonus multiplier
    if mismatch_score >= 70:
        mismatch_bonus = 2.0
    elif mismatch_score >= 40:
        mismatch_bonus = 1.5
    elif mismatch_score >= 15:
        mismatch_bonus = 1.2
    else:
        mismatch_bonus = 1.0
    
    return {
        "mismatch_score": mismatch_score,
        "mismatch_type": mismatch_type,
        "mismatch_bonus": mismatch_bonus,
        "top3_types": top3_types,
        "top1_type": top1_type,
    }


# ─── Gap Score ────────────────────────────────────────────────

def calculate_gap_score(
    trend_score: float,
    agency_count: int,
    publisher_dominance: bool = False,
    top_is_wikipedia: bool = False,
    intent: str = "INFO",
    organic_urls: list[dict] = None,
) -> dict:
    """
    Calculate gap score for a keyword with intent mismatch awareness.
    
    Returns dict with all components, not just the final score.
    
    Formula:
        base = trend_score / (agency_count + 1)
        gap_score = base × publisher_penalty × mismatch_bonus
    """
    agency_count = max(agency_count, 0)
    trend_score = max(trend_score, 0)
    
    # Base: share-of-voice opportunity
    base = trend_score / (agency_count + 1)
    
    # Publisher penalty: if non-agencies dominate, keyword is uncontested
    publisher_penalty = 1.5 if publisher_dominance else 1.0
    
    # Wikipedia top = deprioritize (too generic — nobody converts from Wikipedia)
    if top_is_wikipedia:
        publisher_penalty *= 0.5
    
    # Intent mismatch bonus
    mismatch = {"mismatch_score": 0, "mismatch_type": "MATCH", "mismatch_bonus": 1.0}
    if organic_urls is not None:
        mismatch = detect_intent_mismatch(intent, organic_urls)
    
    gap_score = round(base * publisher_penalty * mismatch["mismatch_bonus"], 2)
    
    return {
        "gap_score": gap_score,
        "base_score": round(base, 2),
        "publisher_penalty": publisher_penalty,
        "mismatch_score": mismatch["mismatch_score"],
        "mismatch_type": mismatch["mismatch_type"],
        "mismatch_bonus": mismatch["mismatch_bonus"],
        "top3_types": mismatch.get("top3_types", []),
        "top1_type": mismatch.get("top1_type", ""),
    }


def classify_serp_dominance(
    classification: dict,
    organic_urls: list[dict],
) -> tuple[int, bool, bool]:
    """
    Analyze SERP composition for a keyword.
    
    Returns:
        (agency_count, publisher_dominance, top_is_wikipedia)
    
    agency_count: number of COMPETITOR-classified URLs
    publisher_dominance: True if top 3 results are REDDIT/NEWS/WIKIPEDIA/DIRECTORY
    top_is_wikipedia: True if position #1 is WIKIPEDIA
    """
    agency_count = 0
    publisher_count = 0
    top_is_wikipedia = False
    
    # Use classification breakdown if available
    if classification:
        agency_count = classification.get("COMPETITOR", 0)
    
    # Check top positions individually
    for item in sorted(organic_urls[:5], key=lambda x: x.get("position", 99)):
        ctype = item.get("type", "UNKNOWN")
        pos = item.get("position", 99)
        
        if ctype == "COMPETITOR":
            agency_count = max(agency_count, classification.get("COMPETITOR", 0))
        
        # Check what's in position 1
        if pos == 1:
            if ctype == "WIKIPEDIA":
                top_is_wikipedia = True
    
    # Publisher dominance: check if top 3 have non-competitor types
    top3_types = []
    for item in sorted(organic_urls[:3], key=lambda x: x.get("position", 99)):
        top3_types.append(item.get("type", "UNKNOWN"))
    
    non_comp_count = sum(1 for t in top3_types if t in ("REDDIT", "NEWS", "WIKIPEDIA", "DIRECTORY"))
    publisher_dominance = non_comp_count >= 2  # 2+ of top 3 are non-competitors
    
    return agency_count, publisher_dominance, top_is_wikipedia


# ─── Prioritization labels ────────────────────────────────────

def gap_priority(score: float) -> str:
    """Categorize gap score into priority levels."""
    if score >= 40:
        return "P1_CRITICAL"
    elif score >= 20:
        return "P2_HIGH"
    elif score >= 10:
        return "P3_MEDIUM"
    else:
        return "P4_LOW"


def gap_recommendation(score: float, intent: str, top_is_wikipedia: bool,
                       mismatch_score: int = 0, mismatch_type: str = "MATCH") -> str:
    """Generate human-readable recommendation with intent mismatch awareness."""
    if top_is_wikipedia:
        return "DEPRIORITIZE — keyword too generic, Wikipedia dominates"
    
    parts = []
    
    if score >= 30:
        parts.append("PUBLISH ASAP — high trend, low competition")
    elif score >= 15:
        parts.append("Good opportunity — create targeted content")
    elif score >= 5:
        parts.append("Moderate — consider only if fits existing content plan")
    else:
        parts.append("Low priority — competitors already cover this")
    
    # Intent mismatch recommendation
    if mismatch_score >= 70:
        parts.append("🎯 INTENT MISMATCH — nobody built the right page for this query")
    elif mismatch_score >= 40:
        parts.append("📌 Partial mismatch — gap in SERP intent coverage")
    
    if intent == "COMMERCIAL":
        parts.append("→ Create service page")
    elif intent == "INFO":
        parts.append("→ Create blog post / guide")
    elif intent == "TRANSACTIONAL":
        parts.append("→ Create pricing/comparison page")
    
    return " | ".join(parts)


# ─── Main ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="gap_scorer.py — Keyword White Space Detection."
    )
    parser.add_argument("--trends", required=True,
                        help="Ranked keywords JSON (from trend_validator.py)")
    parser.add_argument("--serp", required=True,
                        help="SERP URLs JSON (from serp_scraper.py, with classification)")
    parser.add_argument("--output", default=None, help="Output JSON")
    parser.add_argument("--min-trend", type=float, default=0,
                        help="Minimum trend_score to include (def: 0 = all)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--run-id", default=None, help="Pipeline run ID for Supabase insertion")
    args = parser.parse_args()

    # Read trend data
    trends_raw = json.loads(Path(args.trends).read_text("utf-8"))
    trends_list = trends_raw if isinstance(trends_raw, list) else trends_raw.get("results", [])

    # Read SERP data (with classification)
    serp_raw = json.loads(Path(args.serp).read_text("utf-8"))
    serp_list = serp_raw if isinstance(serp_raw, list) else serp_raw.get("results", [])

    # Build SERP lookup by keyword
    serp_by_keyword = {}
    for s in serp_list:
        kw = s.get("keyword", "").lower().strip()
        serp_by_keyword[kw] = s

    if args.verbose:
        print(f"[verbose] {len(trends_list)} trending keywords, "
              f"{len(serp_list)} SERP results loaded", file=sys.stderr)

    # Calculate gap scores
    scored = []
    skipped_no_serp = 0

    for kw_data in trends_list:
        keyword = kw_data.get("keyword", "")
        trend_score = kw_data.get("trend_score", 0) or 0
        intent = kw_data.get("intent", "INFO")

        if trend_score < args.min_trend:
            continue

        # Find corresponding SERP data
        serp = serp_by_keyword.get(keyword.lower().strip())
        if not serp:
            skipped_no_serp += 1
            continue

        classification = serp.get("classification", {})
        organic_urls = serp.get("organic_urls", [])

        agency_count, publisher_dom, top_is_wiki = classify_serp_dominance(
            classification, organic_urls
        )

        gap_result = calculate_gap_score(
            trend_score, agency_count, publisher_dom, top_is_wiki,
            intent=intent, organic_urls=organic_urls,
        )
        gap = gap_result["gap_score"]
        priority = gap_priority(gap)
        recommendation = gap_recommendation(
            gap, intent, top_is_wiki,
            mismatch_score=gap_result["mismatch_score"],
            mismatch_type=gap_result["mismatch_type"],
        )

        entry = {
            "keyword": keyword,
            "trend_score": trend_score,
            "intent": intent,
            
            # Gap components
            "agency_in_top_10": agency_count,
            "publisher_dominance": publisher_dom,
            "top_is_wikipedia": top_is_wiki,
            
            # Intent mismatch
            "mismatch_score": gap_result["mismatch_score"],
            "mismatch_type": gap_result["mismatch_type"],
            "mismatch_bonus": gap_result["mismatch_bonus"],
            
            # Result
            "gap_score": gap,
            "priority": priority,
            "recommendation": recommendation,
            
            # SERP composition
            "top1_type": gap_result.get("top1_type", ""),
            "top3_types": gap_result.get("top3_types", []),
            "total_serp_urls": len(organic_urls),
            "classification": classification,
        }
        scored.append(entry)

    # Sort by gap score descending
    scored.sort(key=lambda x: x["gap_score"], reverse=True)

    # Summary
    p1 = sum(1 for s in scored if s["priority"] == "P1_CRITICAL")
    p2 = sum(1 for s in scored if s["priority"] == "P2_HIGH")
    p3 = sum(1 for s in scored if s["priority"] == "P3_MEDIUM")
    p4 = sum(1 for s in scored if s["priority"] == "P4_LOW")

    output = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_trends": len(trends_list),
        "total_serp_results": len(serp_list),
        "skipped_no_serp": skipped_no_serp,
        "scored": len(scored),
        "priority_summary": {
            "P1_CRITICAL": p1,
            "P2_HIGH": p2,
            "P3_MEDIUM": p3,
            "P4_LOW": p4,
        },
        "results": scored,
        "top_opportunities": [
            {
                "keyword": s["keyword"],
                "gap_score": s["gap_score"],
                "priority": s["priority"],
                "intent": s["intent"],
                "recommendation": s["recommendation"],
                "agency_count": s["agency_in_top_10"],
                "mismatch_type": s["mismatch_type"],
                "mismatch_score": s["mismatch_score"],
            }
            for s in scored[:5]
        ],
    }

    # ─── Supabase insertion ────────────────────────────────────────
    if args.run_id:
        try:
            supabase = get_supabase()
            rows = []
            for s in scored:
                rows.append({
                    "run_id": args.run_id,
                    "keyword": s.get("keyword", ""),
                    "gap_score": s.get("gap_score", 0),
                    "priority": s.get("priority", ""),
                    "intent": s.get("intent", ""),
                    "trend_score": s.get("trend_score", 0),
                    "agency_in_top_10": s.get("agency_in_top_10", 0),
                    "mismatch_type": s.get("mismatch_type", ""),
                    "recommendation": s.get("recommendation", ""),
                    "classification": s.get("classification", {}),
                })
            if rows:
                supabase.table("gap_analysis").insert(rows).execute()
                if args.verbose:
                    print(f"[verbose] Inserted {len(rows)} rows into 'gap_analysis' table",
                          file=sys.stderr)
        except Exception as e:
            print(f"Warning: Supabase insert failed: {e}", file=sys.stderr)

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), "utf-8"
        )
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)
            print(f"  P1 (CRITICAL): {p1}, P2 (HIGH): {p2}, "
                  f"P3 (MEDIUM): {p3}, P4 (LOW): {p4}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
