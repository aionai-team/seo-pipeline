#!/usr/bin/env python3
"""
organize_data.py — Οργάνωση δεδομένων ανά ημερομηνία.

Δημιουργεί δομή:
  data/
    latest/          ← Symlinks to most recent run's files
    runs/YYYY-MM-DD/ ← All data from that pipeline run
    archive/         ← Files without date or unknown origin
    competitors/     ← Per-competitor Googlebot data (shared across runs)

Usage:
    python organize_data.py              # Organize all files
    python organize_data.py --dry-run    # Show what would happen
    python organize_data.py --run-date 2026-06-14  # Force a date for undated files
"""

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent
RUNS_DIR = DATA_DIR / "runs"
LATEST_DIR = DATA_DIR / "latest"
ARCHIVE_DIR = DATA_DIR / "archive"
COMPETITORS_DIR = DATA_DIR / "competitors"


# ─── Date extraction ───────────────────────────────────────────

def extract_date_from_filename(name: str) -> str | None:
    """
    Extract YYYY-MM-DD date from filename.
    Matches patterns like: *_2026-06-14*, *_2026-06-14.json
    """
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    return m.group(1) if m else None


def extract_date_from_json(path: Path) -> str | None:
    """Try to get date from JSON content (timestamp field)."""
    try:
        data = json.loads(path.read_text("utf-8"))
        ts = data.get("timestamp", "")
        if ts:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", str(ts))
            if m:
                return m.group(1)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def extract_date_from_mtime(path: Path) -> str:
    """Get date from file modification time."""
    mtime = path.stat().st_mtime
    dt = datetime.fromtimestamp(mtime)
    return dt.strftime("%Y-%m-%d")


# ─── File classification ──────────────────────────────────────

def classify_file(path: Path) -> dict:
    """
    Classify a file and determine where it should go.
    
    Returns {path, name, date, run_dir, should_move, reason}
    """
    name = path.name
    
    # Skip directories and hidden files
    if path.is_dir() or name.startswith("."):
        return {"skip": True, "reason": "directory or hidden"}
    
    # Skip if already inside organized structure
    if any(p in path.parts for p in ["runs", "latest", "archive"]):
        return {"skip": True, "reason": "already in organized dir"}
    
    # Skip organize_data.py itself if in data/
    if name == "organize_data.py":
        return {"skip": True, "reason": "script itself"}
    
    # Extract date from filename
    date = extract_date_from_filename(name)
    
    # Fall back to JSON timestamp field
    if not date and name.endswith(".json"):
        date = extract_date_from_json(path)
    
    # Fall back to file modification time
    if not date:
        date = extract_date_from_mtime(path)
        source = "mtime"
    else:
        source = "filename" if extract_date_from_filename(name) else "json_timestamp"
    
    run_dir = RUNS_DIR / date
    dest_name = _canonical_name(name)
    
    return {
        "skip": False,
        "path": path,
        "name": name,
        "dest_name": dest_name,
        "date": date,
        "date_source": source,
        "run_dir": run_dir,
        "dest_path": run_dir / dest_name,
    }


def _canonical_name(name: str) -> str:
    """
    Convert inconsistent filenames to canonical form.
    
    Examples:
        comparison_report_2026-06-14.json → comparison_report.json
        keywords_full_2026-06-14.json → keywords.json  
        keywords_with_intent_2026-06-14.json → keywords.json
        ranked_full_2026-06-14.json → ranked.json
        site_full_2026-06-14.json → site.json
        gap_report_2026-06-14.json → gap_report.json
        gap_full_2026-06-14.json → gap_report.json
        rendered_full_report.json → rendered_report.json
        jsonld_full_validation.json → jsonld_validation.json
        serp_full_2026-06-14.json → serp.json
        final_report_2026-06-14.json → comparison_report.json
    """
    # Remove date pattern
    name = re.sub(r"_\d{4}-\d{2}-\d{2}", "", name)
    
    # Normalize specific files (check BEFORE regex normalization)
    aliases = {
        "keywords_with_intent.json": "keywords.json",
        "keywords_full.json": "keywords.json",
        "final_report.json": "comparison_report.json",
        "gap_full.json": "gap_report.json",
        "gap_report.json": "gap_report.json",
        "serp_full.json": "serp.json",
        "site_full.json": "site.json",
        "rendered_full.json": "rendered_report.json",
        "geo_self_check.json": "geo_self_check.json",
        "competitors_with_geo.json": "competitors_with_geo.json",
    }
    if name in aliases:
        name = aliases[name]
    
    # Normalize _full patterns (after aliases)
    name = name.replace("_full_", "_")
    name = re.sub(r"_full\.", ".", name)  # ranked_full.json → ranked.json
    if name.startswith("full_"):
        name = name[5:]
    
    return name


