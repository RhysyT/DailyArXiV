#!/usr/bin/env python3
import re, requests, datetime
from bs4 import BeautifulSoup
from typing import List, Tuple, Dict, Set

UA = {"User-Agent": "arxiv-onecall-html/1.1 (+you@example.com)"}
BASE = "https://arxiv.org"

PRIORITY_CODES: Set[str] = {"astro-ph.GA", "astro-ph.IM"}
INTEREST_CATS: List[str] = ["physics.hist-ph", "physics.ed-ph", "physics.pop-ph"]

HUMAN_NAMES: Dict[str, str] = {
    "astro-ph.GA": "Astrophysics of Galaxies",
    "astro-ph.IM": "Instrumentation and Methods",
    "physics.hist-ph": "History & Philosophy of Physics",
    "physics.ed-ph": "Physics Education",
    "physics.pop-ph": "Popular Physics",
}

def fetch_list_html(category: str) -> str:
    url = f"{BASE}/list/{category}/new"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.text

def parse_list(html: str) -> List[Dict[str, object]]:
    """Return list of entries: {id, title, abstract, abs_url, codes(set[str])}"""
    soup = BeautifulSoup(html, "html.parser")
    dts = soup.select("dl#articles > dt")
    dds = soup.select("dl#articles > dd")

    entries: List[Dict[str, object]] = []
    for dt, dd in zip(dts, dds):
        a = dt.select_one('a[href^="/abs/"]')
        if not a:
            continue
        m = re.search(r"/abs/(\d{4}\.\d{5}(?:v\d+)?)", a.get("href", ""))
        if not m:
            continue
        arxid = m.group(1)
        abs_url = BASE + a["href"]

        # Title
        t_el = dd.select_one(".list-title")
        title = t_el.get_text(" ", strip=True).replace("Title:", "", 1).strip() if t_el else ""

        # Abstract
        p = dd.select_one("p.mathjax")
        abstract = p.get_text(" ", strip=True) if p else ""
        if abstract.startswith("Abstract:"):
            abstract = abstract[len("Abstract:"):].strip()

        # Subjects → codes like (astro-ph.GA), (physics.hist-ph)
        subj_el = dd.select_one(".list-subjects")
        subj_txt = subj_el.get_text(" ", strip=True) if subj_el else ""
        codes: Set[str] = set(re.findall(r"\(([A-Za-z0-9.\-]+)\)", subj_txt))

        # Apply LaTeX-like text normalizer outside math regions
        title = normalize_tex_like(title)
        abstract = normalize_tex_like(abstract)

        entries.append({
            "id": arxid,
            "title": title,
            "abstract": abstract,
            "abs_url": abs_url,
            "codes": codes,
        })
    return entries

def escape_html(s: str) -> str:
    return (s.replace("&","&amp;")
             .replace("<","&lt;")
             .replace(">","&gt;")
             .replace('"',"&quot;"))

def ordinal_day(d: int) -> str:
    if 10 <= d % 100 <= 20: suf = "th"
    else: suf = {1:"st",2:"nd",3:"rd"}.get(d % 10, "th")
    return f"{d}{suf}"

def nice_date(dt: datetime.date) -> str:
    return f"{ordinal_day(dt.day)} {dt.strftime('%B %Y')}"

def html_head(page_title: str) -> str:
    mj_config = """
    <script>
    window.MathJax = {
      tex: {
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$','$$'], ['\\\\[','\\\\]']],
        packages: {'[+]': ['textmacros']}
      },
      options: { skipHtmlTags: ['script','noscript','style','textarea','pre','code'] }
    };
    </script>
    <script id="MathJax-script" async
      src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape_html(page_title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{
    --ink: #1b1f23; --muted: #666; --rule: #eee; --accent: #004aad;
  }}
  body {{ font: 16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
         margin: 2rem auto; max-width: 900px; padding: 0 1rem; color: var(--ink); }}
  h1 {{ margin: 0 0 .25rem 0; font-size: 1.8rem; }}
  .sub {{ color: var(--muted); margin: 0 0 1.25rem 0; }}
  h2 {{ margin: 1.5rem 0 .5rem; font-size: 1.15rem; color: var(--muted); font-weight: 600; }}
  article {{ padding: .75rem 0; border-top: 1px solid var(--rule); }}
  a.title {{ text-decoration: none; font-weight: 600; color: inherit; }}
  a.title:hover {{ text-decoration: underline; color: var(--accent); }}
  .id {{ color:#999; font-size:.9rem; margin-left:.5rem; }}
  details {{ margin-top: .35rem; }}
  summary {{ cursor: pointer; color: var(--accent); outline: none; }}
  .num {{ font-variant-numeric: tabular-nums; width: 2.25rem; display:inline-block; color:#999; }}
</style>
{mj_config}
</head>
<body>
"""

def html_tail() -> str:
    return "</body>\n</html>"

def html_section(heading: str, items: List[Dict[str, object]], start_index: int = 1) -> Tuple[str, int]:
    parts = [f"<h2>{escape_html(heading)}</h2>"]
    n = start_index
    for it in items:
        title = (it["title"] or it["id"])  # type: ignore
        parts.append(
            f'<article>'
            f'<div><span class="num">{n:>2}.</span> '
            f'<a class="title" href="{it["abs_url"]}" target="_blank" rel="noopener noreferrer">{escape_html(str(title))}</a>'
            f'<span class="id">[{it["id"]}]</span></div>'
            f'<details><summary>Abstract</summary><div><p>{escape_html(str(it["abstract"]))}</p></div></details>'
            f'</article>'
        )
        n += 1
    return "".join(parts), n

