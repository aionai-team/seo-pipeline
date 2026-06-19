#!/usr/bin/env python3

"""
competitor_scraper.py — Αναλύει competitor sites από URLs (Phase B).

Παίρνει τα URLs από serp_scraper.py (Phase A), μπαίνει σε κάθε site
με requests (όχι browser — γρήγορο, no CAPTCHA), και βγάζει:
  - title, meta description, headings (H1/H2/H3)
  - word count, JSON-LD schema, FAQ
  - visible paragraphs

Usage:
    python serp_scraper.py --input ranked.json --output urls.json
    python competitor_scraper.py --input urls.json --output competitor_data.json
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
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from lib import url_utils
from lib.supabase_client import get_supabase


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)

REQUEST_DELAY = 1.0  # seconds between competitor site requests


def fetch_page(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch a page's HTML. Returns None on failure."""
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


def extract_meta(html: str) -> dict:
    """Extract title and meta tags."""
    meta = {}
    m = re.search(r"<title>([^<]+)</title>", html, re.DOTALL)
    if m:
        meta["title"] = m.group(1).strip()
    for match in re.finditer(
        r'<meta\s+(?:name|property)="([^"]+)"[^>]*content="([^"]+)"', html
    ):
        meta[match.group(1)] = match.group(2)
    return meta


def extract_headings(html: str) -> dict:
    """Extract H1, H2, H3 tags."""
    headings = {"h1": [], "h2": [], "h3": []}
    for level in ["h1", "h2", "h3"]:
        for match in re.finditer(f"<{level}[^>]*>(.*?)</{level}>", html, re.DOTALL):
            text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            if text and len(text) > 3:
                headings[level].append(text)
    return headings


