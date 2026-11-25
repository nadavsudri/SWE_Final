"""Country profile: which admin units count as 'districts' and which OSM tags count as an
existing health facility. Chosen per country by an LLM; defaults when no API key is set.

The decision is cached per country in <root>/_profiles/<ISO3>.json so every run of a country
uses the same choice (reproducible) and the LLM is asked once.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pycountry

from leg.data.area import Area
from leg.llm import claude

ALLOWED_TAG_KEYS = {"amenity", "healthcare", "emergency"}
_VALUE_RE = re.compile(r"^(\*|[a-z_]+)$")


@dataclass(frozen=True)
class CountryProfile:
    admin_provider: str                 # "geoboundaries" | "osm"
    admin_levels: tuple[str, ...]       # geoboundaries: ("ADM1","ADM2"); osm: ("8",). Last = districts
    facility_tags: tuple[tuple[str, str], ...]  # (key, value), value "*" = any value
    source: str = "default"             # "default" | "llm"
    rationale: str = ""

    def fetcher_options(self) -> dict[str, dict]:
        return {"boundaries": {"provider": self.admin_provider, "levels": self.admin_levels},
                "osm_facilities": {"tags": self.facility_tags}}

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "CountryProfile":
        return cls(d["admin_provider"], tuple(d["admin_levels"]),
                   tuple(tuple(t) for t in d["facility_tags"]), d.get("source", "llm"),
                   d.get("rationale", ""))


# The values the fetchers used before profiles existed.
DEFAULT_PROFILE = CountryProfile(
    admin_provider="geoboundaries",
    admin_levels=("ADM1", "ADM2"),
    facility_tags=(("amenity", "hospital"), ("amenity", "clinic"), ("amenity", "doctors"), ("healthcare", "*")),
)

PROMPT = """You configure a health-facility location study.

Study area: {country} (ISO3 {iso3}), bbox (lon/lat W,S,E,N) {bbox}, about {area_km2:,} km2
({width_km:,} km x {height_km:,} km).

The study places NEW health facilities to maximise the population within reach of one. Facilities
that already exist cover their surroundings, so you must decide which OpenStreetMap tags count as
an existing facility that already serves the population.
- Judge from this country's health system: where primary care is dense and nearly universal,
  basic clinics do not define the gap, so count only the facilities whose distance matters
  (e.g. hospitals, emergency care). Where access is sparse, every health facility matters,
  so count all of them.
- Keys allowed: amenity, healthcare, emergency. Value "*" means any value of that key.

(The administrative level used as districts is chosen by a separate rule, not by you.)

Reply with ONLY this JSON:
{{"facility_tags": [["key", "value"], ...],
  "rationale": "two sentences: why these facilities, for this country"}}"""


def _area_km2(area: Area) -> float:
    """Approximate area of the polygon (equirectangular projection at its mid-latitude)."""
    lat = math.radians(area.geometry.centroid.y)
    return area.geometry.area * 111.32 ** 2 * math.cos(lat)


def validate(d: dict) -> CountryProfile:
    """Checks an LLM reply. The admin level is chosen by leg.data.levels, so admin fields are
    optional here; when present they must still be valid."""
    provider = d.get("admin_provider", DEFAULT_PROFILE.admin_provider)
    levels = [str(x) for x in d.get("admin_levels", DEFAULT_PROFILE.admin_levels)]
    if provider == "geoboundaries":
        ok = levels and all(re.fullmatch(r"ADM[1-5]", lv) for lv in levels)
    elif provider == "osm":
        ok = levels and all(lv.isdigit() and 2 <= int(lv) <= 11 for lv in levels)
    else:
        ok = False
    if not ok:
        raise ValueError(f"bad admin choice: {provider!r} {levels!r}")
    tags = [tuple(t) for t in d.get("facility_tags", [])]
    if not tags or any(len(t) != 2 or t[0] not in ALLOWED_TAG_KEYS or not _VALUE_RE.match(t[1]) for t in tags):
        raise ValueError(f"bad facility_tags: {tags!r}")
    return CountryProfile(provider, tuple(levels), tuple(tags), "llm", str(d.get("rationale", ""))[:500])


def resolve_profile(area: Area, root: Path | str = "data/raw", api_key: str | None = None,
                    refresh: bool = False, ask=claude.complete_json) -> CountryProfile:
    """Cached LLM profile for the country; else ask the LLM; else defaults (with a printed notice)."""
    cache = Path(root) / "_profiles" / f"{area.iso3}.json"
    if cache.exists() and not refresh:
        return CountryProfile.from_json(json.loads(cache.read_text()))

    api_key = api_key or claude.load_api_key()
    if not api_key:
        print("no llm key - using default values")
        return DEFAULT_PROFILE

    country = pycountry.countries.get(alpha_3=area.iso3).name
    w, s_, e, n = area.bbox
    height_km = (n - s_) * 111.32
    width_km = (e - w) * 111.32 * math.cos(math.radians((n + s_) / 2))
    prompt = PROMPT.format(country=country, iso3=area.iso3, bbox=[round(v, 3) for v in area.bbox],
                           width_km=round(width_km), height_km=round(height_km),
                           area_km2=round(_area_km2(area)))
    try:
        profile = validate(ask(prompt, api_key))
    except Exception as e:  # network, bad JSON, invalid choice -> say so and fall back
        print(f"llm profile failed ({type(e).__name__}: {e}) - using default values")
        return DEFAULT_PROFILE
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(profile.to_json(), indent=2, ensure_ascii=False))
    return profile
