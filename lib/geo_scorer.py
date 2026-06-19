#!/usr/bin/env python3
"""
geo_scorer.py — Unified GEO scoring library.

Single source of truth for GEO readiness scoring.
Measures ALL sites (us AND competitors) from RENDERED HTML
using IDENTICAL criteria — no more source code vs rendered mismatch.

Usage (shared):
    from lib.geo_scorer import score_geo_readiness, GEO_SIGNALS

Key principle:
    - Input: rendered HTML (what a crawler sees)
    - Output: GEO score 0-100 with per-signal breakdown
    - Same method for aionai.gr and all competitors
"""

import re
from typing import Optional


# ─── GEO Signal definitions ──────────────────────────────────────────────
# Each signal: (name, weight, description)
# Weight = contribution to max score (total = 100)
# These weights reflect what matters MOST for LLM/AI engine extraction

GEO_SIGNALS = [
    ("has_faq_schema", 15, "FAQPage JSON-LD schema present in rendered HTML"),
    ("has_faq_text", 10, "FAQ text visible in rendered HTML (not just schema)"),
    ("has_org_schema", 5, "Organization/ProfessionalService schema"),
    ("has_tldr", 10, "TL;DR / summary block visible in HTML"),
    ("is_answer_first", 10, "First paragraph after H1 is definitive answer"),
    ("word_count_ge1500", 10, "≥1500 words of visible text content"),
    ("has_lists_ge2", 8, "≥2 <ul>/<ol> lists in content"),
    ("has_tables", 5, "≥1 <table> for data"),
    ("has_citations_ge2", 8, "≥2 citation-type outbound links"),
    ("has_author_name", 9, "Author byline or meta author tag"),
    ("has_statistics", 5, "Statistical claims (%, numbers, etc.)"),
    ("has_llms_txt", 5, "llms.txt file exists at domain"),
]

MAX_GEO_SCORE = sum(w for _, w, _ in GEO_SIGNALS)  # = 100


def extract_signals_from_html(html: str, domain: str = "") -> dict:
    """
    Extract ALL GEO signals from rendered HTML.
    Same function for us and competitors — the ONLY source of GEO data.
    
    Args:
        html: Full rendered HTML (what a no-JS crawler or curl would see)
        domain: Optional domain for llms.txt check (only works for us)
    
    Returns:
        dict of signal_name -> bool/value
    """
    signals = {}
    
    # ── Signal 1: FAQPage schema ──
    signals["has_faq_schema"] = bool(re.search(
        r'"@type"\s*:\s*"FAQPage"', html, re.IGNORECASE
    ))
    
    # ── Signal 2: FAQ text visible ──
    faq_keywords = [
        "Συχνές Ερωτήσεις", "Frequently Asked Questions", "FAQ",
        "Από πού ξεκινάμε", "Πόσο κοστίζει", "Πόσο γρήγορα",
        "Είναι τα δεδομένα", "Τι είδους επιχειρήσεις",
    ]
    # Check if FAQ keywords appear in visible text (not JSON-LD)
    # Remove script/style blocks first
    body = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL)
    body_text = re.sub(r'<[^>]+>', ' ', body)
    body_text = re.sub(r'\s+', ' ', body_text)
    
    signals["has_faq_text"] = sum(1 for kw in faq_keywords if kw.lower() in body_text.lower()) >= 2
    
    # ── Signal 3: Organization schema ──
    signals["has_org_schema"] = bool(re.search(
        r'"@type"\s*:\s*"(Organization|ProfessionalService|LocalBusiness)"',
        html, re.IGNORECASE
    ))
    
    # ── Signal 4: TL;DR / summary ──
    tldr_patterns = [
        r"TL;DR", r"tl;dr", r"Summary", r"Overview",
        r"συνοπτικά", r"περίληψη", r"με λίγα λόγια",
        r"In short", r"Key takeaway",
    ]
    signals["has_tldr"] = any(
        re.search(p, body_text) for p in tldr_patterns
    )
    
    # ── Signal 5: Answer-first structure ──
    # First substantial paragraph after H1
    h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    if h1_match:
        after_h1 = html[h1_match.end():]
        # Find first <p> after H1 with reasonable length
        p_matches = re.findall(r'<p[^>]*>(.*?)</p>', after_h1, re.DOTALL)
        first_p = ""
        for p in p_matches:
            p_text = re.sub(r'<[^>]+>', '', p).strip()
            if len(p_text) > 30:
                first_p = p_text
                break
        # Check if it starts with definition pattern
        def_patterns = [
            r"^(Είναι|Είναι ένα|Είναι μια|Ορίζεται)",
            r"^(Refers to|Is a|Is an|Means|Defined as)",
            r"^(Τι είναι|What is|What are)",
            r"(ορίζεται ως|αναφέρεται σε)",
        ]
        signals["is_answer_first"] = any(
            re.search(p, first_p, re.IGNORECASE) for p in def_patterns
        ) if first_p else False
    else:
        signals["is_answer_first"] = False
    
    # ── Signal 6: Word count ──
    words = len(body_text.split())
    signals["word_count_ge1500"] = words >= 1500
    signals["word_count"] = words  # raw value for reference
    
    # ── Signal 7: Lists ──
    ul_count = len(re.findall(r'<ul\b', html))
    ol_count = len(re.findall(r'<ol\b', html))
    signals["has_lists_ge2"] = (ul_count + ol_count) >= 2
    signals["ul_count"] = ul_count
    signals["ol_count"] = ol_count
    
    # ── Signal 8: Tables ──
    table_count = len(re.findall(r'<table\b', html))
    signals["has_tables"] = table_count > 0
    signals["table_count"] = table_count
    
    # ── Signal 9: Citations/outbound links ──
    # Count external hrefs (excluding same-domain, anchors, mailto)
    external_links = re.findall(
        r'href=["\']https?://(?:[^"\']*\.)?([^"\']+)["\']', html
    )
    # Count citation keywords in text
    citation_kw = re.findall(
        r'(πηγή|source|σύμφωνα|μελέτη|στοιχεία|έρευνα|research|study|report|survey)',
        body_text, re.IGNORECASE
    )
    signals["has_citations_ge2"] = len(citation_kw) >= 2
    signals["external_link_count"] = len(external_links)
    signals["citation_keyword_count"] = len(citation_kw)
    
    # ── Signal 10: Author ──
    has_author_meta = bool(re.search(
        r'<meta\s+name=["\']author["\'][^>]*content=["\']([^"\']+)["\']',
        html, re.IGNORECASE
    ))
    has_byline = bool(re.search(
        r'(by|από|συγγραφέας)\s+[A-ZΆ-Ϋ][a-zά-ώ]+', body_text[:500]
    ))
    has_author_schema = bool(re.search(
        r'"author"\s*:\s*\{[^}]*"name"\s*:', html, re.DOTALL
    ))
    signals["has_author_name"] = has_author_meta or has_byline or has_author_schema
    
    # ── Signal 11: Statistics ──
    stat_pattern = re.compile(
        r'\d+\.?\d*\s*%|'                        # 50%, 12.5%
        r'\d+\s*(percent|ποσοστό)|'
        r'(πάνω από|περισσότεροι από|less than|more than|over)\s*\d+|'
        r'\d+\s*(out of|από τους|στους|στα)|'
        r'(1 in|1 στα|ένας στους)', re.IGNORECASE
    )
    stats = stat_pattern.findall(body_text)
    signals["has_statistics"] = len(stats) >= 1
    signals["stat_count"] = len(stats)
    
    # ── Signal 12: llms.txt ──
    # Can only check for our own domain (fetched separately)
    signals["has_llms_txt"] = False  # Set externally if needed
    
    return signals


