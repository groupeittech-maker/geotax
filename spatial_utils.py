"""Utilitaires PostGIS : extension, index spatial, filtre BBox, synchronisation geom."""
import json
import logging

from sqlalchemy import text

from db_utils import is_postgresql, column_exists

logger = logging.getLogger(__name__)


def postgis_available(engine):
    if not is_postgresql(engine):
        return False
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'postgis')"
            )).scalar()
            return bool(row)
    except Exception as exc:
        logger.warning('PostGIS indisponible : %s', exc)
        return False


def ensure_postgis(engine):
    """Active l'extension PostGIS si absente (PostgreSQL uniquement)."""
    if not is_postgresql(engine):
        return False
    if postgis_available(engine):
        return True
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
        logger.info('Extension PostGIS activée.')
        return True
    except Exception as exc:
        if postgis_available(engine):
            return True
        logger.warning('PostGIS non activé : %s', exc)
        return False


def ensure_geom_column(engine, session):
    """Ajoute la colonne geom et l'index GIST si absents (idempotent)."""
    if not is_postgresql(engine) or not postgis_available(engine):
        return False
    if column_exists(engine, 'boutiques', 'geom'):
        pass
    else:
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'boutiques' AND column_name = 'geom'
                ) THEN
                    ALTER TABLE boutiques ADD COLUMN geom geometry(Geometry, 4326);
                END IF;
            END $$;
        """))
        session.commit()
        logger.info('Colonne boutiques.geom créée.')
    session.execute(text(
        'CREATE INDEX IF NOT EXISTS idx_boutiques_geom ON boutiques USING GIST (geom)'
    ))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_boutiques_coords
        ON boutiques (latitude, longitude)
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """))
    session.commit()
    return True


def sync_boutique_geom(session, boutique):
    """Synchronise boutiques.geom depuis GeoJSON ou lat/lng."""
    engine = session.get_bind()
    if not engine or not is_postgresql(engine):
        return
    if not postgis_available(engine) or not column_exists(engine, 'boutiques', 'geom'):
        return
    geom_json = boutique.geometry
    if not geom_json:
        parsed = boutique.get_geometry_parsed()
        if parsed:
            geom_json = json.dumps(parsed)
    if geom_json:
        session.execute(
            text(
                'UPDATE boutiques SET geom = ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326) '
                'WHERE id = :id'
            ),
            {'geojson': geom_json, 'id': boutique.id},
        )
    elif boutique.latitude is not None and boutique.longitude is not None:
        session.execute(
            text(
                'UPDATE boutiques SET geom = ST_SetSRID('
                'ST_MakePoint(:lng, :lat), 4326) WHERE id = :id'
            ),
            {'lng': boutique.longitude, 'lat': boutique.latitude, 'id': boutique.id},
        )
    else:
        session.execute(
            text('UPDATE boutiques SET geom = NULL WHERE id = :id'),
            {'id': boutique.id},
        )


def backfill_all_geoms(session, batch_size=500):
    """Remplit geom pour les boutiques qui n'ont pas encore de geom PostGIS."""
    engine = session.get_bind()
    if not engine or not is_postgresql(engine):
        return 0
    if not postgis_available(engine) or not column_exists(engine, 'boutiques', 'geom'):
        return 0
    from models import Boutique

    updated = 0
    last_id = 0
    while True:
        ids = session.execute(
            text("""
                SELECT id FROM boutiques
                WHERE id > :last_id
                  AND geom IS NULL
                  AND (latitude IS NOT NULL OR geometry IS NOT NULL)
                ORDER BY id
                LIMIT :batch
            """),
            {'last_id': last_id, 'batch': batch_size},
        ).scalars().all()
        if not ids:
            break
        for bid in ids:
            row = session.get(Boutique, bid)
            if not row:
                continue
            sync_boutique_geom(session, row)
            last_id = bid
            updated += 1
        session.commit()
    if updated:
        logger.info('Synchronisation geom : %s boutique(s).', updated)
    return updated


