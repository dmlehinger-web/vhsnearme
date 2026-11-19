#!/usr/bin/env python3
"""Generate the static VHS Near Me site from data/*.json.

Run from the repository root:

    python3 scripts/build.py

The script rewrites HTML, sitemap.xml, robots.txt, and og.png.
Edit the data files and templates, then rebuild. Do not hand-edit
the generated HTML; the next build overwrites it.
"""

from __future__ import annotations

import html
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TEMPLATE = (ROOT / "templates" / "page.html").read_text(encoding="utf-8")

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+|/[^\s)]+)\)")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# 5x7 glyphs. Each row is five bits, left to right.
FONT = {
    " ": ["00000"] * 7,
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
}


def die(message: str) -> None:
    print(f"build error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{path.relative_to(ROOT)} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        die(f"{path.relative_to(ROOT)} must be a JSON object")
    return data


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def human_date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{MONTHS[int(month) - 1]} {int(day)}, {year}"


def require(obj: dict, keys: list[str], label: str) -> None:
    missing = [key for key in keys if key not in obj or obj[key] in ("", None, [], {})]
    if missing:
        die(f"{label} is missing {', '.join(missing)}")


def strings(value, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        die(f"{label} must be a non-empty list of strings")
    return value


def walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)


SITE = load_json(DATA / "site.json")
require(SITE, ["name", "base_path", "origin", "checked"], "data/site.json")
if not DATE_RE.match(SITE["checked"]):
    die("data/site.json checked must be YYYY-MM-DD")
BASE = SITE["base_path"].rstrip("/")
ORIGIN = SITE["origin"].rstrip("/")
if not BASE.startswith("/"):
    die("base_path must start with /")


def apply_base(value):
    if isinstance(value, str):
        return value.replace("{{base}}", BASE)
    if isinstance(value, dict):
        return {key: apply_base(item) for key, item in value.items()}
    if isinstance(value, list):
        return [apply_base(item) for item in value]
    return value


def href(*parts: str) -> str:
    cleaned = [part.strip("/") for part in parts if part and part.strip("/")]
    if not cleaned:
        return BASE + "/"
    return BASE + "/" + "/".join(cleaned) + "/"


def href_file(path: str) -> str:
    return BASE + "/" + path.lstrip("/")


def absolute(path: str) -> str:
    return ORIGIN + path


def inline(text: str) -> str:
    pieces = []
    last = 0
    for match in LINK_RE.finditer(text):
        pieces.append(esc(text[last:match.start()]))
        url = match.group(2)
        if url.startswith("/"):
            if url != BASE + "/" and not url.startswith(BASE + "/"):
                die(f"internal link is outside {BASE}: {url}")
        elif not url.startswith(("https://", "http://")):
            die(f"unsupported link: {url}")
        pieces.append(f'<a href="{esc(url)}">{esc(match.group(1))}</a>')
        last = match.end()
    pieces.append(esc(text[last:]))
    return "".join(pieces)


def paragraphs(items: list[str]) -> str:
    return "\n".join(f"<p>{inline(item)}</p>" for item in items)


def bullets(items: list[str]) -> str:
    lis = "\n".join(f"<li>{inline(item)}</li>" for item in items)
    return f"<ul class=\"clean\">\n{lis}\n</ul>"


AFFILIATES = apply_base(load_json(DATA / "affiliates.json"))
require(AFFILIATES, ["partners"], "data/affiliates.json")
PARTNERS = AFFILIATES["partners"]
if not isinstance(PARTNERS, dict):
    die("data/affiliates.json partners must be an object")
for key, partner in PARTNERS.items():
    require(partner, ["name", "url"], f"affiliate {key}")
    aid = str(partner.get("affiliate_id", "")).strip()
    param = str(partner.get("affiliate_param", "")).strip()
    if bool(aid) != bool(param):
        die(f"affiliate {key}: set affiliate_id and affiliate_param together, or leave both empty")
    if aid and not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", aid):
        die(f"affiliate {key}: affiliate_id must be a short public code, not a secret blob")
    if param and not re.fullmatch(r"[A-Za-z0-9_]{1,32}", param):
        die(f"affiliate {key}: affiliate_param must be a query-parameter name")
    partner["affiliate_id"] = aid
    partner["affiliate_param"] = param


def visit_url(service: dict) -> tuple[str, bool]:
    url = service["url"]
    key = service.get("affiliate_key")
    if not key:
        return url, False
    if key not in PARTNERS:
        die(f"service {service['id']} points at unknown affiliate {key}")
    partner = PARTNERS[key]
    if partner["affiliate_id"] and partner["affiliate_param"]:
        sep = "&" if "?" in url else "?"
        stamped = (
            f"{url}{sep}{quote(partner['affiliate_param'])}="
            f"{quote(partner['affiliate_id'])}"
        )
        return stamped, True
    return url, False


SNIPPETS = apply_base(load_json(DATA / "snippets.json"))
HOME = apply_base(load_json(DATA / "home.json"))
ABOUT = apply_base(load_json(DATA / "about.json"))
SERVICES_DOC = apply_base(load_json(DATA / "services.json"))


def load_cities() -> list[dict]:
    cities = []
    for path in sorted((DATA / "cities").glob("*.json")):
        if path.name.startswith("_"):
            continue
        city = apply_base(load_json(path))
        label = f"data/cities/{path.name}"
        require(
            city,
            ["slug", "name", "state", "state_name", "areas", "meta_title",
             "meta_description", "intro", "checked", "businesses"],
            label,
        )
        if path.stem != city["slug"]:
            die(f"{label}: filename must match slug ({city['slug']})")
        if not SLUG_RE.match(city["slug"]):
            die(f"{label}: slug must be lowercase words separated by hyphens")
        if not DATE_RE.match(city["checked"]):
            die(f"{label}: checked must be YYYY-MM-DD")
        strings(city["intro"], f"{label} intro")
        strings(city["areas"], f"{label} areas")
        for blob in walk_strings(city):
            if any(token in blob for token in ("example.com", "REPLACE", "YYYY-MM-DD", "123 Main St", "(000) 000-0000")):
                die(f"{label} still contains template placeholder text")
        ids = set()
        for biz in city["businesses"]:
            blabel = f"{label} business"
            require(
                biz,
                ["id", "name", "area", "website", "source_url", "source_label",
                 "formats", "service_mode", "price_summary", "turnaround", "notes"],
                blabel,
            )
            if biz["id"] in ids:
                die(f"{label}: duplicate business id {biz['id']}")
            ids.add(biz["id"])
            if not SLUG_RE.match(biz["id"]):
                die(f"{blabel} {biz['name']}: id must be a slug")
            for field in ("website", "source_url"):
                if not str(biz[field]).startswith(("https://", "http://")):
                    die(f"{biz['name']}: {field} must be an http(s) URL")
            strings(biz["formats"], f"{biz['name']} formats")
            strings(biz["notes"], f"{biz['name']} notes")
            if biz.get("phone"):
                if not PHONE_RE.match(biz.get("phone_e164", "")):
                    die(f"{biz['name']}: phone_e164 must be + and digits when phone is set")
            address = biz.get("address")
            if address:
                require(address, ["street", "locality", "region", "postal_code"], f"{biz['name']} address")
            for extra in biz.get("extra_sources", []):
                require(extra, ["label", "url"], f"{biz['name']} extra source")
            for line in biz.get("price_lines", []):
                require(line, ["label", "value"], f"{biz['name']} price line")
        cities.append(city)
    if not cities:
        die("no city files in data/cities")
    return cities


def load_formats() -> list[dict]:
    formats = []
    for path in sorted((DATA / "formats").glob("*.json")):
        guide = apply_base(load_json(path))
        label = f"data/formats/{path.name}"
        require(
            guide,
            ["slug", "order", "nav_label", "title", "meta_title", "meta_description",
             "kicker", "lede", "sections"],
            label,
        )
        if path.stem != guide["slug"]:
            die(f"{label}: filename must match slug")
        if not SLUG_RE.match(guide["slug"]):
            die(f"{label}: bad slug")
        formats.append(guide)
    if not formats:
        die("no format guides")
    return sorted(formats, key=lambda item: item["order"])


CITIES = load_cities()
FORMATS = load_formats()
SERVICES = sorted(SERVICES_DOC["services"], key=lambda item: item["order"])
for service in SERVICES:
    require(
        service,
        ["id", "name", "order", "url", "where", "formats", "table_price",
         "table_turnaround", "table_delivery", "summary", "details", "sources"],
        f"service {service.get('id', '?')}",
    )
    strings(service["details"], f"{service['name']} details")
    strings(service["formats"], f"{service['name']} formats")
    visit_url(service)


def jsonld(graph: list[dict]) -> str:
    payload = {"@context": "https://schema.org", "@graph": graph}
    raw = json.dumps(payload, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    return f'<script type="application/ld+json">\n{raw}\n</script>'


def crumbs(items: list[tuple[str, str]]) -> tuple[str, dict]:
    html_bits = []
    elements = []
    for index, (name, path) in enumerate(items, start=1):
        url = absolute(href(path) if path != "HOME" else href())
        if path == "HOME":
            url = absolute(href())
        elements.append({
            "@type": "ListItem",
            "position": index,
            "name": name,
            "item": url,
        })
        if index == len(items):
            html_bits.append(f"<li>{esc(name)}</li>")
        else:
            target = href() if path == "HOME" else href(path)
            html_bits.append(f'<li><a href="{esc(target)}">{esc(name)}</a></li>')
    markup = '<nav aria-label="Breadcrumb"><ol class="crumbs">' + "".join(html_bits) + "</ol></nav>"
    data = {"@type": "BreadcrumbList", "itemListElement": elements}
    return markup, data


def nav(section: str) -> str:
    items = [
        ("Home", href(), "home"),
        ("Cities", href("cities"), "cities"),
        ("Mail-in", href("mail-in"), "mail"),
        ("Formats", href("formats"), "formats"),
        ("About", href("about"), "about"),
    ]
    parts = []
    for label, url, key in items:
        current = ' aria-current="page"' if key == section else ""
        parts.append(f'<a href="{esc(url)}"{current}>{esc(label)}</a>')
    return "\n".join(parts)


def render(title: str, description: str, path: str, body: str, section: str,
           graph: list[dict], robots: str = "") -> str:
    if path == "404":
        canonical = absolute(href_file("404.html"))
    else:
        canonical = absolute(href() if path == "" else href(path))
    robot_tag = f'<meta name="robots" content="{esc(robots)}">' if robots else ""
    script = jsonld(graph)
    page = TEMPLATE
    replacements = {
        "@@TITLE@@": esc(title),
        "@@DESCRIPTION@@": esc(description),
        "@@CANONICAL@@": esc(canonical),
        "@@SITE_NAME@@": esc(SITE["name"]),
        "@@OG_IMAGE@@": esc(absolute(href_file("og.png"))),
        "@@FAVICON@@": esc(href_file("favicon.svg")),
        "@@CSS@@": esc(href_file("css/styles.css")),
        "@@ROBOTS@@": robot_tag,
        "@@JSONLD@@": script,
        "@@HOME@@": esc(href()),
        "@@CITIES@@": esc(href("cities")),
        "@@MAIL@@": esc(href("mail-in")),
        "@@FORMATS@@": esc(href("formats")),
        "@@ABOUT@@": esc(href("about")),
        "@@NAV@@": nav(section),
        "@@BODY@@": body,
    }
    for token, value in replacements.items():
        if token not in page:
            die(f"template is missing {token}")
        page = page.replace(token, value)
    if "@@" in page:
        die("unreplaced template token in output")
    comment = "<!-- Generated by scripts/build.py from data files. Do not edit by hand. -->\n"
    return comment + page


def write_page(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def website_node() -> dict:
    return {
        "@type": "WebSite",
        "name": SITE["name"],
        "url": absolute(href()),
        "description": HOME["meta_description"],
        "inLanguage": SITE.get("locale", "en"),
    }


def render_home() -> str:
    city_cards = []
    for city in CITIES:
        areas = ", ".join(city["areas"])
        city_cards.append(
            f'<a class="card" href="{esc(href("cities", city["slug"]))}">'
            f'<p class="step-no">{esc(city["state_name"])}</p>'
            f'<h3>{esc(city["name"])}</h3>'
            f'<p>{esc(areas)}</p>'
            f'<p>{len(city["businesses"])} listed businesses · checked {esc(human_date(city["checked"]))}</p>'
            f'<span class="more">Open the city page</span></a>'
        )
    format_cards = []
    for guide in FORMATS:
        format_cards.append(
            f'<a class="card" href="{esc(href("formats", guide["slug"]))}">'
            f'<p class="step-no">Format</p>'
            f'<h3>{esc(guide["title"])}</h3>'
            f'<p>{esc(guide["lede"])}</p>'
            f'<span class="more">Read the guide</span></a>'
        )
    mail_rows = []
    for service in SERVICES:
        mail_rows.append(
            "<tr>"
            f'<th scope="row"><a href="{esc(href("mail-in"))}#{esc(service["id"])}">{esc(service["name"])}</a></th>'
            f"<td>{esc(service['table_price'])}</td>"
            f"<td>{esc(service['table_turnaround'])}</td>"
            "</tr>"
        )
    steps = []
    for step in HOME["choose"]:
        steps.append(
            f"<li><strong>{esc(step['title'])}.</strong> {esc(step['text'])}</li>"
        )
    body = f"""
<div class="wrap">
  <header class="page-head">
    <p class="kicker">{esc(HOME["kicker"])}</p>
    <h1>{esc(HOME["title"])}</h1>
    <p class="lede">{esc(HOME["lede"])}</p>
  </header>
  <section>
    <h2>{esc(HOME["what_heading"])}</h2>
    <div class="section-intro">{paragraphs(HOME["what"])}</div>
  </section>
  <section>
    <h2>{esc(HOME["choose_heading"])}</h2>
    <ol class="choose">{''.join(steps)}</ol>
  </section>
  <section>
    <h2>{esc(HOME["formats_heading"])}</h2>
    <p class="section-intro">{esc(HOME["formats_intro"])}</p>
    <div class="grid cards">{''.join(format_cards)}</div>
  </section>
  <section>
    <h2>{esc(HOME["cities_heading"])}</h2>
    <p class="section-intro">{esc(HOME["cities_intro"])}</p>
    <div class="grid cards">{''.join(city_cards)}</div>
  </section>
  <section>
    <h2>{esc(HOME["mail_heading"])}</h2>
    <p class="section-intro">{esc(HOME["mail_intro"])}</p>
    <div class="table-scroll" tabindex="0">
      <table>
        <caption>Mail-in prices, short version</caption>
        <thead><tr><th scope="col">Company</th><th scope="col">Published price</th><th scope="col">Turnaround they state</th></tr></thead>
        <tbody>{''.join(mail_rows)}</tbody>
      </table>
    </div>
    <p><a href="{esc(href("mail-in"))}">Open the full mail-in comparison</a></p>
  </section>
</div>
"""
    city_list = {
        "@type": "ItemList",
        "name": "Cities with local digitizing listings",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": f"{city['name']}, {city['state']}",
                "url": absolute(href("cities", city["slug"])),
            }
            for index, city in enumerate(CITIES, start=1)
        ],
    }
    return render(
        HOME["meta_title"], HOME["meta_description"], "", body, "home",
        [website_node(), city_list],
    )


def render_about() -> str:
    sections = []
    for section in ABOUT["sections"]:
        sections.append(f"<section><h2>{esc(section['heading'])}</h2>{paragraphs(section['paragraphs'])}</section>")
    crumb, crumb_data = crumbs([("Home", "HOME"), ("About", "about")])
    body = f"""
<div class="wrap">
  {crumb}
  <header class="page-head">
    <p class="kicker">About</p>
    <h1>{esc(ABOUT["title"])}</h1>
    <p class="lede">{esc(ABOUT["lede"])}</p>
  </header>
  {''.join(sections)}
</div>
"""
    return render(
        ABOUT["meta_title"], ABOUT["meta_description"], "about", body, "about",
        [{"@type": "AboutPage", "name": ABOUT["title"], "url": absolute(href("about"))}, crumb_data],
    )


def render_formats_index() -> str:
    cards = []
    for guide in FORMATS:
        cards.append(
            f'<a class="card" href="{esc(href("formats", guide["slug"]))}">'
            f'<h2>{esc(guide["title"])}</h2><p>{esc(guide["lede"])}</p>'
            f'<span class="more">Read the guide</span></a>'
        )
    crumb, crumb_data = crumbs([("Home", "HOME"), ("Formats", "formats")])
    body = f"""
<div class="wrap">
  {crumb}
  <header class="page-head">
    <p class="kicker">Formats</p>
    <h1>What you are actually holding</h1>
    <p class="lede">A cassette, a reel, and a shoebox of prints are different jobs. These notes are here so a price on a city page or a mail-in page means something before you pay.</p>
  </header>
  <div class="grid cards">{''.join(cards)}</div>
</div>
"""
    return render(
        "Formats: VHS, photos, slides, film, and camcorder tapes",
        "Short guides to VHS, photos and slides, movie film, and camcorder tapes before you hire a transfer shop.",
        "formats", body, "formats",
        [{"@type": "CollectionPage", "name": "Format guides", "url": absolute(href("formats"))}, crumb_data],
    )


def render_format(guide: dict) -> str:
    blocks = []
    for section in guide["sections"]:
        parts = [f"<h2>{esc(section['heading'])}</h2>"]
        if section.get("paragraphs"):
            parts.append(paragraphs(section["paragraphs"]))
        if section.get("bullets"):
            parts.append(bullets(section["bullets"]))
        blocks.append(f'<section class="format-block">{"".join(parts)}</section>')
    crumb, crumb_data = crumbs([
        ("Home", "HOME"),
        ("Formats", "formats"),
        (guide["nav_label"], f"formats/{guide['slug']}"),
    ])
    body = f"""
<div class="wrap">
  {crumb}
  <header class="page-head">
    <p class="kicker">{esc(guide["kicker"])}</p>
    <h1>{esc(guide["title"])}</h1>
    <p class="lede">{esc(guide["lede"])}</p>
  </header>
  {''.join(blocks)}
</div>
"""
    return render(
        guide["meta_title"], guide["meta_description"], f"formats/{guide['slug']}",
        body, "formats",
        [{"@type": "Article", "headline": guide["title"],
          "url": absolute(href("formats", guide["slug"])),
          "dateModified": SITE["checked"]}, crumb_data],
    )


def source_links(pairs: list[tuple[str, str]]) -> str:
    seen = set()
    items = []
    for label, url in pairs:
        if url in seen:
            continue
        seen.add(url)
        items.append(f'<li><a href="{esc(url)}">{esc(label)}</a></li>')
    return f'<ul class="sources">{"".join(items)}</ul>'


def render_city(city: dict) -> str:
    rows = []
    cards = []
    schema_items = []
    for index, biz in enumerate(city["businesses"], start=1):
        rows.append(
            "<tr>"
            f'<th scope="row"><a href="#{esc(biz["id"])}">{esc(biz["name"])}</a></th>'
            f'<td>{esc(biz["area"])}</td>'
            f'<td>{esc(biz["price_summary"])}</td>'
            f'<td>{esc(biz["turnaround"])}</td>'
            "</tr>"
        )
        facts = [
            ("How", biz["service_mode"]),
            ("Price", biz["price_summary"]),
            ("Turnaround", biz["turnaround"]),
        ]
        if biz.get("delivery"):
            facts.append(("You get", biz["delivery"]))
        if biz.get("hours"):
            facts.append(("Hours", biz["hours"]))
        if biz.get("phone"):
            phone = f'<a href="tel:{esc(biz["phone_e164"])}">{esc(biz["phone"])}</a>'
            facts.append(("Phone", phone))
        address = biz.get("address")
        if address:
            line = f'{address["street"]}, {address["locality"]}, {address["region"]} {address["postal_code"]}'
            facts.append(("Address", esc(line)))
        fact_bits = []
        for label, value in facts:
            if label == "Phone":
                shown = value
            elif label == "Address":
                shown = value
            else:
                shown = esc(value)
            fact_bits.append(f"<dt>{esc(label)}</dt><dd>{shown}</dd>")
        rates = ""
        if biz.get("price_lines"):
            lis = "".join(
                f'<li><strong>{esc(line["value"])}</strong><span>{esc(line["label"])}</span></li>'
                for line in biz["price_lines"]
            )
            rates = f'<ul class="rates">{lis}</ul>'
        chips = "".join(f"<li>{esc(fmt)}</li>" for fmt in biz["formats"])
        pairs = [(biz["source_label"], biz["source_url"])]
        if biz["website"] != biz["source_url"]:
            pairs.insert(0, ("Website", biz["website"]))
        for extra in biz.get("extra_sources", []):
            pairs.append((extra["label"], extra["url"]))
        cards.append(
            f'<article class="biz" id="{esc(biz["id"])}">'
            f'<div class="biz-top"><h2>{esc(biz["name"])}</h2>'
            f'<p class="area">{esc(biz["area"])}</p></div>'
            f'<dl class="facts">{"".join(fact_bits)}</dl>'
            f'{rates}'
            f'<h3>Formats they name</h3><ul class="chips">{chips}</ul>'
            f'{paragraphs(biz["notes"])}'
            f'<h3>Sources</h3>{source_links(pairs)}'
            f'</article>'
        )
        item = {
            "@type": "LocalBusiness",
            "name": biz["name"],
            "url": biz["website"],
            "areaServed": f"{city['name']}, {city['state']}",
        }
        if biz.get("phone_e164"):
            item["telephone"] = biz["phone_e164"]
        if address:
            item["address"] = {
                "@type": "PostalAddress",
                "streetAddress": address["street"],
                "addressLocality": address["locality"],
                "addressRegion": address["region"],
                "postalCode": address["postal_code"],
                "addressCountry": "US",
            }
        schema_items.append({"@type": "ListItem", "position": index, "item": item})

    checklist = "".join(f"<li>{esc(item)}</li>" for item in SNIPPETS["city_checklist"])
    crumb, crumb_data = crumbs([
        ("Home", "HOME"),
        ("Cities", "cities"),
        (city["name"], f"cities/{city['slug']}"),
    ])
    body = f"""
<div class="wrap">
  {crumb}
  <header class="page-head">
    <p class="kicker">{esc(city["state_name"])} · local directory</p>
    <h1>{esc(city["name"])} tape, film, and photo transfer</h1>
    <p class="lede">{inline(city["intro"][0])}</p>
    <p class="checked">Facts checked {esc(human_date(city["checked"]))} against each business’s own website.</p>
  </header>
  <div class="section-intro">{paragraphs(city["intro"][1:])}</div>
  <section class="callout">
    <h2>How a business gets on this page</h2>
    {paragraphs(SNIPPETS["city_policy"])}
  </section>
  <section>
    <h2>At a glance</h2>
    <p class="meta-note table-hint">Swipe sideways to see every column.</p>
    <div class="table-scroll" tabindex="0">
      <table>
        <caption>{esc(city["name"])} prices and turnaround. “Call for pricing” means the site did not print a number.</caption>
        <thead>
          <tr><th scope="col">Business</th><th scope="col">Area</th><th scope="col">Price</th><th scope="col">Turnaround</th></tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
  </section>
  <section>
    <h2>Before you go</h2>
    <ul class="clean">{checklist}</ul>
  </section>
  <section>
    <h2>The businesses</h2>
    <div class="grid">{''.join(cards)}</div>
  </section>
  <section class="callout">
    <h2>Mailing instead of driving</h2>
    <p>National labs with a published price are on the <a href="{esc(href("mail-in"))}">mail-in comparison</a>. Read the unit of the price, and keep the originals’ labels written down before a box leaves the house.</p>
  </section>
</div>
"""
    graph = [
        {
            "@type": "ItemList",
            "name": f"Digitizing services in {city['name']}, {city['state']}",
            "url": absolute(href("cities", city["slug"])),
            "itemListElement": schema_items,
        },
        crumb_data,
    ]
    return render(city["meta_title"], city["meta_description"], f"cities/{city['slug']}", body, "cities", graph)


def render_cities_index() -> str:
    cards = []
    for city in sorted(CITIES, key=lambda item: (item["state"], item["name"])):
        cards.append(
            f'<a class="card" href="{esc(href("cities", city["slug"]))}">'
            f'<p class="step-no">{esc(city["state"])}</p>'
            f'<h2>{esc(city["name"])}</h2>'
            f'<p>{esc(", ".join(city["areas"]))}</p>'
            f'<p>{len(city["businesses"])} businesses · checked {esc(human_date(city["checked"]))}</p>'
            f'<span class="more">Open the city page</span></a>'
        )
    crumb, crumb_data = crumbs([("Home", "HOME"), ("Cities", "cities")])
    body = f"""
<div class="wrap">
  {crumb}
  <header class="page-head">
    <p class="kicker">Cities</p>
    <h1>Local transfer shops</h1>
    <p class="lede">Each city is a file in data/cities. Adding a file and running the build adds a page here, a card on the homepage, and a line in the sitemap.</p>
  </header>
  <div class="grid cards">{''.join(cards)}</div>
</div>
"""
    listing = {
        "@type": "ItemList",
        "name": "Cities",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": f"{city['name']}, {city['state']}",
                "url": absolute(href("cities", city["slug"])),
            }
            for index, city in enumerate(sorted(CITIES, key=lambda item: (item["state"], item["name"])), start=1)
        ],
    }
    return render(
        "Cities with local tape and photo transfer",
        "City-by-city directory of local shops that digitize VHS, film, photos, slides, and negatives.",
        "cities", body, "cities", [listing, crumb_data],
    )