def score_geo_readiness(signals: dict) -> dict:
    """
    Calculate unified GEO readiness score from extracted signals.
    
    Returns:
        {
            "score": 0-100,
            "level": "CRITICAL"|"POOR"|"MODERATE"|"GOOD"|"EXCELLENT",
            "signals": {signal_name: {score, weight, max}},
            "gaps": [{name, detail, priority}],
        }
    """
    result = {
        "signals": {},
        "gaps": [],
        "score": 0,
        "max_score": MAX_GEO_SCORE,
    }
    
    for name, weight, desc in GEO_SIGNALS:
        # Check if signal is present (bool or truthy value)
        value = signals.get(name, False)
        if value:
            result["signals"][name] = {
                "score": weight,
                "weight": weight,
                "max": weight,
                "status": "✅",
                "detail": desc,
            }
            result["score"] += weight
        else:
            result["signals"][name] = {
                "score": 0,
                "weight": weight,
                "max": weight,
                "status": "❌",
                "detail": desc,
            }
            priority = "HIGH" if weight >= 10 else ("MEDIUM" if weight >= 6 else "LOW")
            result["gaps"].append({
                "signal": name,
                "priority": priority,
                "weight": weight,
                "detail": desc,
            })
    
    # Calculate percentage
    score_pct = round((result["score"] / MAX_GEO_SCORE) * 100)
    result["score"] = score_pct
    
    # Level
    if score_pct >= 80:
        result["level"] = "EXCELLENT"
    elif score_pct >= 60:
        result["level"] = "GOOD"
    elif score_pct >= 40:
        result["level"] = "MODERATE"
    elif score_pct >= 20:
        result["level"] = "POOR"
    else:
        result["level"] = "CRITICAL"
    
    # Sort gaps by priority
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    result["gaps"].sort(key=lambda g: (priority_order.get(g["priority"], 99), -g["weight"]))
    
    return result


def format_score_report(scored: dict, domain: str = "") -> str:
    """Human-readable score report."""
    lines = [
        f"GEO Score für {domain or 'site'}: {scored['score']}/100 ({scored['level']})",
        f"{'='*50}",
    ]
    for name, s in scored["signals"].items():
        bar = s["status"]
        lines.append(f"  {bar} {name}: {s['score']}/{s['max']}")
    if scored["gaps"]:
        lines.append(f"\nGaps ({len(scored['gaps'])}):")
        for g in scored["gaps"]:
            lines.append(f"  [{g['priority']}] {g['signal']} ({g['weight']}pts)")
    return "\n".join(lines)
