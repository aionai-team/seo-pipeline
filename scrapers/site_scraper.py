#!/usr/bin/env python3

"""
site_scraper.py — Εξαγωγή περιεχομένου & seeds από το aionAI site.

Λειτουργίες:
  1. --extract (default): Διαβάζει source files (TS/HTML) → content inventory + seeds
  2. --health-check: Κάνει render το Angular SPA → συγκρίνει με source → report
  3. --googlebot: Κάνει fetch σαν Googlebot (raw, no JS) → εξάγει ό,τι βλέπει το crawler → gap report
  4. --googlebot-rendered: Κάνει render με Chromium (5s timeout) → προσομοιώνει το JS pass του Googlebot → σύγκριση raw vs rendered vs source
  5. --validate-jsonld: Κάνει fetch και επικυρώνει JSON-LD structured data (phone, email, URL format, required fields)

Pipeline:
    python site_scraper.py --extract --output data/site_2026-06-13.json
    python site_scraper.py --health-check --url http://localhost:4200
    python site_scraper.py --googlebot --url https://aionai.gr --output data/gap_report.json
    python site_scraper.py --googlebot-rendered --url https://aionai.gr --output data/rendered_report.json
    python site_scraper.py --validate-jsonld --url https://aionai.gr --output data/jsonld_validation.json

Requirements:
    stdlib only (--extract, --googlebot, --validate-jsonld)
    playwright>=1.52.0 (for --health-check, --googlebot-rendered)
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
from urllib.request import Request, urlopen
from urllib.error import URLError

from lib.supabase_client import get_supabase

# ─── Project paths ────────────────────────────────────────────────────────
AI_SITE_ROOT = Path("/home/bog/main_folder/projects/ai_site")
INDEX_HTML = AI_SITE_ROOT / "src/index.html"
APP_TS = AI_SITE_ROOT / "src/app/app.ts"
SECTIONS_DIR = AI_SITE_ROOT / "src/app/sections"
CONFIG_DIR = AI_SITE_ROOT / "src/app/config"
SERVICES_DIR = AI_SITE_ROOT / "src/app/services"

# ─── Confidence levels ─────────────────────────────────────────────────────
# How accurately each measurement reflects real Googlebot behavior.
# Higher = more actionable without external verification.

CONFIDENCE = {
    "googlebot_raw": {
        "level": 95,
        "label": "HIGH",
        "reason": "Server returns identical HTML to curl and Googlebot",
    },
    "googlebot_rendered": {
        "level": 70,
        "label": "MEDIUM",
        "reason": "Local Chromium has more resources than Googlebot's sandboxed render",
    },
    "jsonld_validation": {
        "level": 95,
        "label": "HIGH",
        "reason": "Validation rules are deterministic — same inputs = same results",
    },
    "competitor_raw": {
        "level": 90,
        "label": "HIGH",
        "reason": "Some servers may redirect differently to Googlebot UA vs curl",
    },
    "source_extraction": {
        "level": 50,
        "label": "MEDIUM",
        "reason": "Source code ≠ rendered content; noise filtering is imperfect",
    },
}


# ─── Noise patterns ───────────────────────────────────────────────────────
# Patterns that indicate non-content text (JS code, template syntax, etc.)
NOISE_PATTERNS = [
    r'\{\{', r'\}\}',                      # Angular template bindings
    r'@if\b', r'@for\b', r'@else\b', r'@ViewChild\b',
    r'constructor\s*\(', r'afterNextRender\b',
    r'import\s+\{', r'interface\s+\w+', r'}\s*;?\s*$',
    r'\bthis\.', r'\bsignal\(', r'\bcomputed\(', r'\binject\(',
    r'DomSanitizer', r'bypassSecurityTrustHtml',
    r'\.replace\(', r'\.set\(', r'\.update\(',
    r'//\s', r'/\*', r'\*/\s*$',
    r'^\s*const\s', r'^\s*let\s', r'^\s*var\s', r'^\s*function\b',
    r'\bMath\.', r'requestAnimationFrame',
    r'<svg', r'polyline', r'stroke-', r'xmlns', r'viewBox',
    r'fill\s*=\s*["\']', r'd\s*=\s*["\']',
    r'^[@#]', r'^[\s{}.]',
    r'^\d+[.\s]*$',
    r'^[`\']', r"^['\"]",
    r'\bPromise\b', r'\bnew\s+', r'\basync\b', r'\bawait\b',
    r'^\s*\)', r'^\s*\]', r'^\s*\}\)',
    r'^import\s', r'^from\s',
    r'@media', r'@font-face', r'@keyframes',
    r'^scope\s*{', r'^\s*}\s*$',
]

NOISE_RE = re.compile('|'.join(NOISE_PATTERNS), re.MULTILINE)

# Angular template binding patterns in headings
TEMPLATE_HEADING_RE = re.compile(r'\{\{.*?\}\}')


def is_noise(text: str) -> bool:
    """Check if text is likely non-content (JS code, template syntax, etc.)"""
    # Very short non-Greek fragments
    if len(text) < 15 and not re.search(r'[α-ωΑ-Ωάέήίόύώ]', text):
        return True
    # JavaScript code patterns
    if bool(NOISE_RE.search(text)):
        return True
    # Lines that are just closing brackets
    if text.strip() in ['}', ']);', '});', '};', '`,' , '\');', '",']:
        return True
    # Number-only lines
    if re.match(r'^\s*[\d.,\s]+\s*$', text):
        return True
    return False


# ─── Regex helpers ────────────────────────────────────────────────────────

def extract_inline_text(ts_content: str) -> list[str]:
    """Extract visible Greek text from Angular inline template content.

    Gets text inside HTML tags, excluding:
      - SVG content
      - Angular-specific syntax ({{}}, @for, @if, etc.)
      - CSS in styles: [] blocks
      - HTML attributes
    """
    texts = []
    # Remove styles blocks
    cleaned = re.sub(r"styles\s*:\s*\[.*?\]", "", ts_content, flags=re.DOTALL)

    # Find text inside HTML tags (not SVGs, not attributes)
    # Match > ... < pattern, capture the text content
    for match in re.finditer(r">([^<]{4,})<", cleaned):
        text = match.group(1).strip()
        if not text:
            continue
        if is_noise(text):
            continue
        texts.append(text)
    return texts


def extract_text_content(html: str) -> dict:
    """Extract text content that a search bot can see in raw HTML.

    This strips all tags and JS/CSS, returning only visible text.
    Similar to what Googlebot extracts from the DOM without JS execution.
    """
    # Remove script and style blocks
    cleaned = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL)

    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', cleaned)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return {
        "raw_text": text,
        "word_count": len(text.split()),
    }


def extract_json_ld(html_content: str) -> dict:
    """Extract and parse JSON-LD from index.html."""
    match = re.search(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
        html_content,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
    return {}


def extract_meta(html_content: str) -> dict:
    """Extract all meta tags from index.html."""
    meta = {}
    # Title
    title_match = re.search(r"<title>(.*?)</title>", html_content, re.DOTALL)
    if title_match:
        meta["title"] = title_match.group(1).strip()

    # Meta tags — handle multiline attributes with newlines
    for match in re.finditer(
        r'<meta\s+(?:name|property)="([^"]+)"[^>]*content="([^"]+)"',
        html_content,
    ):
        meta[match.group(1)] = match.group(2)

    # Also match reversed order
    for match in re.finditer(
        r'<meta\s+content="([^"]+)"\s+(?:name|property)="([^"]+)"',
        html_content,
    ):
        meta[match.group(2)] = match.group(1)

    return meta


# ─── Googlebot fetch ──────────────────────────────────────────────────────

def fetch_as_googlebot(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch a URL with Googlebot User-Agent, return raw HTML.

    This is what Googlebot actually receives — no JS execution.
    """
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; Googlebot/2.1; "
                "+http://www.google.com/bot.html)"
            ),
            "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        return None


