"""Read-only discovery from the public Ollama library."""
import json
import re
import sys
import time
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import urlopen
from urllib.error import URLError

BASE = "https://ollama.com"
NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]*"

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.active = [dict(attrs).get("href", ""), []]

    def handle_data(self, data):
        if self.active:
            self.active[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            href, chunks = self.active
            self.rows.append((href, " ".join(" ".join(chunks).split())))
            self.active = None

def fetch(path, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("Catalog time budget exhausted.")
    try:
        with urlopen(BASE + path, timeout=min(10, remaining)) as response:
            body = response.read(8_000_001)
        if len(body) > 8_000_000:
            raise RuntimeError("Catalog response too large.")
    except (URLError, OSError):
        raise RuntimeError("Ollama catalog unavailable; try again later.") from None
    parser = Links()
    parser.feed(body.decode("utf-8"))
    return parser.rows

def library_path(href):
    url = urlsplit(href)
    if url.netloc not in ("", "ollama.com"):
        return ""
    return unquote(url.path)

def table(headers, rows):
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    for row in [headers, *rows]:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())

def search(query, all_models):
    catalog = json.loads(Path(__file__).with_name("catalog.json").read_text())
    results = {}
    deadline = time.monotonic() + 30
    print("Fetching Ollama catalog...", file=sys.stderr, flush=True)
    # Query each known prefix for the expanded view; never crawl every tag page.
    terms = sorted({p for prefixes in catalog.values() for p in prefixes}) if all_models else [query or ""]
    incomplete = False
    for term in terms:
        try:
            links = fetch("/search?" + urlencode({"q": term}), deadline)
        except RuntimeError as exc:
            if not results:
                raise
            print("Warning: " + str(exc), file=sys.stderr)
            incomplete = True
            break
        for href, label in links:
            match = re.fullmatch("/library/(" + NAME + ")", library_path(href))
            if not match:
                continue
            name = match[1]
            if query and query.lower() not in name.lower():
                continue
            if re.search(r"\bcloud\b", label) and not re.search(r"\b(?:e?\d+(?:\.\d+)?b)\b", label, re.I):
                continue
            for vendor, prefixes in catalog.items():
                if any(name.lower().startswith(p) for p in prefixes):
                    sizes = ", ".join(dict.fromkeys(re.findall(r"\b(?:e?\d+(?:\.\d+)?b)\b", label, re.I)))
                    results[name] = (vendor, name, sizes or "—")
                    break
    if results:
        table(("DEVELOPER", "MODEL", "PARAMETERS (approx.)"), sorted(results.values()))
    else:
        print("No matching models in returned catalog pages.")
    print("Note: public search results are limited; completeness and local availability are not guaranteed.", file=sys.stderr)
    if incomplete:
        raise RuntimeError("Partial catalog results; narrow the search.")

def tags(model):
    if not re.fullmatch(NAME, model):
        raise RuntimeError("Use a library model name without a tag, e.g. qwen3.")
    print("Fetching Ollama tags...", file=sys.stderr, flush=True)
    rows = {}
    for href, label in fetch("/library/" + model + "/tags", time.monotonic() + 30):
        match = re.fullmatch("/library/(" + re.escape(model) + r":[A-Za-z0-9_.-]+)", library_path(href))
        if not match:
            continue
        name = match[1]
        if "cloud" in name.lower() or re.search(r"\bcloud\b", label, re.I):
            continue
        size = re.search(r"\b\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB)\b", label, re.I)
        if size or name not in rows:
            rows[name] = (name, size[0] if size else "—")
    if not rows:
        raise RuntimeError("No local tags found; check the model name or catalog layout.")
    table(("MODEL TAG", "DOWNLOAD SIZE"), list(rows.values()))
