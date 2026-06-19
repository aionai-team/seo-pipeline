#!/usr/bin/env python3
"""
migrate_to_supabase.py — Migrate all existing JSON data to Supabase.

Reads every JSON file in data/latest/ and inserts into the corresponding table.
Runs once — creates a pipeline_run entry for the migration.
"""

import sys
import os
from datetime import date

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.supabase_client import get_supabase, create_pipeline_run, complete_pipeline_run, load_json


def migrate_keywords(supabase, run_id: str, data_dir: str):
    """Migrate keywords.json and ranked.json → keywords table."""
    print("\n📄 keywords.json + ranked.json → keywords table")

    # keywords.json
    kw_path = os.path.join(data_dir, "keywords.json")
    if os.path.exists(kw_path):
        kw_data = load_json(kw_path)
        seeds = kw_data.get("seeds_used", 0)
        rows = []
        for kw in kw_data.get("keywords", []):
            rows.append({
                "run_id": run_id,
                "query": kw["query"],
                "intent": kw.get("intent"),
                "is_question": kw.get("question", False),
            })
        if rows:
            # Insert in batches of 100
            for i in range(0, len(rows), 100):
                supabase.table("keywords").insert(rows[i:i+100]).execute()
            print(f"  ✅ {len(rows)} keywords inserted")
    else:
        print(f"  ⏭️  keywords.json not found")

    # ranked.json — update existing keywords with trend data
    rk_path = os.path.join(data_dir, "ranked.json")
    if os.path.exists(rk_path):
        rk_data = load_json(rk_path)
        for rk in rk_data.get("results", []):
            supabase.table("keywords").update({
                "trend_score": rk.get("trend_score"),
                "trend_direction": rk.get("trend_direction"),
                "rank": rk.get("rank"),
                "percent_change": rk.get("percent_change"),
                "peak_month": rk.get("peak_month"),
                "data_points": rk.get("data_points"),
            }).eq("run_id", run_id).eq("query", rk["keyword"]).execute()
        print(f"  ✅ {len(rk_data.get('results', []))} ranked keywords updated")

    return seeds


def migrate_serp(supabase, run_id: str, data_dir: str):
    """Migrate serp.json → serp_results table."""
    path = os.path.join(data_dir, "serp.json")
    if not os.path.exists(path):
        print("\n⏭️  serp.json not found, skipping")
        return

    data = load_json(path)
    rows = []
    for r in data.get("results", []):
        rows.append({
            "run_id": run_id,
            "keyword": r["keyword"],
            "trend_score": r.get("trend_score"),
            "organic_urls": r.get("organic_urls", []),
            "blocked": r.get("blocked", False),
        })

    if rows:
        supabase.table("serp_results").insert(rows).execute()
    print(f"  ✅ {len(rows)} SERP results inserted")


def migrate_competitors(supabase, run_id: str, data_dir: str):
    """Migrate competitors.json + competitors_with_geo.json → competitors table."""
    print("\n📄 competitors.json → competitors table")

    path = os.path.join(data_dir, "competitors_with_geo.json")
    if not os.path.exists(path):
        path = os.path.join(data_dir, "competitors.json")
    if not os.path.exists(path):
        print("  ⏭️  competitors file not found")
        return

    data = load_json(path)
    rows = []
    for r in data.get("results", []):
        headings = r.get("headings", {})
        faqs = r.get("faqs", [])
        row = {
            "run_id": run_id,
            "url": r["url"],
            "domain": r.get("domain"),
            "keyword": r.get("keyword"),
            "meta_title": r.get("meta_title"),
            "word_count": r.get("word_count"),
            "h1_count": r.get("h1_count") or len(headings.get("h1", [])),
            "h2_count": r.get("h2_count") or len(headings.get("h2", [])),
            "h3_count": r.get("h3_count") or len(headings.get("h3", [])),
            "faqs": faqs if faqs else None,
            "schema_count": r.get("schema_count"),
            "has_faq_schema": r.get("has_faq_schema", False),
            "has_org_schema": r.get("has_org_schema", False),
            "geo_score": r.get("geo_score"),
            "geo_level": r.get("geo_level"),
            "geo_signals": r.get("geo_signals"),
        }
        rows.append(row)

    if rows:
        supabase.table("competitors").insert(rows).execute()
    print(f"  ✅ {len(rows)} competitors inserted")