def extract_googlebot_view(html: str) -> dict:
    """Extract exactly what Googlebot can see from the raw HTML.

    Googlebot (without JS execution) sees:
    - <head> content (meta, title, JSON-LD)
    - Only server-rendered <body> content
    - NO Angular-rendered content (just <app-root></app-root>)
    """
    # Extract head content
    head_match = re.search(r'<head[^>]*>(.*?)</head>', html, re.DOTALL)
    head_html = head_match.group(1) if head_match else ""

    meta = extract_meta(html)
    json_ld = extract_json_ld(html)

    # Extract body content
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL)
    body_html = body_match.group(1) if body_match else ""

    body_text = extract_text_content(body_html)

    # Extract any links Googlebot could follow
    links = re.findall(r'<a\s+[^>]*href="([^"]+)"', body_html)

    # Check if there are any custom elements (Angular components)
    custom_elements = re.findall(r'<app-(\w+)[>\s]', body_html)

    # Detect if this is a JS-required SPA
    has_app_root = "<app-root>" in body_html or "<app-root " in body_html
    body_has_content = body_text["word_count"] > 0 and not has_app_root

    return {
        "meta": meta,
        "json_ld": json_ld,
        "body": {
            "raw_text_snippet": body_text["raw_text"][:500] if body_text["word_count"] > 0 else "(empty — SPA shell)",
            "word_count": body_text["word_count"],
            "has_app_root": has_app_root,
            "has_rendered_content": body_has_content,
            "custom_elements_found": custom_elements,
            "links_found": len(links),
            "links": links[:20],
        },
        "assessment": {
            "needs_javascript": has_app_root and not body_has_content,
            "json_ld_available": bool(json_ld),
            "meta_available": bool(meta),
        },
    }


# ─── Section parsers ─────────────────────────────────────────────────────

def extract_heading_text(element_html: str) -> str:
    """Extract full text from a heading element, stripping inner HTML tags.

    Handles: <h1>text <span>more</span> text</h1> → "text more text"
    """
    # Replace tags with spaces to avoid word merging: <span>word1</span><span>word2</span>
    text = re.sub(r'<[^>]+>', ' ', element_html)
    # Collapse multiple spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def parse_section_files() -> list[dict]:
    """Read all section TS files and extract visible content.

    Returns list of {section: str, headings: [str], paragraphs: [str],
                     faq: [dict], use_cases: [dict], services: [str]}
    """
    sections = []

    if not SECTIONS_DIR.exists():
        return sections

    for ts_path in sorted(SECTIONS_DIR.glob("*.ts")):
        section_name = ts_path.stem
        content = ts_path.read_text("utf-8")

        entry = {
            "section": section_name,
            "headings": [],
            "paragraphs": [],
            "bullets": [],
            "cta_buttons": [],
        }

        # Extract headings from h1-h3, handling nested elements
        for match in re.finditer(
            r"<h[1-3][^>]*>(.*?)</h[1-3]>", content, re.DOTALL
        ):
            raw_heading = match.group(1)
            heading_text = extract_heading_text(raw_heading)
            # Skip template bindings-only headings
            if not TEMPLATE_HEADING_RE.sub('', heading_text).strip():
                continue
            if heading_text:
                entry["headings"].append(heading_text)

        # Extract text that looks like a heading (section-title class, etc.)
        for match in re.finditer(
            r'class="[^"]*section-title[^"]*"[^>]*>\s*(.*?)\s*<',
            content,
        ):
            text = extract_heading_text(match.group(1))
            if text and text not in entry["headings"] and not is_noise(text):
                entry["headings"].append(text)

        # Extract visible paragraphs — filter out noise
        for match in re.finditer(r">([^<]{15,400})<", content):
            text = match.group(1).strip()
            if not text:
                continue
            if is_noise(text):
                continue
            if text.startswith("https://") or text.startswith("http://"):
                continue
            # Skip lines that look like HTML attributes
            if re.match(r'^[a-z-]+="', text):
                continue
            entry["paragraphs"].append(text)

        # Extract FAQ items from component data (question: / answer: pattern)
        faq_q = list(re.finditer(r"question\s*:\s*'([^']+)'", content))
        faq_a = list(re.finditer(r"answer\s*:\s*'([^']+)'", content))

        for i, qm in enumerate(faq_q):
            entry.setdefault("faq", []).append({
                "question": qm.group(1),
                "answer": faq_a[i].group(1) if i < len(faq_a) else None,
            })

        # Extract use cases (UseCaseCard arrays)
        uc_matches = re.finditer(
            r"title\s*:\s*'([^']+)'(?:.*?)description\s*:\s*'([^']+)'",
            content,
            re.DOTALL,
        )
        for ucm in uc_matches:
            entry.setdefault("use_cases", []).append({
                "title": ucm.group(1),
                "description": ucm.group(2),
            })

        # Extract CTA buttons
        for match in re.finditer(r">([^<]{8,60})</a>", content):
            text = match.group(1).strip()
            if any(kw in text.lower() for kw in
                   ["κλείστε", "δείτε", "μάθετε", "επικοινων", "ξεκινήστε",
                    "κανονίστε"]):
                entry["cta_buttons"].append(text)

        sections.append(entry)

    return sections