def extract_text(html: str) -> str:
    """Extract readable text, stripping HTML tags."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_json_ld(html: str) -> list:
    """Extract JSON-LD schema blocks."""
    schemas = []
    for match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        try:
            data = json.loads(match.group(1))
            schemas.append(data)
        except json.JSONDecodeError:
            pass
    return schemas


def extract_faq(html: str) -> list[dict]:
    """Extract FAQ-like Q&A patterns from the page."""
    faqs = []
    # Try JSON-LD FAQPage first
    for schema in extract_json_ld(html):
        if isinstance(schema, dict):
            main_entity = schema.get("mainEntity", [])
            if isinstance(main_entity, list):
                for item in main_entity:
                    if isinstance(item, dict) and item.get("@type") == "Question":
                        q = item.get("name", "")
                        a = ""
                        answer = item.get("acceptedAnswer", {})
                        if isinstance(answer, dict):
                            a = answer.get("text", "")
                        if q:
                            faqs.append({"question": q, "answer": a[:200]})
    return faqs


def analyze_page(url: str, html: str) -> dict:
    """Extract all relevant data from a competitor page."""
    meta = extract_meta(html)
    headings = extract_headings(html)
    text = extract_text(html)
    word_count = len(text.split())
    domain = urlparse(url).netloc
    faqs = extract_faq(html)
    schemas = extract_json_ld(html)

    return {
        "url": url,
        "domain": domain,
        "meta_title": meta.get("title", ""),
        "meta_description": meta.get("description", ""),
        "word_count": word_count,
        "headings": headings,
        "h1_count": len(headings["h1"]),
        "h2_count": len(headings["h2"]),
        "h3_count": len(headings["h3"]),
        "faq_count": len(faqs),
        "faqs": faqs[:10],
        "schema_count": len(schemas),
        "has_faq_schema": any(
            isinstance(s, dict) and s.get("@type") == "FAQPage"
            for s in schemas[:5]
        ),
        "has_organization_schema": any(
            isinstance(s, dict) and s.get("@type") in (
                "ProfessionalService", "Organization", "LocalBusiness"
            )
            for s in schemas[:5]
        ),
    }
    # NOTE: GEO signals are added by the calling code (main loop)
    # after analyze_page returns, because analyze_page returns early
    # for failed fetches. The main loop adds them to the result.


# ─── GEO Extraction Functions ─────────────────────────────────────────

def extract_geo_tldr(html: str) -> dict:
    """Detect TL;DR / summary blocks near the top of the page."""
    tldr_keywords = re.compile(
        r"(TL;DR|tl;dr|summary|συνοπτικά|με λίγα λόγια|περίληψη|key takeaways)", re.IGNORECASE
    )
    text = extract_text(html)
    first_chars = text[:800]
    has_in_text = bool(tldr_keywords.search(first_chars))
    class_pattern = re.compile(
        r'class=["\'][^"\']*(?:summary|tldr|takeaway|key-points)[^"\']*["\']', re.IGNORECASE
    )
    has_class = bool(class_pattern.search(html))
    return {
        "has_tldr": has_in_text or has_class,
        "in_text_snippet": tldr_keywords.search(first_chars).group(0) if has_in_text else "",
    }


def extract_geo_faq_text(html: str) -> dict:
    """Detect FAQ sections in visible HTML (not just JSON-LD schema)."""
    text = extract_text(html)
    has_faq_section = False
    faq_item_count = 0
    faq_headings = []
    faq_section_re = re.compile(
        r'<(?:section|div)[^>]*class=["\'][^"\']*(?:faq|accordion|questions|συχνές|ερωτήσεις)[^"\']*["\']',
        re.IGNORECASE,
    )
    if faq_section_re.search(html):
        has_faq_section = True
    for h2 in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL):
        h2_clean = re.sub(r"<[^>]+>", "", h2).strip()
        if any(kw in h2_clean.lower() for kw in ["faq", "συχνές ερωτήσεις", "questions", "q&a", "ερωτήσεις"]):
            has_faq_section = True
            faq_headings.append(h2_clean)
    qa_pattern = re.compile(r"<strong[^>]*>(.*?)</strong>\s*<p[^>]*>(.*?)</p>", re.DOTALL)
    faq_item_count = len(qa_pattern.findall(html))
    return {
        "has_faq_section": has_faq_section,
        "faq_section_count": faq_item_count,
        "faq_headings": faq_headings[:5],
    }


def extract_geo_lists(html: str) -> dict:
    """Count list elements (ul/ol) for LLM-parsable structured content."""
    ul_count = len(re.findall(r"<ul\b", html))
    ol_count = len(re.findall(r"<ol\b", html))
    total_items = len(re.findall(r"<li\b", html))
    total_lists = ul_count + ol_count
    return {
        "ul_count": ul_count,
        "ol_count": ol_count,
        "total_list_items": total_items,
        "total_lists": total_lists,
        "avg_items_per_list": round(total_items / total_lists, 1) if total_lists > 0 else 0,
    }


def extract_geo_tables(html: str) -> int:
    """Count data table elements."""
    return len(re.findall(r"<table\b", html))


def extract_geo_citations(html: str) -> dict:
    """Detect outbound citation-style links and source references."""
    hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', html)
    outbound_total = len(hrefs)
    citation_keywords = re.compile(r"(πηγή|source|μελέτη|research|σύμφωνα|στοιχεία|έρευνα|study)", re.IGNORECASE)
    citation_matches = 0
    for match in re.finditer(r"<a[^>]*href=[\"\'](https?://[^\"\']+)[\"\'][^>]*>(.*?)</a>", html, re.DOTALL):
        link_text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        if citation_keywords.search(link_text):
            citation_matches += 1
    sup_citations = len(re.findall(r"<sup[^>]*>.*?</sup>", html))
    return {
        "outbound_links_total": outbound_total,
        "citation_keyword_matches": citation_matches,
        "sup_citations": sup_citations,
    }


def extract_geo_author(html: str) -> dict:
    """Detect author/credentials information."""
    has_author_meta = False
    has_byline = False
    has_author_schema = False
    author_name = ""
    meta_match = re.search(r'<meta\s+name="author"\s+content="([^"]+)"', html)
    if meta_match:
        has_author_meta = True
        author_name = meta_match.group(1)
    byline_pattern = re.compile(
        r'class=["\'][^"\']*(?:author|byline|writer|συγγραφέας)[^"\']*["\']', re.IGNORECASE
    )
    if byline_pattern.search(html):
        has_byline = True
        name_match = re.search(r'<div[^>]*class=["\'][^"\']*author[^"\']*["\'][^>]*>([^<]+)', html)
        if name_match and not author_name:
            author_name = name_match.group(1).strip()
    for match in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                graph = data.get("@graph", [data])
                for item in graph if isinstance(graph, list) else [graph]:
                    if isinstance(item, dict) and item.get("author"):
                        author_data = item["author"]
                        if isinstance(author_data, dict) and author_data.get("name"):
                            has_author_schema = True
                            if not author_name:
                                author_name = author_data["name"]
        except (json.JSONDecodeError, AttributeError):
            pass
    return {
        "has_author_meta": has_author_meta,
        "has_byline": has_byline,
        "has_author_schema": has_author_schema,
        "author_name": author_name,
    }


def extract_geo_answer_first(html: str, keyword: str = "") -> dict:
    """Detect if the first content paragraph answers the query directly."""
    h1_match = re.search(r"<h1[^>]*>.*?</h1>", html, re.DOTALL)
    if not h1_match:
        return {"is_answer_first": False, "first_paragraph": "", "confidence": "no_h1"}
    after_h1 = html[h1_match.end():]
    p_matches = re.findall(r"<p[^>]*>(.*?)</p>", after_h1, re.DOTALL)
    first_p = ""
    for p in p_matches:
        p_text = re.sub(r"<[^>]+>", "", p).strip()
        if len(p_text) > 40:
            first_p = p_text
            break
    if not first_p:
        return {"is_answer_first": False, "first_paragraph": "", "confidence": "no_content"}
    definition_patterns = [
        r"^(είναι|είναι ένα|είναι μια|είναι ο|είναι η|είναι το)",
        r"^(refers to|is a|is an|is the|means|ορίζεται)",
        r"^(τι είναι|what is|what are|what does)",
    ]
    is_answer = any(re.search(p, first_p, re.IGNORECASE) for p in definition_patterns)
    keyword_in_first_p = False
    if keyword and len(keyword) > 3:
        keyword_in_first_p = keyword.lower() in first_p.lower()
    confidence = "high" if is_answer else ("medium" if keyword_in_first_p else "low")
    return {
        "is_answer_first": is_answer or keyword_in_first_p,
        "first_paragraph": first_p[:150],
        "confidence": confidence,
    }


def extract_geo_statistics(html: str) -> dict:
    """Detect statistical claims in visible text."""
    text = extract_text(html)
    stat_pattern = re.compile(
        r"\d+\.?\d*\s*%|"
        r"\d+\s*(percent|ποσοστό)|"
        r"(πάνω από|περισσότεροι από|less than|more than|over)\s*\d+|"
        r"\d+\s*(out of|από τους|στους|στα)|"
        r"(1 in|1 στα|ένας στους)", re.IGNORECASE
    )
    matches = stat_pattern.findall(text[:3000])  # Only first 3000 chars
    stats = [m for tup in matches for m in tup if m]
    return {"stat_count": len(stats), "stats_sample": stats[:5]}


def calculate_geo_readiness(signals: dict) -> dict:
    """Calculate composite GEO readiness score (0-100) from extracted signals."""
    weights = {
        "has_faq_schema": 15, "has_org_schema": 5,
        "has_faq_section": 10, "has_tldr": 10,
        "is_answer_first": 10, "has_lists_ge2": 8,
        "has_tables": 5, "has_citations_ge2": 8,
        "has_author": 9, "has_stats": 5,
        "word_count_ge2000": 5, "has_howto_schema": 5,
        "has_product_schema": 5,
    }
    total_possible = sum(weights.values())
    score = 0
    breakdown = {}
    score += 15 if signals.get("has_faq_schema") else 0
    breakdown["has_faq_schema"] = 15 if signals.get("has_faq_schema") else 0
    score += 5 if signals.get("has_org_schema") else 0
    breakdown["has_org_schema"] = 5 if signals.get("has_org_schema") else 0
    score += 10 if signals.get("has_faq_section") else 0
    breakdown["has_faq_section"] = 10 if signals.get("has_faq_section") else 0
    score += 10 if signals.get("has_tldr") else 0
    breakdown["has_tldr"] = 10 if signals.get("has_tldr") else 0
    score += 10 if signals.get("is_answer_first") else 0
    breakdown["is_answer_first"] = 10 if signals.get("is_answer_first") else 0
    has_lists = (signals.get("ul_count", 0) + signals.get("ol_count", 0)) >= 2
    score += 8 if has_lists else 0
    breakdown["has_lists_ge2"] = 8 if has_lists else 0
    score += 5 if signals.get("table_count", 0) > 0 else 0
    breakdown["has_tables"] = 5 if signals.get("table_count", 0) > 0 else 0
    has_citations = signals.get("citation_keyword_matches", 0) >= 2
    score += 8 if has_citations else 0
    breakdown["has_citations_ge2"] = 8 if has_citations else 0
    has_author = signals.get("has_author_meta") or signals.get("has_byline") or signals.get("has_author_schema")
    score += 9 if has_author else 0
    breakdown["has_author"] = 9 if has_author else 0
    score += 5 if signals.get("stat_count", 0) > 0 else 0
    breakdown["has_stats"] = 5 if signals.get("stat_count", 0) > 0 else 0
    score += 5 if signals.get("word_count", 0) >= 2000 else 0
    breakdown["word_count_ge2000"] = 5 if signals.get("word_count", 0) >= 2000 else 0
    score += 5 if signals.get("has_howto_schema") else 0
    breakdown["has_howto_schema"] = 5 if signals.get("has_howto_schema") else 0
    score += 5 if signals.get("has_product_schema") else 0
    breakdown["has_product_schema"] = 5 if signals.get("has_product_schema") else 0
    return {
        "geo_score": round((score / total_possible) * 100),
        "signal_scores": breakdown,
        "total_possible": total_possible,
    }


def main():
    parser = argparse.ArgumentParser(
        description="competitor_scraper.py — Αναλύει competitor sites από URLs."
    )
    parser.add_argument("--input", required=True, help="URLs JSON from serp_scraper.py")
    parser.add_argument("--output", default=None, help="Output JSON")
    parser.add_argument("--no-filter", action="store_true",
                        help="Skip blocklist/classification filter (process all URLs)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--run-id", default=None, help="Pipeline run ID for Supabase insertion")
    args = parser.parse_args()

    # Read input — flexible format
    raw = json.loads(Path(args.input).read_text("utf-8"))

    # Extract all unique URLs with their keyword context
    tasks: list[dict] = []

    if isinstance(raw, dict):
        results = raw.get("results", [raw])
    else:
        results = raw if isinstance(raw, list) else [raw]

    # Load blocklist for filtering
    blocked_domains, path_patterns = url_utils.load_blocklist()

    for r in results:
        keyword = r.get("keyword", "unknown")

        # Try pre-filtered 'competitors' field first (from updated serp_scraper)
        url_entries = r.get("competitors", r.get("organic_urls", []))

        for url_entry in url_entries:
            url = url_entry.get("url", "")
            title = url_entry.get("title", "")
            if not url or not url.startswith("http"):
                continue

            # Filter with blocklist unless --no-filter
            if not args.no_filter:
                if url_utils.is_blocked(url, blocked_domains, path_patterns):
                    continue
                ctype = url_entry.get("type") or url_utils.classify_url(url, title)
                if ctype != "COMPETITOR":
                    continue

            tasks.append({
                "keyword": keyword,
                "title": title,
                "url": url,
            })

    if not tasks:
        print("Error: No URLs found in input.", file=sys.stderr)
        return 1

    # Remove duplicate URLs (keep first occurrence)
    seen = set()
    unique_tasks = []
    for t in tasks:
        if t["url"] not in seen:
            seen.add(t["url"])
            unique_tasks.append(t)

    if args.verbose:
        print(f"[verbose] Scraping {len(unique_tasks)} unique competitor URLs...", file=sys.stderr)

    scraped = []
    failed = 0

    for idx, task in enumerate(unique_tasks):
        if args.verbose:
            print(f"\n[verbose] [{idx+1}/{len(unique_tasks)}] {task['url'][:70]}", file=sys.stderr)

        html = fetch_page(task["url"])

        if html is None:
            failed += 1
            if args.verbose:
                print("  -> FAILED to fetch", file=sys.stderr)
            scraped.append({
                "keyword": task["keyword"],
                "url": task["url"],
                "title": task["title"],
                "status": "fetch_failed",
            })
            time.sleep(REQUEST_DELAY)
            continue

        analysis = analyze_page(task["url"], html)
        analysis["keyword"] = task["keyword"]
        analysis["search_title"] = task["title"]
        analysis["status"] = "success"

        # ─── GEO Extraction ──────────────────────────────────────────
        geo = {}
        geo.update(extract_geo_tldr(html))
        geo.update(extract_geo_faq_text(html))
        geo.update(extract_geo_lists(html))
        geo["table_count"] = extract_geo_tables(html)
        geo.update(extract_geo_citations(html))
        geo.update(extract_geo_author(html))
        geo.update(extract_geo_answer_first(html, keyword=task["keyword"]))
        geo.update(extract_geo_statistics(html))
        # Reuse existing schema detections
        geo["has_faq_schema"] = analysis.get("has_faq_schema", False)
        geo["has_org_schema"] = analysis.get("has_organization_schema", False)
        # Check additional schema types
        schemas = extract_json_ld(html)
        geo["has_howto_schema"] = any(
            isinstance(s, dict) and s.get("@type") == "HowTo"
            for s in schemas[:5]
        )
        geo["has_product_schema"] = any(
            isinstance(s, dict) and s.get("@type") == "Product"
            for s in schemas[:5]
        )
        geo["word_count"] = analysis.get("word_count", 0)
        geo_ready = calculate_geo_readiness(geo)

        analysis["geo_signals"] = {
            "tldr": {"has_tldr": geo.get("has_tldr", False)},
            "faq_section": {"has_faq_section": geo.get("has_faq_section", False),
                            "faq_item_count": geo.get("faq_section_count", 0)},
            "lists": {"ul_count": geo.get("ul_count", 0),
                       "ol_count": geo.get("ol_count", 0),
                       "total_items": geo.get("total_list_items", 0)},
            "tables": geo.get("table_count", 0),
            "citations": {"outbound_total": geo.get("outbound_links_total", 0),
                           "keyword_matches": geo.get("citation_keyword_matches", 0)},
            "author": {"has_meta": geo.get("has_author_meta", False),
                        "has_byline": geo.get("has_byline", False),
                        "has_schema": geo.get("has_author_schema", False),
                        "name": geo.get("author_name", "")},
            "answer_first": {"is_answer_first": geo.get("is_answer_first", False),
                              "confidence": geo.get("confidence", "")},
            "statistics": {"count": geo.get("stat_count", 0)},
            "advanced_schema": {"has_howto": geo.get("has_howto_schema", False),
                                 "has_product": geo.get("has_product_schema", False)},
        }
        analysis["geo_score"] = geo_ready["geo_score"]
        analysis["geo_score_detail"] = geo_ready

        if args.verbose:
            wc = analysis["word_count"]
            h1 = analysis["h1_count"]
            faq = analysis["faq_count"]
            gs = analysis.get("geo_score", "N/A")
            print(f"  -> {wc} words, {h1} H1, {faq} FAQs, GEO={gs}", file=sys.stderr)

        scraped.append(analysis)
        time.sleep(REQUEST_DELAY)

    output = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_input": len(tasks),
        "unique_urls": len(unique_tasks),
        "successful": len(scraped) - failed,
        "failed": failed,
        "results": scraped,
    }

    # ─── Supabase insertion ────────────────────────────────────────
    if args.run_id:
        try:
            supabase = get_supabase()
            rows = []
            for r in scraped:
                if r.get("status") != "success":
                    continue
                rows.append({
                    "run_id": args.run_id,
                    "url": r.get("url", ""),
                    "domain": r.get("domain", ""),
                    "keyword": r.get("keyword", ""),
                    "meta_title": r.get("meta_title", ""),
                    "word_count": r.get("word_count", 0),
                    "h1_count": r.get("h1_count", 0),
                    "h2_count": r.get("h2_count", 0),
                    "h3_count": r.get("h3_count", 0),
                    "faqs": r.get("faqs", []),
                    "schema_count": r.get("schema_count", 0),
                    "has_faq_schema": r.get("has_faq_schema", False),
                    "has_org_schema": r.get("has_organization_schema", False),
                    "geo_score": r.get("geo_score", 0),
                    "geo_signals": r.get("geo_signals", {}),
                })
            if rows:
                supabase.table("competitors").insert(rows).execute()
                if args.verbose:
                    print(f"[verbose] Inserted {len(rows)} rows into 'competitors' table",
                          file=sys.stderr)
        except Exception as e:
            print(f"Warning: Supabase insert failed: {e}", file=sys.stderr)

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
