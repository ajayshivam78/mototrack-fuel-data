"""Reads today's petrol/diesel price for every city and writes prices.json."""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CITIES = json.loads((ROOT / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
VARIANTS = json.loads((ROOT / "data" / "variants.json").read_text(encoding="utf-8"))["retailers"]
OUT = ROOT / "prices.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
}
PAUSE = 1.5          # seconds between requests, to be polite to the website
MAX_CHANGE = 0.10    # ignore a new value that jumps more than 10% from the last live value


def slug(city: dict) -> str:
    return city.get("slug") or re.sub(r"[^a-z0-9]+", "-", city["city"].lower()).strip("-")


def scrape(city: dict, fuel: str):
    url = f"https://www.goodreturns.in/{fuel}-price-in-{slug(city)}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  ! {url} -> HTTP {r.status_code}")
            return None
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        for m in re.finditer(r"₹\s*([0-9]{2,3}\.[0-9]{1,2})", text):
            value = float(m.group(1))
            if 60 <= value <= 200:
                return value
        print(f"  ! no price found on {url}")
    except Exception as e:
        print(f"  ! {url} -> {e}")
    return None


def sane(new, old_record, field):
    """Accept the value unless it jumps unrealistically from the previous live value."""
    if old_record and old_record.get("live"):
        old = old_record[field]
        return abs(new - old) / old <= MAX_CHANGE
    return True


def main():
    old = {}
    if OUT.exists():
        try:
            old = {c["city"]: c for c in json.loads(OUT.read_text(encoding="utf-8")).get("cities", [])}
        except Exception:
            old = {}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result, ok = [], 0

    for c in CITIES:
        print(f"{c['city']}")
        prev = old.get(c["city"])
        petrol = scrape(c, "petrol")
        time.sleep(PAUSE)
        diesel = scrape(c, "diesel")
        time.sleep(PAUSE)

        if petrol and diesel and sane(petrol, prev, "petrol") and sane(diesel, prev, "diesel"):
            ok += 1
            print(f"  petrol {petrol}  diesel {diesel}  (live)")
            rec = {"petrol": petrol, "diesel": diesel, "live": True, "checked": now}
        else:
            src = prev if prev else c
            print(f"  keeping previous/fallback: petrol {src['petrol']}  diesel {src['diesel']}")
            rec = {"petrol": src["petrol"], "diesel": src["diesel"], "live": False,
                   "checked": prev.get("checked", "") if prev else ""}

        result.append({"city": c["city"], "state": c["state"], "lat": c["lat"], "lon": c["lon"], **rec})

    OUT.write_text(
        json.dumps({"updated": now, "cities": result, "retailers": VARIANTS}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nDone: {ok}/{len(CITIES)} cities updated live.")
    if ok == 0:
        print("::error::No city could be read. The website layout may have changed.")
        sys.exit(1)


if __name__ == "__main__":
    main()