# ─── Seed generation ──────────────────────────────────────────────────────

def generate_seeds(
    meta: dict,
    json_ld: dict,
    sections: list[dict],
) -> dict:
    """Generate seed keyword candidates from site content.

    Seeds organized by category for keyword_discovery.py.
    """
    seeds = {
        "from_meta_keywords": [],
        "from_service_types": [],
        "from_faq": [],
        "from_use_cases": [],
        "from_headings": [],
        "from_areas": [],
        "from_cta": [],
        "all_short_seeds": [],
    }

    # 1. Meta keywords → short seeds only
    if "keywords" in meta:
        for kw in meta["keywords"].split(","):
            kw = kw.strip()
            if kw and len(kw.split()) <= 4:
                seeds["from_meta_keywords"].append(kw)

    # 2. Service types → seed candidates
    try:
        graph = json_ld.get("@graph", [])
        for entity in graph:
            services = entity.get("serviceType", [])
            for s in services:
                seeds["from_service_types"].append(s)
                # Simplified Greek versions
                greek_map = {
                    "AI Consulting": "ai consulting ελλάδα",
                    "Workflow Automation": "αυτοματοποίηση ροών",
                    "AI Agent Development": "ai agents",
                    "Business Process Automation": "αυτοματοποίηση διαδικασιών",
                    "CRM Integration": "crm αυτοματοποίηση",
                    "ERP Integration": "erp με ai",
                    "Invoice Processing": "αυτοματοποίηση τιμολογίων",
                    "Document Search & Q&A": "αναζήτηση εγγράφων ai",
                    "Email Automation": "αυτοματοποίηση email",
                    "Reporting Automation": "αυτόματες αναφορές",
                    "Appointment Scheduling": "αυτόματο κλείσιμο ραντεβού",
                }
                if s in greek_map:
                    seeds["from_service_types"].append(greek_map[s])

            # Area served → geo seeds
            areas = entity.get("areaServed", [])
            for area in areas:
                city = area.get("name", "")
                if city:
                    seeds["from_areas"].append(f"ai {city}")
                    seeds["from_areas"].append(f"τεχνητή νοημοσύνη {city}")

            # Founding date
            seeds["metadata"] = {
                "founding_date": entity.get("foundingDate", ""),
                "phone": entity.get("telephone", ""),
                "email": entity.get("email", ""),
                "target_industries": [
                    "υπηρεσίες", "logistics", "ιατρεία",
                    "δικηγορικά γραφεία", "e-commerce", "creative studios",
                ],
            }
    except (KeyError, TypeError, AttributeError):
        pass

    # 3. FAQ → question seeds (from BOTH component and JSON-LD)
    # Component FAQ
    seen_questions = set()
    for section in sections:
        for faq in section.get("faq", []):
            q = faq.get("question", "")
            if q and q not in seen_questions:
                seen_questions.add(q)
                seeds["from_faq"].append(q)

    # JSON-LD FAQ (may have additional questions the component doesn't)
    try:
        for entity in json_ld.get("@graph", []):
            if entity.get("@type") == "FAQPage":
                for item in entity.get("mainEntity", []):
                    q = item.get("name", "")
                    if q and q not in seen_questions:
                        seen_questions.add(q)
                        seeds["from_faq"].append(q)
    except (KeyError, TypeError, AttributeError):
        pass

    # 4. Use cases → seeds
    seen_uc = set()
    for section in sections:
        for uc in section.get("use_cases", []):
            title = uc.get("title", "")
            if title and title not in seen_uc:
                seen_uc.add(title)
                seeds["from_use_cases"].append(title)


    # 5. Headings → short seeds
    for section in sections:
        for heading in section.get("headings", []):
            text = heading.get("text", "") if isinstance(heading, dict) else str(heading) if heading else ""
            if text and len(text.split()) <= 4:
                seeds["from_headings"].append(text)

    # 6. CTA texts → seeds
    seeds["from_cta"] = [
        "ai consulting ελλάδα",
        "αυτοματοποίηση επιχειρήσεων",
        "ai λύσεις για μμες",
    ]

    # Compile all short seeds (≤3 words)
    all_short: list[str] = []
    for category_list in seeds.values():
        if isinstance(category_list, list):
            for s in category_list:
                if len(s.split()) <= 3 and s.strip():
                    all_short.append(s.strip())

    seeds["all_short_seeds"] = list(dict.fromkeys(all_short))
    return seeds


# ─── Gap analysis ──────────────────────────────────────────────

def analyze_missing_content(
    source_data: dict,
    googlebot_view: dict,
) -> list[dict]:
    """Compare source content with Googlebot view to find gaps.

    Returns list of gap items describing what Googlebot misses.
    """
    gaps: list[dict] = []

    source_sections = source_data.get("sections", [])
    bot_body = googlebot_view.get("body", {})
    bot_has_app_root = bot_body.get("has_app_root", False)
    bot_words = bot_body.get("word_count", 0)

    # Source headings vs Googlebot headings
    source_headings: set[str] = set()
    for s in source_sections:
        for h in s.get("headings", []):
            text = h.get("text", "").strip() if isinstance(h, dict) else str(h).strip()
            if text:
                source_headings.add(text.lower())

    bot_headings: set[str] = set()
    for h in bot_body.get("headings", []):
        text = h.get("text", "").strip() if isinstance(h, dict) else str(h).strip()
        if text:
            bot_headings.add(text.lower())

    missing_headings = source_headings - bot_headings
    if missing_headings:
        gaps.append({
            "type": "headings",
            "severity": "HIGH" if len(missing_headings) > 3 else "MEDIUM",
            "message": f"{len(missing_headings)} headings missing in Googlebot view",
            "missing": list(missing_headings)[:10],
        })

    # FAQ gap
    source_faqs: set[str] = set()
    for s in source_sections:
        for f in s.get("faq", []):
            q = f.get("question", "")
            if q:
                source_faqs.add(q.lower())

    # Also check JSON-LD FAQ
    try:
        json_ld_data = source_data.get("json_ld", {})
        graph = json_ld_data.get("@graph", [])
        for entity in graph:
            if entity.get("@type") == "FAQPage":
                for item in entity.get("mainEntity", []):
                    q = item.get("name", "")
                    if q:
                        source_faqs.add(q.lower())
    except (KeyError, TypeError, AttributeError):
        pass

    bot_faqs: set[str] = set()
    bot_jsonld = googlebot_view.get("json_ld", {})
    if isinstance(bot_jsonld, dict):
        graph = bot_jsonld.get("@graph", [])
        for entity in graph if isinstance(graph, list) else []:
            if entity.get("@type") == "FAQPage":
                for item in entity.get("mainEntity", []):
                    q = item.get("name", "")
                    if q:
                        bot_faqs.add(q.lower())

    missing_faqs = source_faqs - bot_faqs
    if missing_faqs:
        gaps.append({
            "type": "faq",
            "severity": "MEDIUM",
            "message": f"{len(missing_faqs)} FAQ questions missing in Googlebot view",
            "missing": list(missing_faqs)[:5],
        })

    # SPA shell detection
    if bot_has_app_root:
        gaps.append({
            "type": "spa_shell",
            "severity": "CRITICAL",
            "message": "Googlebot sees <app-root></app-root> — SPA not rendered",
        })

    # Content volume gap
    source_words = 0
    for s in source_sections:
        for p in s.get("paragraphs", []):
            source_words += len(p.split())
    if source_words > 0 and bot_words < source_words * 0.3:
        gaps.append({
            "type": "content_volume",
            "severity": "HIGH",
            "message": f"Googlebot sees {bot_words} words vs {source_words} in source ({bot_words/source_words*100:.0f}%)",
        })

    return gaps


