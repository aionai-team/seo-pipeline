#!/usr/bin/env python3

"""
keyword_discovery.py — Ανακάλυψη ελληνικών business/AI keywords.

Χρησιμοποιεί Google Suggest API (free, no CAPTCHA) για να βρει
τι πραγματικά ψάχνουν Έλληνες επιχειρηματίες.

Στρατηγική:
  1. Short seeds (1-3 λέξεις) από τις υπηρεσίες της aionAI
  2. Google Suggest τα επεκτείνει σε 10 suggestions το καθένα
  3. Relevance filter κρατάει μόνο business/AI σχετικά queries
  4. Output σε JSON — έτοιμο για pytrends validation (Script #2)

Usage examples:
    python keyword_discovery.py                        # built-in seeds
    python keyword_discovery.py "ai agents"             # one custom seed
    python keyword_discovery.py --seed-file seeds.txt   # custom seed list
    python keyword_discovery.py --list-seeds            # show built-in seeds
    python keyword_discovery.py --parse-site ../ai_site/src/index.html
    python keyword_discovery.py --output results.json

Requirements:
    requests>=2.28.0
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
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests

from lib.supabase_client import get_supabase, create_pipeline_run

# ─── Built-in seeds ───────────────────────────────────────────────────────
# Derived from aionAI's services, FAQ, meta, and use cases.
# SHORT seeds only (1-3 words) — Google Suggest returns 0 for longer.
# Each seed expands to ~5-10 suggestions via the API.

AIONAI_SEEDS = sorted(set([
    # --- Core English terms (Google Suggest works great) ---
    "ai agents",
    "ai consulting",
    "ai automation",
    "chatbot",
    "workflow automation",
    "business automation",

    # --- Greek terms ---
    "αυτοματοποίηση",
    "τεχνητή νοημοσύνη",
    "ψηφιακός μετασχηματισμός",

    # --- Greek + business intent (high-value!) ---
    "ai επιχειρήσεις",
    "ai ελλάδα",
    "ai αθήνα",
    "ai υπηρεσίες",

    # --- Specific services ---
    "τιμολόγια",
    "voicebot",
    "ai customer service",
    "ai sales",

    # --- Industries we serve (SME focus) ---
    "εστιατόρια",
    "καταστήματα",
    "δικηγορικά",
    "e commerce",
    "logistics",
]))

# Relevance filter — keep suggestions that match ANY of these terms.
# These define what's "about us" (AI + business + automation for Greek SMEs).
RELEVANCE_TERMS = [
    # Primary: AI & automation
    "τεχνητή νοημοσύνη", "τεχνητη", "νοημοσυνη", "νοημοσύνη",
    "ai ", "artificial intelligence",
    "agent", "automation", "automatio",
    "chatbot", "chat bot",
    "machine learning",

    # Business & enterprise (Greek)
    "επιχείρησ", "εταιρεί", "εταιρί",
    "οργανισμ", "εταιρει",
    "μικρομεσαί", "μικρεσ", "μμ",
    "πελάτ", "εξυπηρέτησ", "υπηρεσί",
    "τιμολογ", "παραστατικ",
    "email", "e-mail",

    # Business problems we solve
    "αυτοματοποι", "αυτόματ",
    "αυτοματισμ",
    "κόστο", "χρόνο", "απόδοσ",
    "ψηφιακ", "μετασχηματισμ",
    "βελτιώσ", "μείωσ", "εξοικονομ",
    "ρομποτική", "ρομποτικ",

    # Professions & industries
    "ιατρεί", "δικηγορ",
    "logistics", "e-commerce", "ecommerc",
    "ιατρ", "φαρμακεί",

    # Tools & tech
    "εργαλεί", "λύσει",
    "δεδομέν", "πληροφορί",
    "πωλήσει", "μάρκετινγκ", "marketing",

    # Decision keywords (intent)
    "δωρεάν", "τιμη", "τιμή",
    "προσφορ", "καλύτερ",
    "πιστοποιητ", "εκπαίδευσ",
    "σεμινάρ",

    # English business terms (mix with Greek queries)
    " for business", " for small",
    " cost", " price", " free",
    " consulting", " services",
    " integration", " development",
    " workflow", " process",
]

# Greek question word detector
QUESTION_RE = re.compile(
    r"(^|[\s,;])(τι|πώς|ποια|γιατί|ποιος|πόσο|που|πότε|"
    r"μπορώ|θέλω|πρέπει|υπάρχει|χρειάζεται|"
    r"είναι|έχει|γίνεται|λέγεται|ορίζεται|σημαίνει|"
    r"κάνει|αξίζει|μπορεί|προσφέρει|βοηθάει)([\s?]|$)",
    re.IGNORECASE,
)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
)


# ─── API call ─────────────────────────────────────────────────────────────

def build_suggest_url(query: str) -> str:
    encoded = quote_plus(query)
    return (
        f"https://suggestqueries.google.com/complete/search"
        f"?output=toolbar&hl=el&gl=gr&q={encoded}"
    )


def fetch_suggestions(query: str, timeout: int = 10) -> list[str]:
    """Call Google Suggest API, return raw suggestion strings."""
    url = build_suggest_url(query)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
        "Accept": "text/xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)
    suggestions: list[str] = []
    for complete_suggestion in root.findall(".//CompleteSuggestion"):
        suggestion_elem = complete_suggestion.find("suggestion")
        if suggestion_elem is not None:
            data = suggestion_elem.get("data", "")
            if data:
                suggestions.append(data)
    return suggestions


# ─── Filtering ────────────────────────────────────────────────────────────

def looks_like_question(text: str) -> bool:
    return bool(QUESTION_RE.search(text))


def is_relevant(text: str) -> bool:
    """Keep suggestions related to AI/business — our niche."""
    text_lower = text.lower().strip()

    if len(text_lower) < 4:
        return False

    for term in RELEVANCE_TERMS:
        if term.lower() in text_lower:
            return True
    return False


# ─── Intent classification ────────────────────────────────────────────────

# Patterns that determine keyword intent
INTENT_PATTERNS = {
    "NAVIGATIONAL": [
        r"\baionai\b", r"\baion ai\b",
        r"\bwebout\b", r"\bgrowl\b", r"\bconnectingdots\b",
        r"\bflipnewmedia\b", r"\baiagency\b",
        r"\blogin\b", r"\bsign\s*in\b", r"\blog\s*in\b",
        r"^\w+\.gr$", r"^\w+\.com$",
    ],
    "TRANSACTIONAL": [
        r"\bτιμή\b", r"\bτιμέ\b", r"\bκόστο\b", r"\bκόστος\b",
        r"\bπόσο\b", r"\bπροσφορ\b", r"\bδωρεάν\b",
        r"\bαγορά\b", r"\bαγοράσ\b", r"\bπαραγγελ\b",
        r"\bκαλύτερ\b", r"\bfree\b", r"\bprice\b", r"\bcost\b",
        r"\bbuy\b", r"\btrial\b", r"\bdemo\b", r"\bquote\b",
        r"\bσύγκριση\b", r"\bσυγκρι\b", r"\bvs\b",
        r"\bπάροχο\b", r"\bπάροχος\b",
    ],
    "COMMERCIAL": [
        r"\bυπηρεσί\b", r"\bυπηρεσία\b",
        r"\bεταιρεί\b", r"\bεταιρί\b", r"\bεταιρεία\b", r"\bεταιρειεσ\b",
        r"\bπάροχο\b", r"\bπάροχος\b",
        r"\bconsulting\b", r"\bagency\b", r"\bservices\b",
        r"\bελλάδα\b", r"\bελλαδα\b", r"\bελάδα\b",
        r"\bαθήνα\b", r"\bαθηνα\b", r"\bathens\b",
        r"\bgreece\b",
        r"\bγια επιχειρήσει\b", r"\bγια μικρομεσαί\b",
        r"\bεφαρμογή\b", r"\bεφαρμογέ\b", r"\bλύση\b", r"\bλύσει\b",
        r"\bintegration\b", r"\bενσωμάτωσ\b",
        r"\bautomation\b", r"\bαυτοματοποι\b",
        r"\bagent\b", r"\bagents\b",
        r"\bimplementation\b", r"\bdeployment\b",
        r"\bdigital\b",
        r"\bελληνικ\b",
    ],
}

# Compile all intent patterns
INTENT_RE = {}
for intent, patterns in INTENT_PATTERNS.items():
    INTENT_RE[intent] = re.compile(
        "|".join(patterns), re.IGNORECASE
    )


def classify_intent(query: str) -> str:
    """Classify keyword into: INFO, COMMERCIAL, TRANSACTIONAL, NAVIGATIONAL.

    Order matters: NAVIGATIONAL > TRANSACTIONAL > INFO (educational) > COMMERCIAL > INFO.
    """
    q_lower = query.lower().strip()

    # 0. Educational keywords override commercial — these are INFO even if they match COMMERCIAL
    educational_patterns = [
        r"\bcourse\b", r"\bcourses\b", r"\btutorial\b",
        r"\bexamples\b", r"\bexample\b",
        r"\bοδηγός\b", r"\bοδηγοσ\b",
        r"\bπαράδειγμα\b", r"\bπαραδειγμα\b",
        r"\bεκπαίδευσ\b", r"\bμαθήμα\b",
        r"\bforum\b",
        r"\bτι είναι\b", r"\bτι ειναι\b",
        r"\bορισμό\b", r"\bορισμοσ\b",
        r"\bσημαίνει\b",
    ]
    if any(re.search(p, q_lower) for p in educational_patterns):
        # But if it's also transactional (cost/price), keep it transactional
        if INTENT_RE["TRANSACTIONAL"].search(q_lower):
            return "TRANSACTIONAL"
        return "INFO"

    # 1. Check NAVIGATIONAL first (specific brand/company queries)
    if INTENT_RE["NAVIGATIONAL"].search(q_lower):
        return "NAVIGATIONAL"

    # 2. Check if it's a question → usually INFORMATIONAL
    if looks_like_question(query):
        if INTENT_RE["TRANSACTIONAL"].search(q_lower):
            return "TRANSACTIONAL"
        return "INFO"

    # 3. Check TRANSACTIONAL (buying intent)
    if INTENT_RE["TRANSACTIONAL"].search(q_lower):
        return "TRANSACTIONAL"

    # 4. Check COMMERCIAL (research/comparison intent)
    if INTENT_RE["COMMERCIAL"].search(q_lower):
        return "COMMERCIAL"

    # 5. Default: INFORMATIONAL
    return "INFO"


# ─── Process one seed ─────────────────────────────────────────────────────

def process_seed(
    seed: str,
    seen: set[str],
    verbose: bool = False,
) -> list[dict]:
    """Run Google Suggest for one seed. Returns [{query, question}]."""
    entries: list[dict] = []

    queries_to_try = [seed]
    # Also try "τι" prefix if it makes sense
    if not seed.lower().startswith("τι") and len(seed) < 20:
        queries_to_try.append(f"τι {seed}")

    for q in queries_to_try:
        if verbose:
            print(f"  Suggest: '{q}'", file=sys.stderr)

        try:
            suggestions = fetch_suggestions(q)
        except requests.exceptions.RequestException as e:
            if verbose:
                print(f"    -> failed: {e}", file=sys.stderr)
            continue

        if verbose:
            print(f"    -> {len(suggestions)} suggestions", file=sys.stderr)

        for suggestion in suggestions:
            norm = suggestion.lower().strip()
            if norm in seen:
                continue
            seen.add(norm)

            if not is_relevant(suggestion):
                continue

            entries.append({
                "query": suggestion,
                "question": looks_like_question(suggestion),
                "intent": classify_intent(suggestion),
            })

        time.sleep(0.2)

    return entries


# ─── Site content parser ──────────────────────────────────────────────────

def parse_seeds_from_site(html_path: str) -> list[str]:
    """Extract seed candidates from aionAI's index.html."""
    seeds: list[str] = []
    try:
        content = Path(html_path).read_text("utf-8")
    except (FileNotFoundError, OSError):
        print(f"[warn] Site file not found: {html_path}", file=sys.stderr)
        return seeds

    # meta keywords
    m = re.search(
        r'<meta\s+name="keywords"\s+content="([^"]+)"', content, re.IGNORECASE
    )
    if m:
        for kw in m.group(1).split(","):
            kw = kw.strip()
            if kw and len(kw.split()) <= 3:  # keep short only
                seeds.append(kw)

    # FAQ questions — extract question names from JSON-LD
    for qm in re.finditer(
        r'"name"\s*:\s*"([^"]+)"\s*,\s*"acceptedAnswer"', content
    ):
        q = qm.group(1)
        if len(q.split()) <= 5:  # keep reasonable length
            seeds.append(q)

    return list(dict.fromkeys(seeds))  # dedup preserve order


