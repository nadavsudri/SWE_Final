import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from leg.data import Area


@pytest.fixture(autouse=True)
def no_llm_key(request, monkeypatch):
    """Offline tests never call the real Claude API, even if a key is in .env."""
    if not request.node.get_closest_marker("live"):
        monkeypatch.setattr("leg.data.profile.claude.load_api_key", lambda *a, **k: None)


@pytest.fixture
def area():
    # 1x1 degree box inside a 4x4 degree fake "country" raster (see country_tif)
    return Area.from_bbox("Test Area", "ISR", 34.0, 30.0, 35.0, 31.0)


@pytest.fixture
def country_tif(tmp_path):
    """4x4 cells of 1 degree each, covering lon 33..37, lat 28..32. Cell value = 10, one nodata."""
    path = tmp_path / "country.tif"
    data = np.full((1, 4, 4), 10.0, dtype="float32")
    data[0, 0, 0] = -99999.0
    with rasterio.open(path, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(33.0, 32.0, 1.0, 1.0),
                       nodata=-99999.0) as dst:
        dst.write(data)
    return path