# ─── Run modes ─────────────────────────────────────────────────

def run_extract(output_path: str = "", verbose: bool = False) -> dict:
    """Main extraction: read source files, build content inventory + seeds."""
    if verbose:
        print("[verbose] Reading index.html...", file=sys.stderr)

    html = Path(INDEX_HTML).read_text("utf-8")
    meta = extract_meta(html)
    json_ld = extract_json_ld(html)
    sections = parse_section_files()

    if verbose:
        print(f"[verbose] Meta tags: {len(meta)}", file=sys.stderr)
        print(f"[verbose] JSON-LD entities: {len(json_ld.get('@graph', []))}", file=sys.stderr)
        print(f"[verbose] Sections: {len(sections)}", file=sys.stderr)

    seeds = generate_seeds(meta, json_ld, sections)

    # Clean word count
    clean_words = 0
    for s in sections:
        for p in s.get("paragraphs", []):
            if not is_noise(p):
                clean_words += len(p.split())

    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source": "site_scraper --extract",
        "meta": meta,
        "json_ld": json_ld,
        "sections": sections,
        "seeds": seeds,
        "word_count_clean": clean_words,
        "total_sections": len(sections),
    }

    output = json.dumps(data, ensure_ascii=False, indent=2)
    print(output)
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        if verbose:
            print(f"[verbose] Saved to {output_path}", file=sys.stderr)
    return data


