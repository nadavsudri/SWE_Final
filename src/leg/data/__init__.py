"""Data fetching layer: Area (what to fetch), fetchers (from where), SnapshotCache (where it's kept),
CountryProfile (country-specific choices: district level, which facilities count)."""
from __future__ import annotations

from leg.data.area import Area
from leg.data.cache import Snapshot, SnapshotCache
from leg.data.fetchers import REGISTRY
from leg.data.profile import DEFAULT_PROFILE, CountryProfile, resolve_profile


def fetch_all(area: Area, sources: list[str] | None = None, cache: SnapshotCache | None = None,
              refresh: bool = False, pinned: dict[str, str] | None = None,
              options: dict[str, dict] | None = None,
              profile: CountryProfile | None = None) -> dict[str, Snapshot | Exception]:
    """Fetch every requested source for `area`. One failing source does not stop the others;
    its exception is returned in its slot so the caller reports it explicitly.

    pinned:  {source: snapshot_id} to reuse an exact snapshot (experiments).
    options: {source: kwargs} for that fetcher; overrides the profile, e.g. {"worldpop": {"year": 2025}}.
    profile: country choices; default = resolve_profile() (LLM, cached, or defaults without a key).
    """
    cache = cache or SnapshotCache()
    profile = profile or resolve_profile(area, cache.root)
    pinned = pinned or {}
    opts = profile.fetcher_options()
    for src, kw in (options or {}).items():
        opts[src] = {**opts.get(src, {}), **kw}

    results: dict[str, Snapshot | Exception] = {}
    for name in sources or list(REGISTRY):
        if name not in REGISTRY:
            results[name] = KeyError(f"unknown source {name!r}; choose from {list(REGISTRY)}")
            continue
        try:
            fetcher = REGISTRY[name](**opts.get(name, {}))
            results[name] = cache.get(fetcher, area, refresh=refresh, snapshot_id=pinned.get(name))
        except Exception as e:  # reported, not hidden
            results[name] = e
    return results


__all__ = ["Area", "Snapshot", "SnapshotCache", "fetch_all", "REGISTRY",
           "CountryProfile", "DEFAULT_PROFILE", "resolve_profile"]
