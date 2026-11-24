"""Read-only discovery from the public Ollama library."""
import json
import os
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
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    for index, row in enumerate([headers, *rows]):
        cells = []
        for i, (value, width) in enumerate(zip(row, widths)):
            cell = value.ljust(width)
            if color and (index == 0 or headers[i] in ("MODEL", "MODEL TAG")):
                cell = ("\033[36m" if index == 0 else "\033[32m") + cell + "\033[0m"
            cells.append(cell)
        print("  ".join(cells).rstrip())

def search(query):
    catalog = json.loads(Path(__file__).with_name("catalog.json").read_text())
    results = {}
    deadline = time.monotonic() + 30
    print("Fetching Ollama catalog...", file=sys.stderr, flush=True)
    # Browse each known family when no query is supplied.
    terms = [query] if query else sorted({p for prefixes in catalog.values() for p in prefixes})
    cloud_matches = set()
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
                cloud_matches.add(name)
                continue
            for vendor, prefixes in catalog.items():
                if any(name.lower().startswith(p) for p in prefixes):
                    sizes = ", ".join(dict.fromkeys(s.lower() for s in re.findall(r"\b(?:e?\d+(?:\.\d+)?b)\b", label, re.I)))
                    results[name] = (vendor, name, sizes or "—")
                    break
    if results:
        table(("DEVELOPER", "MODEL", "PARAMETERS (approx.)"), sorted(results.values()))
        print(f"{len(results)} models found.")
    elif cloud_matches:
        print("No local matches; cloud-only candidates were excluded.")
    else:
        print("No matching models in returned catalog pages.")
    if incomplete:
        raise RuntimeError("Partial catalog results; narrow the search.")

def tags(model, all_tags=False):
    model, separator, prefix = model.partition(":")
    if not re.fullmatch(NAME, model) or (separator and not re.fullmatch(NAME, prefix)):
        raise RuntimeError("Use a model name or tag prefix, e.g. qwen3 or qwen3:4b.")
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
    if separator:
        rows = {name: row for name, row in rows.items()
                if name.split(":", 1)[1] == prefix
                or name.split(":", 1)[1].startswith(prefix + "-")}
        if not rows:
            print("No matching local tags.")
            return
    total = len(rows)
    selected = list(rows.values())
    if not all_tags and not separator:
        short = [row for row in selected if re.fullmatch(
            r"latest|\d+(?:\.\d+)?[bm]", row[0].split(":", 1)[1], re.I)]
        if short:
            selected = short
        else:
            selected = selected[:20]
            print("No standard short tags; showing up to 20 catalog entries.")
    table(("MODEL TAG", "DOWNLOAD SIZE"), selected)
    print(f"{len(selected)} of {total} matching local tags shown.")
    if len(selected) < total:
        print("Use --all to show additional variants.")
