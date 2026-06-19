#!/usr/bin/env python3
"""Convert PIPELINE-ARCHITECTURE.md to a professional PDF."""

import sys
from pathlib import Path

import markdown
from weasyprint import HTML

# ─── Paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent.parent
MD_PATH = SCRIPT_DIR / "PIPELINE-ARCHITECTURE.md"
PDF_PATH = SCRIPT_DIR / "PIPELINE-ARCHITECTURE.pdf"

# ─── CSS styling ──────────────────────────────────────────────────────────
CSS = """
@page {
  size: A4;
  margin: 2cm 2.2cm;
  @top-center {
    content: "aionAI — SEO/GEO Pipeline Architecture";
    font-size: 9pt;
    color: #888;
    font-family: 'DejaVu Sans', sans-serif;
  }
  @bottom-center {
    content: "Page " counter(page) " of " counter(pages);
    font-size: 8pt;
    color: #888;
    font-family: 'DejaVu Sans', sans-serif;
  }
}

body {
  font-family: 'DejaVu Sans', sans-serif;
  font-size: 10pt;
  line-height: 1.6;
  color: #1a1a1a;
}

/* ── Headings ──────────────────────────────────────────────────── */
h1 {
  font-size: 18pt;
  color: #0d47a1;
  border-bottom: 2px solid #0d47a1;
  padding-bottom: 4px;
  margin-top: 30px;
  page-break-before: always;
}
h1:first-of-type {
  page-break-before: avoid;
}

h2 {
  font-size: 14pt;
  color: #1565c0;
  border-bottom: 1px solid #bbb;
  padding-bottom: 3px;
  margin-top: 24px;
}

h3 {
  font-size: 12pt;
  color: #1976d2;
  margin-top: 18px;
}

h4 {
  font-size: 10.5pt;
  color: #333;
  margin-top: 14px;
}

/* ── Tables ─────────────────────────────────────────────────────── */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 9pt;
}
th {
  background: #0d47a1;
  color: white;
  padding: 6px 8px;
  text-align: left;
  font-weight: bold;
}
td {
  padding: 5px 8px;
  border-bottom: 1px solid #ddd;
}
tr:nth-child(even) td {
  background: #f5f8ff;
}

/* ── Code blocks ────────────────────────────────────────────────── */
code {
  font-family: 'DejaVu Sans Mono', monospace;
  font-size: 8.5pt;
}
pre {
  background: #f0f4f8;
  border: 1px solid #d0d8e0;
  border-left: 3px solid #0d47a1;
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 7.8pt;
  line-height: 1.3;
  margin: 10px 0;
}
pre code {
  background: none;
  padding: 0;
}

/* ── Inline code ────────────────────────────────────────────────── */
p code, li code {
  background: #eef3f7;
  padding: 1px 4px;
  border-radius: 2px;
  font-size: 8.5pt;
}

/* ── Lists ──────────────────────────────────────────────────────── */
ul, ol {
  margin: 6px 0;
  padding-left: 20px;
}
li {
  margin-bottom: 3px;
}

/* ── Blockquotes / notes ────────────────────────────────────────── */
blockquote {
  border-left: 4px solid #ff9800;
  background: #fff8e1;
  padding: 8px 12px;
  margin: 10px 0;
  font-size: 9.5pt;
}
blockquote p { margin: 0; }

/* ── Strong / emphasis ──────────────────────────────────────────── */
strong { color: #0d47a1; }

/* ── Section dividers ───────────────────────────────────────────── */
hr {
  border: none;
  border-top: 1px solid #ccc;
  margin: 20px 0;
}

/* ── First page title area ──────────────────────────────────────── */
.title-area {
  text-align: center;
  padding: 60px 0 30px 0;
}
.title-area h1 {
  font-size: 22pt;
  border: none;
  margin: 0;
  page-break-before: avoid;
}
.title-area .subtitle {
  font-size: 12pt;
  color: #666;
  margin-top: 6px;
}
.title-area .date {
  font-size: 10pt;
  color: #999;
  margin-top: 4px;
}
.title-area .logo {
  font-size: 28pt;
  color: #0d47a1;
  margin-bottom: 10px;
}
"""


def md_to_html(md_text: str) -> str:
    """Convert markdown to HTML with extensions."""
    extensions = [
        'extra',           # tables, fenced code, footnotes, etc
        'toc',             # table of contents
        'sane_lists',      # better list behavior
        'smarty',          # smart quotes
    ]
    html_body = markdown.markdown(md_text, extensions=extensions)

    # ── Build full HTML document ─────────────────────────────────────────
    # Extract title for the title area
    title = "SEO/GEO Pipeline Architecture"
    subtitle = "aionAI — Complete Technical Reference"

    html_full = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>

<div class="title-area">
  <div class="logo">⚙️</div>
  <h1>{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="date">Generated: 2026-06-17</div>
</div>

{html_body}

</body>
</html>"""
    return html_full


def main():
    if not MD_PATH.exists():
        print(f"ERROR: {MD_PATH} not found")
        sys.exit(1)

    print(f"📖 Reading {MD_PATH}...")
    md_text = MD_PATH.read_text(encoding="utf-8")
    print(f"   {len(md_text):,} characters, {len(md_text.splitlines())} lines")

    print("🔄 Converting markdown to HTML...")
    html = md_to_html(md_text)

    print(f"📄 Generating PDF → {PDF_PATH}...")
    HTML(string=html).write_pdf(str(PDF_PATH))

    pdf_size = PDF_PATH.stat().st_size
    print(f"✅ PDF created: {PDF_PATH}")
    print(f"   Size: {pdf_size:,} bytes ({pdf_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