# ─── Symlink management ───────────────────────────────────────

def update_latest(run_dirs: list[Path]):
    """Create/update symlinks in latest/ to the most recent run."""
    if not run_dirs:
        print("  No runs to link.", file=sys.stderr)
        return
    
    # Most recent run
    latest_run = max(run_dirs)
    
    print(f"  Latest run: {latest_run.name}", file=sys.stderr)
    
    # Clear existing latest
    if LATEST_DIR.exists():
        for f in LATEST_DIR.iterdir():
            if f.is_symlink() or f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
    else:
        LATEST_DIR.mkdir(parents=True)
    
    # Create symlinks for each file in latest run
    for f in sorted(latest_run.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            link_path = LATEST_DIR / f.name
            try:
                # Use relative symlink for portability
                rel_path = Path(os.path.relpath(f, LATEST_DIR))
                link_path.symlink_to(rel_path)
            except (OSError, NameError):
                # If os isn't imported or symlink fails, copy
                import os
                rel_path = Path(os.path.relpath(f, LATEST_DIR))
                try:
                    link_path.symlink_to(rel_path)
                except OSError:
                    shutil.copy2(f, link_path)
    
    print(f"  Created {len(list(latest_run.iterdir()))} symlinks in latest/", file=sys.stderr)


# ─── Main ─────────────────────────────────────────────────────

def main():
    import argparse
    import os
    
    parser = argparse.ArgumentParser(
        description="organize_data.py — Οργάνωση δεδομένων ανά ημερομηνία."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen, don't move anything")
    parser.add_argument("--run-date", type=str, default=None,
                        help="Force date for files without detectable date (YYYY-MM-DD)")
    args = parser.parse_args()
    
    if not DATA_DIR.exists():
        print(f"Error: data directory not found: {DATA_DIR}", file=sys.stderr)
        return 1
    
    # Collect all files
    all_items = sorted(DATA_DIR.iterdir())
    files = [f for f in all_items if f.is_file() and not f.name.startswith(".")]
    
    if not files:
        print("No files to organize.", file=sys.stderr)
        return 0
    
    print(f"Found {len(files)} files in {DATA_DIR}/", file=sys.stderr)
    print(file=sys.stderr)
    
    # Classify each file
    organized: dict[str, list[dict]] = {}  # date → [file_info]
    archive_files = []
    skipped = []
    
    for f in files:
        info = classify_file(f)
        if info.get("skip"):
            skipped.append(info)
            continue
        
        date = info["date"]
        if date not in organized:
            organized[date] = []
        organized[date].append(info)
    
    # Handle files without date → archive
    # (already handled by classify_file which falls back to mtime,
    #  so this shouldn't happen often)
    
    if args.dry_run:
        print("=== DRY RUN — no files will be moved ===\n", file=sys.stderr)
    
    # Move files to run directories
    total_moved = 0
    run_dirs = []
    
    for date in sorted(organized.keys()):
        run_dir = RUNS_DIR / date
        run_dirs.append(run_dir)
        
        if not args.dry_run:
            run_dir.mkdir(parents=True, exist_ok=True)
        
        files_in_run = organized[date]
        print(f"[{date}] {len(files_in_run)} files:", file=sys.stderr)
        
        for info in files_in_run:
            dest = info["dest_path"]
            action = "MOVE" if not dest.exists() else "MERGE"
            
            if args.dry_run:
                print(f"  {info['name']:45s} → {info['run_dir'].name}/{info['dest_name']}", file=sys.stderr)
                continue
            
            # Only move if destination doesn't exist or source is newer
            if dest.exists():
                src_mtime = info["path"].stat().st_mtime
                dst_mtime = dest.stat().st_mtime
                if src_mtime <= dst_mtime:
                    print(f"  ○ {info['name']:45s} (skipped, dest newer)", file=sys.stderr)
                    continue
            
            # Move
            shutil.move(str(info["path"]), str(dest))
            total_moved += 1
            print(f"  ✓ {info['name']:45s} → runs/{date}/{info['dest_name']}", file=sys.stderr)
        
        print(file=sys.stderr)
    
    # Handle competitors directory
    if COMPETITORS_DIR.exists() and COMPETITORS_DIR.is_dir():
        if args.dry_run:
            print(f"[competitors/] Would keep in place (shared across all runs)", file=sys.stderr)
        else:
            print(f"[competitors/] Keeping in place — shared across all runs", file=sys.stderr)
    
    # Update latest symlinks
    if not args.dry_run:
        print(f"\nUpdating latest/ symlinks...", file=sys.stderr)
        update_latest(run_dirs)
    
    print(f"\nDone. {total_moved} files organized.", file=sys.stderr)
    if run_dirs:
        newest = max(run_dirs)
        print(f"Latest run: {newest.name} → data/latest/", file=sys.stderr)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
