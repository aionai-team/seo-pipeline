#!/usr/bin/env python3

"""
secondary_extractor.py — Εξαγωγή intelligence από non-competitor URLs.

Παίρνει το output του serp_scraper.py (με classified URLs) και εξάγει:
  - Reddit/Quora → questions + pain points + vocabulary
  - Directories (Clutch, G2) → listed agency names (free competitor discovery)
  - News → trending topics
  - YouTube → video titles (topic demand signal)

Usage:
    python secondary_extractor.py --input data/urls_2026-06-14.json --output data/secondary_2026-06-14.json
    python secondary_extractor.py --input data/urls.json --questions-only
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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)

REQUEST_DELAY = 0.5  # polite delay between requests


# ─── Reddit / Quora ───────────────────────────────────────────

def extract_questions_from_html(html: str, source: str) -> list[str]:
    """Extract question-like phrases from a page."""
    questions = []
    
    if source == "reddit":
        # Reddit post titles
        for match in re.finditer(
            r'<h3[^>]*>(.*?)</h3>', html, re.DOTALL
        ):
            text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            if text and len(text) > 10:
                questions.append(text)
        # Also try shreddit-post title attr
        for match in re.finditer(
            r'post-title[^>]*>(.*?)</', html, re.DOTALL
        ):
            text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            if text and len(text) > 10:
                questions.append(text)
    
    elif source == "quora":
        # Quora question titles
        for match in re.finditer(
            r'<span[^>]*class="[^"]*question[^"]*"[^>]*>(.*?)</span>',
            html, re.DOTALL
        ):
            text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            if text and text.endswith("?"):
                questions.append(text)
        # Fallback: <title> tag often has the question
        m = re.search(r"<title>([^<]+)</title>", html, re.DOTALL)
        if m:
            title = m.group(1).strip()
            if title.endswith("?"):
                questions.append(title)

    return questions


def extract_pain_points(text: str) -> list[str]:
    """Extract pain points / problem statements from text.
    Looks for Greek and English patterns indicating problems/challenges."""
    pain_points = []
    patterns = [
        (r"(πρόβλημα[^\.;]*[\.;])", "el"),
        (r"(δυσκολ[ίι]α[^\.;]*[\.;])", "el"),
        (r"(χάνω[^\.;]*[\.;])", "el"),
        (r"(δεν μπορώ[^\.;]*[\.;])", "el"),
        (r"(θέλω[^\.;]*αλλά[^\.;]*[\.;])", "el"),
        (r"(problem[^\.;]*[\.;])", "en"),
        (r"(struggl[^\.;]*[\.;])", "en"),
        (r"(difficult[^\.;]*[\.;])", "en"),
        (r"(waste[^\.;]*time[^\.;]*[\.;])", "en"),
        (r"(challenge[^\.;]*[\.;])", "en"),
        (r"(how do I[^?]*\?)", "en"),
        (r"(πως[^?]*\?)", "el"),
    ]
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    for pattern, lang in patterns:
        for match in re.finditer(pattern, clean, re.IGNORECASE):
            pp = match.group(1).strip()
            if pp and len(pp) < 300:
                pain_points.append({"text": pp, "language": lang})
    return pain_points


def fetch_page(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch a page's HTML with basic headers."""
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException:
        return None


# ─── Directories ──────────────────────────────────────────────