def render_mail() -> str:
    rows = []
    blocks = []
    schema_items = []
    for index, service in enumerate(SERVICES, start=1):
        url, sponsored = visit_url(service)
        rel = ' rel="sponsored noopener"' if sponsored else ' rel="noopener"'
        if service.get("affiliate_key") and sponsored:
            link_note = '<span class="meta-note">(Affiliate link)</span>'
        elif service.get("affiliate_key"):
            link_note = '<span class="meta-note">(Plain link, no affiliate code yet)</span>'
        else:
            link_note = ""
        rows.append(
            "<tr>"
            f'<th scope="row"><a href="#{esc(service["id"])}">{esc(service["name"])}</a></th>'
            f'<td>{esc(", ".join(service["formats"][:6]))}{"…" if len(service["formats"]) > 6 else ""}</td>'
            f'<td>{esc(service["table_price"])}</td>'
            f'<td>{esc(service["table_turnaround"])}</td>'
            f'<td>{esc(service["table_delivery"])}</td>'
            f'<td>{esc(service["where"])}</td>'
            "</tr>"
        )
        chips = "".join(f"<li>{esc(fmt)}</li>" for fmt in service["formats"])
        pairs = [(source["label"], source["url"]) for source in service["sources"]]
        blocks.append(
            f'<article class="biz" id="{esc(service["id"])}">'
            f'<div class="biz-top"><h2>{esc(service["name"])}</h2>'
            f'<p class="area">{esc(service["where"])}</p></div>'
            f'<p>{esc(service["summary"])}</p>'
            f'<ul class="chips">{chips}</ul>'
            f'{paragraphs(service["details"])}'
            f'<p><a href="{esc(url)}"{rel}>Visit {esc(service["name"])}</a> {link_note}</p>'
            f'<h3>Sources checked {esc(human_date(SITE["checked"]))}</h3>'
            f'{source_links(pairs)}'
            f'</article>'
        )
        schema_items.append({
            "@type": "ListItem",
            "position": index,
            "item": {
                "@type": "Service",
                "name": f"{service['name']} digitizing",
                "serviceType": "Mail-in media digitizing",
                "url": service["url"],
                "provider": {"@type": "Organization", "name": service["name"], "url": service["url"]},
                "areaServed": "US",
            },
        })
    examples = []
    for example in SERVICES_DOC["examples"]:
        examples.append(
            f'<section class="example"><h3>{esc(example["heading"])}</h3>{paragraphs(example["paragraphs"])}</section>'
        )
    crumb, crumb_data = crumbs([("Home", "HOME"), ("Mail-in", "mail-in")])
    body = f"""
<div class="wrap">
  {crumb}
  <header class="page-head">
    <p class="kicker">Mail-in · checked {esc(human_date(SITE["checked"]))}</p>
    <h1>{esc(SERVICES_DOC["title"])}</h1>
    <p class="lede">{esc(SERVICES_DOC["lede"])}</p>
  </header>
  <div class="section-intro">{paragraphs(SERVICES_DOC["intro"])}</div>
  <p class="meta-note table-hint">Swipe sideways to see every column.</p>
  <div class="table-scroll" tabindex="0">
    <table>
      <caption>Mail-in comparison. Open a company below for the unit, the add-ons, and the source.</caption>
      <thead>
        <tr>
          <th scope="col">Company</th>
          <th scope="col">Formats they list</th>
          <th scope="col">Published price</th>
          <th scope="col">Turnaround they state</th>
          <th scope="col">Delivery</th>
          <th scope="col">Where the work happens</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
  <section>
    <h2>The same job, priced their way</h2>
    {''.join(examples)}
  </section>
  <section>
    <h2>Each company</h2>
    <div class="grid">{''.join(blocks)}</div>
  </section>
  <section class="callout">
    <p>Links for ScanMyPhotos, Legacybox, and iMemories are wired through <span class="path">data/affiliates.json</span>. The IDs are empty, so those buttons are ordinary links. The <a href="{esc(href("about"))}">affiliate disclosure</a> explains what changes when an ID is filled in. Local shops are on the <a href="{esc(href("cities"))}">city pages</a>.</p>
  </section>
</div>
"""
    graph = [{
        "@type": "ItemList",
        "name": "Mail-in digitizing services",
        "url": absolute(href("mail-in")),
        "itemListElement": schema_items,
    }, crumb_data]
    return render(
        SERVICES_DOC["meta_title"], SERVICES_DOC["meta_description"], "mail-in",
        body, "mail", graph,
    )