def migrate_gap_analysis(supabase, run_id: str, data_dir: str):
    """Migrate gap_report.json → gap_analysis table."""
    path = os.path.join(data_dir, "gap_report.json")
    if not os.path.exists(path):
        print("\n⏭️  gap_report.json not found")
        return

    data = load_json(path)
    rows = []
    for r in data.get("results", []):
        rows.append({
            "run_id": run_id,
            "keyword": r["keyword"],
            "gap_score": r.get("gap_score"),
            "priority": r.get("priority"),
            "intent": r.get("intent"),
            "trend_score": r.get("trend_score"),
            "agency_in_top_10": r.get("agency_in_top_10"),
            "mismatch_type": r.get("mismatch_type"),
            "recommendation": r.get("recommendation"),
            "classification": r.get("classification"),
        })

    if rows:
        supabase.table("gap_analysis").insert(rows).execute()
    print(f"  ✅ {len(rows)} gap analysis rows inserted")


def migrate_secondary(supabase, run_id: str, data_dir: str):
    """Migrate secondary.json → secondary_intel table."""
    path = os.path.join(data_dir, "secondary.json")
    if not os.path.exists(path):
        return

    data = load_json(path)
    rows = []
    for r in data.get("results", []):
        ss = r.get("secondary_summary", {})
        rows.append({
            "run_id": run_id,
            "keyword": r["keyword"],
            "trend_score": r.get("trend_score"),
            "total_secondary_urls": ss.get("total_secondary_urls", 0),
            "questions_found": ss.get("questions_found", 0),
            "agencies_discovered": ss.get("agencies_discovered", 0),
            "secondary_data": r.get("secondary"),
        })

    if rows:
        supabase.table("secondary_intel").insert(rows).execute()
    print(f"  ✅ {len(rows)} secondary intel rows inserted")


def migrate_geo_self(supabase, run_id: str, data_dir: str):
    """Migrate geo_self_check.json or geo_self_rendered.json → geo_self table."""
    path = os.path.join(data_dir, "geo_self_rendered.json")
    if not os.path.exists(path):
        path = os.path.join(data_dir, "geo_self_check.json")
    if not os.path.exists(path):
        return

    data = load_json(path)
    row = {
        "run_id": run_id,
        "geo_score": data.get("geo_score"),
        "geo_level": data.get("geo_level"),
        "word_count": data.get("basic_stats", {}).get("word_count"),
        "signals": data.get("signals") or data.get("geo_signals"),
        "basic_stats": data.get("basic_stats"),
    }
    supabase.table("geo_self").insert(row).execute()
    print(f"  ✅ geo_self inserted (score={row['geo_score']})")


def migrate_geo_market(supabase, run_id: str, data_dir: str):
    """Migrate geo_market.json → geo_market table."""
    path = os.path.join(data_dir, "geo_market.json")
    if not os.path.exists(path):
        return

    data = load_json(path)
    ms = data.get("market_summary", data)
    row = {
        "run_id": run_id,
        "competitors_analyzed": ms.get("competitors_analyzed") or data.get("competitors_analyzed"),
        "avg_score": ms.get("avg_score"),
        "median_score": ms.get("median_score"),
        "max_score": ms.get("max_score"),
        "min_score": ms.get("min_score"),
        "score_distribution": ms.get("scores_distribution") or ms.get("score_distribution"),
        "signal_analysis": ms.get("signal_market_analysis") or data.get("signal_analysis"),
    }
    supabase.table("geo_market").insert(row).execute()
    print(f"  ✅ geo_market inserted (avg={row['avg_score']})")