def run_googlebot_check(url: str, verbose: bool = False, output_path: str = "",
                         run_id: str = "") -> dict:
    """Fetch as Googlebot, extract content, compare with source, report gaps."""
    if verbose:
        print(f"[verbose] Fetching as Googlebot: {url}", file=sys.stderr)

    html = fetch_as_googlebot(url)
    if html is None:
        print(f"Error: Could not fetch {url}", file=sys.stderr)
        sys.exit(1)

    if verbose:
        print(f"[verbose] Fetched {len(html)} bytes", file=sys.stderr)

    googlebot_view = extract_googlebot_view(html)

    # Compare with source
    source = run_extract(verbose=verbose)
    gaps = analyze_missing_content(source, googlebot_view)

    # Score
    score = 100
    for g in gaps:
        if g["severity"] == "CRITICAL":
            score -= 25
        elif g["severity"] == "HIGH":
            score -= 15
        elif g["severity"] == "MEDIUM":
            score -= 8
    score = max(0, score)

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "target_url": url,
        "confidence": {"level": 95, "label": "HIGH", "reason": "Server returns identical HTML to curl and Googlebot"},
        "googlebot_view": googlebot_view,
        "source_summary": {
            "sections": source["total_sections"],
            "word_count_clean": source["word_count_clean"],
            "seeds": len(source["seeds"].get("all_short_seeds", [])),
        },
        "gaps": gaps,
        "gap_count": len(gaps),
        "score": score,
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        if verbose:
            print(f"[verbose] Saved to {output_path}", file=sys.stderr)

    # Write to Supabase if run_id provided
    if run_id:
        try:
            supabase = get_supabase()
            gv = report.get("googlebot_view", {})
            supabase.table("site_assessments").insert({
                "run_id": run_id,
                "assessment_type": "googlebot_raw",
                "score": report.get("score", 0),
                "word_count": gv.get("body", {}).get("word_count", 0),
                "data": report,
            }).execute()
            if verbose:
                print(f"[verbose] Written to Supabase site_assessments table (googlebot_raw)", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to write googlebot_raw to Supabase: {e}", file=sys.stderr)

    return report


# Required fields per entity type for JSON-LD validation
JSONLD_REQUIRED_ORG_FIELDS = {
    "ProfessionalService": ["name", "url", "description", "address", "serviceType"],
    "Organization": ["name", "url", "description", "address"],
    "LocalBusiness": ["name", "url", "description", "address", "telephone"],
    "FAQPage": ["mainEntity"],
    "Product": ["name", "description"],
}


def validate_jsonld(json_ld: dict) -> list[dict]:
    """Validate JSON-LD structured data for common issues."""
    issues: list[dict] = []

    graph = json_ld.get("@graph", [])
    if not graph:
        issues.append({
            "type": "missing_graph",
            "severity": "CRITICAL",
            "message": "JSON-LD has no @graph array",
        })
        return issues

    for entity in graph:
        etype = entity.get("@type", "unknown")
        for field in JSONLD_REQUIRED_ORG_FIELDS.get(etype, []):
            val = entity.get(field)
            if not val:
                issues.append({
                    "type": f"missing_{field}",
                    "severity": "HIGH",
                    "message": f"{etype} missing required field: {field}",
                })

        # Phone validation
        phone = entity.get("telephone", "")
        if phone:
            phone_clean = re.sub(r"[^\d+]", "", phone)
            if not phone_clean.startswith("+30") or len(phone_clean) not in (13, 14):
                issues.append({
                    "type": "phone_format",
                    "severity": "MEDIUM",
                    "message": f"Phone '{phone_clean}' has {len(phone_clean)} digits (expected 13 for Greek mobile: +30 69X XXXXXXX)",
                })

        # Email validation
        email = entity.get("email", "")
        if email and "@" not in email:
            issues.append({
                "type": "email_format",
                "severity": "HIGH",
                "message": f"Email '{email}' is missing @",
            })

        # URL validation
        url = entity.get("url", "")
        if url and not url.startswith("http"):
            issues.append({
                "type": "url_format",
                "severity": "HIGH",
                "message": f"URL '{url}' does not start with http",
            })

        # Area served
        areas = entity.get("areaServed", [])
        if not areas:
            issues.append({
                "type": "missing_areaServed",
                "severity": "MEDIUM",
                "message": f"No areaServed defined — Google needs location context",
            })

    return issues


def run_jsonld_validation(url: str, verbose: bool = False, output_path: str = "",
                           run_id: str = "") -> dict:
    """Fetch URL and validate JSON-LD."""
    if verbose:
        print(f"[verbose] Validating JSON-LD at: {url}", file=sys.stderr)

    html = fetch_as_googlebot(url)
    if html is None:
        print(f"Error: Could not fetch {url}", file=sys.stderr)
        sys.exit(1)

    json_ld = extract_json_ld(html)
    issues = validate_jsonld(json_ld)

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "target_url": url,
        "confidence": {"level": 95, "label": "HIGH", "reason": "Validation rules are deterministic"},
        "json_ld": json_ld,
        "issues": issues,
        "total_issues": len(issues),
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        if verbose:
            print(f"[verbose] Saved to {output_path}", file=sys.stderr)

    # Write to Supabase if run_id provided
    if run_id:
        try:
            supabase = get_supabase()
            supabase.table("site_assessments").insert({
                "run_id": run_id,
                "assessment_type": "jsonld",
                "score": None,
                "verdict": str(report.get("total_issues", 0)),
                "data": report,
            }).execute()
            if verbose:
                print(f"[verbose] Written to Supabase site_assessments table (jsonld)", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to write jsonld to Supabase: {e}", file=sys.stderr)

    return report


# ─── GEO check ─────────────────────────────────────────────────────────

def run_geo_check(output_path: str = "", verbose: bool = False) -> dict:
    """
    --geo-check mode: Analyze our own source code for GEO (Generative Engine Optimization) signals.

    Reads Angular source files (index.html, app.ts, sections/*.ts, public/llms.txt)
    and extracts GEO-specific signals that determine whether LLMs (ChatGPT, Perplexity,
    Gemini) can extract, parse, and cite our content.

    Returns a structured report with:
      - Per-signal detection (present/absent)
      - Composite GEO readiness score (0-100)
      - Gap analysis with priority levels
    """
    if verbose:
        print("[geo-check] Analyzing aionAI source code for GEO signals...", file=sys.stderr)

    # ─── Read all source files ────────────────────────────────────────
    index_html = INDEX_HTML.read_text("utf-8", errors="ignore") if INDEX_HTML.exists() else ""
    app_ts_content = APP_TS.read_text("utf-8", errors="ignore") if APP_TS.exists() else ""
    llms_path = AI_SITE_ROOT / "public/llms.txt"
    llms_content = llms_path.read_text("utf-8", errors="ignore") if llms_path.exists() else ""

    section_files = sorted(SECTIONS_DIR.glob("*.ts")) if SECTIONS_DIR.exists() else []
    all_templates = []
    for sf in section_files:
        try:
            content = sf.read_text("utf-8", errors="ignore")
            # Extract template strings (backtick content)
            templates = re.findall(r"template:\s*`(.*?)`\s*,", content, re.DOTALL)
            for t in templates:
                # Remove styles blocks to avoid false positives
                t_clean = re.sub(r"styles\s*:\s*\[.*?\]", "", t, flags=re.DOTALL)
                all_templates.append({"file": sf.name, "template": t_clean})
        except Exception as e:
            if verbose:
                print(f"  [warn] Skipping {sf.name}: {e}", file=sys.stderr)

    # ─── Signal 1: Static body content (no-JS visibility) ─────────────
    body_match = re.search(r"<body[^>]*>(.*?)</body>", index_html, re.DOTALL)
    body_text = ""
    if body_match:
        body_raw = body_match.group(1)
        body_text = re.sub(r"<[^>]+>", " ", body_raw)
        body_text = re.sub(r"\s+", " ", body_text).strip()
    static_body_words = len(body_text.split())
    has_static_content = static_body_words > 20

    # ─── Signal 2: FAQ visibility (is FAQ text in static HTML?) ──────
    faq_static_keywords = ["Συχνές Ερωτήσεις", "Από πού ξεκινάμε", "Χρειάζεται να αντικαταστήσουμε",
                           "Είναι τα δεδομένα", "Πόσο γρήγορα", "Τι είδους επιχειρήσεις",
                           "Μπορείτε να συνδεθείτε", "Πόσο κοστίζει"]
    faq_text_in_static = any(kw in index_html for kw in faq_static_keywords)

    # ─── Signal 3: FAQPage schema in static HTML ─────────────────────
    faq_schema_in_static = "FAQPage" in index_html

    # ─── Signal 4: TL;DR / summary blocks ────────────────────────────
    tldr_pattern = re.compile(r"(TL;DR|tl;dr|summary|με λίγα λόγια|συνοπτικά|περίληψη)", re.IGNORECASE)
    tldr_present = bool(tldr_pattern.search(index_html))
    if not tldr_present:
        for t in all_templates:
            if tldr_pattern.search(t["template"]):
                tldr_present = True
                break

    # ─── Signal 5: Answer-first structure (H1 analysis) ──────────────
    # Check hero.ts for answer-style H1 vs CTA-style H1
    h1_text = ""
    for t in all_templates:
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", t["template"], re.DOTALL)
        if h1_match:
            h1_text = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
            break
    if not h1_text:
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", index_html, re.DOTALL)
        if h1_match:
            h1_text = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()

    # Answer-first heuristic: H1 starts with a definition pattern
    answer_first_keywords = ["τι είναι", "ορίζεται", "ορισμός", "τι σημαίνει",
                             "οδηγός", "πώς", "τι πρέπει"]
    h1_is_definitive = any(kw in h1_text.lower() for kw in answer_first_keywords)
    h1_is_cta = any(kw in h1_text.lower() for kw in ["μάθετε", "κλείστε", "ξεκινήστε", "δοκιμάστε"])

    # ─── Signal 6: Lists (ul/ol) in templates ────────────────────────
    ul_count = 0
    ol_count = 0
    list_items_total = 0
    for t in all_templates:
        ul_count += len(re.findall(r"<ul\b", t["template"]))
        ol_count += len(re.findall(r"<ol\b", t["template"]))
        list_items_total += len(re.findall(r"<li\b", t["template"]))
    has_lists = (ul_count + ol_count) > 0

    # ─── Signal 7: Tables in templates ───────────────────────────────
    table_count = 0
    for t in all_templates:
        table_count += len(re.findall(r"<table\b", t["template"]))
    has_tables = table_count > 0

    # ─── Signal 8: Inline citations / external links ─────────────────
    citation_count = 0
    # External hrefs in templates (excluding # anchors and mailto)
    all_hrefs = []
    for t in all_templates:
        hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', t["template"])
        all_hrefs.extend(hrefs)
    citation_count = len(all_hrefs)
    has_citations = citation_count > 0

    # Citation keywords in content
    citation_keywords = re.compile(r"(πηγή|source|σύμφωνα|μελέτη|στοιχεία|έρευνα|research|study)", re.IGNORECASE)
    citation_keyword_count = 0
    for t in all_templates:
        citation_keyword_count += len(citation_keywords.findall(t["template"]))
    citation_keyword_count += len(citation_keywords.findall(index_html))
    has_citation_mentions = citation_keyword_count > 0

    # ─── Signal 9: Author info ───────────────────────────────────────
    author_match = re.search(r'<meta\s+name="author"\s+content="([^"]+)"', index_html)
    has_author_meta = bool(author_match)
    author_name = author_match.group(1) if author_match else ""

    # Author bio section in templates
    author_bio_pattern = re.compile(r"(συγγραφέας|byline|author|bio|about the author)", re.IGNORECASE)
    has_author_bio = False
    for t in all_templates:
        if author_bio_pattern.search(t["template"]):
            has_author_bio = True
            break

    # ─── Signal 10: Statistics in content ────────────────────────────
    stat_pattern = re.compile(
        r"\d+\.?\d*\s*%|"           # 50%, 12.5%
        r"\d+\s*(percent|ποσοστό)|"
        r"(πάνω από|περισσότεροι από|less than|more than)\s*\d+|"
        r"\d+\s*(out of|στο)|"
        r"(1 in|1 στα|ένας στους)", re.IGNORECASE
    )
    stat_count = 0
    for t in all_templates:
        # Only match in visible text, not CSS/SVG
        texts_in_template = re.findall(r">([^<]{10,})<", t["template"])
        for txt in texts_in_template:
            stat_count += len(stat_pattern.findall(txt))
    has_stats = stat_count > 0

    # ─── Signal 11: JSON-LD schema types present ─────────────────────
    schema_types = []
    if "ProfessionalService" in index_html:
        schema_types.append("ProfessionalService")
    if "FAQPage" in index_html:
        schema_types.append("FAQPage")
    if "Organization" in index_html:
        schema_types.append("Organization")
    if "LocalBusiness" in index_html:
        schema_types.append("LocalBusiness")
    if "Article" in index_html:
        schema_types.append("Article")
    if "HowTo" in index_html:
        schema_types.append("HowTo")
    if "Product" in index_html:
        schema_types.append("Product")
    if "BreadcrumbList" in index_html:
        schema_types.append("BreadcrumbList")

    # ─── Signal 12: llms.txt check ───────────────────────────────────
    has_llms_txt = llms_path.exists()
    llms_lines = len(llms_content.splitlines()) if llms_content else 0
    llms_has_pages = "## Pages" in llms_content
    llms_has_faq = "## FAQ" in llms_content or "FAQ" in llms_content

    # ─── Signal 13: Meta tags completeness ───────────────────────────
    meta = {}
    for match in re.finditer(r'<meta\s+(?:name|property)="([^"]+)"[^>]*content="([^"]+)"', index_html):
        meta[match.group(1)] = match.group(2)
    meta_count = len(meta)
    has_og_tags = any(k.startswith("og:") for k in meta)
    has_twitter_tags = any(k.startswith("twitter:") for k in meta)

    # ─── Calculate GEO Readiness Score (0-100) ───────────────────────
    # Weighted: each signal contributes to max score
    scores = {
        "static_content": 15 if has_static_content else 0,
        "faq_text_visible": 8 if faq_text_in_static else 0,
        "faq_schema": 12 if faq_schema_in_static else 0,
        "tldr": 10 if tldr_present else 0,
        "answer_first_h1": 10 if h1_is_definitive else (3 if not h1_is_cta else 0),
        "lists": 8 if has_lists else 0,
        "tables": 5 if has_tables else 0,
        "citations": 8 if has_citations else (3 if has_citation_mentions else 0),
        "author": 9 if (has_author_meta or has_author_bio) else 0,
        "statistics": 5 if has_stats else 0,
        "llms_txt": 10 if has_llms_txt else 0,
        "meta_tags": 5 if meta_count >= 15 else 0,
    }
    total_score = sum(scores.values())
    max_score = 15 + 8 + 12 + 10 + 10 + 8 + 5 + 8 + 9 + 5 + 10 + 5
    geo_score_pct = round((total_score / max_score) * 100)

    # ─── Identify gaps ───────────────────────────────────────────────
    gaps = []
    if not has_static_content:
        gaps.append({"signal": "static_body_content", "priority": "CRITICAL",
                      "detail": f"Only {static_body_words} words visible in static HTML — LLM crawlers see empty body"})
    if not faq_text_in_static and faq_schema_in_static:
        gaps.append({"signal": "faq_text_visibility", "priority": "HIGH",
                      "detail": "FAQPage schema exists but FAQ text is NOT in static HTML — JS-only for visible text"})
    if not tldr_present:
        gaps.append({"signal": "tldr_block", "priority": "MEDIUM",
                      "detail": "No TL;DR or summary block — LLMs need quick-extract answer"})
    if h1_is_cta:
        gaps.append({"signal": "answer_first_h1", "priority": "HIGH",
                      "detail": f"H1 is CTA-style ('{h1_text[:60]}') instead of answer-first"})
    if not has_lists:
        gaps.append({"signal": "lists", "priority": "MEDIUM",
                      "detail": "No <ul>/<ol> lists in content — LLMs prefer structured content"})
    if not has_tables:
        gaps.append({"signal": "tables", "priority": "LOW",
                      "detail": "No data tables — useful for comparison/content extraction"})
    if not has_citations and not has_citation_mentions:
        gaps.append({"signal": "citations", "priority": "MEDIUM",
                      "detail": "No inline citations or source references — key for E-E-A-T and LLM citation"})
    if not has_author_meta and not has_author_bio:
        gaps.append({"signal": "author_info", "priority": "LOW",
                      "detail": "No author bio or credentials — weakens E-E-A-T for LLMs"})
    if not has_stats:
        gaps.append({"signal": "statistics", "priority": "MEDIUM",
                      "detail": "No statistical claims — LLMs love citing content with data"})

    # ─── Assemble report ─────────────────────────────────────────────
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "tool": "site_scraper.py --geo-check",
        "site": "aionAI",
        "source_files": {
            "index_html": INDEX_HTML.name if INDEX_HTML.exists() else None,
            "app_ts": APP_TS.name if APP_TS.exists() else None,
            "sections_analyzed": len(section_files),
            "llms_txt": llms_path.name if has_llms_txt else None,
        },
        "geo_signals": {
            "static_body_words": static_body_words,
            "faq_text_in_static_html": faq_text_in_static,
            "faq_schema_in_static_html": faq_schema_in_static,
            "tldr_present": tldr_present,
            "h1_text": h1_text,
            "h1_is_definitive": h1_is_definitive,
            "h1_is_cta": h1_is_cta,
            "list_count": {"ul": ul_count, "ol": ol_count, "total_items": list_items_total},
            "table_count": table_count,
            "citation_count": citation_count,
            "citation_keyword_mentions": citation_keyword_count,
            "author_meta": author_name if has_author_meta else None,
            "author_bio_section": has_author_bio,
            "stat_count": stat_count,
            "schema_types": schema_types,
            "llms_txt": {"exists": has_llms_txt, "lines": llms_lines, "has_pages_section": llms_has_pages},
            "meta_count": meta_count,
            "has_og_tags": has_og_tags,
            "has_twitter_tags": has_twitter_tags,
        },
        "geo_score": {
            "value": geo_score_pct,
            "components": scores,
            "max_possible": max_score,
        },
        "gaps": sorted(gaps, key=lambda g: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[g["priority"]]),
        "summary": (f"geo_score={geo_score_pct}/100 | "
                    f"gaps={len(gaps)} ({sum(1 for g in gaps if g['priority']=='CRITICAL')}C, "
                    f"{sum(1 for g in gaps if g['priority']=='HIGH')}H, "
                    f"{sum(1 for g in gaps if g['priority']=='MEDIUM')}M, "
                    f"{sum(1 for g in gaps if g['priority']=='LOW')}L)"),
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        if verbose:
            print(f"[verbose] GEO check saved to {output_path}", file=sys.stderr)

    if verbose:
        print(f"\n[verbose] GEO Score: {geo_score_pct}/100", file=sys.stderr)
        for g in report["gaps"]:
            print(f"  [{g['priority']}] {g['signal']}: {g['detail'][:80]}", file=sys.stderr)

    return report


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="site_scraper.py — Εξαγωγή περιεχομένου & seeds από aionAI.",
    )
    parser.add_argument("--extract", action="store_true", default=False,
                        help="Extract content from source files (default)")
    parser.add_argument("--health-check", type=str, default=None, metavar="URL",
                        help="Render Angular SPA and compare with source")
    parser.add_argument("--googlebot", type=str, default=None, metavar="URL",
                        help="Fetch with Googlebot UA and report visibility gap")
    parser.add_argument("--googlebot-rendered", type=str, default=None, metavar="URL",
                        help="Full Chromium render with Googlebot constraints")
    parser.add_argument("--validate-jsonld", type=str, default=None, metavar="URL",
                        help="Validate JSON-LD structured data")
    parser.add_argument("--batch-competitors", type=str, default=None, metavar="FILE",
                        help="Batch competitor analysis from file of URLs")
    parser.add_argument("--geo-check", action="store_true", default=False,
                        help="Analyze our own source code for GEO signals (no URL needed)")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file")
    parser.add_argument("--run-id", type=str, default=None, help="Pipeline run ID for Supabase insertion")
    parser.add_argument("--verbose", action="store_true", default=False, help="Print progress to stderr")
    return parser.parse_args(argv)


def run_batch_competitors(url_file: str, verbose: bool = False) -> list[dict]:
    """Read competitor URLs from file, run Googlebot fetch + JSON-LD validation on each."""
    try:
        urls_raw = Path(url_file).read_text("utf-8").splitlines()
    except FileNotFoundError:
        print(f"Error: File not found: {url_file}", file=sys.stderr)
        sys.exit(1)

    urls = []
    for line in urls_raw:
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)

    if not urls:
        print(f"Error: No URLs found in {url_file}", file=sys.stderr)
        sys.exit(1)

    results = []
    COMPETITOR_DIR.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls):
        if verbose:
            parsed = urlparse(url)
            domain = parsed.netloc
            print(f"\n[{i+1}/{len(urls)}] {domain}", file=sys.stderr)

        # Googlebot check
        html = fetch_as_googlebot(url)
        if html:
            view = extract_googlebot_view(html)
            safe_name = Path(urlparse(url).netloc.replace(".", "_")).stem
            gb_path = COMPETITOR_DIR / f"{safe_name}_googlebot.json"
            gb_path.write_text(json.dumps(view, ensure_ascii=False, indent=2), "utf-8")

            # JSON-LD validation
            json_ld = extract_json_ld(html)
            jl_issues = validate_jsonld(json_ld)
            jl_path = COMPETITOR_DIR / f"{safe_name}_jsonld.json"
            jl_path.write_text(json.dumps(jl_issues, ensure_ascii=False, indent=2), "utf-8")

            body = view.get("body", {})
            assessment = view.get("assessment", {})
            results.append({
                "url": url,
                "domain": safe_name,
                "body_words": body.get("word_count", 0),
                "has_spa_shell": body.get("has_app_root", False),
                "has_json_ld": assessment.get("json_ld_available", False),
                "jsonld_issues": len(jl_issues),
            })

            if verbose:
                print(f"  -> {body.get('word_count', 0)} body words", file=sys.stderr)

        time.sleep(0.5)

    # Save batch summary
    summary_path = COMPETITOR_DIR / "batch_summary.json"
    summary = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_competitors": len(results),
        "results": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return results


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)

    # Default: --extract if no other mode specified
    if not any([args.extract, args.health_check, args.googlebot,
                args.googlebot_rendered, args.validate_jsonld, args.batch_competitors,
                args.geo_check]):
        args.extract = True

    if args.extract:
        run_extract(output_path=args.output or "", verbose=args.verbose)
    elif args.health_check:
        # Requires Playwright
        run_health_check(args.health_check, args.output or "", args.verbose)
    elif args.googlebot:
        run_googlebot_check(args.googlebot, args.verbose, args.output or "", run_id=args.run_id or "")
    elif args.googlebot_rendered:
        run_googlebot_rendered(args.googlebot_rendered, args.verbose, args.output or "", run_id=args.run_id or "")
    elif args.validate_jsonld:
        run_jsonld_validation(args.validate_jsonld, args.verbose, args.output or "", run_id=args.run_id or "")
    elif args.batch_competitors:
        run_batch_competitors(args.batch_competitors, args.verbose)
    elif args.geo_check:
        run_geo_check(output_path=args.output or "", verbose=args.verbose)

    return 0