# ─── CLI ──────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="keyword_discovery.py — Ανακάλυψη ελληνικών business/AI keywords.",
    )
    parser.add_argument(
        "keyword",
        type=str,
        nargs="?",
        default=None,
        help="Seed keyword. If omitted, uses built-in aionAI seeds.",
    )
    parser.add_argument(
        "--seed-file",
        type=str,
        default=None,
        help="File with one seed per line (overrides built-in)",
    )
    parser.add_argument(
        "--parse-site",
        type=str,
        default=None,
        metavar="PATH",
        help="Parse aionAI index.html for seeds, then run discovery",
    )
    parser.add_argument(
        "--list-seeds",
        action="store_true",
        default=False,
        help="Print built-in seeds and exit",
    )
    parser.add_argument(
        "--max-per-seed",
        type=int,
        default=10,
        help="Max suggestions per seed (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file path (default: stdout only)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print progress to stderr",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Supabase pipeline run ID (creates one if not provided)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.list_seeds:
        print("=== Built-in aionAI seeds ===")
        for s in AIONAI_SEEDS:
            print(f"  {s}")
        return 0

    # Determine seeds
    seeds: list[str] = []

    if args.parse_site:
        seeds = parse_seeds_from_site(args.parse_site)
        if not seeds:
            print(f"Error: No seeds found in {args.parse_site}", file=sys.stderr)
            return 1
        if args.verbose:
            print(f"[verbose] Extracted {len(seeds)} seeds from site", file=sys.stderr)

    elif args.seed_file:
        try:
            seeds = [
                line.strip() for line in
                Path(args.seed_file).read_text("utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
        except FileNotFoundError:
            print(f"Error: Seed file not found: {args.seed_file}", file=sys.stderr)
            return 1

    elif args.keyword:
        seeds = [args.keyword.strip()]

    else:
        seeds = AIONAI_SEEDS.copy()

    if not seeds:
        print("Error: No seeds provided.", file=sys.stderr)
        return 1

    # Run discovery
    all_keywords: list[dict] = []
    seen: set[str] = set()
    seeds_done = 0

    for seed in seeds:
        if args.verbose:
            print(f"\n[verbose] [{seeds_done + 1}/{len(seeds)}] '{seed}'", file=sys.stderr)

        entries = process_seed(seed, seen, verbose=args.verbose)

        for entry in entries[:args.max_per_seed]:
            all_keywords.append(entry)

        seeds_done += 1

    # Intent breakdown
    intent_counts: dict[str, int] = {}
    for kw in all_keywords:
        intent = kw["intent"]
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seeds_used": seeds_done,
        "total_keywords": len(all_keywords),
        "intent_breakdown": {
            "INFO": intent_counts.get("INFO", 0),
            "COMMERCIAL": intent_counts.get("COMMERCIAL", 0),
            "TRANSACTIONAL": intent_counts.get("TRANSACTIONAL", 0),
            "NAVIGATIONAL": intent_counts.get("NAVIGATIONAL", 0),
        },
        "keywords": all_keywords,
        "source": "google_suggest_api",
    }

    output = json.dumps(data, ensure_ascii=False, indent=2)
    print(output)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)

    # ─── Supabase write ────────────────────────────────────────────────
    try:
        supabase = get_supabase()
        run_id = args.run_id
        if run_id is None:
            run_id = create_pipeline_run(
                supabase,
                run_date=time.strftime("%Y-%m-%d"),
                seeds_used=seeds_done,
            )
        # Insert each keyword into 'keywords' table
        for kw in all_keywords:
            supabase.table("keywords").insert({
                "run_id": run_id,
                "query": kw["query"],
                "intent": kw["intent"],
                "is_question": kw["question"],
            }).execute()
        # Update seeds_used in pipeline_runs
        supabase.table("pipeline_runs").update({"seeds_used": seeds_done}).eq("id", run_id).execute()
        if args.verbose:
            print(f"[verbose] Written {len(all_keywords)} keywords to Supabase (run_id={run_id})", file=sys.stderr)
    except Exception as e:
        print(f"[warn] Supabase write failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