def migrate_geo_gaps(supabase, run_id: str, data_dir: str):
    """Migrate geo_gaps.json → geo_gaps table."""
    path = os.path.join(data_dir, "geo_gaps.json")
    if not os.path.exists(path):
        return

    data = load_json(path)
    gaps = data.get("gap_analysis", {}).get("gaps", [])
    rows = []
    for g in gaps:
        rows.append({
            "run_id": run_id,
            "signal": g.get("signal"),
            "weight": g.get("weight"),
            "we_have_it": g.get("we_have_it", False),
            "market_presence_pct": g.get("market_presence_pct"),
            "priority": g.get("priority"),
            "score": g.get("score"),
        })

    if rows:
        supabase.table("geo_gaps").insert(rows).execute()
    print(f"  ✅ {len(rows)} geo gaps inserted")


def migrate_site_assessments(supabase, run_id: str, data_dir: str):
    """Migrate googlebot_view, rendered_report, jsonld_validation, comparison_report."""
    assessments = {
        "googlebot_raw": "googlebot_view.json",
        "rendered": "rendered_report.json",
        "jsonld": "jsonld_validation.json",
        "comparison": "comparison_report.json",
    }

    for atype, fname in assessments.items():
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            continue

        data = load_json(path)
        score = None
        verdict = None
        wc = None

        if atype == "googlebot_raw":
            gv = data.get("googlebot_view", data)
            score = data.get("googlebot_raw", {}).get("score") or gv.get("score")
            verdict = data.get("googlebot_raw", {}).get("verdict") or gv.get("verdict")
        elif atype == "rendered":
            score = data.get("rendered", {}).get("word_count")
            verdict = data.get("js_gap", {}).get("status")
            wc = data.get("rendered", {}).get("word_count")
        elif atype == "jsonld":
            score = data.get("jsonld_health", {}).get("score")
            verdict = data.get("jsonld_health", {}).get("verdict")
        elif atype == "comparison":
            score = data.get("googlebot_raw", {}).get("score")
            verdict = data.get("googlebot_raw", {}).get("verdict")

        row = {
            "run_id": run_id,
            "assessment_type": atype,
            "score": score,
            "verdict": str(verdict) if verdict else None,
            "word_count": wc,
            "data": data,
        }
        supabase.table("site_assessments").insert(row).execute()
        print(f"  ✅ {atype} assessment inserted")


def migrate_status(supabase, run_id: str, data_dir: str):
    """Migrate status.json → status_snapshots table."""
    path = os.path.join(data_dir, "status.json")
    if not os.path.exists(path):
        return

    data = load_json(path)
    row = {
        "run_id": run_id,
        "summary": data.get("summary", ""),
        "full_snapshot": data,
    }
    supabase.table("status_snapshots").insert(row).execute()
    print(f"  ✅ status snapshot inserted")


def main():
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "latest")
    if not os.path.exists(data_dir):
        print(f"❌ Data directory not found: {data_dir}")
        sys.exit(1)

    print("=" * 60)
    print("  aionAI Pipeline — Data Migration to Supabase")
    print("=" * 60)

    supabase = get_supabase()
    run_id = create_pipeline_run(supabase, status="migrating", seeds_used=0)
    print(f"\n📌 Migration run ID: {run_id}")

    # Migrate each data source
    migrate_keywords(supabase, run_id, data_dir)
    migrate_serp(supabase, run_id, data_dir)
    migrate_competitors(supabase, run_id, data_dir)
    migrate_gap_analysis(supabase, run_id, data_dir)
    migrate_secondary(supabase, run_id, data_dir)
    migrate_geo_self(supabase, run_id, data_dir)
    migrate_geo_market(supabase, run_id, data_dir)
    migrate_geo_gaps(supabase, run_id, data_dir)
    migrate_site_assessments(supabase, run_id, data_dir)
    migrate_status(supabase, run_id, data_dir)

    complete_pipeline_run(supabase, run_id, "complete")
    print(f"\n✅ Migration complete! Run ID: {run_id}")


if __name__ == "__main__":
    main()
