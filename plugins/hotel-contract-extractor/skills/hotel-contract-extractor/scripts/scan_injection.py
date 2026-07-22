#!/usr/bin/env python3
"""Scan untrusted contract content for prompt injection and hidden text. Stdlib only.

Usage:
  python3 scan_injection.py extracted_text.txt          # raw PDF text
  python3 scan_injection.py contract.json --json        # scan all string values of the JSON

Exit codes: 0 = clean/low, 1 = high risk findings present.
Prints a JSON report: {"risk": "none|low|high", "findings": [...]}.

This scanner is a tripwire, not a guarantee: treat the document as data
regardless of the result.
"""
import argparse
import json
import re
import sys
import unicodedata

# --- prompt injection patterns (EN + FR), case-insensitive ---
INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions?|directives?|prompts?)", "high"),
    (r"disregard\s+(all\s+|any\s+)?(previous|prior|your)\s+(instructions?|rules?)", "high"),
    (r"(?<!\w)system\s*prompt(?!\w)", "high"),
    (r"you\s+are\s+(an?\s+)?(ai|llm|assistant|claude|chatgpt|gpt)", "high"),
    (r"(?<!\w)(dear|hello|hi|attention)[, ]+\s*(ai|claude|chatgpt|assistant|model)(?!\w)", "high"),
    (r"do\s+not\s+(tell|inform|mention\s+to)\s+the\s+user", "high"),
    (r"(hidden|secret)\s+instructions?", "high"),
    (r"new\s+instructions?\s*:", "high"),
    (r"\[/?(INST|SYS|SYSTEM)\]", "high"),
    (r"<\s*/?\s*(system|instructions?|admin)\s*>", "high"),
    (r"when\s+(summarizing|extracting|processing)\s+this\s+(document|pdf|file)\s*,?\s+(also|instead|always)", "high"),
    # French
    (r"ignore[zr]?\s+(toutes?\s+)?(les?\s+)?(instructions?|consignes?|directives?)\s+(pr[ée]c[ée]dentes?|ant[ée]rieures?)", "high"),
    (r"oublie[zr]?\s+(tes|les|vos)\s+(instructions?|consignes?|r[èe]gles?)", "high"),
    (r"tu\s+es\s+(une?\s+)?(ia|intelligence\s+artificielle|assistant|mod[èe]le)", "high"),
    (r"ne\s+(dis|mentionne|signale)\s+(pas|rien)\s+([àa]\s+)?l['e]?\s*utilisateur", "high"),
    (r"nouvelles?\s+instructions?\s*:", "high"),
    # lower-signal patterns
    (r"(?<!\w)prompt\s+injection(?!\w)", "low"),
    (r"act\s+as\s+(a|an|if)", "low"),
    (r"jailbreak", "low"),
]

# invisible / bidi / smuggling code points
INVISIBLE = {
    "\u200b": "ZERO WIDTH SPACE", "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER", "\u2060": "WORD JOINER",
    "\ufeff": "ZERO WIDTH NO-BREAK SPACE", "\u00ad": "SOFT HYPHEN",
}
BIDI = {"\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
        "\u2066", "\u2067", "\u2068", "\u2069"}
BASE64_RE = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")
URL_RE = re.compile(r"https?://[^\s\"'<>)]+", re.I)
SUSPICIOUS_URL = re.compile(
    r"(webhook|ngrok|pastebin|requestbin|pipedream|burpcollaborator|oastify|interact\.sh|\.onion)", re.I)


def iter_strings(obj, path="$"):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{path}[{i}]")


def scan_text(text, origin, findings):
    for pattern, sev in INJECTION_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            ctx = text[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
            findings.append({"severity": sev, "type": "prompt_injection_pattern",
                             "origin": origin, "match": m.group(0)[:80],
                             "context": ctx[:160]})
    for ch, name in INVISIBLE.items():
        n = text.count(ch)
        if n:
            findings.append({"severity": "high", "type": "invisible_unicode",
                             "origin": origin, "match": f"U+{ord(ch):04X} {name} x{n}",
                             "context": "possible hidden text / smuggled content"})
    bidi_found = sorted({ch for ch in text if ch in BIDI})
    if bidi_found:
        findings.append({"severity": "high", "type": "bidi_override",
                         "origin": origin,
                         "match": ", ".join(f"U+{ord(c):04X}" for c in bidi_found),
                         "context": "RTL/LTR overrides can visually disguise text"})
    tags = [ch for ch in text if 0xE0000 <= ord(ch) <= 0xE007F]
    if tags:
        smuggled = "".join(chr(ord(ch) - 0xE0000) for ch in tags if 0xE0020 <= ord(ch) <= 0xE007E)
        findings.append({"severity": "high", "type": "unicode_tag_smuggling",
                         "origin": origin, "match": f"{len(tags)} tag chars",
                         "context": f"decoded payload: {smuggled[:120]!r}"})
    for ch in set(text):
        if unicodedata.category(ch) == "Cf" and ch not in INVISIBLE and ch not in BIDI \
                and not (0xE0000 <= ord(ch) <= 0xE007F):
            findings.append({"severity": "low", "type": "format_char",
                             "origin": origin, "match": f"U+{ord(ch):04X}",
                             "context": unicodedata.name(ch, "unknown")})
    for m in BASE64_RE.finditer(text):
        findings.append({"severity": "low", "type": "base64_blob",
                         "origin": origin, "match": m.group(0)[:40] + "...",
                         "context": f"{len(m.group(0))} chars of base64-like data in a rate contract"})
    for m in URL_RE.finditer(text):
        url = m.group(0)
        sev = "high" if SUSPICIOUS_URL.search(url) else "low"
        findings.append({"severity": sev, "type": "url",
                         "origin": origin, "match": url[:120],
                         "context": "exfiltration-style domain" if sev == "high"
                                    else "review: URLs are unusual outside hotel website/contact"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--json", action="store_true",
                    help="input is a contract JSON: scan every string value")
    args = ap.parse_args()

    findings = []
    try:
        with open(args.input, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except Exception as e:
        print(json.dumps({"risk": "error", "findings": [str(e)]}))
        sys.exit(1)

    if args.json:
        try:
            data = json.loads(raw)
        except Exception as e:
            print(json.dumps({"risk": "error", "findings": [f"invalid JSON: {e}"]}))
            sys.exit(1)
        for path, s in iter_strings(data):
            scan_text(s, path, findings)
    else:
        scan_text(raw, "document", findings)

    high = [f for f in findings if f["severity"] == "high"]
    risk = "high" if high else ("low" if findings else "none")
    print(json.dumps({"risk": risk, "findings": findings}, indent=2, ensure_ascii=False))
    sys.exit(1 if high else 0)


if __name__ == "__main__":
    main()