# ─── Async health check ─────────────────────────────────────────

def run_health_check(url: str, output_path: str = "", verbose: bool = False) -> dict:
    """Render the Angular SPA and compare with source extraction."""
    from playwright.async_api import async_playwright

    async def _render():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.6422.0 Mobile Safari/537.36"
                ),
                viewport={"width": 412, "height": 915},
                locale="el-GR",
                timezone_id="Europe/Athens",
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Give Angular time to bootstrap
            await page.wait_for_timeout(500)
            content = await page.content()
            await browser.close()
            return content

    if verbose:
        print(f"[verbose] Rendering {url} with Playwright...", file=sys.stderr)

    import asyncio
    try:
        rendered_html = asyncio.run(_render())
    except Exception as e:
        print(f"Error rendering: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract from rendered HTML
    rendered_view = extract_googlebot_view(rendered_html)
    source = run_extract(verbose=verbose)

    # Compare
    source_headings: set[str] = set()
    for s in source.get("sections", []):
        for h in s.get("headings", []):
            text = h.get("text", "").strip()
            if text:
                source_headings.add(text.lower())

    rendered_headings: set[str] = set()
    for h in rendered_view.get("body", {}).get("headings", []):
        text = h.get("text", "").strip()
        if text:
            rendered_headings.add(text.lower())

    missing_from_render = source_headings - rendered_headings

    render_word_count = rendered_view.get("body", {}).get("word_count", 0)
    source_word_count = source.get("word_count_clean", 0)
    efficiency = round(render_word_count / source_word_count * 100) if source_word_count > 0 else 0

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "target_url": url,
        "rendered": {
            "word_count": render_word_count,
            "heading_count": len(rendered_headings),
            "has_app_root": rendered_view.get("body", {}).get("has_app_root", False),
        },
        "source": {
            "word_count": source_word_count,
            "heading_count": len(source_headings),
        },
        "js_gap": {
            "missing_headings": list(missing_from_render)[:10],
            "missing_count": len(missing_from_render),
            "render_efficiency_pct": efficiency,
        },
        "health_score": round((render_word_count / source_word_count * 50 + 50) if source_word_count > 0 else 0),
    }

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        if verbose:
            print(f"[verbose] Saved to {output_path}", file=sys.stderr)
    return report


