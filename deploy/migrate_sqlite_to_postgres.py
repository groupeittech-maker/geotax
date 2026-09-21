#!/usr/bin/env python3
"""
Copie les données SQLite vers PostgreSQL.

LEGACY — À n'utiliser qu'une seule fois si vos données sont encore dans
instance/database.db et n'ont jamais été migrées vers PostgreSQL.
Si PostgreSQL contient déjà vos données, utilisez pg_dump / pg_restore.

Usage :
  export DATABASE_URL=postgresql://user:pass@localhost:5432/paiement_fisc
  python deploy/migrate_sqlite_to_postgres.py --sqlite instance/database.db

Ou avec un fichier .env à la racine du projet.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except ImportError:
    pass

from sqlalchemy import MetaData, create_engine, inspect, text

from db_utils import reset_postgres_sequences

TABLE_ORDER = [
    'instituts',
    'pays',
    'natures_poi',
    'secteurs_activite',
    'users',
    'departements',
    'types_commerce',
    'communes',
    'champs_poi',
    'quartiers_villages',
    'marches',
    'taxes',
    'boutiques',
    'boutique_taxes',
    'paiements',
    'commercants',
    'collectes_terrain',
    'map_features',
    'configurations',
]


def _normalize_postgres_url(url: str) -> str:
    url = url.strip()
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


def _sqlite_url(path: str) -> str:
    path = os.path.abspath(path).replace('\\', '/')
    return f'sqlite:///{path}'


def _find_default_sqlite() -> str | None:
    candidates = [
        os.path.join(ROOT, 'instance', 'database.db'),
        os.path.join(ROOT, 'database.db'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def truncate_postgres_tables(dst_engine):
    """Vide toutes les tables avant import (respecte les FK via CASCADE)."""
    existing = set(inspect(dst_engine).get_table_names())
    to_truncate = [t for t in reversed(TABLE_ORDER) if t in existing]
    if not to_truncate:
        return
    with dst_engine.begin() as conn:
        conn.execute(text(
            f"TRUNCATE TABLE {', '.join(to_truncate)} RESTART IDENTITY CASCADE"
        ))


def copy_table(src_engine, dst_engine, table_name: str) -> int:
    src_meta = MetaData()
    dst_meta = MetaData()
    src_meta.reflect(bind=src_engine, only=[table_name])
    if table_name not in src_meta.tables:
        return 0
    table = src_meta.tables[table_name]

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        rows = src_conn.execute(table.select()).mappings().all()
        if not rows:
            return 0

        dst_meta.reflect(bind=dst_engine, only=[table_name])
        if table_name not in dst_meta.tables:
            raise RuntimeError(f'Table {table_name} absente sur PostgreSQL — lancez init_db() d\'abord.')

        dst_table = dst_meta.tables[table_name]
        dst_conn.execute(dst_table.insert(), [dict(row) for row in rows])
        dst_conn.commit()
        return len(rows)


def main():
    parser = argparse.ArgumentParser(description='Migrer SQLite → PostgreSQL')
    parser.add_argument(
        '--sqlite',
        default=_find_default_sqlite(),
        help='Chemin vers database.db (défaut : instance/database.db ou database.db)',
    )
    parser.add_argument(
        '--postgres-url',
        default=os.environ.get('DATABASE_URL', ''),
        help='URL PostgreSQL (ou variable DATABASE_URL)',
    )
    parser.add_argument(
        '--skip-empty-check',
        action='store_true',
        help='Copier même si PostgreSQL contient déjà des données',
    )
    args = parser.parse_args()

    if not args.sqlite or not os.path.isfile(args.sqlite):
        print('Erreur : fichier SQLite introuvable. Indiquez --sqlite chemin/vers/database.db')
        sys.exit(1)

    if not args.postgres_url:
        print('Erreur : DATABASE_URL PostgreSQL requis (argument ou variable d\'environnement)')
        sys.exit(1)

    postgres_url = _normalize_postgres_url(args.postgres_url)
    if not postgres_url.startswith('postgresql'):
        print('Erreur : DATABASE_URL doit être une URL PostgreSQL')
        sys.exit(1)

    sqlite_url = _sqlite_url(args.sqlite)
    src_engine = create_engine(sqlite_url)
    dst_engine = create_engine(postgres_url)

    if dst_engine.dialect.name != 'postgresql':
        print('Erreur : la cible doit être PostgreSQL')
        sys.exit(1)

    os.environ['DATABASE_URL'] = postgres_url
    os.environ['FLASK_ENV'] = 'development'
    os.environ.pop('FLASK_PRODUCTION', None)

    from app import app, db, init_db

    dst_inspector = inspect(dst_engine)
    existing_tables = set(dst_inspector.get_table_names())

    def _postgres_has_data():
        for table in ('boutiques', 'paiements', 'users'):
            if table not in existing_tables:
                continue
            with dst_engine.connect() as conn:
                if conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar():
                    return True
        return False

    if not args.skip_empty_check and _postgres_has_data():
        print('PostgreSQL contient déjà des données. Utilisez --skip-empty-check pour écraser.')
        sys.exit(1)

    with app.app_context():
        db.create_all()

    print(f'Source SQLite : {args.sqlite}')
    print(f'Cible         : {postgres_url.split("@")[-1]}')
    print('')

    print('Vidage des tables PostgreSQL...')
    truncate_postgres_tables(dst_engine)

    total = 0
    copied_tables = []
    for table_name in TABLE_ORDER:
        if table_name not in inspect(src_engine).get_table_names():
            continue
        n = copy_table(src_engine, dst_engine, table_name)
        if n:
            print(f'  {table_name}: {n} ligne(s)')
            total += n
            copied_tables.append(table_name)

    reset_postgres_sequences(dst_engine, copied_tables)

    print('')
    print('Initialisation des données par défaut (si nécessaire)...')
    with app.app_context():
        init_db()

    print('')
    print(f'Migration terminée : {total} ligne(s) copiée(s).')
    print('Mettez à jour .env avec DATABASE_URL PostgreSQL et redémarrez l\'application.')


if __name__ == '__main__':
    main()
