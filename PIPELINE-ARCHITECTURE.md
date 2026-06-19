# PIPELINE ARCHITECTURE — SEO/GEO for aionAI

> Αναλυτική τεκμηρίωση κάθε script, των δεδομένων που παράγει, και της ροής μεταξύ τους.
> Τελευταία ενημέρωση: 2026-06-17

---

## Πίνακας Περιεχομένων

1. [Επισκόπηση Πιπελίνου](#1-επισκόπηση-πιπελίνου)
2. [Αποθήκευση Δεδομένων](#2-αποθήκευση-δεδομένων)
3. [Φάση 1 — Keyword Discovery & Trend Validation](#3-φάση-1--keyword-discovery--trend-validation)
4. [Φάση 2 — SERP Collection (Google URLs)](#4-φάση-2--serp-collection-google-urls)
5. [Φάση 3 — Competitor Analysis](#5-φάση-3--competitor-analysis)
6. [Φάση 4 — Gap Analysis](#6-φάση-4--gap-analysis)
7. [Φάση 5 — Self-Assessment (Monitoring Loop)](#7-φάση-5--self-assessment-monitoring-loop)
8. [Φάση 6 — Comparison Report](#8-φάση-6--comparison-report)
9. [GEO Analysis Pipeline](#9-geo-analysis-pipeline)
10. [Tools & Utilities](#10-tools--utilities)
11. [Πίνακας Scores — Quick Reference](#11-πίνακας-scores--quick-reference)
12. [Πίνακας Cadence](#12-πίνακας-cadence)
13. [Current State Snapshot](#13-current-state-snapshot)
14. [Γνωστά Bugs & Issues](#14-γνωστά-bugs--issues)

---

## 1. Επισκόπηση Πιπελίνου

```
ΦΑΣΗ 1 (SAFE)
  keyword_discovery.py ──────────→ keywords.json  [Google Suggest API, free, no CAPTCHA]
       │                                ↓
       └── trend_validator.py ──────→ ranked.json  [pytrends, geo=GR, min-score filter]
                                            ↓
ΦΑΣΗ 2 (RISKY — CAPTCHA πιθανό)
  serp_scraper.py --intent-filter COMMERCIAL,TRANSACTIONAL
       │  (Playwright stealth, 8-layer anti-detection)
       │                                ↓
       │                           serp.json
       │  ┌───────────────────────────┤
       │  │                           │
       ↓  ↓                           ↓
ΦΑΣΗ 3 (SAFE — requests)
  competitor_scraper.py        secondary_extractor.py
  (site structure + GEO        (Reddit/Quora/Directory/News
   signals extraction)          intelligence)
       ↓                           ↓
  competitors.json             secondary.json
  competitors_with_geo.json
       ↓
ΦΑΣΗ 4 (SAFE — local calc)
  gap_scorer.py
  (trend × 1/(agency+1) × mismatch_bonus)
       ↓
  gap_report.json
       ↓
ΦΑΣΗ 5 (SAFE — monitoring loop)
  site_scraper.py:
    ├── --googlebot (curl)         → gap_report.json    [Googlebot raw view]
    ├── --googlebot-rendered       → rendered_report.json [Playwright 5s JS render]
    ├── --validate-jsonld          → jsonld_validation.json
    ├── --geo-check                → geo_self_check.json
    └── --batch-competitors        → competitors/*.json
       ↓
ΦΑΣΗ 6 (SAFE)
  comparison_report.py
  (Googlebot views comparison)
       ↓
  comparison_report.json
       ↓
GEO PIPELINE
  citation_scraper.py              [Google brand proxy για AI engines]
       ↓
  geo_market_analysis.py           [lib/geo_scorer.py — unified scoring]
       ↓
  geo_gap_scorer.py
       ↓
  geo_market.json + geo_gaps.json
       ↓
TOOLS
  generate_status.py → status.json [το πρώτο file που διαβάζεις κάθε session]
  organize_data.py → ενημερώνει data/latest/ symlinks
```

---

## 2. Αποθήκευση Δεδομένων

```
data/
├── latest/                    # Symlinks — δείχνουν πάντα στο πιο πρόσφατο run
│   ├── keywords.json
│   ├── ranked.json
│   ├── serp.json
│   ├── competitors.json
│   ├── secondary.json
│   ├── gap_report.json
│   ├── comparison_report.json
│   ├── geo_market.json
│   ├── geo_gaps.json
│   ├── geo_self_check.json
│   ├── geo_report.json
│   ├── citation_report.json
│   ├── jsonld_validation.json
│   ├── googlebot_view.json
│   ├── rendered_report.json
│   └── status.json
├── runs/
│   ├── 2026-06-13/
│   ├── 2026-06-14/
│   ├── 2026-06-14-full/
│   └── 2026-06-15/          # Τελευταίο πλήρες run
│       ├── keywords.json
│       ├── ranked.json
│       ├── serp.json
│       ├── competitors.json
│       ├── competitors_with_geo.json
│       ├── geo_report.json
│       ├── geo_self_check.json
│       └── ...
├── competitors/              # Shared — googlebot views από batch-competitors
│   ├── batch_summary.json
│   ├── aiagency_gr_googlebot.json
│   └── ...
└── organize_data.py
```

**Κανόνας:** Διάβαζε από `data/latest/`, γράφε σε `data/runs/YYYY-MM-DD/`, τρέχε `organize_data.py` μετά.

---

## 3. Φάση 1 — Keyword Discovery & Trend Validation

---

### 3a. `keyword_discovery.py`

**Ρόλος:** Παραγωγή ελληνικών business/AI keywords από Google Suggest API.

**Tool:** `analysis/keyword_discovery.py`

**Method:** Google Suggest API (`suggestqueries.google.com/complete/search?output=toolbar&hl=el&gl=gr`)
— δωρεάν, no CAPTCHA, no API key.

**Input:** Seeds (μία από):

| Πηγή | Flag | Παράδειγμα |
|---|---|---|
| Built-in seeds (20) | (default) | ai agents, chatbot, crm, erp, softone, αυτοματοποίηση, κλπ |
| Parse from site | `--parse-site <path>` | Διαβάζει meta keywords & FAQ από index.html |
| Custom file | `--seed-file <file>` | Ένα seed ανά γραμμή, # για σχόλια |
| CLI argument | `python keyword_discovery.py "ai agents"` | Ένα custom seed |

**Output file:** `keywords.json`

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "seeds_used": 20,
  "total_keywords": 148,
  "intent_breakdown": {
    "INFO": 99,
    "COMMERCIAL": 45,
    "TRANSACTIONAL": 4,
    "NAVIGATIONAL": 0
  },
  "keywords": [
    {
      "query": "ai agents",
      "question": false,
      "intent": "COMMERCIAL"
    },
    {
      "query": "ai agents τι ειναι",
      "question": true,
      "intent": "INFO"
    }
  ]
}
```

**Intent classification** (heuristic — pattern-based, no API):

| Intent | Triggers | Παράδειγμα |
|---|---|---|
| `INFO` | course, examples, οδηγός, forum, τι ειναι, ορισμός | "ai agents τι ειναι" |
| `COMMERCIAL` | ελλάδα, αθήνα, υπηρεσίες, consulting, agency, services | "ai agents ελλαδα" |
| `TRANSACTIONAL` | τιμή, δωρεάν, vs, free, price, cost, comparison | "ai agents free" |
| `NAVIGATIONAL` | Brand names (aionai, softone, webout) | "softone" |

**ΠΡΟΣΟΧΗ:**
- Long seeds (4+ λέξεις) → 0 suggestions. Κράτα 1-3 λέξεις.
- Μην χρησιμοποιείς generic AI seeds (καταλήγουν σε saturated keywords).
- Ιδανικά: seeds από competitor H1/H2 headings (η ανακάλυψη 2026-06-15).
- Τρέχε κάθε 4-6 εβδομάδες.

---

### 3b. `trend_validator.py`

**Ρόλος:** Validation trend όγκου για κάθε keyword (pytrends, geo=GR).

**Tool:** `analysis/trend_validator.py`

**Method:** pytrends, 12-month weekly data, `hl=el-GR`, `tz=360`, `geo=GR`.

**Input:** Ένα από:
- JSON από keyword_discovery.py (`--input keywords.json`)
- Plain text (μία λέξη ανά γραμμή)

**Output file:** `ranked.json`

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "total": 38,
  "source": "trend_validator.py",
  "min_score": 3,
  "results": [
    {
      "query": "ai agents",
      "trend_score": 54.2,
      "trend_direction": "rising",
      "percent_change": 12.5,
      "peak_month": "2026-03",
      "intent": "COMMERCIAL"
    }
  ]
}
```

**Fields & interpretation:**

| Field | Τιμή | Τι σημαίνει |
|---|---|---|
| `trend_score` | 0-100 | Μέσος όρος pytrends τους τελευταίους 12 μήνες. 0 = zero volume, >50 = high |
| `trend_direction` | `rising` / `falling` / `stable` | Κατεύθυνση trend (σύγκριση 3-month windows) |
| `percent_change` | -100 έως +∞ | % μεταβολή (3-month τώρα vs 3-month πριν) |
| `peak_month` | "YYYY-MM" | Μήνας με την υψηλότερη κορυφή |
| `intent` | INFO/COMMERCIAL/... | Pass-through από keyword_discovery.py |

**Thresholds:**

| Παράμετρος | Τιμή | Σχόλιο |
|---|---|---|
| `--min-score` | 3 (default) | Φιλτράρει keywords με trend_score < 3. Για Ελληνικά niche: χρήση 0 ή 1 |
| Rate limit | 1.2s μεταξύ calls | Αποφυγή 429 |
| Retry | exponential backoff | Σε 429 |

**ΠΡΟΣΟΧΗ:**
- pytrends για Ελλάδα έχει sparse data. `--min-score 3` κρατάει μόνο ~5% (15/277 σε competitor run).
- Για Ελληνικά: `--min-score 0` ή `1`. Φιλτράρισμα με intent αντί για score.
- `Path.home()` → profile home, όχι system home. Χρήση hardcoded paths.

---

## 4. Φάση 2 — SERP Collection (Google URLs)

### 4a. `serp_scraper.py`

**Ρόλος:** Εξαγωγή Google SERP URLs με classification και rank position.

**Tool:** `scrapers/serp_scraper.py`

**Method:** Playwright stealth με 8-layer anti-detection + CAPTCHA handling.

**Input:** JSON file με `results` array (output από trend_validator.py — `ranked.json`).

**Output file:** `serp.json`

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "total_keywords": 8,
  "successful": 8,
  "blocked": 0,
  "results": [
    {
      "keyword": "logistics",
      "trend_score": 67.6,
      "trend_direction": "falling",
      "organic_urls": [
        {
          "position": 1,
          "title": "Logistics: Τι είναι...",
          "url": "https://cears.edu.gr/...",
          "type": "COMPETITOR"
        }
      ],
      "total_urls": 7,
      "status": "success",
      "competitors": [
        {
          "position": 1,
          "title": "Logistics: Τι είναι...",
          "url": "https://cears.edu.gr/...",
          "type": "COMPETITOR"
        }
      ],
      "classification": {
        "COMPETITOR": 7,
        "BLOCKED": 1
      },
      "total_competitors": 7
    }
  ]
}
```

**URL Classification Types** (από `url_utils.py`):

| Type | Παραδείγματα | Handling |
|---|---|---|
| `COMPETITOR` | business sites, agency sites | Πάει σε competitor_scraper |
| `REDDIT` | reddit.com/r/... | Πάει σε secondary_extractor |
| `DIRECTORY` | clutch.co, g2.com, yuboto.gr | Πάει σε secondary_extractor |
| `NEWS` | ot.gr, news247.gr | Πάει σε secondary_extractor |
| `YOUTUBE` | youtube.com | Πάει σε secondary_extractor |
| `WIKIPEDIA` | wikipedia.org | Penalty στο gap scoring |
| `SOCIAL` | facebook.com, linkedin.com | Πάει σε secondary_extractor |
| `BLOCKED` | Blocklisted domains | Αγνοείται |
| `FORUM` | quora.com, stackoverflow.com | Πάει σε secondary_extractor |
| `OTHER` | Anything else | Αγνοείται |

**Flags:**

| Flag | Τι κάνει |
|---|---|
| `--intent-filter COMMERCIAL,TRANSACTIONAL` | Skip INFO/NAVIGATIONAL keywords πριν καν request |
| `--max-runs 5` | Πόσα keywords να τρέξει (default: 3 — για προστασία IP) |
| `--input <file>` | JSON input |
| `--output <file>` | JSON output |

**Stealth layers:**
1. WebDriver hiding (Object.defineProperty + prototype deletion)
2. Chrome runtime emulation (chrome.* API)
3. 4-plugin spoofing (PDF, PDF Viewer, Native Client, Widevine CDM)
4. Language & platform (navigator.languages, 'Win32', random UA)
5. Hardware fingerprint (8 cores, 8GB RAM, 0 touch points)
6. WebGL vendor spoofing ("Google Inc. (Intel)")
7. Canvas fingerprint noise (±1-bit noise, ~5% pixels)
8. Screen specifics (24-bit color depth)

**Human-like behavior:**
- Typing: 30-80ms ανά key
- Mouse: random path πριν submit, 5-15 steps, small jitter
- Submit: 50/50 Enter ή click
- Viewport: 7 presets με ±20px jitter
- Geolocation: Athens (37.9838, 23.7275), locale el-GR
- Inter-search delay: 15-25s random

**CAPTCHA handling:**
- Ανίχνευση `sorry.google.com` redirect → wait 5-8s, retry μία φορά
- Αν ακόμα blocked → `status: "blocked"` — skip, μην ξαναδοκιμάσεις
- Δεν ξαναδοκιμάζουμε ίδιο keyword στο ίδιο 24ωρο

**ΠΡΟΣΟΧΗ — Volume Control:**
- Fresh IP: 3-4 keywords πρώτη φορά, μετά 5-8/ημέρα max
- Αν IP αλλάξει (Cosmote residential rotates) → block εξαφανίζεται
- Check IP: `curl -s https://api.ipify.org?format=text`
- Μην ξεπερνάς 10 searches/ημέρα από μία IP

---

## 5. Φάση 3 — Competitor Analysis

### 5a. `competitor_scraper.py`

**Ρόλος:** Εξαγωγή δομής και GEO signals από competitor sites.

**Tool:** `scrapers/competitor_scraper.py`

**Method:** `requests` (no browser, no CAPTCHA risk). Blocklist filter από `url_utils.py`.

**Input:** SERP JSON (από serp_scraper.py). Χρησιμοποιεί `competitors[]` array (προ-φιλτραρισμένο).

**Flags:**

| Flag | Τι κάνει |
|---|---|
| `--input <file>` | SERP JSON |
| `--output <file>` | Output file |
| `--no-filter` | Skip blocklist filter |
| `--verbose` | Detailed output |

**Output file:** `competitors.json` (basic) + `competitors_with_geo.json` (enhanced)

**Output schema (competitors_with_geo.json):**
```json
[
  {
    "url": "https://cears.edu.gr/logistics-ti-einai/",
    "meta_title": "...",
    "meta_description": "...",
    "headings": {
      "h1": 1,
      "h2": 5,
      "h3": 12
    },
    "word_count": 3849,
    "jsonld_types": ["FAQPage", "Organization"],
    "has_faq_schema": true,
    "geo_signals": {
      "has_tldr": false,
      "has_faq_text": true,
      "has_lists_ge2": true,
      "has_tables": false,
      "has_citations_ge2": true,
      "has_author_name": false,
      "is_answer_first": true,
      "has_statistics": true
    },
    "geo_score": 47,
    "confidence": 90
  }
]
```

**8 GEO extraction functions:**

| Function | Τι ψάχνει | Detection |
|---|---|---|
| `extract_geo_tldr()` | TL;DR, συνοπτικά, περίληψη, summary, overview | Regex patterns in visible text |
| `extract_geo_faq_text()` | FAQ sections in HTML (not JSON-LD) | FAQ keywords + heading patterns |
| `extract_geo_lists()` | `<ul>`/`<ol>` count | HTML tag counting |
| `extract_geo_tables()` | `<table>` count | HTML tag counting |
| `extract_geo_citations()` | Citation keywords + outbound hrefs | πηγή, source, μελέτη, research κλπ |
| `extract_geo_author()` | Meta author + byline + JSON-LD author | Meta tag + "by/από" + schema detection |
| `extract_geo_answer_first()` | First paragraph after H1 is definition | Regex: "Είναι", "Ορίζεται", "Τι είναι" κλπ |
| `extract_geo_statistics()` | % numbers, "πάνω από", "1 στους" | Regex pattern matching |

**Θέματα:**
- SPA sites (aiagency.gr) → 0-9 words rendered. Χρειάζονται Playwright για πλήρη extraction.
- 0.5s polite delay between requests.
- Confidence πεδίο: 90% για requests (curl), 70% για Playwright.

---

### 5b. `secondary_extractor.py`

**Ρόλος:** Εξαγωγή intelligence από non-competitor URLs (Reddit, Quora, directories, news).

**Tool:** `scrapers/secondary_extractor.py`

**Method:** `requests` (safe, no CAPTCHA).

**Input:** SERP JSON (από serp_scraper.py — χρησιμοποιεί `secondary{}` grouped URLs).

**Output file:** `secondary.json`

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "total_questions_found": 12,
  "agencies_discovered": ["agency1.gr", "agency2.gr"],
  "news_topics": ["AI στην Ελλάδα", ...],
  "video_signals": ["Ai agents explained"],
  "results": [
    {
      "keyword": "ai agents",
      "reddit_threads": [
        {"title": "...", "url": "...", "score": 42}
      ],
      "quora_questions": ["..."],
      "directory_listings": ["..."],
      "news_articles": ["..."],
      "youtube_videos": [{"title": "...", "url": "..."}]
    }
  ]
}
```

**Uses per URL type:**

| URL Type | Εξαγωγή | Χρήση |
|---|---|---|
| Reddit threads | Questions + pain points | Content angles, FAQ topics |
| Quora questions | Question titles | Content gaps, user vocabulary |
| Directories (Clutch, G2) | Listed agencies | Δωρεάν competitor discovery |
| News articles | Meta keywords, title, H1 | Trending topic signals |
| YouTube videos | Video titles | Topic demand signals |

---

## 6. Φάση 4 — Gap Analysis

### 6a. `gap_scorer.py`

**Ρόλος:** Υπολογισμός Gap Score — trending keywords με χαμηλό ανταγωνισμό.

**Tool:** `analysis/gap_scorer.py`

**Method:** Local calculation — trend_score × competition factor × intent mismatch bonus.

**Inputs:**
- `--trends <ranked.json>` (από trend_validator.py)
- `--serp <serp.json>` (από serp_scraper.py)

**Output file:** `gap_report.json`

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "total_trends": 38,
  "total_serp_results": 8,
  "skipped_no_serp": 30,
  "scored": 8,
  "priority_summary": {
    "P1_CRITICAL": 0,
    "P2_HIGH": 0,
    "P3_MEDIUM": 2,
    "P4_LOW": 6
  },
  "results": [
    {
      "keyword": "softone",
      "trend_score": 66.9,
      "intent": "NAVIGATIONAL",
      "agency_in_top_10": 5,
      "publisher_dominance": false,
      "top_is_wikipedia": false,
      "mismatch_score": 0,
      "mismatch_type": "NAVIGATIONAL_MATCH",
      "mismatch_bonus": 1.0,
      "gap_score": 11.15,
      "priority": "P3_MEDIUM",
      "recommendation": "Moderate — consider only if fits existing content plan",
      "top1_type": "COMPETITOR",
      "top3_types": ["COMPETITOR", "COMPETITOR", "COMPETITOR"],
      "total_serp_urls": 5,
      "classification": {"COMPETITOR": 5, "BLOCKED": 1}
    }
  ],
  "top_opportunities": [...]
}
```

**Formula:**

```
Gap Score = trend_score × (1 / (agency_in_top_10 + 1)) × publisher_penalty × mismatch_bonus
```

| Factor | Τιμή | Εξήγηση |
|---|---|---|
| `trend_score` | 0-100 | Από trend_validator |
| `agency_in_top_10` | 0-10 | Πόσοι COMPETITOR-classified URLs στο SERP |
| `publisher_penalty` | 1.5x αν 2+ Reddit/News/Wikipedia στα top 3 | Uncontested keyword — μπόνους |
| Wikipedia στο #1 | 0.5x penalty | Keyword πολύ generic |
| `mismatch_bonus` | 1.0x - 2.0x | Βάσει intent mismatch (δες παρακάτω) |

**Intent Mismatch Types:**

| Type | Score | Bonus | Πότε συμβαίνει |
|---|---|---|---|
| `COMMERCIAL_INTENT_INFO_RESULTS` | 90 | 2.0x | Commercial keyword, top 3 είναι Wiki/News/Reddit |
| `TRANSACTIONAL_INTENT_NO_PRICING` | 85 | 2.0x | Transactional keyword, καμία pricing page |
| `COMMERCIAL_INTENT_PARTIAL_MISMATCH` | 50 | 1.5x | Μόνο 1 agency στα top 3 |
| `INFO_INTENT_COMMERCIAL_RESULTS` | 30 | 1.2x | Info keyword, κυρίως agency pages |
| `*_MATCH` | 0 | 1.0x | Good match — agencies κυριαρχούν |

**Priority Tiers:**

| Score Range | Priority | Action |
|---|---|---|
| ≥ 40 | `P1_CRITICAL` | Publish ASAP |
| ≥ 20 | `P2_HIGH` | Good opportunity |
| ≥ 10 | `P3_MEDIUM` | Moderate |
| < 10 | `P4_LOW` | Skip |

**Συμπεριφορά με πραγματικά δεδομένα:**
- Θεωρητικά scores (NO_SERP_DATA) → πολύ υψηλότερα (π.χ. logistics 67.6 P1)
- Πραγματικά scores (με SERP) → χαμηλότερα (logistics 10.14 P3)
- Αυτό είναι **αναμενόμενο** — το formula διορθώνει όταν υπάρχουν 7 competitors.
- Μην ανησυχείς για absolute scores. Sort by score και πάρε τα top.

---

## 7. Φάση 5 — Self-Assessment (Monitoring Loop)

Το `site_scraper.py` έχει **6 modes**:

### 7a. `--googlebot <url>`

**Τι κάνει:** Fetch με Googlebot UA (curl) — ΠΡΩΤΟ crawl pass. ΧΩΡΙΣ JavaScript.

**Output file:** `gap_report.json` (ή `googlebot_view.json`)

**Output schema:**
```json
{
  "url": "https://aionai.gr/",
  "meta_tags": 19,
  "jsonld_count": 2,
  "body_words": 0,
  "has_spa_shell": true,
  "spa_shell": "<app-root></app-root>",
  "gap_report": {
    "total_gaps": 3,
    "critical": ["spa_shell_no_body"],
    "high": [],
    "medium": ["missing_meta", "no_h1"],
    "low": []
  }
}
```

**Key value:** `body_words: 0` — το #1 πρόβλημα. SPA shell.

**Confidence:** 95% 🟢 — πανομοιότυπο με Googlebot first pass.

---

### 7b. `--googlebot-rendered <url>`

**Τι κάνει:** Full Chromium render με Googlebot constraints (5s timeout, mobile viewport 412x915, Android UA). Προσομοιώνει το **δεύτερο** crawl pass της Google (με JS).

**Output file:** `rendered_report.json`

**Output schema:**
```json
{
  "url": "https://aionai.gr/",
  "rendered": true,
  "render_time_ms": 3200,
  "rendered_word_count": 1307,
  "rendered_headings": 7,
  "rendered_links": 15,
  "source_word_count": 862,
  "render_efficiency": 152,
  "js_gap": "Angular renders fully within 5s budget",
  "timeout": false,
  "verdict": "Adequate — but 0 words in raw view means no featured snippets"
}
```

**Key values:**
- `rendered_word_count`: 1307 (vs source 862 = 152% efficiency — Angular injects more content) ✅
- `render_efficiency`: > 80% = GOOD, 50-80% = FAIR, < 50% = POOR
- `timeout`: αν > 5s → partial capture

**Confidence:** 70% 🟡 — local Playwright ≠ Googlebot cloud. Googlebot έχει tighter budget. Ισχυρό positive signal αλλά όχι εγγύηση.

---

### 7c. `--validate-jsonld <url>`

**Τι κάνει:** Εκτεταμένη επικύρωση structured data.

**Output file:** `jsonld_validation.json`

**Έλεγχοι:**

| Check | Τι ελέγχει | Αν αποτύχει |
|---|---|---|
| Phone format | `+30 69X...` 13 digits | CRITICAL — Google απορρίπτει όλο το schema |
| Email | `@` present | CRITICAL |
| HTTPS URL | protocol validation | HIGH |
| areaServed | non-empty | HIGH |
| serviceType | non-empty | HIGH |
| description | ≥50 chars + Greek content | MEDIUM |
| FAQ Q&A pairs | complete pairs | MEDIUM |

**Output schema:**
```json
{
  "url": "https://aionai.gr/",
  "jsonld_entities": 2,
  "types": ["ProfessionalService", "FAQPage"],
  "issues": [
    {
      "severity": "HIGH",
      "field": "telephone",
      "detail": "Phone '+30 693461355' has 12 digits, expected 13",
      "expected": "+30 6934613555"
    }
  ],
  "health_score": 75,
  "verdict": "MODERATE — 1 HIGH issue"
}
```

**Confidence:** 95% 🟢

---

### 7d. `--geo-check`

**Τι κάνει:** Αναλύει το Angular source code για GEO signals.

**Tool flag:** `scrapers/site_scraper.py --geo-check`

**Output file:** `geo_self_check.json`

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "site": "aionAI",
  "source_files": {
    "index_html": "index.html",
    "app_ts": "app.ts",
    "sections_analyzed": 13,
    "llms_txt": "llms.txt"
  },
  "geo_signals": {
    "static_body_words": 0,
    "faq_text_in_static_html": true,
    "faq_schema_in_static_html": true,
    "tldr_present": true,
    "h1_text": "Μάθετε αν το AI ταιριάζει στην επιχείρησή σας.",
    "h1_is_definitive": false,
    "h1_is_cta": true,
    "list_count": {"ul": 2, "ol": 0, "total_items": 2},
    "table_count": 0,
    "citation_count": 0,
    "citation_keyword_mentions": 1,
    "author_meta": "aionAI",
    "author_bio_section": false,
    "stat_count": 13,
    "schema_types": ["ProfessionalService", "FAQPage"],
    "llms_txt": {"exists": true, "lines": 42, "has_pages_section": true},
    "meta_count": 18,
    "has_og_tags": true,
    "has_twitter_tags": true
  },
  "geo_score": {
    "value": 67,
    "components": {
      "static_content": 0,
      "faq_text_visible": 8,
      "faq_schema": 12,
      "tldr": 10,
      "answer_first_h1": 0,
      "lists": 8,
      "tables": 0,
      "citations": 3,
      "author": 9,
      "statistics": 5,
      "llms_txt": 10,
      "meta_tags": 5
    },
    "max_possible": 105
  },
  "gaps": [
    {"signal": "static_body_content", "priority": "CRITICAL",
     "detail": "Only 0 words visible in static HTML — LLM crawlers see empty body"},
    {"signal": "answer_first_h1", "priority": "HIGH",
     "detail": "H1 is CTA-style instead of answer-first"},
    {"signal": "tables", "priority": "LOW",
     "detail": "No data tables"}
  ],
  "summary": "geo_score=67/100 | gaps=3 (1C, 1H, 0M, 1L)"
}
```

**ΠΡΟΣΟΧΗ:**
- `--geo-check` μετράει από **source code**, όχι rendered HTML.
- Το score 67/100 είναι **διαφορετικό** από το unified score 34/100 που μετράει `lib/geo_scorer.py` από rendered HTML.
- Μην συγκρίνεις 67 με competitor scores — τα competitors μετρήθηκαν από rendered HTML.

---

### 7e. `--batch-competitors <file>`

**Τι κάνει:** Batch Googlebot analysis για competitors.

**Input:** File με URLs (μία ανά γραμμή, `#` για comments).

**Output:** `data/competitors/{domain}_googlebot.json` + `batch_summary.json`

**Output schema (batch_summary.json):**
```json
{
  "total": 7,
  "results": [
    {
      "domain": "www.ot.gr",
      "body_words": 3849,
      "has_spa_shell": false,
      "has_json_ld": true,
      "jsonld_issues": 3,
      "spa_shell": false
    }
  ]
}
```

**Key findings (2026-06-14):**
- aionAI είναι το **ΜΟΝΟ** SPA — όλοι οι competitors έχουν SSR/static HTML με 610-3,871 words.
- aionAI είναι ο **ΜΟΝΟΣ** με FAQPage schema — 0% competitors.
- Αλλά competitors έχουν λιγότερα JSON-LD issues (μέσος όρος 7-11 vs δικό μας 1).

---

## 8. Φάση 6 — Comparison Report

### 8a. `comparison_report.py`

**Ρόλος:** Σύγκριση aionAI vs competitors σε Googlebot-view με βάρη και confidence.

**Tool:** `analysis/comparison_report.py`

**Method:** Συνδυάζει όλες τις μετρήσεις από site_scraper + keyword data.

**Flags:**

| Flag | Input | Optional? |
|---|---|---|
| `--self` | (none) | Required για self-analysis mode |
| `--site-googlebot` | gap_report.json | Required |
| `--site-rendered` | rendered_report.json | Optional (JS render scoring) |
| `--jsonld-validation` | jsonld_validation.json | Optional (JSON-LD health) |
| `--keywords` | keywords.json | Optional (content recommendations) |
| `--competitors <dir>` | competitors/ dir | Optional (comparison) |
| `--output <file>` | Output JSON | Required |

**Scoring logic:**

| Component | Πηγή | Confidence | Βάρος |
|---|---|---|---|
| Googlebot raw score | `--site-googlebot` | 95% | 0.5 |
| JS render score | `--site-rendered` | 70% | 0.3 |
| JSON-LD health score | `--jsonld-validation` | 95% | 0.2 |

**Googlebot raw penalties:**
- 0 body words = -40 points
- SPA shell detected = -20 points
- "needs JS" in body = -20 points
- Gap severity deductions

**Domain Authority (δυναμική):**

| Domain Age | Sandbox Stage | Expectation |
|---|---|---|
| 0-3 months | EARLY_SANDBOX | 0-5 μήνες πριν rankings |
| 3-6 months | MID_SANDBOX | 2-6 μήνες ακόμα |
| 6-12 months | LATE_SANDBOX | Rankings should start |
| 12+ months | ESTABLISHED | Low rankings = content/tech issues |

Διαβάζει `foundingDate` από JSON-LD. Υπολογίζει αυτόματα.

---

## 9. GEO Analysis Pipeline

### 9a. `citation_scraper.py`

**Ρόλος:** Proxy για AI engine citations (ChatGPT/Perplexity/Gemini blocked).

**Tool:** `scrapers/citation_scraper.py`

**Method:** Playwright stealth → Google search → έλεγχος αν aionai.gr εμφανίζεται.

**Input:** List of Greek AI/business keywords (built-in 15 seeds).

**Flags:**

| Flag | Default | Τι κάνει |
|---|---|---|
| `--keywords` | 15 built-in | Custom keywords |
| `--include-brand` | false | Include aionAI brand queries |
| `--max` | all | Max keywords to search |
| `--output` | stdout | Output file |

**Output schema:**
```json
{
  "timestamp": "ISO datetime",
  "queries_run": 3,
  "queries_success": 3,
  "queries_blocked": 0,
  "citation_gap_score": {
    "score": 0,
    "level": "CRITICAL",
    "found_in_queries": 0,
    "total_queries": 3,
    "visibility_ratio": 0,
    "avg_position_when_found": null
  },
  "top_competitors_all": [
    {"domain": "aiagency.gr", "appearances": 3},
    {"domain": "yuboto.gr", "appearances": 2}
  ],
  "top_direct_competitors": [
    {"domain": "aiagency.gr", "appearances": 3}
  ],
  "keyword_results": [
    {
      "keyword": "AI agents Ελλάδα",
      "status": "success",
      "us_found": false,
      "our_position": null,
      "competitors": ["aiagency.gr", "yuboto.gr"]
    }
  ],
  "summary": "citation_gap=0.0/100 (CRITICAL) | found in 0/3 queries"
}
```

**Key values:**
- `citation_gap_score.score`: 0-100. 0 = brand not found anywhere.
- `top_direct_competitors`: φιλτραρισμένοι (χωρίς directories/news/social).

**Πραγματικά αποτελέσματα (2026-06-16):**
- 3/3 queries succeeded, 0 CAPTCHA
- Score: 0.0/100 (CRITICAL)
- aionai.gr ΔΕΝ βρέθηκε σε κανένα query
- Top competitors: aiagency.gr, yuboto.gr, digibot.gr, proxima.gr

**ΠΡΟΣΟΧΗ:**
- Είναι proxy measure (Google → όχι πραγματικές AI engine citations).
- True citation check θέλει API keys για ChatGPT/Perplexity.
- Name pollution: το ακαδημαϊκό paper "AIonAI" (Ashrafian, 2014) κυριαρχεί στα search results για το brand name μας.

---

### 9b. `geo_market_analysis.py` + `lib/geo_scorer.py`

**Ρόλος:** Unified GEO scoring — ίδια κριτήρια για εμάς και competitors.

**Tool:** `analysis/geo_market_analysis.py` (uses `lib/geo_scorer.py`)

**Method:** Fetch rendered HTML από competitors → `lib/geo_scorer.score_geo_readiness()` → market statistics.

**Output file:** `geo_market.json`

**GEO Signals (12 συνολικά, max = 100 points):**

| # | Signal | Weight | Τι ελέγχει | Market avg (20 competitors) |
|---|---|---|---|---|
| 1 | `has_faq_schema` | 15 | FAQPage JSON-LD | 0% ✅ |
| 2 | `has_faq_text` | 10 | FAQ text visible σε HTML | 5% |
| 3 | `has_org_schema` | 5 | Organization schema | 15% ✅ (έχουμε) |
| 4 | `has_tldr` | 10 | TL;DR/summary block | 10% |
| 5 | `is_answer_first` | 10 | First paragraph is answer | 0% |
| 6 | `word_count_ge1500` | 10 | ≥1500 λέξεις rendered | 20% ❌ |
| 7 | `has_lists_ge2` | 8 | ≥2 lists | 85% ❌ |
| 8 | `has_tables` | 5 | ≥1 data table | 20% ❌ |
| 9 | `has_citations_ge2` | 8 | ≥2 citation links | 35% ❌ |
| 10 | `has_author_name` | 9 | Author meta/byline | 15% ✅ (έχουμε) |
| 11 | `has_statistics` | 5 | Statistics/percentages | 30% ❌ |
| 12 | `has_llms_txt` | 5 | llms.txt | 0% ✅ |

**Scoring levels:**

| Range | Level |
|---|---|
| 80-100 | EXCELLENT |
| 60-79 | GOOD |
| 40-59 | MODERATE |
| 20-39 | POOR |
| 0-19 | CRITICAL |

**Output schema (geo_market.json):**
```json
{
  "generated": "ISO datetime",
  "competitors_analyzed": 20,
  "market_summary": {
    "avg_score": 17.7,
    "median_score": 14.5,
    "max_score": 50,
    "min_score": 0,
    "scores_distribution": {
      "EXCELLENT": 0,
      "GOOD": 0,
      "MODERATE": 3,
      "POOR": 3,
      "CRITICAL": 14
    },
    "signal_market_analysis": {
      "has_faq_schema": {"market_presence_pct": 0, "weight": 15},
      "has_lists_ge2": {"market_presence_pct": 85, "weight": 8}
    }
  }
}
```

---

### 9c. `geo_gap_scorer.py`

**Ρόλος:** Σύγκριση δικού μας GEO score vs market → identification of gaps + strengths.

**Tool:** `analysis/geo_gap_scorer.py`

**Inputs:**
- Δικό μας `--geo-check` output (source code)
- Market data από `geo_market.json`

**Output file:** `geo_gaps.json`

**Output schema (full):**
```json
{
  "generated": "ISO datetime",
  "our_geo_score": 34,
  "our_geo_level": "POOR",
  "market_avg_geo": 17.7,
  "market_max_geo": 50,
  "market_median_geo": 14.5,
  "competitors_analyzed": 20,
  "gap_analysis": {
    "summary": {
      "total_gaps": 5,
      "critical_gaps": 0,
      "high_gaps": 2,
      "medium_gaps": 1,
      "low_gaps": 2,
      "our_strengths": 4,
      "market_opportunities": 3,
      "gap_intensity_score": 15
    },
    "gaps": [
      {
        "signal": "word_count_ge1500",
        "description": "≥1500 words of visible text content",
        "weight": 10,
        "we_have_it": false,
        "market_presence_pct": 20,
        "priority": "HIGH",
        "score": 15.0
      }
    ],
    "opportunities": [
      {
        "signal": "has_faq_text",
        "description": "FAQ text visible in HTML",
        "weight": 10,
        "we_have_it": false,
        "market_presence_pct": 5,
        "priority": "MEDIUM"
      }
    ],
    "our_strengths": [
      {
        "signal": "has_faq_schema",
        "description": "FAQPage JSON-LD schema",
        "weight": 15,
        "we_have_it": true,
        "market_presence_pct": 0,
        "priority": "NONE"
      }
    ],
    "recommendations": [
      {
        "priority": "HIGH",
        "signal": "word_count_ge1500",
        "action": "Add substantial visible content",
        "effort": "High",
        "impact": "Critical"
      }
    ]
  },
  "summary": "Our GEO: 34/100 (POOR) | Market: 17.7 avg, 50 max | Gaps: 0C + 2H + 1M | Strengths: 4"
}
```

**Metrics:**

| Field | Τιμή | Ερμηνεία |
|---|---|---|
| `our_geo_score` | 34 | Από rendered HTML (unified scoring) |
| `gap_intensity_score` | 0-100 | Πόσο πίσω είμαστε από την αγορά. >30 = σοβαρό |
| `gaps[].priority` | HIGH/MEDIUM/LOW | Βάσει weight × market_presence × απουσία μας |
| `opportunities` | Signals με < 20% market presence | "Blue ocean" — κανείς δεν το κάνει |
| `our_strengths` | Signals που έχουμε και η αγορά όχι | Ανταγωνιστικό πλεονέκτημα |

**Gap priority formula (internal):**
```
score = weight × (market_presence_pct / 100) × (1 if not we_have_it else 0)
```
- HIGH: score ≥ 8
- MEDIUM: score ≥ 4
- LOW: score < 4

---

## 10. Tools & Utilities

### 10a. `generate_status.py`

**Ρόλος:** Lightweight status index — ένα file που σου λέει τα πάντα.

**Tool:** `tools/generate_status.py`

**Input:** Διαβάζει όλα τα `data/latest/*.json` files.

**Output:** `data/latest/status.json` (~2.5KB)

**Output schema (συνοπτικά):**
```json
{
  "generated": "ISO datetime",
  "summary": "site=NO_DATA (0/100) | keywords=148 | gaps:P1=0 | geo_self=67 | geo_market=21.9",
  "keywords": {"total": 148, "intent_breakdown": {"INFO": 99, "COMMERCIAL": 45}},
  "ranked": {"total": 38},
  "serp": {"keywords_scraped": 8, "total_competitors": 53},
  "gaps": {"priority_summary": {"P1": 0, "P2": 0, "P3": 2, "P4": 6}},
  "site": {"googlebot_score": 0, "sandbox_stage": "UNKNOWN"},
  "competitors": {"total": 7, "top_by_content": [...]},
  "geo": {"self_score": 67, "market_avg_geo": 21.9, "market_max_geo": 47},
  "files": {"keywords.json": {"exists": true, "age_days": 0}},
  "outdated": {}
}
```

**Αυτόνομη χρήση:** Μετά από ΚΑΘΕ pipeline run, τρέξε:
```bash
python tools/generate_status.py
```

---

### 10b. `organize_data.py`

**Ρόλος:** Διαχείριση symlinks στο `data/latest/`.

**Tool:** `data/organize_data.py`

**Μέθοδος:** Εντοπίζει όλα τα canonical files στο `data/runs/`, βρίσκει το πιο πρόσφατο, ενημερώνει symlinks στο `data/latest/`.

**Idempotent:** Ασφαλές να τρέχεις πολλές φορές.

---

## 11. Πίνακας Scores — Quick Reference

### SEO Scores

| Score | Tool | Range | Δικός μας | Market avg | Ερμηνεία |
|---|---|---|---|---|---|
| Googlebot raw | `site_scraper --googlebot` | 0-100 | **0/100** | 35-70 | SPA shell — 0 words visible |
| JS render | `site_scraper --googlebot-rendered` | 0-100 | **~75/100** | N/A | Angular renders OK in 5s |
| JSON-LD health | `site_scraper --validate-jsonld` | 0-100 | **~75/100** | ~50/100 | 1 HIGH issue (phone) |
| Keyword trend | `trend_validator` | 0-100 | top: 67.6 | N/A | Trend score per keyword |
| Gap score | `gap_scorer` | 0-100 | top: 11.15 | N/A | P3_MEDIUM (saturated market) |

### GEO Scores

| Score | Tool | Range | Δικός μας | Market avg | Market max |
|---|---|---|---|---|---|
| Source code GEO | `site_scraper --geo-check` | 0-105 | **67/100** | N/A | N/A |
| Rendered HTML GEO | `lib/geo_scorer` (unified) | 0-100 | **34/100** | 17.7 | 50 |
| Citation gap | `citation_scraper` | 0-100 | **0/100** | N/A | N/A |

### Levels

| Level | SEO Googlebot | GEO Unified | Citation |
|---|---|---|---|
| EXCELLENT | 80-100 | 80-100 | 80-100 |
| GOOD | 60-79 | 60-79 | 60-79 |
| MODERATE | 40-59 | 40-59 | 40-59 |
| POOR | 20-39 | 20-39 | 20-39 |
| CRITICAL | 0-19 | 0-19 | 0-19 |

---

## 12. Πίνακας Cadence

| Φάση | Script | Κάθε πότε | Risk | Συνθήκη αλλαγής |
|---|---|---|---|---|
| **1** | keyword_discovery + trend_validator | 4-6 εβδομάδες | 🟢 None | Αν trend direction αλλάξει >30% → νωρίτερα |
| **2** | serp_scraper | 3 μήνες | 🔴 CAPTCHA | Μόνο σε fresh IP ή όταν αλλάξουν trends |
| **2b** | secondary_extractor | Μετά από Phase 2 | 🟢 None | Αμέσως μετά SERP |
| **2c** | gap_scorer | Μετά από Phase 2 | 🟢 None | Αμέσως μετά SERP |
| **3** | competitor_scraper | Μετά από Phase 2 | 🟢 None | Αμέσως μετά SERP |
| **5** | site_scraper (all modes) | Μόνο σε deployment | 🟢 None | Αν αλλάξει το Angular app |
| **6** | comparison_report | Μετά από dataset refresh | 🟢 None | Πάντα με νέα δεδομένα |
| **GEO** | geo_market_analysis | Μετά από competitor refresh | 🟢 None | Όταν αλλάξουν competitors |
| **GEO** | citation_scraper | Μηνιαία | 🟡 Medium | Μετά από content production |
| **Tools** | organize_data + generate_status | Μετά από ΚΑΘΕ run | 🟢 None | Πάντα |

---

## 13. Current State Snapshot

**Τελευταία ενημέρωση status.json:** 2026-06-15T22:28:43
**Τελευταίο πλήρες run:** 2026-06-15

| Τομέας | Κατάσταση |
|---|---|
| **Keywords** | 148 total (99 INFO, 45 COMMERCIAL, 4 TRANSACTIONAL) ✅ |
| **Trend validated** | 38 keywords ✅ |
| **SERP scraped** | 8 keywords, 53 competitors ✅ |
| **Gap analysis** | 0 P1, 0 P2, 2 P3, 6 P4 ⚠️ |
| **Googlebot view** | 0/100 — SPA shell ❌ |
| **JSON-LD** | ~75/100 — 1 HIGH issue (phone truncation) ⚠️ |
| **GEO self (source)** | 67/100 ✅ |
| **GEO unified (rendered)** | 34/100 (POOR) — vs market avg 17.7 ✅ (μπροστά αλλά θέλει δουλειά) |
| **Citation** | 0/100 (CRITICAL) — brand not found anywhere ❌ |
| **Competitors analyzed** | 20 για GEO, 7 για Googlebot comparison ✅ |
| **Comparison report** | ΔΕΝ υπάρχει στο data/latest/ ❌ |

---

## 14. Γνωστά Bugs & Issues

| # | Issue | Priority | Status |
|---|---|---|---|
| 1 | **Phone truncation**: server `+30 693461355` (12 digits) vs source `+30 6934613555` (13 digits) — πιθανά ακυρώνει ολόκληρο το JSON-LD schema | 🔴 HIGH | 🟡 UNFIXED |
| 2 | **Name pollution**: Academic paper "AIonAI" (Ashrafian, 2014) dominates search results για aionAI brand — χρειάζεται content volume για να το ξεπεράσει | 🟡 MEDIUM | 🟡 Ongoing |
| 3 | **comparison_report.json λείπει** από data/latest/ — χρειάζεται regenerate | 🟡 MEDIUM | ❌ NOT DONE |
| 4 | **site.json** (συνδυασμός googlebot + rendered) λείπει από data/latest/ | 🟢 LOW | ❌ NOT DONE |
| 5 | **GEO score discrepancy**: Source code score (67) vs rendered score (34) — το `--geo-check` μετράει source, το `lib/geo_scorer` μετράει rendered. Είναι intentional αλλά μπερδευτικό | 🟢 LOW | 📝 Documented |
| 6 | **Angular SPA**: 0 words visible στο Googlebot first pass — το #1 SEO και GEO πρόβλημα | 🔴 CRITICAL | 📝 Planned (static pages) |