def render_404() -> str:
    body = f"""
<div class="wrap">
  <header class="page-head">
    <p class="kicker">404</p>
    <h1>That page is not in the directory.</h1>
    <p class="lede">The address does not match a city, a format guide, or the mail-in comparison.</p>
  </header>
  <p><a href="{esc(href())}">Back to the homepage</a> · <a href="{esc(href("cities"))}">Cities</a> · <a href="{esc(href("mail-in"))}">Mail-in</a></p>
</div>
"""
    return render(
        "Page not found",
        "That VHS Near Me address does not match a page.",
        "404", body, "home",
        [{"@type": "WebPage", "name": "Not found", "url": absolute(href_file("404.html"))}],
        robots="noindex",
    )


def write_sitemap(pages: list[tuple[str, str]]) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, lastmod in pages:
        loc = absolute(href() if path == "" else href(path))
        lines.append("  <url>")
        lines.append(f"    <loc>{esc(loc)}</loc>")
        lines.append(f"    <lastmod>{esc(lastmod)}</lastmod>")
        lines.append("  </url>")
    lines.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_robots() -> None:
    text = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {absolute(href_file('sitemap.xml'))}\n"
    )
    (ROOT / "robots.txt").write_text(text, encoding="utf-8")


def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def text_width(label: str, scale: int, gap: int) -> int:
    return len(label) * (5 * scale + gap) - gap


