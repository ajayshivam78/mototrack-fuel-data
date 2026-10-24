"""Reads today's petrol/diesel prices from the goodreturns price TABLES and writes prices.json.
Never invents prices: a city that cannot be read is saved with null prices."""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CITIES = json.loads((ROOT / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
VARIANTS = json.loads((ROOT / "data" / "variants.json").read_text(encoding="utf-8"))["retailers"]
OUT = ROOT / "prices.json"

BASE = "https://www.goodreturns.in/"
VERSION = 2
PAUSE = 1.0
MAX_CHANGE = 0.15
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}


def get(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return r.text
            print(f"  ! HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"  ! {e} for {url}")
        time.sleep(2 * (attempt + 1))
    return None


def parse_table_rows(html, fuel):
    """Returns {url-slug: price} from table rows like: [City link] | ₹107.76 | 0.00"""
    out = {}
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=True)
        if not a:
            continue
        m = re.search(rf"{fuel}-price-in-([a-z0-9-]+)\.html", a["href"])
        if not m or re.search(r"-s\d+$", m.group(1)):      # skip state links
            continue
        p = re.search(r"₹\s*([0-9]{2,3}(?:\.[0-9]+)?)", tr.get_text(" ", strip=True))
        if p and 60 <= float(p.group(1)) <= 200:
            out[m.group(1)] = float(p.group(1))
    return out


def collect(fuel):
    """Reads the national page and every state page for one fuel."""
    prices = {}
    html = get(urljoin(BASE, f"{fuel}-price.html"))
    if not html:
        return prices
    prices.update(parse_table_rows(html, fuel))
    states = sorted({urljoin(BASE, a["href"]) for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)
                     if re.search(rf"{fuel}-price-in-[a-z0-9-]+-s\d+\.html$", a["href"])})
    print(f"{fuel}: national page has {len(prices)} cities, {len(states)} state pages to read")
    for url in states:
        time.sleep(PAUSE)
        page = get(url)
        if page:
            for k, v in parse_table_rows(page, fuel).items():
                prices.setdefault(k, v)
    print(f"{fuel}: {len(prices)} places read in total")
    return prices


def candidates(city):
    s = city.get("slug")
    if isinstance(s, list):
        return s
    if s:
        return [s]
    return [re.sub(r"[^a-z0-9]+", "-", city["city"].lower()).strip("-")]


def lookup(table, city):
    for key in candidates(city):
        if key in table:
            return table[key]
    return None


def sane(new, prev, field):
    if prev and prev.get(field):
        return abs(new - prev[field]) / prev[field] <= MAX_CHANGE
    return True


def main():
    old = {}
    if OUT.exists():
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
            if data.get("version") == VERSION:          # ignore files made by the old buggy script
                old = {c["city"]: c for c in data.get("cities", [])}
        except Exception:
            old = {}

    petrol_table = collect("petrol")
    diesel_table = collect("diesel")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result, ok = [], 0
    print("\n--- Results ---")
    for c in CITIES:
        prev = old.get(c["city"])
        petrol, diesel = lookup(petrol_table, c), lookup(diesel_table, c)

        if petrol and diesel and sane(petrol, prev, "petrol") and sane(diesel, prev, "diesel"):
            ok += 1
            print(f"{c['city']:20} petrol {petrol:7.2f}  diesel {diesel:7.2f}  (live)")
            rec = {"petrol": petrol, "diesel": diesel, "live": True, "checked": now}
        elif prev and prev.get("checked") and prev.get("petrol") and prev.get("diesel"):
            print(f"{c['city']:20} not found today; keeping last real reading")
            rec = {"petrol": prev["petrol"], "diesel": prev["diesel"], "live": False, "checked": prev["checked"]}
        else:
            print(f"{c['city']:20} NOT FOUND (tried {candidates(c)}). Fix its slug in cities.json")
            rec = {"petrol": None, "diesel": None, "live": False, "checked": ""}

        result.append({"city": c["city"], "state": c["state"], "lat": c["lat"], "lon": c["lon"], **rec})

    OUT.write_text(
        json.dumps({"version": VERSION, "updated": now, "cities": result, "retailers": VARIANTS},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nDone: {ok}/{len(CITIES)} cities read live.")
    if ok == 0:
        print("::error::No city could be read. The site layout changed or it blocks GitHub.")
        sys.exit(1)


if __name__ == "__main__":
    main()