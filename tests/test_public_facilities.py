import json

import pytest
from openpyxl import Workbook

from leg.data import Area, SnapshotCache
from leg.data.fetchers import PublicFacilitiesFetcher
from leg.data.fetchers.public_facilities import country_iso3

HEADER = ["Country", "Admin1", "Facility name", "Facility type", "Ownership", "Lat", "Long", "LL source"]
ROWS = [
    ["Ethiopia", "Amhara", "Kon Health Center", "Health Center", "MoH", 11.40, 39.30, "GPS"],
    ["Ethiopia", "Amhara", "Far Away HP", "Health Post", "MoH", 7.00, 36.00, "GPS"],   # outside area
    ["Ethiopia", "Amhara", "No coords", "Health Post", "MoH", "", "", ""],               # bad row
    ["Kenya", "Nairobi", "Elsewhere", "Dispensary", "MoH", 11.41, 39.31, "GPS"],        # other country
    ["Cote d'Ivoire", "Abidjan", "CHU", "Hospital", "MoH", 5.3, -4.0, "GPS"],
]


@pytest.fixture
def eth_area():
    return Area.from_bbox("t", "ETH", 39.0, 11.0, 39.6, 11.6)


def _xlsx(root):
    p = root / "_manual" / "ssa_public_health_facilities.xlsx"
    p.parent.mkdir(parents=True)
    wb = Workbook()
    ws = wb.active
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    wb.save(p)


def test_reads_only_this_country_inside_area(tmp_path, eth_area):
    _xlsx(tmp_path)
    snap = SnapshotCache(tmp_path).get(PublicFacilitiesFetcher(), eth_area)
    feats = json.loads((snap.path / "facilities.geojson").read_text())["features"]
    assert [f["properties"]["name"] for f in feats] == ["Kon Health Center"]
    assert feats[0]["geometry"]["coordinates"] == [39.3, 11.4]
    assert snap.manifest["summary"] == {"facilities": 1, "in_country": 3, "bad_coordinates": 1}
    assert "Scientific Data" in snap.manifest["citation"]


def test_csv_also_works(tmp_path, eth_area):
    p = tmp_path / "_manual" / "ssa_public_health_facilities.csv"
    p.parent.mkdir(parents=True)
    p.write_text(",".join(HEADER) + "\n" + "\n".join(",".join(map(str, r)) for r in ROWS[:1]) + "\n")
    snap = SnapshotCache(tmp_path).get(PublicFacilitiesFetcher(), eth_area)
    assert snap.manifest["summary"]["facilities"] == 1


def test_missing_file_is_an_error_with_instructions(tmp_path, eth_area):
    with pytest.raises(FileNotFoundError, match="_manual"):
        SnapshotCache(tmp_path).get(PublicFacilitiesFetcher(), eth_area)


def test_country_outside_ssa_is_empty_not_an_error(tmp_path):
    area = Area.from_bbox("t", "ISR", 34.5, 30.5, 35.0, 31.0)
    snap = SnapshotCache(tmp_path).get(PublicFacilitiesFetcher(), area)
    assert snap.manifest["summary"]["facilities"] == 0
    assert "sub-Saharan" in snap.manifest["summary"]["note"]


def test_missing_columns_rejected(tmp_path, eth_area):
    p = tmp_path / "_manual" / "ssa_public_health_facilities.csv"
    p.parent.mkdir(parents=True)
    p.write_text("Country,Name\nEthiopia,X\n")
    with pytest.raises(ValueError, match="missing columns"):
        SnapshotCache(tmp_path).get(PublicFacilitiesFetcher(), eth_area)


def test_country_names_resolve():
    assert country_iso3("Ethiopia") == "ETH"
    assert country_iso3("Cote d'Ivoire") == "CIV"
    assert country_iso3("Democratic Republic of the Congo") == "COD"
