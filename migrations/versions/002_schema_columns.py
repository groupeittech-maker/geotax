"""Colonnes pays (centre carte) + champs POI unifié sur boutiques.

Revision ID: 002_schema_columns
Revises: 001_postgis_geom
Create Date: 2026-08-19
"""
from alembic import op

revision = '002_schema_columns'
down_revision = '001_postgis_geom'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != 'postgresql':
        return

    op.execute('ALTER TABLE pays ADD COLUMN IF NOT EXISTS center_lat DOUBLE PRECISION')
    op.execute('ALTER TABLE pays ADD COLUMN IF NOT EXISTS center_lng DOUBLE PRECISION')
    op.execute('ALTER TABLE pays ADD COLUMN IF NOT EXISTS default_zoom INTEGER DEFAULT 6')

    for stmt in (
        "ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS categorie VARCHAR(20) DEFAULT 'contribuable'",
        "ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS feature_type VARCHAR(20) DEFAULT 'point'",
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS geometry TEXT',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS description TEXT',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS properties TEXT',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS length_m DOUBLE PRECISION',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS area_ha DOUBLE PRECISION',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS perimeter_m DOUBLE PRECISION',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS radius_m DOUBLE PRECISION',
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS legacy_map_feature_id INTEGER',
        "ALTER TABLE commercants ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT false",
        'ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS pays_id INTEGER',
    ):
        op.execute(stmt)

    op.execute(
        "UPDATE boutiques SET categorie = 'contribuable' "
        "WHERE categorie IS NULL OR categorie = ''"
    )
    op.execute(
        "UPDATE boutiques SET feature_type = 'point' "
        "WHERE feature_type IS NULL OR feature_type = ''"
    )


def downgrade():
    conn = op.get_bind()
    if conn.dialect.name != 'postgresql':
        return
    op.execute('ALTER TABLE pays DROP COLUMN IF EXISTS default_zoom')
    op.execute('ALTER TABLE pays DROP COLUMN IF EXISTS center_lng')
    op.execute('ALTER TABLE pays DROP COLUMN IF EXISTS center_lat')
