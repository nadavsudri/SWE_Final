from leg.data.fetchers.base import Fetcher
from leg.data.fetchers.boundaries import BoundariesFetcher
from leg.data.fetchers.gtfs import GtfsFetcher
from leg.data.fetchers.osm import OsmFacilitiesFetcher, OsmRoadsFetcher
from leg.data.fetchers.worldpop import WorldPopFetcher

# Default fetcher per source. The CLI / UI picks from here by name.
REGISTRY: dict[str, type[Fetcher]] = {
    "worldpop": WorldPopFetcher,
    "boundaries": BoundariesFetcher,
    "osm_facilities": OsmFacilitiesFetcher,
    "osm_roads": OsmRoadsFetcher,
    "gtfs": GtfsFetcher,
}

__all__ = ["Fetcher", "REGISTRY", "WorldPopFetcher", "BoundariesFetcher",
           "OsmFacilitiesFetcher", "OsmRoadsFetcher", "GtfsFetcher"]
