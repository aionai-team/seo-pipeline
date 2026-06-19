#!/usr/bin/env python3
"""
generate_status.py — Παράγει lightweight status.json για γρήγορη επισκόπηση.

Διαβάζει όλα τα data/latest/*.json και παράγει ένα compact status summary.
Σχεδιασμένο να διαβάζεται από τον SEO agent στην αρχή κάθε session.

Usage:
    python3 tools/generate_status.py
    python3 tools/generate_status.py --verbose

Output: data/latest/status.json
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path for lib imports
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.supabase_client import get_supabase, upsert_status
DATA_DIR = ROOT / "data"
LATEST_DIR = DATA_DIR / "latest"
RUNS_DIR = DATA_DIR / "runs"
COMPETITORS_DIR = DATA_DIR / "competitors"


def resolve_symlink(path: Path) -> Path | None:
    """Resolve a symlink to its target, return None if broken."""
    try:
        if path.is_symlink():
            target = path.resolve()
            return target if target.exists() else None
        return path if path.exists() else None
    except OSError:
        return None


def safe_read_json(path: Path) -> dict | list | None:
    """Read JSON file, return None on failure."""
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_file_age_days(path: Path) -> int | None:
    """Get file age in days from modification time."""
    try:
        mtime = path.stat().st_mtime
        return int((time.time() - mtime) / 86400)
    except OSError:
        return None


def check_intent_in_ranked(data: dict | list | None) -> bool | str:
    """Check if ranked data has intent fields."""
    if not data:
        return "no data"
    if isinstance(data, dict):
        results = data.get("results", [])
    else:
        results = data
    if not results:
        return "empty"
    sample = results[0] if isinstance(results, list) else results
    if isinstance(sample, dict) and "intent" in sample:
        return True
    return False


def check_serp_classification(data: dict | list | None) -> bool | str:
    """Check if serp data has classification."""
    if not data:
        return "no data"
    if isinstance(data, dict):
        results = data.get("results", [])
    else:
        results = data
    if not results:
        return "empty"
    sample = results[0] if isinstance(results, list) else results
    if isinstance(sample, dict) and "classification" in sample:
        return bool(sample.get("classification"))
    return False


def parse_runs() -> list[str]:
    """Get list of available run dates."""
    if not RUNS_DIR.exists():
        return []
    return sorted([d.name for d in RUNS_DIR.iterdir() if d.is_dir() and d.name[0].isdigit()], reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Generate status.json and optionally save to status_snapshots")
    parser.add_argument("--verbose", action="store_true", help="Print verbose debug output")
    parser.add_argument("--run-id", type=str, default=None,
                        help="UUID of a pipeline_run to associate this snapshot with")
    args = parser.parse_args()
    verbose = args.verbose

    status = {
        "generated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "agent": "seo-improver",
    }

    # ─── Available runs ───
    runs = parse_runs()
    status["available_runs"] = runs
    status["last_run"] = runs[0] if runs else None

    # ─── Files availability ───
    expected_files = [
        "keywords.json", "ranked.json", "serp.json",
        "gap_report.json", "comparison_report.json",
        "rendered_report.json", "jsonld_validation.json",
        "site.json", "geo_self_check.json",
        "competitors_with_geo.json",
    ]
    files_available = {}
    outdated = {}

    for fname in expected_files:
        link = LATEST_DIR / fname
        target = resolve_symlink(link)
        if target:
            age = get_file_age_days(target)
            files_available[fname] = {"exists": True, "age_days": age}
            if verbose:
                print(f"  ✓ {fname} ({age}d old)", file=sys.stderr)
        else:
            files_available[fname] = {"exists": False, "age_days": None}

    status["files"] = files_available

    # ─── keywords.json ───
    kw_file = LATEST_DIR / "keywords.json"
    kw_data = safe_read_json(kw_file)
    if kw_data:
        total = kw_data.get("total_keywords", kw_data.get("total_input", 0))
        ib = kw_data.get("intent_breakdown", {})
        status["keywords"] = {
            "total": total,
            "intent_breakdown": ib,
        }
    else:
        status["keywords"] = {"total": 0, "intent_breakdown": {}}

    # ─── ranked.json ───
    rn_file = LATEST_DIR / "ranked.json"
    rn_data = safe_read_json(rn_file)
    if rn_data and isinstance(rn_data, dict):
        results = rn_data.get("results", [])
        status["ranked"] = {
            "total": len(results),
            "has_intent": check_intent_in_ranked(rn_data),
        }
        if results:
            top = results[0]
            status["ranked"]["top"] = {
                "keyword": top.get("keyword", "?"),
                "trend_score": top.get("trend_score", 0),
                "intent": top.get("intent", "N/A"),
            }
        if status["ranked"].get("has_intent") == False:
            outdated["ranked"] = "Missing intent field — needs trend_validator re-run"

    # ─── serp.json ───
    srp_file = LATEST_DIR / "serp.json"
    srp_data = safe_read_json(srp_file)
    if srp_data and isinstance(srp_data, dict):
        sr_results = srp_data.get("results", [])
        has_cls = check_serp_classification(srp_data)
        status["serp"] = {
            "keywords_scraped": len(sr_results),
            "has_classification": has_cls,
            "total_competitors": sum(
                r.get("total_competitors", 0) for r in sr_results
            ) if has_cls else 0,
        }
        if not has_cls:
            outdated["serp"] = "Old format — needs refresh for URL classification"
    else:
        status["serp"] = {"keywords_scraped": 0, "has_classification": False}

    # ─── gap_report.json ───
    gp_file = LATEST_DIR / "gap_report.json"
    gp_data = safe_read_json(gp_file)
    if gp_data and isinstance(gp_data, dict):
        gres = gp_data.get("results", [])
        ps = gp_data.get("priority_summary", {})
        top_opps = gp_data.get("top_opportunities", [])
        status["gaps"] = {
            "total_scored": len(gres),
            "priority_summary": {
                "P1_CRITICAL": ps.get("P1_CRITICAL", 0),
                "P2_HIGH": ps.get("P2_HIGH", 0),
                "P3_MEDIUM": ps.get("P3_MEDIUM", 0),
                "P4_LOW": ps.get("P4_LOW", 0),
            },
            "top_opportunities": [
                {
                    "keyword": o.get("keyword", "?"),
                    "gap_score": o.get("gap_score", 0),
                    "priority": o.get("priority", "?"),
                    "intent": o.get("intent", "?"),
                    "mismatch": o.get("mismatch_type", "?"),
                }
                for o in top_opps[:5]
            ],
        }
        if len(gres) == 0:
            outdated["gap_report"] = "No scored keywords — needs SERP data with classification"
    else:
        status["gaps"] = {"total_scored": 0, "priority_summary": {}, "top_opportunities": []}

    # ─── comparison_report.json (site health) ───
    cr_file = LATEST_DIR / "comparison_report.json"
    cr_data = safe_read_json(cr_file)
    if cr_data and isinstance(cr_data, dict):
        overall = cr_data.get("overall", {})
        domain = cr_data.get("domain_authority", {})
        recs = cr_data.get("recommendations", [])
        status["site"] = {
            "googlebot_score": overall.get("score", 0),
            "verdict": overall.get("verdict", "UNKNOWN"),
            "sandbox_stage": domain.get("sandbox_stage", "UNKNOWN"),
            "domain_age_months": domain.get("domain_age_months", 0),
            "recommendations": recs[:5],
        }
        # Rendered data (from separate file, but can merge)
        rr_file = LATEST_DIR / "rendered_report.json"
        rr_data = safe_read_json(rr_file)
        if rr_data and isinstance(rr_data, dict):
            rendered = rr_data.get("rendered", {})
            status["site"]["rendered_word_count"] = rendered.get("word_count", 0)
            js_gap = rr_data.get("js_gap", {})
            status["site"]["render_efficiency"] = js_gap.get("render_efficiency_pct", 0)

        # JSON-LD issues (from separate file)
        jl_file = LATEST_DIR / "jsonld_validation.json"
        jl_data = safe_read_json(jl_file)
        if jl_data and isinstance(jl_data, dict):
            issues = jl_data.get("issues", [])
            critical = [i for i in issues if i.get("severity") == "CRITICAL"]
            status["site"]["jsonld_issues"] = len(issues)
            status["site"]["jsonld_critical"] = len(critical)
            if issues:
                status["site"]["jsonld_top_issue"] = issues[0].get("message", "")[:100]
    else:
        status["site"] = {
            "googlebot_score": 0,
            "verdict": "NO_DATA",
            "sandbox_stage": "UNKNOWN",
            "domain_age_months": 0,
            "recommendations": [],
        }

    # ─── Competitors summary ───
    if COMPETITORS_DIR.exists():
        batch_file = COMPETITORS_DIR / "batch_summary.json"
        batch = safe_read_json(batch_file)
        if batch and isinstance(batch, dict):
            comps = batch.get("results", [])
            status["competitors"] = {
                "total": len(comps),
                "with_spa": sum(1 for c in comps if c.get("has_spa_shell", False)),
                "with_jsonld": sum(1 for c in comps if c.get("has_json_ld", False)),
            }
            if comps:
                # Sort by body words descending
                sorted_comps = sorted(comps, key=lambda x: x.get("body_words", 0), reverse=True)
                status["competitors"]["top_by_content"] = [
                    {"domain": c.get("domain", "?")[:30], "body_words": c.get("body_words", 0)}
                    for c in sorted_comps[:3]
                ]
        else:
            # Count individual files
            gb_files = list(COMPETITORS_DIR.glob("*_googlebot.json"))
            status["competitors"] = {
                "total": len(gb_files),
                "note": "No batch_summary.json, using file count",
            }
    else:
        status["competitors"] = {"total": 0}

    # ─── GEO summary ───
    geo_file = LATEST_DIR / "geo_self_check.json"
    geo_data = safe_read_json(geo_file)
    if geo_data and isinstance(geo_data, dict):
        geo_score_raw = geo_data.get("geo_score", {})
        # Handle both dict format {"value": 67} and int format 34
        if isinstance(geo_score_raw, dict):
            geo_score = geo_score_raw.get("value", 0)
        else:
            geo_score = geo_score_raw if isinstance(geo_score_raw, (int, float)) else 0
        gaps = geo_data.get("gaps", [])
        status["geo"] = {
            "self_score": geo_score,
            "gaps_critical": sum(1 for g in gaps if g.get("priority") == "CRITICAL"),
            "gaps_high": sum(1 for g in gaps if g.get("priority") == "HIGH"),
            "gaps_medium": sum(1 for g in gaps if g.get("priority") == "MEDIUM"),
            "gaps_low": sum(1 for g in gaps if g.get("priority") == "LOW"),
            "top_gap": gaps[0].get("signal", "") if gaps else "",
        }

    comp_geo_file = LATEST_DIR / "competitors_with_geo.json"
    comp_geo_data = safe_read_json(comp_geo_file)
    if comp_geo_data and isinstance(comp_geo_data, dict):
        results = [r for r in comp_geo_data.get("results", []) if r.get("status") == "success"]
        scores = [r.get("geo_score", 0) for r in results if r.get("geo_score") is not None]
        if scores:
            if "geo" not in status:
                status["geo"] = {}
            status["geo"]["competitors_analyzed"] = len(results)
            status["geo"]["market_avg_geo"] = round(sum(scores) / len(scores), 1)
            status["geo"]["market_max_geo"] = max(scores)

    # ─── Outdated data flags ───
    if outdated:
        status["outdated"] = outdated
    else:
        status["outdated"] = {}

    # ─── Summary line ───
    s = status["site"]
    k = status["keywords"]
    g = status["gaps"]
    summary_parts = [
        f"site={s.get('verdict','?')} ({s.get('googlebot_score',0)}/100)",
        f"sandbox={s.get('sandbox_stage','?')}",
        f"keywords={k.get('total',0)}",
        f"gaps:P1={g.get('priority_summary',{}).get('P1_CRITICAL',0)}",
    ]

    # Add GEO to summary line
    geo_part = status.get("geo", {})
    summary_parts.append(f"geo_self={geo_part.get('self_score','?')}")
    summary_parts.append(f"geo_market={geo_part.get('market_avg_geo','?')}")

    status["summary"] = " | ".join(summary_parts)

    if outdated:
        status["summary"] += f" | ⚠️ {len(outdated)} outdated: {', '.join(outdated.keys())}"

    # ─── Write output ───
    output = json.dumps(status, ensure_ascii=False, indent=2)
    dest = LATEST_DIR / "status.json"
    dest.write_text(output, encoding="utf-8")

    print(output)
    if verbose:
        print(f"\n[verbose] Status written to {dest}", file=sys.stderr)
        print(f"[verbose] Summary: {status['summary']}", file=sys.stderr)

    # ─── Supabase snapshot (optional, requires --run-id) ───
    if args.run_id:
        try:
            supabase = get_supabase()
            upsert_status(supabase, args.run_id, status["summary"], status)
            if verbose:
                print(f"[verbose] Snapshot saved to status_snapshots (run_id={args.run_id})", file=sys.stderr)
        except Exception as e:
            print(f"[warning] Failed to save to status_snapshots: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
