#!/usr/bin/env python3

"""
comparison_report.py — Αναφορά σύγκρισης aionAI vs competitors.

Χρησιμοποιεί ΜΟΝΟ Googlebot views (raw + rendered) για σύγκριση —
όχι rendered word counts από source code.

Λειτουργίες:
  1. --self: Ανάλυση μόνο του δικού μας site (Googlebot health + JSON-LD + keyword coverage)
  2. --competitors: Σύγκριση με competitors (όταν έχουμε Googlebot data τους)

Pipeline:
    # Self analysis (no competitors needed)
    python comparison_report.py --self \\
        --site-googlebot data/gap_report.json \\
        --site-rendered data/rendered_report.json \\
        --jsonld-validation data/jsonld_validation.json \\
        --keywords data/keywords_with_intent.json \\
        --output data/comparison_report.json

    # With competitors (requires competitor Googlebot data)
    python comparison_report.py \\
        --site-googlebot data/gap_report.json \\
        --site-rendered data/rendered_report.json \\
        --jsonld-validation data/jsonld_validation.json \\
        --keywords data/keywords_with_intent.json \\
        --competitors data/competitor_googlebot/ \\
        --output data/comparison_report.json

Requirements:
    stdlib only
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


def load_json_or_exit(path: str, label: str = "") -> dict:
    """Load JSON file or print error and exit."""
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except FileNotFoundError:
        print(f"Error: {label or 'File'} not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: {label or 'File'} {path} is not valid JSON: {e}",
              file=sys.stderr)
        sys.exit(1)


# ─── Scoring helpers ─────────────────────────────────────────────────────

def score_googlebot_health(googlebot_data: dict) -> dict:
    """Score our Googlebot visibility from --googlebot output.

    Returns score 0-100, confidence, and findings.
    """
    confidence = googlebot_data.get("confidence", {"level": 50, "label": "UNKNOWN"})
    view = googlebot_data.get("googlebot_view", {})
    body = view.get("body", {})
    assessment = view.get("assessment", {})
    gaps = googlebot_data.get("gaps", [])

    word_count = body.get("word_count", 0)
    has_app_root = body.get("has_app_root", False)
    needs_js = assessment.get("needs_javascript", False)

    score = 100

    # Penalties
    if word_count == 0:
        score -= 40  # No visible content
    elif word_count < 200:
        score -= 20
    elif word_count < 500:
        score -= 10

    if has_app_root:
        score -= 20  # SPA shell detected

    if needs_js:
        score -= 20  # Relies on JS

    # Deductions from gap analysis
    for g in gaps:
        sev = g.get("severity", "LOW")
        if sev == "CRITICAL":
            score -= 10
        elif sev == "HIGH":
            score -= 5

    score = max(0, min(100, score))

    verdict = "CRITICAL" if score < 30 else \
              "POOR" if score < 50 else \
              "FAIR" if score < 70 else \
              "GOOD" if score < 90 else "EXCELLENT"

    return {
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "raw_word_count": word_count,
        "has_spa_shell": has_app_root,
        "needs_javascript": needs_js,
        "gaps_found": len(gaps),
        "summary": (
            f"Googlebot raw visibility score: {score}/100 ({verdict}). "
            f"{word_count} words visible, SPA shell={has_app_root}, "
            f"needs JS={needs_js}."
        ),
    }


def analyze_rendered_gap(rendered_data: Optional[dict]) -> dict:
    """Analyze the JS rendering gap from --googlebot-rendered."""
    if not rendered_data:
        return {"has_data": False}

    confidence = rendered_data.get("confidence", {"level": 50, "label": "UNKNOWN"})
    js_gap = rendered_data.get("js_gap", {})
    rendered = rendered_data.get("rendered", {})
    raw_comp = rendered_data.get("raw_comparison", {})

    raw_words = js_gap.get("raw_words", 0)
    rendered_words = js_gap.get("rendered_words", 0)
    source_words = js_gap.get("source_words", 0)
    efficiency = js_gap.get("render_efficiency_pct", 0)
    timed_out = js_gap.get("timed_out", False)

    # Score: how well does the Angular app render in 5 seconds?
    if timed_out:
        render_score = 30
        verdict = "POOR"
    elif rendered_words >= source_words * 0.8:
        render_score = 90
        verdict = "GOOD"
    elif rendered_words >= source_words * 0.5:
        render_score = 65
        verdict = "FAIR"
    elif rendered_words > 0:
        render_score = 40
        verdict = "POOR"
    else:
        render_score = 10
        verdict = "CRITICAL"

    return {
        "has_data": True,
        "render_score": render_score,
        "verdict": verdict,
        "confidence": confidence,
        "raw_words": raw_words,
        "rendered_words": rendered_words,
        "source_words": source_words,
        "efficiency_pct": efficiency,
        "timed_out": timed_out,
        "improvement": rendered_words - raw_words,
        "summary": (
            f"JS render score: {render_score}/100 ({verdict}). "
            f"Raw: {raw_words} words → Rendered: {rendered_words} words "
            f"(+{rendered_words - raw_words}, {efficiency}% of source)."
        ),
    }


def analyze_jsonld_health(jsonld_data: Optional[dict]) -> dict:
    """Analyze JSON-LD validation results."""
    if not jsonld_data:
        return {"has_data": False}

    confidence = jsonld_data.get("confidence", {"level": 50, "label": "UNKNOWN"})
    issues = jsonld_data.get("issues", [])
    has_json_ld = jsonld_data.get("has_json_ld", False)

    critical = [i for i in issues if i.get("severity") == "CRITICAL"]
    high = [i for i in issues if i.get("severity") == "HIGH"]
    medium = [i for i in issues if i.get("severity") == "MEDIUM"]
    low = [i for i in issues if i.get("severity") == "LOW"]

    score = 100
    score -= len(critical) * 25
    score -= len(high) * 15
    score -= len(medium) * 8
    score -= len(low) * 3
    score = max(0, min(100, score))

    if not has_json_ld:
        score = 0

    verdict = "CRITICAL" if score < 30 else \
              "POOR" if score < 50 else \
              "FAIR" if score < 70 else \
              "GOOD" if score < 90 else "EXCELLENT"

    return {
        "has_data": True,
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "has_json_ld": has_json_ld,
        "total_issues": len(issues),
        "by_severity": {
            "CRITICAL": len(critical),
            "HIGH": len(high),
            "MEDIUM": len(medium),
            "LOW": len(low),
        },
        "issues": issues,
        "summary": (
            f"JSON-LD health: {score}/100 ({verdict}). "
            f"{len(issues)} issues found "
            f"({len(critical)} critical, {len(high)} high, "
            f"{len(medium)} medium, {len(low)} low)."
        ),
    }


def analyze_keyword_coverage(keywords_data: Optional[dict]) -> dict:
    """Analyze keyword coverage by intent."""
    if not keywords_data:
        return {"has_data": False}

    keywords = keywords_data.get("keywords", [])
    breakdown = keywords_data.get("intent_breakdown", {})

    # Count by intent
    by_intent = {}
    for kw in keywords:
        intent = kw.get("intent", "INFO")
        by_intent.setdefault(intent, []).append(kw["query"])

    return {
        "has_data": True,
        "total_keywords": len(keywords),
        "intent_breakdown": breakdown,
        "keywords_by_intent": {
            intent: len(kws)
            for intent, kws in by_intent.items()
        },
        "samples": {
            intent: kws[:5]
            for intent, kws in by_intent.items()
        },
        "recommendations": _keyword_recommendations(breakdown),
    }


def _keyword_recommendations(breakdown: dict) -> list[str]:
    """Generate content recommendations based on keyword intent distribution."""
    recs = []
    info = breakdown.get("INFO", 0)
    commercial = breakdown.get("COMMERCIAL", 0)
    transactional = breakdown.get("TRANSACTIONAL", 0)

    if info > commercial + transactional:
        recs.append(
            f"Prioritize blog posts / guides ({info} informational keywords). "
            f"These attract top-of-funnel traffic."
        )
    if commercial > 0:
        recs.append(
            f"Create service pages for {commercial} commercial keywords. "
            f"These capture users who are evaluating solutions."
        )
    if transactional > 0:
        recs.append(
            f"Add pricing / demo pages for {transactional} transactional "
            f"keywords. These convert high-intent visitors."
        )
    return recs


# ─── Domain Authority (dynamic) ───────────────────────────────────────────

def analyze_domain_authority(googlebot_data: dict) -> dict:
    """Calculate domain age from foundingDate in JSON-LD.

    Provides context for interpreting SEO scores — new domains
    face a sandbox effect regardless of content quality.
    """
    today = datetime.now()

    # Extract foundingDate from JSON-LD
    view = googlebot_data.get("googlebot_view", {})
    json_ld = view.get("json_ld", {})
    graph = json_ld.get("@graph", [])

    founding_date_str = ""
    for entity in graph:
        fd = entity.get("foundingDate", "")
        if fd:
            founding_date_str = fd
            break

    # Parse founding date
    founding_year = None
    founding_month = None
    if founding_date_str:
        try:
            founding_year = int(founding_date_str[:4])
            if len(founding_date_str) >= 7:
                founding_month = int(founding_date_str[5:7])
        except (ValueError, IndexError):
            pass

    # Calculate age in months
    if founding_year:
        if founding_month:
            months_old = (today.year - founding_year) * 12 + (today.month - founding_month)
        else:
            months_old = (today.year - founding_year) * 12 + today.month
    else:
        months_old = 0

    months_old = max(0, months_old)

    # Sandbox estimate
    if months_old < 3:
        sandbox_stage = "EARLY_SANDBOX"
        sandbox_expectation = "0-5 months before meaningful rankings"
    elif months_old < 6:
        sandbox_stage = "MID_SANDBOX"
        sandbox_expectation = "2-6 more months before steady rankings"
    elif months_old < 12:
        sandbox_stage = "LATE_SANDBOX"
        sandbox_expectation = "Rankings should start appearing. If not, check link profile."
    else:
        sandbox_stage = "ESTABLISHED"
        sandbox_expectation = "Domain is established. Low rankings = content/tech issues."

    return {
        "founding_date": founding_date_str or "unknown",
        "domain_age_months": months_old,
        "sandbox_stage": sandbox_stage,
        "sandbox_expectation": sandbox_expectation,
        "context": (
            f"aionAI domain is {months_old} month(s) old (founded {founding_date_str or '?'}). "
            f"Stage: {sandbox_stage}. "
            f"Expected: {sandbox_expectation}. "
            f"Content improvements compound over time — early SEO investment will pay off "
            f"as the domain ages."
        ),
    }


# ─── Main report generation ──────────────────────────────────────────────

def generate_report(
    googlebot_data: dict,
    rendered_data: Optional[dict] = None,
    jsonld_data: Optional[dict] = None,
    keywords_data: Optional[dict] = None,
    competitor_dir: Optional[str] = None,
) -> dict:
    """Generate comprehensive comparison report."""
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "comparison_report_v2",
    }

    # A. Googlebot Raw Health
    report["googlebot_raw"] = score_googlebot_health(googlebot_data)

    # B. Googlebot Rendered Health
    report["googlebot_rendered"] = analyze_rendered_gap(rendered_data)

    # C. JSON-LD Health
    report["jsonld_health"] = analyze_jsonld_health(jsonld_data)

    # D. Keyword Coverage
    report["keyword_coverage"] = analyze_keyword_coverage(keywords_data)

    # D+. Domain Authority Context
    report["domain_authority"] = analyze_domain_authority(googlebot_data)

    # E. Overall score — weighted by confidence
    scored_components = []

    raw = report["googlebot_raw"]
    scored_components.append({
        "name": "Googlebot raw",
        "score": raw["score"],
        "confidence": raw["confidence"]["level"],
    })

    if rendered_data:
        rend = report["googlebot_rendered"]
        scored_components.append({
            "name": "JS render",
            "score": rend["render_score"],
            "confidence": rend["confidence"]["level"],
        })

    if jsonld_data:
        j = report["jsonld_health"]
        scored_components.append({
            "name": "JSON-LD",
            "score": j["score"],
            "confidence": j["confidence"]["level"],
        })

    # Weighted average: high confidence counts more
    total_weight = sum(c["confidence"] for c in scored_components)
    weighted_score = sum(
        c["score"] * c["confidence"] for c in scored_components
    ) / total_weight if total_weight else 0

    overall = round(weighted_score)

    verdict = "CRITICAL" if overall < 30 else \
              "POOR" if overall < 50 else \
              "FAIR" if overall < 70 else \
              "GOOD" if overall < 90 else "EXCELLENT"

    report["overall"] = {
        "score": overall,
        "verdict": verdict,
        "weighted": True,
        "components": scored_components,
    }

    # F. Recommendations
    recs = []

    if report["googlebot_raw"]["score"] < 50:
        recs.append(
            "CRITICAL: Implement SSR (Angular Universal) or prerendering. "
            "Googlebot sees 0 body content."
        )

    if jsonld_data and report["jsonld_health"]["score"] < 70:
        high_issues = [
            i for i in report["jsonld_health"].get("issues", [])
            if i.get("severity") in ("CRITICAL", "HIGH")
        ]
        for issue in high_issues:
            recs.append(f"JSON-LD: {issue['message']}")

    if rendered_data and report["googlebot_rendered"]["verdict"] in ("POOR", "CRITICAL"):
        recs.append(
            "Angular app failed to render within 5s JS budget. "
            "Consider lazy loading, smaller bundle, or SSR."
        )

    report["recommendations"] = recs

    # G. Competitor comparison (if data available)
    if competitor_dir:
        report["competitors"] = analyze_competitors(competitor_dir)

    return report


def analyze_competitors(competitor_dir: str) -> list[dict]:
    """Analyze competitor Googlebot data from a directory of JSON files."""
    comp_dir = Path(competitor_dir)
    if not comp_dir.is_dir():
        print(f"Warning: Competitor directory not found: {competitor_dir}",
              file=sys.stderr)
        return []

    results = []
    for json_file in sorted(comp_dir.glob("*_googlebot.json")):
        try:
            data = json.loads(json_file.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        name = json_file.stem

        # Support both --googlebot and --googlebot-rendered formats
        view = data.get("googlebot_view", {})
        body = view.get("body", {})
        assessment = view.get("assessment", {})
        meta = view.get("meta", {})

        # For rendered data
        rendered = data.get("rendered", {})
        js_gap = data.get("js_gap", {})

        word_count = body.get("word_count", 0)
        has_jsonld = assessment.get("json_ld_available", False)

        results.append({
            "domain": name,
            "title": meta.get("title", "")[:80],
            "confidence": data.get("confidence", {"level": 90, "label": "HIGH"}),
            "raw_word_count": word_count,
            "has_spa_shell": body.get("has_app_root", True),
            "has_json_ld": has_jsonld,
            "needs_js": assessment.get("needs_javascript", True),
            "rendered_word_count": rendered.get("word_count", 0),
            "render_efficiency": js_gap.get("render_efficiency_pct", 0),
        })


# ─── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="comparison_report.py — aionAI vs competitor comparison "
                    "(Googlebot views only).",
    )
    parser.add_argument("--self", action="store_true",
                        help="Self-analysis mode (no competitors needed)")
    parser.add_argument("--site-googlebot", required=True,
                        help="aionAI --googlebot JSON output")
    parser.add_argument("--site-rendered", default=None,
                        help="aionAI --googlebot-rendered JSON (optional)")
    parser.add_argument("--jsonld-validation", default=None,
                        help="aionAI --validate-jsonld JSON (optional)")
    parser.add_argument("--keywords", default=None,
                        help="keyword_discovery.py output with intent (optional)")
    parser.add_argument("--competitors", default=None,
                        help="Directory of competitor _googlebot.json files (optional)")
    parser.add_argument("--output", default=None, help="Output JSON file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    googlebot = load_json_or_exit(args.site_googlebot, "Googlebot data")
    rendered = load_json_or_exit(args.site_rendered, "Rendered data") if args.site_rendered else None
    jsonld = load_json_or_exit(args.jsonld_validation, "JSON-LD") if args.jsonld_validation else None
    keywords = load_json_or_exit(args.keywords, "Keywords") if args.keywords else None

    report = generate_report(googlebot, rendered, jsonld, keywords, args.competitors)

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())

