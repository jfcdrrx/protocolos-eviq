#!/usr/bin/env python3
"""Daily refresh of protocols.json from eviQ's public sitemap.

Reads https://www.eviq.org.au/sitemap.xml, keeps the Radiation oncology
protocol pages, fetches the title of any page that is new or changed, and
marks a protocol as retired when eviQ labels it DISCONTINUED / SUPERSEDED
or when it disappears from the sitemap. Only titles and links are stored;
no eviQ content is copied.
"""
import datetime, html, json, re, sys, time, urllib.request
from pathlib import Path

BASE = "https://www.eviq.org.au"
_HERE = Path(__file__).resolve().parent
OUT = (_HERE.parent if _HERE.name == "scripts" else _HERE) / "protocols.json"
UA = "Mozilla/5.0 (compatible; protocolos-eviq-index/1.0; +https://jfcdrrx.github.io/protocolos-eviq/)"

CATS = {
    "breast": "breast", "head-and-neck": "hn", "neurological": "neuro",
    "respiratory": "resp", "upper-gastrointestinal": "ugi", "colorectal": "cr",
    "gynaecological": "gyn", "urogenital/prostate": "prost",
    "urogenital/bladder": "blad", "urogenital/kidney-and-adrenal": "kid",
    "haematology": "haem", "skin": "skin", "palliative": "pall",
    "stereotactic": "stereo",
}
RETIRED = re.compile(r"discontinued|superseded", re.I)
PROTO = re.compile(r"^https://www\.eviq\.org\.au/radiation-oncology/(.+?)/(\d+)-([a-z0-9-]+)/?$", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def page_title(url):
    m = re.search(r"<title>(.*?)</title>", get(url), re.S | re.I)
    if not m:
        return None
    t = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    t = re.sub(r"\s*\|\s*eviQ\s*$", "", t)
    t = re.sub(r"^\d+\s*-\s*", "", t)          # leading "3650-"
    return t.strip(" -") or None


def parse_sitemap(xml):
    found = {}
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block)
        if not loc:
            continue
        m = PROTO.match(loc.group(1))
        if not m:
            continue
        path, pid, slug = m.group(1).lower(), m.group(2), m.group(3).lower()
        if "redirect" in slug or path.endswith("patient-information"):
            continue
        cat = CATS.get(path)
        if not cat:
            continue
        lm = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block)
        lastmod = lm.group(1) if lm else ""
        prev = found.get(pid)
        if prev is None or lastmod > prev["lastmod"]:   # same ID under several slugs: keep newest
            found[pid] = {"id": pid, "cat": cat, "url": loc.group(1), "slug": slug, "lastmod": lastmod}
    return found


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"protocols": []}
    known = {p["id"]: p for p in old.get("protocols", [])}

    try:
        found = parse_sitemap(get(BASE + "/sitemap.xml"))
    except Exception as e:
        print("No se pudo leer el sitemap de eviQ:", e)
        return 1
    if len(found) < 40:  # sanity check: never wipe the list because of a bad response
        print("Sitemap sospechoso (%d protocolos); no se cambia nada." % len(found))
        return 1

    result, fetched = [], 0
    for pid, f in found.items():
        prev = known.get(pid)
        title = prev["title"] if prev else None
        if prev is None or prev.get("lastmod") != f["lastmod"] or prev.get("url") != f["url"]:
            try:
                title = page_title(f["url"]) or title
                fetched += 1
                time.sleep(1)  # be gentle with eviQ
            except Exception as e:
                print("Título no disponible para", pid, e)
        if not title:
            title = f["slug"].replace("-", " ").capitalize()
        result.append({
            "id": pid, "cat": f["cat"], "title": title,
            "off": bool(RETIRED.search(title) or RETIRED.search(f["slug"])),
            "url": f["url"], "lastmod": f["lastmod"],
        })

    # Protocols that vanished from the sitemap stay listed as retired
    vanished = [p for pid, p in known.items() if pid not in found]
    was_active = sum(not p.get("off") for p in known.values()) or 1
    if sum(not p.get("off") for p in vanished) > 0.3 * was_active:
        print("Demasiados protocolos desaparecidos a la vez (%d); no se cambia nada." % len(vanished))
        return 1
    for p in vanished:
        result.append({**p, "off": True})

    result.sort(key=lambda p: (p["cat"], p["off"], int(p["id"])))
    data = {
        "checked": datetime.date.today().isoformat(),
        "source": BASE + "/sitemap.xml",
        "protocols": result,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    active = sum(not p["off"] for p in result)
    print("Protocolos: %d (%d activos, %d retirados); títulos consultados: %d"
          % (len(result), active, len(result) - active, fetched))
    return 0


if __name__ == "__main__":
    sys.exit(main())
