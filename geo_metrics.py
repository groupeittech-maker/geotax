"""Calculs géographiques légers (WGS84) pour les entités cartographiques."""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

EARTH_RADIUS_M = 6371008.8

FeatureGeometry = Dict[str, Any]

MAP_FEATURE_TYPES = {
    'pylon': {'label': 'Pylône', 'icon': '🗼', 'color': '#e65100'},
    'pipeline': {'label': 'Pipeline', 'icon': '🔧', 'color': '#1565c0'},
    'parcel': {'label': 'Parcelle', 'icon': '📐', 'color': '#2e7d32'},
    'perimeter': {'label': 'Périmètre', 'icon': '⭕', 'color': '#6a1b9a'},
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _flatten_coords(geometry: FeatureGeometry) -> List[Tuple[float, float]]:
    coords = geometry.get('coordinates')
    if coords is None:
        return []

    points: List[Tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                points.append((float(node[0]), float(node[1])))
            else:
                for child in node:
                    walk(child)

    walk(coords)
    return points


def geometry_centroid(geometry: FeatureGeometry) -> Optional[Tuple[float, float]]:
    points = _flatten_coords(geometry)
    if not points:
        return None
    lng = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lng


def geometry_bounds(geometry: FeatureGeometry) -> Optional[Tuple[float, float, float, float]]:
    points = _flatten_coords(geometry)
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def bboxes_intersect(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    min_lon_a, min_lat_a, max_lon_a, max_lat_a = a
    min_lon_b, min_lat_b, max_lon_b, max_lat_b = b
    return not (
        max_lon_a < min_lon_b
        or max_lon_b < min_lon_a
        or max_lat_a < min_lat_b
        or max_lat_b < min_lat_a
    )


def line_length_m(coords: List[List[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i][0], coords[i][1]
        lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
        total += _haversine_m(lat1, lon1, lat2, lon2)
    return total


def ring_perimeter_m(ring: List[List[float]]) -> float:
    if len(ring) < 2:
        return 0.0
    closed = ring if ring[0] == ring[-1] else ring + [ring[0]]
    return line_length_m(closed)


def ring_area_m2(ring: List[List[float]]) -> float:
    if len(ring) < 3:
        return 0.0
    closed = ring if ring[0] == ring[-1] else ring + [ring[0]]
    lat0 = sum(p[1] for p in closed) / len(closed)
    lon0 = sum(p[0] for p in closed) / len(closed)
    cos_lat0 = math.cos(math.radians(lat0))

    def to_xy(lon: float, lat: float) -> Tuple[float, float]:
        x = math.radians(lon - lon0) * cos_lat0 * EARTH_RADIUS_M
        y = math.radians(lat - lat0) * EARTH_RADIUS_M
        return x, y

    area = 0.0
    for i in range(len(closed) - 1):
        x1, y1 = to_xy(closed[i][0], closed[i][1])
        x2, y2 = to_xy(closed[i + 1][0], closed[i + 1][1])
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def polygon_metrics(geometry: FeatureGeometry) -> Dict[str, float]:
    coords = geometry.get('coordinates') or []
    gtype = geometry.get('type')
    area_m2 = 0.0
    perimeter_m = 0.0

    if gtype == 'Polygon' and coords:
        outer = coords[0]
        area_m2 = ring_area_m2(outer)
        perimeter_m = ring_perimeter_m(outer)
        for hole in coords[1:]:
            area_m2 -= ring_area_m2(hole)
            perimeter_m += ring_perimeter_m(hole)
    elif gtype == 'MultiPolygon':
        for poly in coords:
            if not poly:
                continue
            area_m2 += ring_area_m2(poly[0])
            perimeter_m += ring_perimeter_m(poly[0])
            for hole in poly[1:]:
                area_m2 -= ring_area_m2(hole)
                perimeter_m += ring_perimeter_m(hole)

    return {
        'area_m2': max(0.0, area_m2),
        'area_ha': max(0.0, area_m2) / 10000.0,
        'perimeter_m': perimeter_m,
    }


def compute_metrics(
    geometry: FeatureGeometry,
    feature_type: str,
    properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[float]]:
    properties = properties or {}
    gtype = geometry.get('type')
    result: Dict[str, Optional[float]] = {
        'length_m': None,
        'area_ha': None,
        'perimeter_m': None,
        'radius_m': None,
    }

    if feature_type == 'pylon':
        radius = properties.get('radius_m')
        if radius is not None:
            try:
                result['radius_m'] = float(radius)
            except (TypeError, ValueError):
                result['radius_m'] = None
        return result

    if gtype in ('LineString', 'MultiLineString'):
        coords = geometry.get('coordinates') or []
        if gtype == 'LineString':
            result['length_m'] = line_length_m(coords)
        else:
            result['length_m'] = sum(line_length_m(part) for part in coords)
        return result

    if gtype in ('Polygon', 'MultiPolygon'):
        metrics = polygon_metrics(geometry)
        result['area_ha'] = metrics['area_ha']
        result['perimeter_m'] = metrics['perimeter_m']
        return result

    return result


def parse_geometry(raw: Any) -> FeatureGeometry:
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict):
        return raw
    raise ValueError('Géométrie invalide')


def validate_geometry(geometry: FeatureGeometry, feature_type: str) -> None:
    gtype = geometry.get('type')
    if feature_type == 'pipeline' and gtype not in ('LineString', 'MultiLineString'):
        raise ValueError('Un pipeline doit être une ligne (LineString)')
    if feature_type in ('parcel', 'perimeter') and gtype not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Une parcelle ou un périmètre doit être un polygone')
    if feature_type == 'pylon' and gtype != 'Point':
        raise ValueError('Un pylône doit être un point')
    if not _flatten_coords(geometry):
        raise ValueError('Géométrie vide')


def validate_feature_properties(feature_type: str, properties: Optional[Dict[str, Any]]) -> None:
    properties = properties or {}
    if feature_type == 'pylon':
        radius = properties.get('radius_m')
        if radius is None or float(radius) <= 0:
            raise ValueError('Le rayon du pylône (radius_m) doit être > 0')
    if feature_type == 'pipeline':
        diameter = properties.get('diameter_mm')
        if diameter is None or float(diameter) <= 0:
            raise ValueError('Le diamètre du pipeline (diameter_mm) doit être > 0')
