"""PostGIS : extension, colonne geom, index spatial GIST.

Revision ID: 001_postgis_geom
Revises:
Create Date: 2026-08-19

"""
from alembic import op
import sqlalchemy as sa

revision = '001_postgis_geom'
down_revision = None
branch_labels = None
depends_on = None


def _postgis_installed(connection):
    return connection.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'postgis')"
    )).scalar()


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != 'postgresql':
        return

    if not _postgis_installed(conn):
        try:
            with op.get_context().autocommit_block():
                op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
        except Exception:
            pass

    if not _postgis_installed(conn):
        return

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'boutiques' AND column_name = 'geom'
            ) THEN
                ALTER TABLE boutiques ADD COLUMN geom geometry(Geometry, 4326);
            END IF;
        END $$;
    """)

    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_boutiques_geom '
        'ON boutiques USING GIST (geom)'
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_boutiques_coords
        ON boutiques (latitude, longitude)
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
    """)

    op.execute("""
        UPDATE boutiques SET geom = ST_SetSRID(ST_GeomFromGeoJSON(geometry), 4326)
        WHERE geom IS NULL AND geometry IS NOT NULL AND geometry != ''
    """)
    op.execute("""
        UPDATE boutiques SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
        WHERE geom IS NULL
          AND latitude IS NOT NULL AND longitude IS NOT NULL
    """)


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name != 'postgresql':
        return

    op.execute('DROP INDEX IF EXISTS idx_boutiques_coords')
    op.execute('DROP INDEX IF EXISTS idx_boutiques_geom')
    op.execute('ALTER TABLE boutiques DROP COLUMN IF EXISTS geom')