def extract_agency_links(html: str, directory: str) -> list[dict]:
    """Extract agency names and URLs from directory listings."""
    agencies = []
    
    if directory in ("clutch.co",):
        # Clutch agency cards
        for match in re.finditer(
            r'<a[^>]*href="(/profile/[^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            url = "https://clutch.co" + match.group(1)
            name = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if name and len(name) > 2:
                agencies.append({"name": name, "url": url, "source": "clutch"})

    elif directory in ("g2.com",):
        for match in re.finditer(
            r'<a[^>]*class="[^"]*product-name[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            url = match.group(1)
            if url.startswith("/"):
                url = "https://g2.com" + url
            name = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if name and len(name) > 2:
                agencies.append({"name": name, "url": url, "source": "g2"})

    else:
        # Generic: find all external links
        for match in re.finditer(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            link_url = match.group(1)
            name = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            # Only include external (not directory itself)
            parsed = urlparse(link_url)
            if parsed.netloc and directory not in parsed.netloc and name:
                agencies.append({"name": name, "url": link_url, "source": directory})

    return agencies


# ─── News ──────────────────────────────────────────────────────

def extract_topics_from_news(html: str) -> list[str]:
    """Extract topic/keyword signals from news article."""
    topics = []
    
    # Meta keywords
    m = re.search(r'<meta\s+name="[kK]eywords"[^>]*content="([^"]+)"', html)
    if m:
        topics.extend([k.strip() for k in m.group(1).split(",") if len(k.strip()) > 3])
    
    # <title> tag
    m = re.search(r"<title>([^<]+)</title>", html, re.DOTALL)
    if m:
        title = m.group(1).strip()
        topics.append(title)
    
    # H1 tags
    for match in re.finditer(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL):
        text = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if text and len(text) > 10:
            topics.append(text)
    
    return topics


# ─── Main extraction logic ─────────────────────────────────────

def process_keyword_results(keyword_data: dict, questions_only: bool = False) -> dict:
    """
    Process all secondary URLs for one keyword.
    Returns structured intelligence data.
    """
    result = {
        "keyword": keyword_data.get("keyword", "unknown"),
        "trend_score": keyword_data.get("trend_score", 0),
        "intent": keyword_data.get("intent", "INFO"),
        "secondary": {},
    }
    
    secondary = keyword_data.get("secondary", {})
    
    # ── Reddit / Quora ──
    reddit_urls = secondary.get("reddit", [])
    quora_urls = secondary.get("quora", [])  # if exists
    all_forum = reddit_urls + secondary.get("other", [])  # quora might end up in "other"
    # Actually quora is classified as REDDIT in url_utils, so it's in reddit list
    
    reddit_questions = []
    reddit_pain_points = []
    for item in reddit_urls:
        url = item.get("url", "")
        if not url:
            continue
        html = fetch_page(url)
        if not html:
            continue
        questions = extract_questions_from_html(html, "reddit")
        reddit_questions.extend(questions)
        pain = extract_pain_points(html)
        reddit_pain_points.extend(pain)
        time.sleep(REQUEST_DELAY)
    
    # Also check 'other' for quora-like content
    for item in secondary.get("other", []):
        url = item.get("url", "")
        title = item.get("title", "")
        if "quora" in url.lower() or "quora" in title.lower():
            html = fetch_page(url)
            if html:
                questions = extract_questions_from_html(html, "quora")
                reddit_questions.extend(questions)
                time.sleep(REQUEST_DELAY)
    
    if reddit_questions or reddit_pain_points:
        result["secondary"]["forum_questions"] = reddit_questions[:20]
        result["secondary"]["forum_pain_points"] = reddit_pain_points[:10]
    
    # ── Directories ──
    directory_urls = secondary.get("directories", [])
    discovered_agencies = []
    for item in directory_urls:
        url = item.get("url", "")
        if not url:
            continue
        html = fetch_page(url)
        if not html:
            continue
        domain = url_utils.extract_domain(url)
        agencies = extract_agency_links(html, domain)
        discovered_agencies.extend(agencies)
        time.sleep(REQUEST_DELAY)
    
    if discovered_agencies:
        # Deduplicate
        seen = set()
        unique = []
        for a in discovered_agencies:
            if a["url"] not in seen:
                seen.add(a["url"])
                unique.append(a)
        result["secondary"]["discovered_agencies"] = unique[:20]
    
    # ── News ──
    news_urls = secondary.get("news", [])
    news_topics = []
    for item in news_urls:
        url = item.get("url", "")
        if not url:
            continue
        html = fetch_page(url)
        if not html:
            continue
        topics = extract_topics_from_news(html)
        news_topics.extend(topics)
        time.sleep(REQUEST_DELAY)
    
    if news_topics:
        result["secondary"]["news_topics"] = news_topics[:15]
    
    # ── YouTube ──
    youtube_urls = secondary.get("youtube", [])
    video_titles = [item.get("title", "") for item in youtube_urls if item.get("title")]
    if video_titles:
        result["secondary"]["video_titles"] = video_titles[:10]
    
    # ── Summary ──
    classification = keyword_data.get("classification", {})
    total_secondary = sum(
        classification.get(t, 0) for t in ["REDDIT", "DIRECTORY", "NEWS", "YOUTUBE", "WIKIPEDIA"]
    )
    result["secondary_summary"] = {
        "total_secondary_urls": total_secondary,
        "questions_found": len(reddit_questions),
        "agencies_discovered": len(discovered_agencies),
        "news_topics": len(news_topics),
        "video_signals": len(video_titles),
    }
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="secondary_extractor.py — Εξαγωγή intelligence από non-competitor URLs."
    )
    parser.add_argument("--input", required=True, help="SERP URLs JSON (from serp_scraper.py)")
    parser.add_argument("--output", default=None, help="Output JSON")
    parser.add_argument("--questions-only", action="store_true",
                        help="Only extract Reddit/Quora questions (skip directories, news)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Read input
    raw = json.loads(Path(args.input).read_text("utf-8"))
    if isinstance(raw, dict):
        results = raw.get("results", [raw])
    else:
        results = raw if isinstance(raw, list) else [raw]

    if args.verbose:
        print(f"[verbose] Processing {len(results)} keywords for secondary intelligence...",
              file=sys.stderr)

    intelligence = []
    for idx, kw_data in enumerate(results):
        if args.verbose:
            kw = kw_data.get("keyword", "unknown")[:50]
            print(f"\n[{idx+1}/{len(results)}] '{kw}'", file=sys.stderr)

        data = process_keyword_results(kw_data, questions_only=args.questions_only)
        intelligence.append(data)

        # Show brief summary
        if args.verbose:
            s = data.get("secondary_summary", {})
            print(f"  → questions: {s.get('questions_found', 0)}, "
                  f"agencies: {s.get('agencies_discovered', 0)}, "
                  f"topics: {s.get('news_topics', 0)}", file=sys.stderr)

    output = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_keywords": len(intelligence),
        "results": intelligence,
        "aggregate": {
            "total_questions": sum(
                r.get("secondary_summary", {}).get("questions_found", 0)
                for r in intelligence
            ),
            "total_agencies_discovered": sum(
                r.get("secondary_summary", {}).get("agencies_discovered", 0)
                for r in intelligence
            ),
            "total_news_topics": sum(
                r.get("secondary_summary", {}).get("news_topics", 0)
                for r in intelligence
            ),
        },
    }

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), "utf-8"
        )
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    main()