def html_page(page_title: str, date_str: str, top_subtitle: str,
              sections: List[Tuple[str, List[Dict[str, object]]]]) -> str:
    total = sum(len(items) for _, items in sections)
    head = html_head(f"{page_title} — {date_str}")

    # Build category list for this page (only categories that actually have items)
    cats = [subheader for (subheader, items) in sections if items]
    cats_str = "; ".join(cats)

    # Subtitle: date · categories (if any) · total entries
    meta_bits = [date_str]
    if cats_str:
        meta_bits.append(cats_str)
    meta_bits.append(f'{total} entr{"y" if total==1 else "ies"}')

    body = [
        f"<h1>{escape_html(page_title)}</h1>",
        f'<div class="sub">{escape_html(" · ".join(meta_bits))}</div>'
    ]
    if top_subtitle:
        body.append(f"<h2>{escape_html(top_subtitle)}</h2>")
    i = 1
    for subheader, items in sections:
        if not items:
            continue
        sec_html, i = html_section(subheader, items, start_index=i)
        body.append(sec_html)
    return head + "\n".join(body) + html_tail()

# -----------------------------
# LaTeX-like text normalizer
# -----------------------------

# Match math regions and KEEP delimiters so MathJax can render them.
_MATH_RE = re.compile(
    r'(\\\(.+?\\\)|\\\[.+?\\\]|\$\$.*?\$\$|\$.*?\$)',
    re.DOTALL
)

_tex_replacements = [
    (re.compile(r"---"), "—"),        # em dash
    (re.compile(r"--"), "–"),         # en dash
    (re.compile(r"``"), "“"),         # opening double quote
    (re.compile(r"''"), "”"),         # closing double quote
    (re.compile(r"\\,\s*"), "\u2009"),# thin space
    (re.compile(r"\\;"), "\u2005"),   # four-per-em / medium space
    (re.compile(r"\\:"), "\u2005"),   # medium space
    (re.compile(r"\\!"), ""),         # negative thin space → drop
    (re.compile(r"~"), "\u00A0"),     # non-breaking space
    (re.compile(r"\\-"), ""),         # discretionary hyphen → drop
    (re.compile(r"\\/"), ""),         # italic correction → drop
    (re.compile(r"\\&"), "&"),        # escaped ampersand
]

def _apply_tex_outside_math(s: str) -> str:
    out: List[str] = []
    pos = 0
    for m in _MATH_RE.finditer(s):
        # Non-math text before the math region
        if m.start() > pos:
            chunk = s[pos:m.start()]
            for pat, repl in _tex_replacements:
                chunk = pat.sub(repl, chunk)
            out.append(chunk)
        # Math region itself (keep exactly as-is, including delimiters)
        out.append(m.group(0))
        pos = m.end()
    # Trailing non-math text
    if pos < len(s):
        chunk = s[pos:]
        for pat, repl in _tex_replacements:
            chunk = pat.sub(repl, chunk)
        out.append(chunk)
    return "".join(out)

def normalize_tex_like(s: str) -> str:
    """
    Apply a few typographic substitutions commonly used in LaTeX text,
    but leave math segments (delimited by $...$, $$...$$, \(...\), \[...\]) untouched.
    """
    if not s:
        return s
    return _apply_tex_outside_math(s)

# -----------------------------

def main():
    today = datetime.date.today()
    stamp = today.strftime("%Y%m%d")
    date_long = nice_date(today)

    # ASTRO — Priority/Main
    astro_entries = parse_list(fetch_list_html("astro-ph"))

    pri_ga: List[Dict[str, object]] = []
    pri_im: List[Dict[str, object]] = []
    main_rest: List[Dict[str, object]] = []
    for e in astro_entries:
        if "astro-ph.GA" in e["codes"]:
            pri_ga.append(e)
        elif "astro-ph.IM" in e["codes"]:
            pri_im.append(e)
        else:
            main_rest.append(e)

    # INTEREST — per physics subcat
    interest_groups: List[Tuple[str, List[Dict[str, object]]]] = []
    for cat in INTEREST_CATS:
        ents = parse_list(fetch_list_html(cat))
        interest_groups.append((HUMAN_NAMES.get(cat, cat), ents))

    # Write files
    priority_sections: List[Tuple[str, List[Dict[str, object]]]] = [
        (HUMAN_NAMES["astro-ph.GA"], pri_ga),
        (HUMAN_NAMES["astro-ph.IM"], pri_im),
    ]
    with open(f"{stamp}_Priority.html", "w", encoding="utf-8") as f:
        f.write(html_page("Priority", date_long, "", priority_sections))

    main_sections: List[Tuple[str, List[Dict[str, object]]]] = [("Astrophysics (other categories)", main_rest)]
    with open(f"{stamp}_Main.html", "w", encoding="utf-8") as f:
        f.write(html_page("Main", date_long, "", main_sections))

    with open(f"{stamp}_Interest.html", "w", encoding="utf-8") as f:
        f.write(html_page("Interest", date_long, "", interest_groups))

if __name__ == "__main__":
    main()