def run_googlebot_rendered(url: str, verbose: bool = False, output_path: str = "",
                            run_id: str = "") -> dict:
    """Full Chromium render with Googlebot-like constraints (5s timeout)."""
    from playwright.async_api import async_playwright

    async def _render():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.6422.0 Mobile Safari/537.36"
                ),
                viewport={"width": 412, "height": 915},
                locale="el-GR",
                timezone_id="Europe/Athens",
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                await page.wait_for_timeout(500)
                content = await page.content()
            except Exception:
                content = await page.content()
            await browser.close()
            return content

    if verbose:
        print(f"[verbose] Rendering {url} with Playwright (Googlebot constraints)...", file=sys.stderr)

    import asyncio
    source = run_extract(verbose=verbose)
    source_words = source.get("word_count_clean", 0)

    try:
        rendered_html = asyncio.run(_render())
        rendered_view = extract_googlebot_view(rendered_html)
        render_words = rendered_view.get("body", {}).get("word_count", 0)
        render_headings = len(rendered_view.get("body", {}).get("headings", []))
        source_headings_count = len(source.get("sections", []))
        efficiency = round(render_words / source_words * 100) if source_words > 0 else 0
    except Exception as e:
        if verbose:
            print(f"[verbose] Render failed: {e}", file=sys.stderr)
        rendered_view = {"body": {"word_count": 0, "headings": [], "has_app_root": True}}
        render_words = 0
        render_headings = 0
        efficiency = 0

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "target_url": url,
        "confidence": {"level": 70, "label": "MEDIUM", "reason": "Local Chromium has more resources than Googlebot's sandboxed render"},
        "rendered": {
            "word_count": render_words,
            "heading_count": render_headings,
        },
        "source": {
            "word_count": source_words,
            "heading_count": source_headings_count,
        },
        "js_gap": {
            "render_efficiency_pct": efficiency,
            "status": "success" if render_words > 0 else "failed",
        },
    }

    # Also add raw Googlebot view for comparison
    raw_html = fetch_as_googlebot(url)
    if raw_html:
        raw_view = extract_googlebot_view(raw_html)
        report["googlebot_raw"] = raw_view

    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)
    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        if verbose:
            print(f"[verbose] Saved to {output_path}", file=sys.stderr)

    # Write to Supabase if run_id provided
    if run_id:
        try:
            supabase = get_supabase()
            rendered_info = report.get("rendered", {})
            supabase.table("site_assessments").insert({
                "run_id": run_id,
                "assessment_type": "rendered",
                "score": rendered_info.get("word_count", 0),
                "verdict": report.get("js_gap", {}).get("status", ""),
                "word_count": rendered_info.get("word_count", 0),
                "data": report,
            }).execute()
            if verbose:
                print(f"[verbose] Written to Supabase site_assessments table (rendered)", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to write rendered to Supabase: {e}", file=sys.stderr)

    return report


if __name__ == "__main__":
    sys.exit(main())
