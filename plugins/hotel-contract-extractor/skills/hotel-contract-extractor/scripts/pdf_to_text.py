#!/usr/bin/env python3
"""Convert a hotel contract PDF to text before LLM analysis. Token-reduction step.

Usage:
  python3 pdf_to_text.py contract.pdf --out /tmp/contract.txt

What it does:
 1. Extracts the text layer, trying in order: pdftotext -layout (best for
    rate grids), PyMuPDF, pdfplumber, pypdf.
 2. Pages with almost no text are considered scanned and sent to OCR
    (pytesseract + PyMuPDF rasterization at 300 dpi, lang fra+eng). If OCR
    dependencies are missing, those pages are flagged for visual reading.
 3. Scores every page for rate-relevance (currency, dates, FR/EN tariff
    keywords, digit density) so the LLM can skip marketing pages.

Output: text file with '=== PAGE n ===' markers, and a JSON report on
stdout: method, pages, ocr_pages, unreadable_pages, relevant_pages,
noise_pages (with a preview line each so relevance can be sanity-checked).

Dependencies (all optional, graceful degradation):
  pdftotext (poppler-utils) | pip: pymupdf, pdfplumber, pypdf, pytesseract
  OCR additionally needs the tesseract binary (+ tesseract-ocr-fra ideally).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys

MIN_CHARS_TEXT_PAGE = 60  # below this, the page is presumed scanned

KEYWORDS = [
    # FR
    "tarif", "prix", "saison", "chambre", "nuit", "nuitee", "pension",
    "petit-dejeuner", "demi-pension", "pension complete", "annulation",
    "acompte", "arrhes", "supplement", "reduction", "gratuit", "taxe",
    "sejour", "enfant", "adulte", "groupe", "individuel", "conditions",
    "reservation", "release", "occupation", "single", "double", "twin",
    # EN
    "rate", "price", "season", "room", "night", "board", "breakfast",
    "half board", "full board", "cancellation", "deposit", "surcharge",
    "child", "adult", "group", "fit", "allotment", "min stay", "check-in",
    "occupancy", "per person", "per room",
]
KW_RE = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.I)
CURRENCY_RE = re.compile(r"€|\$|£|\b(EUR|USD|GBP|CHF|MAD|TND|THB|IDR)\b")
DATE_RE = re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")


def try_pdftotext(pdf):
    if not shutil.which("pdftotext"):
        return None
    pages, n = [], 1
    while True:
        r = subprocess.run(["pdftotext", "-layout", "-f", str(n), "-l", str(n), pdf, "-"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None if n == 1 else pages
        # pdftotext emits a formfeed even for out-of-range pages on some versions:
        # detect end by asking page count first instead
        pages.append(r.stdout)
        n += 1
        if n > 500:
            return pages
    # unreachable


def page_count_pdftotext(pdf):
    if not shutil.which("pdfinfo"):
        return None
    r = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True)
    m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
    return int(m.group(1)) if m else None


def extract_pdftotext(pdf):
    n = page_count_pdftotext(pdf)
    if n is None or not shutil.which("pdftotext"):
        return None, None
    pages = []
    for i in range(1, n + 1):
        r = subprocess.run(["pdftotext", "-layout", "-f", str(i), "-l", str(i), pdf, "-"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None, None
        pages.append(r.stdout)
    return pages, "pdftotext -layout"


def extract_pymupdf(pdf):
    try:
        import fitz
    except ImportError:
        return None, None
    doc = fitz.open(pdf)
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return pages, "pymupdf"


def extract_pdfplumber(pdf):
    try:
        import pdfplumber
    except ImportError:
        return None, None
    with pdfplumber.open(pdf) as doc:
        pages = [(p.extract_text(layout=True) or "") for p in doc.pages]
    return pages, "pdfplumber"


def extract_pypdf(pdf):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, None
    reader = PdfReader(pdf)
    return [(p.extract_text() or "") for p in reader.pages], "pypdf"


def ocr_page(pdf, page_index):
    """OCR one page via PyMuPDF rasterization + pytesseract. Returns text or None."""
    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        return None
    if not shutil.which("tesseract"):
        return None
    doc = fitz.open(pdf)
    pix = doc[page_index].get_pixmap(dpi=300)
    doc.close()
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    langs = pytesseract.get_languages(config="")
    lang = "fra+eng" if "fra" in langs else "eng"
    try:
        return pytesseract.image_to_string(img, lang=lang)
    except Exception:
        return None


def score_page(text):
    kw = len(KW_RE.findall(text))
    cur = len(CURRENCY_RE.findall(text))
    dates = len(DATE_RE.findall(text))
    alnum = [c for c in text if c.isalnum()]
    digit_ratio = (sum(c.isdigit() for c in alnum) / len(alnum)) if alnum else 0.0
    score = kw + 2 * cur + dates + (5 if digit_ratio > 0.15 else 0)
    return score, {"keywords": kw, "currency": cur, "dates": dates,
                   "digit_ratio": round(digit_ratio, 3)}


def first_line(text, n=70):
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:n]
    return "(blank)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True)
    ap.add_argument("--noise-threshold", type=int, default=3,
                    help="pages scoring below this are classified as noise (default 3)")
    args = ap.parse_args()

    pages, method = None, None
    for extractor in (extract_pdftotext, extract_pymupdf, extract_pdfplumber, extract_pypdf):
        pages, method = extractor(args.pdf)
        if pages is not None:
            break
    if pages is None:
        print(json.dumps({"status": "error",
                          "error": "no PDF text extractor available: install poppler-utils "
                                   "or pip install pymupdf / pdfplumber / pypdf"}))
        sys.exit(2)

    ocr_pages, unreadable = [], []
    for i, text in enumerate(pages):
        if len(text.strip()) < MIN_CHARS_TEXT_PAGE:
            ocr_text = ocr_page(args.pdf, i)
            if ocr_text and len(ocr_text.strip()) >= MIN_CHARS_TEXT_PAGE:
                pages[i] = ocr_text
                ocr_pages.append(i + 1)
            else:
                unreadable.append(i + 1)

    relevant, noise = [], []
    with open(args.out, "w", encoding="utf-8") as fh:
        for i, text in enumerate(pages, 1):
            fh.write(f"=== PAGE {i} ===\n{text.strip()}\n\n")
            score, detail = score_page(text)
            entry = {"page": i, "score": score, "preview": first_line(text), **detail}
            (relevant if score >= args.noise_threshold else noise).append(entry)

    print(json.dumps({
        "status": "ok",
        "method": method,
        "pages": len(pages),
        "ocr_pages": ocr_pages,
        "unreadable_pages": unreadable,
        "unreadable_hint": "read these pages visually from the PDF" if unreadable else None,
        "relevant_pages": [e["page"] for e in relevant],
        "noise_pages": noise,
        "out": args.out
    }, indent=2, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
