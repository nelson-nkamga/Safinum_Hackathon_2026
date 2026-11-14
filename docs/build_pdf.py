#!/usr/bin/env python3
"""Génère NOTE_TECHNIQUE.html (stylé pour impression) puis NOTE_TECHNIQUE.pdf via Chrome headless."""
import subprocess
from pathlib import Path
import markdown

ROOT = Path(__file__).resolve().parent.parent   # racine du projet (le script vit dans docs/)
MD = ROOT / "NOTE_TECHNIQUE.md"
HTML = ROOT / "docs" / "NOTE_TECHNIQUE.html"
PDF = ROOT / "NOTE_TECHNIQUE.pdf"

body = markdown.markdown(
    MD.read_text(encoding="utf-8"),
    extensions=["tables", "fenced_code", "sane_lists", "smarty"],
)

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "DejaVu Sans", "Noto Sans", sans-serif; font-size: 10.2pt; line-height: 1.5; color: #1a1a2e; }
h1 { font-size: 17pt; color: #2D1B69; border-bottom: 3px solid #00BFFF; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 13.5pt; color: #2D1B69; border-bottom: 1.5px solid #00BFFF55; padding-bottom: 3px; margin-top: 22px; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #0e7490; margin-top: 16px; page-break-after: avoid; }
p { margin: 6px 0; text-align: justify; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.3pt; page-break-inside: avoid; }
th { background: #2D1B69; color: #fff; padding: 5px 8px; text-align: left; }
td { border: 1px solid #ccc; padding: 5px 8px; vertical-align: top; }
tr:nth-child(even) td { background: #f6f7fb; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8.8pt; background: #eef1f7; padding: 1px 4px; border-radius: 3px; }
pre { background: #f4f6fb; border: 1px solid #dde3ef; border-left: 4px solid #00BFFF; border-radius: 4px; padding: 10px 12px; font-size: 8.6pt; line-height: 1.35; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
ul, ol { margin: 6px 0; padding-left: 22px; }
li { margin: 3px 0; }
blockquote { border-left: 4px solid #00BFFF; margin: 8px 0; padding: 2px 12px; color: #444; background: #f6f7fb; }
strong { color: #2D1B69; }
hr { border: none; border-top: 1px solid #ccc; margin: 16px 0; }
"""

html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>SAFINUM — Note technique</title><style>{CSS}</style></head><body>{body}</body></html>"""
HTML.write_text(html, encoding="utf-8")

subprocess.run([
    "google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
    f"--print-to-pdf={PDF}", f"file://{HTML}", "--no-pdf-header-footer",
], check=True, capture_output=True, timeout=120)

print("écrit :", PDF)
