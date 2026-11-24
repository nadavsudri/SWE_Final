"""Small HTTP helpers: retries, streaming downloads, and a URL-keyed download cache."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests

USER_AGENT = "leg-facility-location/0.1 (course project; python-requests)"
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _request(method: str, url: str, retries: int = 3, **kw) -> requests.Response:
    kw.setdefault("timeout", 120)
    for attempt in range(1, retries + 1):
        try:
            r = _session.request(method, url, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except requests.ConnectionError:
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def get_json(url: str, **kw):
    return _request("GET", url, **kw).json()


def post(url: str, **kw) -> requests.Response:
    return _request("POST", url, **kw)


def download(url: str, dest: Path, cache_dir: Path | None = None) -> Path:
    """Stream `url` to `dest`. With `cache_dir`, a URL already downloaded once is reused
    (country-wide rasters and GTFS zips are big and shared by every area)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cached = None
    if cache_dir is not None:
        key = hashlib.sha1(url.encode()).hexdigest()[:16]
        cached = cache_dir / f"{key}_{Path(url.split('?')[0]).name or 'file'}"
        if cached.exists():
            _link(cached, dest)
            return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _request("GET", url, stream=True) as r, open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        _link(dest, cached)
    return dest


def _link(src: Path, dst: Path) -> None:
    """Hard-link when possible (no extra disk), else copy."""
    if dst.exists():
        dst.unlink()
    try:
        dst.hardlink_to(src)
    except OSError:
        dst.write_bytes(src.read_bytes())
