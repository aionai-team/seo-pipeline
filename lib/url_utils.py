#!/usr/bin/env python3
"""
url_utils.py — URL filtering, classification, and blocklist utilities.

Shared between serp_scraper.py and competitor_scraper.py.

Functions:
    load_blocklist(path)     -> (set[domain_patterns], list[path_patterns])
    is_blocked(url, domains, paths) -> bool
    classify_url(url, title) -> str (COMPETITOR|REDDIT|DIRECTORY|NEWS|YOUTUBE|WIKIPEDIA|SOCIAL|OTHER)
    extract_domain(url)      -> str
    is_competitor_candidate(url, title) -> bool (convenience wrapper)
"""

import re
from pathlib import Path
from urllib.parse import urlparse


# ─── Classification patterns ───────────────────────────────────

DIRECTORY_DOMAINS = {
    "clutch.co", "g2.com", "glassdoor.com", "capterra.com",
    "goodfirms.co", "trustpilot.com", "sitejabber.com",
    "sortlist.com", "designrush.com", "topseos.com",
}

SOCIAL_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "tiktok.com", "pinterest.com", "linkedin.com",
}

REDDIT_DOMAINS = {"reddit.com", "quora.com"}

WIKI_DOMAINS = {"wikipedia.org", "investopedia.com"}

NEWS_DOMAINS = {
    "forbes.com", "techcrunch.com", "medium.com", "wired.com",
    "venturebeat.com", "thenextweb.com", "zdnet.com",
    "cnet.com", "techradar.com", "bloomberg.com", "reuters.com",
}

YOUTUBE_DOMAINS = {"youtube.com", "youtu.be"}

BLOCKED_DOMAINS = {
    "github.com", "stackoverflow.com", "gitbook.com", "notion.so",
    "npmjs.com", "pypi.org", "docker.com",
}

# Combined blocklist domains (not competitors, no value as secondary)
NOISE_DOMAINS = BLOCKED_DOMAINS | {"facebook.com", "twitter.com", "x.com", "instagram.com", "tiktok.com"}


# ─── Helpers ───────────────────────────────────────────────────