def apply_bbox_filter_sql(session, bbox, table_alias='boutiques'):
    """
    Retourne une clause SQL AND + params pour filtrer par BBox PostGIS.
    bbox = (min_lon, min_lat, max_lon, max_lat)
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    clause = (
        f" AND {table_alias}.geom IS NOT NULL "
        f"AND ST_Intersects({table_alias}.geom, "
        f"ST_MakeEnvelope(:bbox_min_lon, :bbox_min_lat, :bbox_max_lon, :bbox_max_lat, 4326))"
    )
    params = {
        'bbox_min_lon': min_lon,
        'bbox_min_lat': min_lat,
        'bbox_max_lon': max_lon,
        'bbox_max_lat': max_lat,
    }
    return clause, params


def apply_bbox_filter_query(query, bbox, include_missing_geom=False):
    """
    Filtre une requête SQLAlchemy Boutique par BBox.
    PostGIS si disponible, sinon filtrage lat/lng.
    include_missing_geom: inclure les lignes sans geom (filtrage GeoJSON ensuite).
    """
    from models import Boutique

    engine = query.session.get_bind()
    if engine and postgis_available(engine) and column_exists(engine, 'boutiques', 'geom'):
        min_lon, min_lat, max_lon, max_lat = bbox
        if include_missing_geom:
            clause = text(
                '(boutiques.geom IS NOT NULL AND ST_Intersects('
                'boutiques.geom, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))) '
                'OR (boutiques.geom IS NULL AND boutiques.geometry IS NOT NULL '
                "AND boutiques.geometry != '')"
            ).bindparams(
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
            )
        else:
            clause = text(
                'boutiques.geom IS NOT NULL AND ST_Intersects('
                'boutiques.geom, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))'
            ).bindparams(
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
            )
        return query.filter(clause), False

    min_lon, min_lat, max_lon, max_lat = bbox
    return query.filter(
        Boutique.latitude.isnot(None),
        Boutique.longitude.isnot(None),
        Boutique.latitude >= min_lat,
        Boutique.latitude <= max_lat,
        Boutique.longitude >= min_lon,
        Boutique.longitude <= max_lon,
    ), False


def filter_rows_by_bbox_python(rows, bbox, get_geom_fn):
    """Filtre en Python les lignes dont la bbox géométrique intersecte bbox."""
    from geo_metrics import geometry_bounds, bboxes_intersect

    result = []
    for row in rows:
        geom = get_geom_fn(row)
        if not geom:
            continue
        bounds = geometry_bounds(geom)
        if bounds and bboxes_intersect(bounds, bbox):
            result.append(row)
    return result


def _pylon_radius_m(boutique):
    """Rayon d'influence d'un pylône (m), ou None."""
    radius = boutique.radius_m
    if radius is None and boutique.properties:
        try:
            props = json.loads(boutique.properties) if isinstance(boutique.properties, str) else boutique.properties
            radius = props.get('radius_m') if isinstance(props, dict) else None
        except (TypeError, json.JSONDecodeError):
            radius = None
    try:
        radius = float(radius)
    except (TypeError, ValueError):
        return None
    return radius if radius > 0 else None


def compute_pylon_coverage(session, engine, pylon_ids=None, pays_id=None):
    """
    Métriques de couverture des pylônes : aire individuelle, union PostGIS, chevauchements.
    Retourne {pylons: [...], summary: {...}}.
    """
    import math

    from models import Boutique, QuartierVillage, Commune, Departement

    query = Boutique.query.filter(
        Boutique.active.is_(True),
        Boutique.feature_type == 'pylon',
    )
    if pylon_ids:
        query = query.filter(Boutique.id.in_(pylon_ids))
    elif pays_id:
        from sqlalchemy import or_

        pid = int(pays_id)
        admin_filter = Boutique.quartier_village.has(
            QuartierVillage.commune.has(
                Commune.departement.has(Departement.pays_id == pid)
            )
        )
        query = query.filter(or_(admin_filter, Boutique.pays_id == pid))

    rows = query.all()
    pylons = []
    total_individual_m2 = 0.0
    radii = []

    for boutique in rows:
        radius = _pylon_radius_m(boutique)
        lat, lng = boutique.latitude, boutique.longitude
        if (lat is None or lng is None) and boutique.get_geometry_parsed():
            geom = boutique.get_geometry_parsed()
            if geom and geom.get('type') == 'Point' and len(geom.get('coordinates', [])) >= 2:
                lng, lat = geom['coordinates'][0], geom['coordinates'][1]

        area_m2 = math.pi * (radius ** 2) if radius else None
        if area_m2:
            total_individual_m2 += area_m2
        if radius:
            radii.append(radius)

        pylons.append({
            'id': boutique.id,
            'code_unique': boutique.code_unique,
            'nom': boutique.nom,
            'latitude': lat,
            'longitude': lng,
            'radius_m': radius,
            'coverage_area_m2': round(area_m2, 2) if area_m2 else None,
            'coverage_area_ha': round(area_m2 / 10000, 4) if area_m2 else None,
            'statut_validation': boutique.statut_validation,
        })

    summary = {
        'count': len(pylons),
        'located_count': sum(1 for p in pylons if p['latitude'] is not None and p['longitude'] is not None),
        'total_individual_area_m2': round(total_individual_m2, 2),
        'total_individual_area_ha': round(total_individual_m2 / 10000, 4),
        'avg_radius_m': round(sum(radii) / len(radii), 1) if radii else None,
        'min_radius_m': round(min(radii), 1) if radii else None,
        'max_radius_m': round(max(radii), 1) if radii else None,
        'union_coverage_area_m2': None,
        'union_coverage_area_ha': None,
        'overlap_area_m2': None,
        'overlap_area_ha': None,
    }

    located_ids = [
        p['id'] for p in pylons
        if p['latitude'] is not None and p['longitude'] is not None and p['radius_m']
    ]

    if located_ids and postgis_available(engine):
        try:
            id_clause = 'AND id = ANY(:ids)' if pylon_ids else ''
            pays_clause = ''
            if pays_id and not pylon_ids:
                pays_clause = """
                  AND id IN (
                    SELECT b.id FROM boutiques b
                    JOIN quartiers_villages qv ON b.quartier_village_id = qv.id
                    JOIN communes c ON qv.commune_id = c.id
                    JOIN departements d ON c.departement_id = d.id
                    WHERE d.pays_id = :pays_id
                  )
                """
            sql = text(f"""
                SELECT ST_Area(
                    ST_Union(
                        ST_Buffer(
                            COALESCE(
                                geom,
                                ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
                            )::geography,
                            COALESCE(radius_m, 500)
                        )::geometry
                    )::geography
                ) AS union_area
                FROM boutiques
                WHERE feature_type = 'pylon'
                  AND active IS TRUE
                  AND COALESCE(radius_m, 0) > 0
                  AND (
                    geom IS NOT NULL
                    OR (latitude IS NOT NULL AND longitude IS NOT NULL)
                  )
                  {id_clause}
                  {pays_clause}
            """)
            if pylon_ids:
                params = {'ids': located_ids}
            elif pays_id:
                params = {'pays_id': int(pays_id)}
            else:
                params = {}
            union_area = session.execute(sql, params).scalar()
            if union_area is not None:
                union_area = float(union_area)
                summary['union_coverage_area_m2'] = round(union_area, 2)
                summary['union_coverage_area_ha'] = round(union_area / 10000, 4)
                overlap = max(0.0, total_individual_m2 - union_area)
                summary['overlap_area_m2'] = round(overlap, 2)
                summary['overlap_area_ha'] = round(overlap / 10000, 4)
        except Exception as exc:
            logger.warning('Calcul union couverture pylônes : %s', exc)

    if summary['union_coverage_area_m2'] is None and total_individual_m2 > 0:
        summary['union_coverage_area_m2'] = round(total_individual_m2, 2)
        summary['union_coverage_area_ha'] = round(total_individual_m2 / 10000, 4)
        summary['overlap_area_m2'] = 0.0
        summary['overlap_area_ha'] = 0.0

    return {'pylons': pylons, 'summary': summary}
