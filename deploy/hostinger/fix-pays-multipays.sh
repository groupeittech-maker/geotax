#!/usr/bin/env bash
# Corrige le multi-pays : Congo (CG) ≠ RCA (CF), rattache les POI au bon pays.
# Usage : cd /opt/paiement-fisc && bash deploy/hostinger/fix-pays-multipays.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$APP_DIR"

echo "=== Correction multi-pays GeoTax ==="

docker compose --env-file .env exec -T db psql -U "${POSTGRES_USER:-paiement_fisc}" -d "${POSTGRES_DB:-paiement_fisc}" <<'SQL'
ALTER TABLE boutiques ADD COLUMN IF NOT EXISTS pays_id INTEGER;
ALTER TABLE pays ADD COLUMN IF NOT EXISTS center_lat DOUBLE PRECISION;
ALTER TABLE pays ADD COLUMN IF NOT EXISTS center_lng DOUBLE PRECISION;
ALTER TABLE pays ADD COLUMN IF NOT EXISTS default_zoom INTEGER DEFAULT 6;
SQL

docker compose --env-file .env exec -T app python <<'PY'
from app import app, _migrate_pays_map_metadata, _reconcile_boutique_pays_ids, Pays, Departement, Commune, QuartierVillage, Boutique

with app.app_context():
    _migrate_pays_map_metadata()
    n = _reconcile_boutique_pays_ids()
    print(f"Réconciliation pays_id: {n} POI(s)")
    print("\n--- Pays actifs ---")
    for p in Pays.query.filter_by(active=True).order_by(Pays.nom).all():
        dept_ids = [d.id for d in Departement.query.filter_by(pays_id=p.id, active=True).all()]
        nb_dept = len(dept_ids)
        nb_communes = Commune.query.filter(
            Commune.departement_id.in_(dept_ids), Commune.active.is_(True)
        ).count() if dept_ids else 0
        commune_ids = [
            c.id for c in Commune.query.filter(
                Commune.departement_id.in_(dept_ids), Commune.active.is_(True)
            ).all()
        ] if dept_ids else []
        nb_qv = QuartierVillage.query.filter(
            QuartierVillage.commune_id.in_(commune_ids), QuartierVillage.active.is_(True)
        ).count() if commune_ids else 0
        nb_poi = Boutique.query.filter_by(pays_id=p.id, active=True).count()
        nb_contrib = Boutique.query.filter_by(
            pays_id=p.id, active=True, categorie='contribuable'
        ).count()
        nb_infra = Boutique.query.filter_by(
            pays_id=p.id, active=True, categorie='infrastructure'
        ).count()
        print(
            f"  [{p.id}] {p.code} — {p.nom} | "
            f"dept={nb_dept} communes={nb_communes} quartiers={nb_qv} "
            f"poi={nb_poi} contrib={nb_contrib} infra={nb_infra}"
        )
    sans = Boutique.query.filter_by(active=True).filter(
        Boutique.pays_id.is_(None)
    ).count()
    print(f"\nPOI sans pays_id: {sans}")
PY

echo ""
echo "=== Terminé — sélectionnez le pays dans le menu en haut ==="
