#!/usr/bin/env python3

"""
trend_validator.py — Βαθμολογεί keywords με pytrends (geo=GR).

Παίρνει τη λίστα keywords από το keyword_discovery.py (ή οποιαδήποτε λίστα),
τρέχει pytrends για κάθε ένα με region=GR, και βγάζει ranked list.

Pipeline:
    keyword_discovery.py --output keywords.json
    python trend_validator.py --input keywords.json --output ranked.json

Requirements:
    pytrends>=4.9.2
    pandas (installed as pytrends dependency)
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
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from pytrends.request import TrendReq

from lib import url_utils


# ─── Rate limiting ────────────────────────────────────────────────────────
# pytrends recommends ~1 request per second. We use conservative delays.
REQUEST_DELAY = 1.2  # seconds between pytrends API calls
BATCH_SIZE = 3       # pytrends supports up to 5 keywords per batch

# pytrends sometimes returns stale data from cache
# Adding random query params to avoid cached responses
CACHE_BUSTER = 0


# ─── pytrends helper ─────────────────────────────────────────────────────

def make_trendreq() -> TrendReq:
    """Create a pytrends client with Greek locale."""
    return TrendReq(hl="el-GR", tz=360)


def fetch_trend(
    pytrends: TrendReq,
    kw: str,
    retries: int = 2,
) -> Optional[pd.Series]:
    """
    Fetch 12-month weekly interest for a single keyword in Greece.

    Returns a pandas Series (date index -> interest 0-100), or None on failure.
    """
    global CACHE_BUSTER
    CACHE_BUSTER += 1

    for attempt in range(retries + 1):
        try:
            # Build payload with minimal params
            pytrends.build_payload(
                kw_list=[kw],
                cat=0,
                timeframe="today 12-m",
                geo="GR",
                gprop="",
            )
            data = pytrends.interest_over_time()

            if data.empty:
                return None

            # Drop isPartial column if present
            if "isPartial" in data.columns:
                data = data.drop(columns=["isPartial"])

            # Return the single column as a Series
            return data.iloc[:, 0]

        except Exception as e:
            err_msg = str(e).lower()
            # Rate limit — wait and retry
            if "429" in err_msg or "too many" in err_msg:
                if attempt < retries:
                    wait = REQUEST_DELAY * (attempt + 2)
                    if attempt == 0:
                        print(
                            f"  [warn] Rate limited, waiting {wait:.0f}s...",
                            file=sys.stderr,
                        )
                    time.sleep(wait)
                    continue
            # Other errors (no data, connection, etc.)
            if attempt < retries:
                time.sleep(REQUEST_DELAY)
                continue
            return None

    return None


# ─── Metrics calculation ─────────────────────────────────────────────────

def calculate_metrics(series: pd.Series) -> dict:
    """
    Calculate trend metrics from a weekly interest series.

    Returns dict with:
      - trend_score:      average interest over 12 months (0-100)
      - trend_direction:  "rising" / "falling" / "stable"
      - percent_change:   % change (last 3mo vs previous 3mo)
      - peak_month:       YYYY-MM of highest interest
      - data_points:      number of weeks with data
    """
    if series is None or series.empty:
        return {
            "trend_score": 0,
            "trend_direction": "unknown",
            "percent_change": 0,
            "peak_month": None,
            "data_points": 0,
        }

    trend_score = round(float(series.mean()), 1)
    data_points = len(series)

    # Find peak month
    peak_idx = series.idxmax()
    peak_month = peak_idx.strftime("%Y-%m") if hasattr(peak_idx, "strftime") else str(peak_idx)[:7]

    # Compare last 3 months vs previous 3 months
    n = len(series)
    if n >= 24:  # need at least 6 months of weekly data
        recent = series.iloc[-12:].mean()
        previous = series.iloc[-24:-12].mean()
        if previous > 0:
            percent_change = round(((recent - previous) / previous) * 100, 1)
        elif recent > 0:
            percent_change = 100.0  # from zero to something
        else:
            percent_change = 0.0

        if percent_change > 15:
            trend_direction = "rising"
        elif percent_change < -15:
            trend_direction = "falling"
        else:
            trend_direction = "stable"
    else:
        # Not enough data for direction
        percent_change = 0.0
        trend_direction = "insufficient_data"

    return {
        "trend_score": trend_score,
        "trend_direction": trend_direction,
        "percent_change": percent_change,
        "peak_month": peak_month,
        "data_points": data_points,
    }


# ─── Batch processing ─────────────────────────────────────────────────────

def validate_keywords(
    keywords: list[str],
    verbose: bool = False,
) -> list[dict]:
    """
    Process all keywords through pytrends and return ranked results.

    Returns list of dicts sorted by trend_score descending.
    """
    if not keywords:
        return []

    pytrends = make_trendreq()
    results: list[dict] = []
    total = len(keywords)

    for idx, kw in enumerate(keywords):
        if verbose:
            print(
                f"[verbose] [{idx + 1}/{total}] '{kw[:50]}'...",
                file=sys.stderr,
            )

        series = fetch_trend(pytrends, kw, retries=2)

        if series is None:
            if verbose:
                print(f"  -> no data (skipped)", file=sys.stderr)
            continue

        metrics = calculate_metrics(series)
        metrics["keyword"] = kw

        if verbose:
            print(
                f"  -> score={metrics['trend_score']}, "
                f"{metrics['trend_direction']} "
                f"({metrics['percent_change']:+.1f}%)",
                file=sys.stderr,
            )

        results.append(metrics)

        # Rate limiting between keywords
        time.sleep(REQUEST_DELAY)

    # Sort by trend_score descending
    results.sort(key=lambda r: r["trend_score"], reverse=True)

    rerank_results(results)
    return results


def rerank_results(results: list[dict]) -> None:
    """Assign rank and rank_change in-place."""
    for rank, r in enumerate(results, start=1):
        r["rank"] = rank


# ─── Input parsing ────────────────────────────────────────────────────────

def read_keywords(path: str) -> list[str]:
    """Read keywords from a JSON or text file."""
    p = Path(path)
    try:
        content = p.read_text("utf-8")
    except FileNotFoundError:
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    # Try JSON first (keyword_discovery.py output)
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            # keyword_discovery.py format
            kws = []
            kws.extend(data.get("questions", []))
            kws.extend(data.get("related_searches", []))
            # New format: list of {query, intent, question}
            raw_keywords = data.get("keywords", [])
            if raw_keywords and isinstance(raw_keywords[0], dict) and "query" in raw_keywords[0]:
                kws.extend(item["query"] for item in raw_keywords)
            else:
                kws.extend(raw_keywords)
            # Also check for "seeds" field
            kws.extend(data.get("seeds", []))
            if kws:
                return kws
        elif isinstance(data, list):
            # List of strings or list of dicts with 'keyword' key
            if data and isinstance(data[0], dict) and "keyword" in data[0]:
                return [item["keyword"] for item in data]
            elif data and isinstance(data[0], str):
                return data
    except json.JSONDecodeError:
        pass

    # Fallback: one keyword per line
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.startswith("#")
    ]


# ─── CLI ──────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="trend_validator.py — pytrends βαθμολόγηση keywords (geo=GR).",
    )
    parser.add_argument(
        "keyword",
        type=str,
        nargs="?",
        default=None,
        help="Single keyword to validate (or use --input for batch)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input file: JSON (keyword_discovery.py output) or text (one per line)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0,
        help="Minimum trend_score to include (default: 0 = all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print progress to stderr",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    # Read keywords
    keywords: list[str] = []
    if args.input:
        keywords = read_keywords(args.input)
    elif args.keyword:
        keywords = [args.keyword.strip()]
    else:
        print("Error: Provide a keyword or --input file.", file=sys.stderr)
        return 1

    if not keywords:
        print("Error: No keywords to process.", file=sys.stderr)
        return 1

    # Remove duplicates
    keywords = list(dict.fromkeys(kw.strip() for kw in keywords if kw.strip()))

    if args.verbose:
        print(f"[verbose] Processing {len(keywords)} unique keywords...", file=sys.stderr)
        print(file=sys.stderr)

    # Validate
    results = validate_keywords(keywords, verbose=args.verbose)

    if not results:
        print("Warning: No keywords returned data (all had 0 volume in GR).", file=sys.stderr)
        # Still output empty array
        pass

    # Add intent classification to each result
    for r in results:
        r["intent"] = url_utils.classify_keyword_intent(r.get("keyword", ""))
    if args.verbose and results:
        intent_counts = {}
        for r in results:
            intent = r["intent"]
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        print(f"[verbose] Intents: {intent_counts}", file=sys.stderr)

    # Apply min-score filter
    if args.min_score > 0:
        results = [r for r in results if r["trend_score"] >= args.min_score]

    # Build output
    output = json.dumps(
        {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total_input": len(keywords),
            "total_with_data": len(results),
            "min_score_filter": args.min_score,
            "results": results,
        },
        ensure_ascii=False,
        indent=2,
    )

    print(output)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"\n[verbose] Saved to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
