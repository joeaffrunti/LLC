"""Find food and drink businesses with contact details but no website tagged.

Source: OpenStreetMap via the Overpass API (no API key needed). Each candidate
must have an email or phone tag. Anything with a website-like tag is dropped.

Important limits:
  * "No website tag" in OpenStreetMap is NOT proof that a business has no
    website. Contributors often leave the tag out. Check each lead before
    relying on it.
  * Email addresses are rare in OSM. Phone-only leads go to a separate file,
    because the mailer only sends to email addresses.

Output:
  <out>.csv        business_name,email,category,city,website  (importable by `import`)
  <out>-phone.csv  business_name,phone,category,city,address  (manual calls only)

Usage:
  python -m outreach.find_leads --out outreach/data/leads-found
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "outreach-lead-finder/1.0 (contact via repository owner)"

# (south, west, north, east) bounding boxes. Long Island's box also covers the
# eastern part of Queens, so results are de-duplicated by OSM id.
REGIONS = {
    "nyc": (40.4774, -74.2591, 40.9176, -73.7004),
    "long-island": (40.5000, -73.7500, 41.2000, -71.8000),
}

FOOD_AMENITIES = "restaurant|cafe|fast_food|bar|pub|ice_cream|bakery|food_court"

WEBSITE_KEYS = ("website", "contact:website", "url", "contact:url", "homepage", "website:menu")
EMAIL_KEYS = ("email", "contact:email")
PHONE_KEYS = ("phone", "contact:phone")


def build_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    box = f"({s},{w},{n},{e})"
    return (
        "[out:json][timeout:90];"
        f'nwr["amenity"~"^({FOOD_AMENITIES})$"]{box};'
        "out center tags;"
    )


def fetch_elements(bbox, url: str = OVERPASS_URL) -> list[dict]:
    data = urllib.parse.urlencode({"data": build_query(bbox)}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8")).get("elements", [])


def _first(tags: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = (tags.get(key) or "").strip()
        if value:
            return value
    return ""


def _address(tags: dict) -> str:
    parts = [tags.get("addr:housenumber", ""), tags.get("addr:street", "")]
    street = " ".join(p for p in parts if p).strip()
    city = tags.get("addr:city", "")
    return ", ".join(p for p in (street, city) if p)


def to_lead(element: dict) -> dict | None:
    """Return a normalized lead, or None if the element is not a usable candidate."""
    tags = element.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None
    if _first(tags, WEBSITE_KEYS):
        return None  # has a website, so it is not our target

    email = _first(tags, EMAIL_KEYS).lower()
    phone = _first(tags, PHONE_KEYS)
    if not email and not phone:
        return None

    return {
        "business_name": name,
        "email": email,
        "phone": phone,
        "category": tags.get("amenity", ""),
        "city": tags.get("addr:city", "") or tags.get("addr:suburb", ""),
        "address": _address(tags),
        "osm_id": f'{element.get("type")}/{element.get("id")}',
    }


def collect(elements_by_region: list[list[dict]]) -> list[dict]:
    """Merge region results, drop duplicates (same OSM id, or same name+address)."""
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    leads: list[dict] = []
    for elements in elements_by_region:
        for element in elements:
            osm_id = f'{element.get("type")}/{element.get("id")}'
            if osm_id in seen_ids:
                continue
            seen_ids.add(osm_id)
            lead = to_lead(element)
            if lead is None:
                continue
            key = (lead["business_name"].lower(), lead["address"].lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            leads.append(lead)
    return leads


def write_outputs(leads: list[dict], out_base: Path) -> tuple[int, int]:
    email_leads = [l for l in leads if l["email"]]
    phone_only = [l for l in leads if not l["email"] and l["phone"]]

    out_base.parent.mkdir(parents=True, exist_ok=True)
    with (out_base.with_suffix(".csv")).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["business_name", "email", "category", "city", "website"])
        for l in email_leads:
            writer.writerow([l["business_name"], l["email"], l["category"], l["city"], ""])

    phone_path = out_base.with_name(out_base.name + "-phone.csv")
    with phone_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["business_name", "phone", "category", "city", "address"])
        for l in phone_only:
            writer.writerow([l["business_name"], l["phone"], l["category"], l["city"], l["address"]])

    return len(email_leads), len(phone_only)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="output base path, e.g. outreach/data/leads-found")
    parser.add_argument("--regions", nargs="+", default=list(REGIONS), choices=list(REGIONS))
    args = parser.parse_args(argv)

    results = []
    for name in args.regions:
        print(f"querying {name}...", file=sys.stderr)
        results.append(fetch_elements(REGIONS[name]))

    leads = collect(results)
    n_email, n_phone = write_outputs(leads, args.out)
    print(f"{n_email} leads with email, {n_phone} phone-only leads")
    print(f"wrote {args.out.with_suffix('.csv')} and phone-only file alongside it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