def extract_domain(url: str) -> str:
    """Extract clean domain from URL, stripping www."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split("/")[0]
        return domain.removeprefix("www.").lower()
    except Exception:
        return ""


def _domain_matches(url_domain: str, blocked_domain: str) -> bool:
    """Check if url_domain matches a blocked domain (exact or subdomain)."""
    url_domain = url_domain.lower().strip(".")
    blocked_domain = blocked_domain.lower().strip(".")
    return url_domain == blocked_domain or url_domain.endswith("." + blocked_domain)


# ─── Blocklist ─────────────────────────────────────────────────

def load_blocklist(path: str | Path = None) -> tuple[set[str], list[re.Pattern]]:
    """
    Load blocklist from a text file.
    
    Lines starting with # are comments.
    Lines starting with / are path patterns (regex-escaped prefix match).
    Lines starting with ? are query patterns.
    Everything else is a domain.
    
    Returns (domains_set, path_patterns_list).
    """
    domains = set()
    path_patterns = []

    if path is None:
        path = Path(__file__).parent.parent / "blocklist.txt"

    path = Path(path)
    if not path.exists():
        return domains, path_patterns

    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments (everything after first #)
        clean = line.split("#")[0].strip()
        if not clean:
            continue
        if clean.startswith("/"):
            # Path pattern — escape regex special chars, treat as prefix
            escaped = re.escape(clean)
            path_patterns.append(re.compile(escaped))
        elif clean.startswith("?"):
            # Query parameter pattern
            escaped = re.escape(clean.replace("?", "", 1))
            path_patterns.append(re.compile(escaped, re.IGNORECASE))
        else:
            domains.add(clean.lower().strip())

    return domains, path_patterns


def is_blocked(url: str, blocked_domains: set[str] = None, path_patterns: list[re.Pattern] = None) -> bool:
    """Check if a URL matches the blocklist (domain or path)."""
    if not url:
        return True

    domain = extract_domain(url)

    # Domain check
    if blocked_domains:
        for bd in blocked_domains:
            if _domain_matches(domain, bd):
                return True

    # Path check
    if path_patterns:
        parsed = urlparse(url)
        path_qs = (parsed.path + "?" + parsed.query).lower() if parsed.query else parsed.path.lower()
        for pattern in path_patterns:
            if pattern.search(path_qs):
                return True

    return False


# ─── URL Classification ────────────────────────────────────────

def classify_url(url: str, title: str = "") -> str:
    """
    Classify a URL into a category.
    
    Returns: COMPETITOR | REDDIT | DIRECTORY | NEWS | YOUTUBE
             | WIKIPEDIA | SOCIAL | FORUM | BLOCKED | OTHER
    """
    domain = extract_domain(url)
    title_lower = title.lower()

    # Reddit / Quora
    if _domain_matches(domain, "reddit.com") or _domain_matches(domain, "quora.com"):
        return "REDDIT"

    # YouTube
    if _domain_matches(domain, "youtube.com") or _domain_matches(domain, "youtu.be"):
        return "YOUTUBE"

    # Wikipedia / Investopedia
    if any(_domain_matches(domain, w) for w in WIKI_DOMAINS):
        return "WIKIPEDIA"

    # Directories / review sites
    if any(_domain_matches(domain, d) for d in DIRECTORY_DOMAINS):
        return "DIRECTORY"

    # News
    if domain in NEWS_DOMAINS:
        return "NEWS"
    if any(_domain_matches(domain, n) for n in NEWS_DOMAINS):
        return "NEWS"

    # Social (non-Reddit)
    if any(_domain_matches(domain, s) for s in SOCIAL_DOMAINS):
        return "SOCIAL"

    # Blocked (no value)
    if domain in NOISE_DOMAINS:
        return "BLOCKED"

    # Forums
    if "/forum/" in url.lower():
        return "FORUM"

    # Check title for non-competitor signals
    if title_lower:
        non_comp_signals = ["wiki", "wikipedia", "investopedia", "dictionary", "definition"]
        for signal in non_comp_signals:
            if signal in title_lower:
                return "WIKIPEDIA"

    # Default: treat as potential competitor
    return "COMPETITOR"


def is_competitor_candidate(url: str, title: str = "") -> bool:
    """Quick check: is this URL worth crawling as a competitor?
    
    Checks against BOTH classify_url() AND blocklist.txt.
    """
    if classify_url(url, title) != "COMPETITOR":
        return False
    # Also check against blocklist.txt (covers edu.gr, gov.gr, Greek news, etc.)
    blocked_domains, path_patterns = load_blocklist()
    if is_blocked(url, blocked_domains, path_patterns):
        return False
    return True


# ─── URL scoring (simple heuristic) ───────────────────────────

def score_competitor_confidence(url: str, title: str = "") -> int:
    """
    Score 0-100 how likely this URL is a real competitor site.
    For non-binary filtering (vs. pass/fail).
    """
    score = 50  # neutral start
    
    domain = extract_domain(url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    
    # Root domain = more likely a real company
    if path in ("", "/", "/en", "/el"):
        score += 20
    elif len(path.split("/")) <= 3:
        score += 10  # shallow path
    
    # Check for agency/AI terms in title
    title_lower = title.lower()
    agency_terms = ["agency", "ai", "artificial intelligence", "digital", "technology",
                    "software", "consulting", "solutions", "ict"]
    term_count = sum(1 for t in agency_terms if t in title_lower)
    score += min(term_count * 5, 15)  # max +15
    
    # Check for Greek in title
    greek_pattern = re.compile(r'[α-ωΑ-ΩίϊΐόάέύϋήώΏ]')
    if greek_pattern.search(title_lower):
        score += 10  # Greek content = relevant to our market
    
    # Non-competitor signals
    non_comp = ["review", "vs ", "versus", "comparison", "alternatives", "top 10",
                "best ", "pricing", "price", "cost", "coupon"]
    for nc in non_comp:
        if nc in title_lower:
            score -= 10
            break
    
    return max(0, min(score, 100))


# ─── Intent classification (keyword level) ─────────────────────

def classify_keyword_intent(keyword: str) -> str:
    """
    Classify keyword intent: INFO | COMMERCIAL | TRANSACTIONAL | NAVIGATIONAL.
    Reuses the same logic as keyword_discovery.py's intent classifier.
    """
    kw = keyword.lower().strip()
    
    # NAVIGATIONAL — brand names
    nav_signals = ["aionai", "webout", "growl", "flipnewmedia", "connectingdots",
                   "notthesame", "softone", "cosmote"]
    if any(b in kw for b in nav_signals):
        return "NAVIGATIONAL"
    
    # TRANSACTIONAL — pricing, comparison, buying intent
    trans_signals = ["τιμή", "τιμές", "κόστος", "δωρεάν", "free", "pricing", "price",
                     "cost", "coupon", "vs", "versus", "εναλλακτικές", "σύγκριση",
                     "hire", "πρόσληψη", "αγορά", "buy", "πώληση"]
    if any(t in kw for t in trans_signals):
        return "TRANSACTIONAL"
    
    # COMMERCIAL — location, services, agency terms
    comm_signals = ["ελλάδα", "αθήνα", "θεσσαλονίκη", "υπηρεσίες", "υπηρεσία",
                    "services", "agency", "consulting", "εταιρεία", "εταιρία",
                    "πάροχος", "provider", "company", "service", "solution",
                    "εφαρμογή", "ολοκλήρωση", "υλοποίηση", "consultant"]
    if any(c in kw for c in comm_signals):
        return "COMMERCIAL"
    
    # INFO — educational, definition, guide
    info_signals = ["τι είναι", "οδηγός", "παράδειγμα", "παραδείγματα", "ορισμός",
                    "ορισμό", "tutorial", "guide", "examples", "example", "definition",
                    "course", "μαθήματα", "εκπαίδευση", "πως", "πώς",
                    "explain", "explained", "what is", "what does", "how to"]
    if any(i in kw for i in info_signals):
        return "INFO"
    
    # Default: INFO
    return "INFO"


# ─── Quick test ────────────────────────────────────────────────

if __name__ == "__main__":
    # Self-test
    test_urls = [
        ("https://www.reddit.com/r/smallbusiness/", "Small business AI", "REDDIT"),
        ("https://clutch.co/agencies/ai", "Top AI agencies", "DIRECTORY"),
        ("https://medium.com/@user/ai-trends", "AI trends 2026", "NEWS"),
        ("https://youtube.com/watch?v=123", "AI tutorial", "YOUTUBE"),
        ("https://en.wikipedia.org/wiki/Artificial_intelligence", "AI wiki", "WIKIPEDIA"),
        ("https://example-agency.gr/", "AI Agency Athens", "COMPETITOR"),
        ("https://example-agency.gr/services/", "Services | Example Agency", "COMPETITOR"),
        ("https://example-agency.gr/blog/page/2/", "Blog", "COMPETITOR"),
        ("https://forbes.com/sites/ai", "AI trends forbes", "NEWS"),
    ]
    for url, title, expected in test_urls:
        result = classify_url(url, title)
        status = "✓" if result == expected else "✗"
        print(f"{status} {result:12s} ← {url[:60]}")
    print(f"\nBlocklist test:")
    blocked_domains, path_patterns = load_blocklist()
    print(f"  {len(blocked_domains)} blocked domains, {len(path_patterns)} path patterns loaded")
    print(f"  Reddit blocked? {is_blocked('https://reddit.com/r/ai', blocked_domains, path_patterns)}")
    print(f"  Job path blocked? {is_blocked('https://agency.gr/jobs/', blocked_domains, path_patterns)}")
    print(f"  Agency blocked? {is_blocked('https://agency.gr/', blocked_domains, path_patterns)}")
    print(f"\nCompetitor confidence scoring:")
    print(f"  example-agency.gr → {score_competitor_confidence('https://example-agency.gr/', 'AI Agency Athens')}/100")
    print(f"  review.com/best-ai → {score_competitor_confidence('https://review.com/best-ai', 'Best AI Tools Review')}/100")