def glyph_hit(label: str, scale: int, gap: int, origin_x: int, origin_y: int, x: int, y: int) -> bool:
    if not (origin_y <= y < origin_y + 7 * scale):
        return False
    local_x = x - origin_x
    width = text_width(label, scale, gap)
    if local_x < 0 or local_x >= width:
        return False
    cursor = 0
    advance = 5 * scale + gap
    for char in label:
        if cursor <= local_x < cursor + 5 * scale:
            col = (local_x - cursor) // scale
            row = (y - origin_y) // scale
            return FONT[char][row][col] == "1"
        cursor += advance
    return False


def write_og() -> None:
    width, height = 1200, 630
    paper = (244, 234, 215)
    ink = (36, 28, 22)
    oxide = (143, 61, 43)
    gold = (196, 161, 90)
    title = "VHS NEAR ME"
    subtitle = "TAPES  FILM  PHOTOS"
    title_scale, title_gap = 11, 10
    sub_scale, sub_gap = 5, 6
    title_w = text_width(title, title_scale, title_gap)
    sub_w = text_width(subtitle, sub_scale, sub_gap)
    title_x = (width - title_w) // 2
    sub_x = (width - sub_w) // 2
    title_y = 230
    sub_y = 360
    rule_y = 430
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)
        for x in range(width):
            if y < 28:
                color = ink
            elif 28 <= y < 46:
                color = (oxide, gold, paper, ink)[(x // 28) % 4]
            elif glyph_hit(title, title_scale, title_gap, title_x, title_y, x, y):
                color = ink
            elif glyph_hit(subtitle, sub_scale, sub_gap, sub_x, sub_y, x, y):
                color = oxide
            elif rule_y <= y < rule_y + 10 and (width - 280) // 2 <= x < (width + 280) // 2:
                color = oxide
            else:
                color = paper
            pixels.extend(color)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
    png += chunk(b"IEND", b"")
    (ROOT / "og.png").write_bytes(png)


def output_path(url_path: str) -> Path:
    if url_path == href():
        return ROOT / "index.html"
    relative = url_path[len(BASE):].strip("/")
    if relative.endswith(".xml") or relative.endswith(".txt") or relative.endswith(".png") or relative.endswith(".svg") or relative.endswith(".css"):
        return ROOT / relative
    return ROOT / relative / "index.html"


def check_output(pages: list[str]) -> None:
    hrefs = re.compile(r'href="([^"]+)"')
    problems = []
    for relative in pages:
        text = (ROOT / relative).read_text(encoding="utf-8")
        if text.count("<h1") != 1:
            problems.append(f"{relative} should have one h1")
        if 'rel="canonical"' not in text and "canonical" not in text:
            problems.append(f"{relative} missing canonical")
        if "<title>" not in text or 'name="description"' not in text:
            problems.append(f"{relative} missing title or description")
        if "googletagmanager" in text or "google-analytics" in text or "fonts.googleapis" in text:
            problems.append(f"{relative} includes an external tracker or font")
        for match in re.finditer(r'<script(?![^>]*type="application/ld\+json")', text):
            problems.append(f"{relative} has a non-JSON-LD script")
            break
        for raw in hrefs.findall(text):
            if raw.startswith(BASE):
                target = output_path(raw.split("#", 1)[0])
                if not target.exists():
                    problems.append(f"{relative} links to missing {raw}")
            elif raw.startswith("/"):
                problems.append(f"{relative} has a root link outside {BASE}: {raw}")
        for blob in re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S):
            json.loads(blob)
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    if "Sitemap:" not in robots or BASE not in robots:
        problems.append("robots.txt is missing the sitemap URL")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    if "404" in sitemap:
        problems.append("sitemap includes the 404 page")
    for city in CITIES:
        loc = absolute(href("cities", city["slug"]))
        if loc not in sitemap:
            problems.append(f"sitemap missing {loc}")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    if ".env" not in gitignore:
        problems.append(".gitignore does not ignore .env")
    if not (ROOT / ".nojekyll").exists():
        problems.append(".nojekyll is missing")
    joined = "\n".join((ROOT / rel).read_text(encoding="utf-8") for rel in pages)
    if "affiliate_id=" in joined or "?aff=" in joined:
        problems.append("an affiliate query was written even though IDs are empty")
    if problems:
        die("\n".join(problems))


def main() -> None:
    pages: list[tuple[str, str, str]] = []

    def add(path: str, content: str, lastmod: str, file_relative: str) -> None:
        write_page(file_relative, content)
        pages.append((path, lastmod, file_relative))

    add("", render_home(), SITE["checked"], "index.html")
    add("about", render_about(), SITE["checked"], "about/index.html")
    add("mail-in", render_mail(), SITE["checked"], "mail-in/index.html")
    add("formats", render_formats_index(), SITE["checked"], "formats/index.html")
    for guide in FORMATS:
        add(f"formats/{guide['slug']}", render_format(guide), SITE["checked"],
            f"formats/{guide['slug']}/index.html")
    add("cities", render_cities_index(), max(city["checked"] for city in CITIES), "cities/index.html")
    for city in CITIES:
        add(f"cities/{city['slug']}", render_city(city), city["checked"],
            f"cities/{city['slug']}/index.html")
    write_page("404.html", render_404())
    write_sitemap([(path, lastmod) for path, lastmod, _file in pages])
    write_robots()
    write_og()
    check_output([file_rel for _path, _last, file_rel in pages] + ["404.html"])
    print(f"Built {len(pages)} pages, sitemap.xml, robots.txt, and og.png")


if __name__ == "__main__":
    main()
