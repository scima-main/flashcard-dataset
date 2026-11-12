"""Real-source harvester for the flashcard SFT corpus.

Canonical hosts only (no proxies, no URL rewriting):
  {lang}.wikipedia.org, api.stackexchange.com, www.doaj.org,
  raw.githubusercontent.com, www.gutenberg.org, archive.org,
  developer.mozilla.org, openstax.org, www.who.int, oyc.yale.edu,
  www.sqlite.org, legislation.gov.uk, science.nasa.gov ...

Every fetch records the exact URL, HTTP status, licence and timestamp in
harvest/{docid}.json so the sidecar can carry real attribution.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDIR = os.path.join(ROOT, "harvest")
os.makedirs(HDIR, exist_ok=True)

UA = ("FlashcardSFTCorpus/1.0 (educational SFT dataset research; contact: "
      "dataset-maintainer@example.org) python-urllib/3.11")

SKIP = {"script", "style", "noscript", "svg", "head", "form", "button", "input",
        "select", "textarea", "iframe"}
CHROME = {"nav", "header", "footer", "aside"}
BLOCK = {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4",
         "h5", "h6", "br", "blockquote", "pre", "table", "ul", "ol", "dl", "dd",
         "dt", "figure", "figcaption", "hr", "main"}


class H2T(HTMLParser):
    """HTML -> plain text, preserving reference markers, code, tables, math alt."""

    def __init__(self, keep_chrome=False, keep_tables=True, math_alt=True):
        super().__init__(convert_charrefs=True)
        self.keep_chrome = keep_chrome
        self.keep_tables = keep_tables
        self.math_alt = math_alt
        self.out = []
        self.skip_depth = 0
        self.skip_tag = None
        self.pre_depth = 0
        self.in_table = 0
        self.cell = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth += 1
            return
        if tag in SKIP or (tag in CHROME and not self.keep_chrome):
            self.skip_tag = tag
            self.skip_depth = 1
            return
        cls = a.get("class", "") or ""
        # Wikipedia / MediaWiki junk that a browser copy would not include
        if any(k in cls for k in ("mw-editsection", "noprint", "navbox",
                                  "vertical-navbox", "sistersitebox",
                                  "mw-jump-link", "reference-accessdate")):
            if tag in ("span", "div", "table", "sup"):
                self.skip_tag = tag
                self.skip_depth = 1
                return
        if tag == "pre":
            self.pre_depth += 1
            self.out.append("\n")
        elif tag == "table":
            self.in_table += 1
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "img" and self.math_alt:
            alt = a.get("alt", "")
            if alt:
                self._emit(alt)
        elif tag == "math" and self.math_alt:
            alt = a.get("alttext", "")
            if alt:
                self._emit(" " + alt + " ")
        elif tag in BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == self.skip_tag:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip_tag = None
            return
        if tag == "pre":
            self.pre_depth = max(0, self.pre_depth - 1)
            self.out.append("\n")
        elif tag == "table":
            self.in_table = max(0, self.in_table - 1)
            self.out.append("\n")
        elif tag in ("td", "th") and self.in_table and self.keep_tables:
            txt = "".join(self.cell).strip()
            self.out.append(txt + " | ")
            self.cell = []
        elif tag in BLOCK:
            self.out.append("\n")

    def _emit(self, data):
        if self.in_table and self.cell is not None and self.keep_tables:
            self.cell.append(data)
        else:
            self.out.append(data)

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.pre_depth:
            self._emit(data)
        else:
            self._emit(re.sub(r"[ \t\r\f\v]+", " ", data))

    def text(self):
        t = "".join(self.out)
        t = t.replace("\u00a0", " ").replace("\u200b", "")
        lines = []
        for ln in t.split("\n"):
            ln = ln.rstrip()
            ln = re.sub(r" {2,}", " ", ln) if not ln.startswith(("    ", "\t")) else ln
            if ln.strip() == "|":
                continue
            if ln.strip() or (lines and lines[-1].strip()):
                lines.append(ln)
        return "\n".join(lines).strip()


def html2text(raw, **kw):
    p = H2T(**kw)
    p.feed(raw)
    p.close()
    return p.text()


def fetch(url, binary=False, tries=4, pause=2.0):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "en,zh,de,fr,es,ja,ru,pt,ar,hi;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
                enc = r.headers.get_content_charset() or "utf-8"
            return data if binary else data.decode(enc, "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(pause * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {type(last).__name__} {last}")


def save(docid, text, url, licence, origin, title, extra=None):
    with open(os.path.join(HDIR, docid + ".txt"), "w", encoding="utf8") as f:
        f.write(text)
    rec = {"docid": docid, "url": url, "licence": licence, "origin": origin,
           "title": title, "fetched": time.strftime("%Y-%m-%d"), "chars": len(text)}
    if extra:
        rec.update(extra)
    with open(os.path.join(HDIR, docid + ".json"), "w", encoding="utf8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return rec


# ---------------------------------------------------------------- Wikipedia
def wiki(lang, title, docid, mode="html", keep_chrome=False, licence="CC BY-SA 4.0"):
    """mode=html: content HTML -> text (keeps [1] markers, captions, tables).
    mode=page: full canonical page HTML (keeps real nav chrome / retrieval dates).
    mode=extract: clean API plaintext extract."""
    if mode == "extract":
        q = urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": "2",
            "titles": title, "prop": "extracts", "explaintext": "1",
            "redirects": "1"})
        url = f"https://{lang}.wikipedia.org/w/api.php?{q}"
        j = json.loads(fetch(url))
        pg = j["query"]["pages"][0]
        text = pg["extract"]
        real = pg["title"]
    elif mode == "page":
        url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        raw = fetch(url)
        text = html2text(raw, keep_chrome=keep_chrome)
        real = title
    else:
        q = urllib.parse.urlencode({
            "action": "parse", "format": "json", "formatversion": "2",
            "page": title, "prop": "text", "redirects": "1",
            "disablelimitreport": "1"})
        url = f"https://{lang}.wikipedia.org/w/api.php?{q}"
        j = json.loads(fetch(url))
        text = html2text(j["parse"]["text"], keep_chrome=keep_chrome)
        real = j["parse"]["title"]
    return save(docid, text, url, licence, f"{lang}.wikipedia.org", real,
                {"lang": lang, "mode": mode})


# ---------------------------------------------------------- Stack Exchange
def stackexchange(site, qid, docid, answers=1, licence="CC BY-SA 4.0"):
    q = urllib.parse.urlencode({
        "site": site, "filter": "withbody", "order": "desc", "sort": "votes",
        "pagesize": str(answers)})
    url = f"https://api.stackexchange.com/2.3/questions/{qid}/answers?{q}"
    j = json.loads(fetch(url))
    qu = f"https://api.stackexchange.com/2.3/questions/{qid}?site={site}&filter=withbody"
    jq = json.loads(fetch(qu))
    parts = []
    if jq.get("items"):
        it = jq["items"][0]
        parts.append("Q: " + html.unescape(it["title"]) + "\n" +
                     html2text(it.get("body", "")))
    for it in j.get("items", [])[:answers]:
        parts.append("A (score %s):\n" % it.get("score") + html2text(it["body"]))
    text = "\n\n".join(parts)
    link = jq["items"][0]["link"] if jq.get("items") else url
    return save(docid, text, link, licence, f"{site}.stackexchange.com",
                jq["items"][0]["title"] if jq.get("items") else str(qid),
                {"lang": "en", "api_url": url, "score": j.get("items", [{}])[0].get("score")})


# ------------------------------------------------------------------- DOAJ
def doaj(query, docid, licence_filter=None, page_size=8):
    url = ("https://www.doaj.org/api/search/articles/" +
           urllib.parse.quote(query) + f"?pageSize={page_size}")
    j = json.loads(fetch(url))
    out = []
    for it in j.get("results", []):
        b = it["bibjson"]
        lic = next((l.get("type") for l in b.get("link", []) if l.get("type") == "license"), None)
        lic = lic or (b.get("license") or [{}])[0].get("type")
        out.append({"title": b.get("title"), "abstract": b.get("abstract"),
                    "journal": (b.get("journal") or {}).get("title"),
                    "year": b.get("year"), "licence": lic,
                    "doi": next((i["id"] for i in b.get("identifier", []) if i["type"] == "doi"), None),
                    "url": next((l["url"] for l in b.get("link", []) if l.get("type") == "fulltext"), None)})
    with open(os.path.join(HDIR, docid + ".search.json"), "w", encoding="utf8") as f:
        json.dump({"query": query, "url": url, "results": out}, f, ensure_ascii=False, indent=1)
    return out


def doaj_save(pick, docid):
    text = pick["title"] + "\n\n" + (pick.get("abstract") or "")
    return save(docid, text, pick.get("url") or pick.get("doi") or "",
                pick.get("licence") or "unknown", "DOAJ / open-access journal",
                pick["title"], {"lang": "en", "journal": pick.get("journal"),
                                "year": pick.get("year"), "doi": pick.get("doi"),
                                "kind": "abstract"})


# ------------------------------------------------------------------ generic
def page(url, docid, licence, origin, title, lang="en", keep_chrome=False,
         raw_md=False):
    raw = fetch(url)
    text = raw if raw_md else html2text(raw, keep_chrome=keep_chrome)
    return save(docid, text, url, licence, origin, title, {"lang": lang})


def plain(url, docid, licence, origin, title, lang="en"):
    text = fetch(url)
    return save(docid, text, url, licence, origin, title, {"lang": lang})


def show(docid, start=0, words=None, chars=None, head=None):
    """Print a stored source (optionally a slice) for card authoring."""
    t = open(os.path.join(HDIR, docid + ".txt"), encoding="utf8").read()
    if chars:
        t = t[start:start + chars]
    elif words:
        w = t.split()
        t = " ".join(w[start:start + words])
    elif head:
        t = "\n".join(t.split("\n")[:head])
    print(f"===== {docid} ({len(t)} chars) =====")
    print(t)
    print()


def trim(docid, start=0, words=None, chars=None, start_marker=None, end_marker=None):
    """Cut a stored source down to the exact excerpt used for authoring.
    The shipped source is byte-identical to what the card author read."""
    p = os.path.join(HDIR, docid + ".txt")
    t = open(p, encoding="utf8").read()
    if start_marker:
        i = t.find(start_marker)
        if i < 0:
            raise ValueError(f"marker not found in {docid}: {start_marker[:40]}")
        t = t[i:]
    if end_marker:
        j = t.find(end_marker)
        if j > 0:
            t = t[:j]
    if chars:
        t = t[start:start + chars]
    elif words:
        # cut at the end of the Nth word, preserving original newlines/indentation
        ms = list(re.finditer(r"\S+", t))
        if start + words < len(ms):
            t = t[:ms[start + words - 1].end()]
        elif start:
            t = t[ms[start].start():]
    t = t.strip()
    open(p, "w", encoding="utf8").write(t)
    jp = os.path.join(HDIR, docid + ".json")
    rec = json.load(open(jp, encoding="utf8"))
    rec["chars"] = len(t)
    rec["trimmed"] = True
    json.dump(rec, open(jp, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    return t


def who_trim(did, words=None):
    """WHO fact sheets: cut the site-wide nav, keep breadcrumb title onward."""
    p = os.path.join(HDIR, did + ".txt")
    t = open(p, encoding="utf8").read()
    i = t.find("Detail/")
    if i >= 0:
        t = t[i + len("Detail/"):].lstrip(" -\n")
    open(p, "w", encoding="utf8").write(t)
    return trim(did, words=words) if words else t
