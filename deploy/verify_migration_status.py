#!/usr/bin/env python3
"""
Vérifie que les données sont bien sur PostgreSQL (plus sur SQLite).

Usage :
  set DATABASE_URL=postgresql://user:pass@localhost:5432/paiement_fisc
  python deploy/verify_migration_status.py

Code de sortie :
  0 = PostgreSQL contient les données, SQLite absent ou vide
  1 = migration incomplète ou SQLite encore utilisé comme source
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except ImportError:
    pass

SQLITE_PATHS = [
    os.path.join(ROOT, 'instance', 'database.db'),
    os.path.join(ROOT, 'database.db'),
]

KEY_TABLES = [
    'users', 'instituts', 'taxes', 'boutiques', 'paiements',
    'types_commerce', 'natures_poi', 'configurations',
]


def sqlite_counts():
    import sqlite3
    result = {}
    active_path = None
    for path in SQLITE_PATHS:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            continue
        conn = sqlite3.connect(path)
        counts = {}
        for table in KEY_TABLES:
            try:
                n = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                counts[table] = n
            except Exception:
                counts[table] = -1
        conn.close()
        total = sum(v for v in counts.values() if v > 0)
        if total > 0:
            result[path] = counts
            active_path = path
    return result, active_path


def postgres_counts(database_url: str):
    from sqlalchemy import create_engine, inspect, text

    url = database_url.strip()
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    engine = create_engine(url)
    counts = {}
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table in KEY_TABLES:
            if table not in existing:
                counts[table] = -1
                continue
            counts[table] = conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar() or 0
    return counts


def main():
    db_url = os.environ.get('DATABASE_URL', '').strip()
    print('=== État migration PostgreSQL ===\n')

    sqlite_data, sqlite_path = sqlite_counts()
    if sqlite_path:
        print(f'SQLite actif : {sqlite_path}')
        for t in KEY_TABLES:
            n = sqlite_data[sqlite_path].get(t, 0)
            if n > 0:
                print(f'  {t}: {n}')
    else:
        print('SQLite : aucun fichier avec données')

    print('')
    if not db_url:
        print('PostgreSQL : DATABASE_URL non définie')
        print('\n>>> Migration INCOMPLÈTE — configurez DATABASE_URL dans .env')
        sys.exit(1)

    if not db_url.startswith(('postgresql://', 'postgres://')):
        print(f'PostgreSQL : URL non PostgreSQL ({db_url[:20]}...)')
        sys.exit(1)

    print(f'PostgreSQL : {db_url.split("@")[-1]}')
    pg = postgres_counts(db_url)
    pg_total = 0
    for t in KEY_TABLES:
        n = pg.get(t, 0)
        if n > 0:
            print(f'  {t}: {n}')
            pg_total += n

    print('')
    if sqlite_path and pg_total == 0:
        print('>>> Migration INCOMPLÈTE — données encore uniquement dans SQLite')
        print('    Exécutez : python deploy/migrate_sqlite_to_postgres.py --sqlite instance/database.db')
        sys.exit(1)

    if sqlite_path:
        sq = sqlite_data[sqlite_path]
        mismatches = []
        for t in KEY_TABLES:
            sn, pn = sq.get(t, 0), pg.get(t, 0)
            if sn > 0 and pn < sn:
                mismatches.append(f'{t}: SQLite={sn} PostgreSQL={pn}')
        if mismatches:
            print('>>> ATTENTION — PostgreSQL a moins de données que SQLite :')
            for m in mismatches:
                print(f'    {m}')
            print('    Relancez la migration ou vérifiez que DATABASE_URL pointe la bonne base.')
            sys.exit(1)

    if pg_total > 0:
        print('>>> OK — Données présentes dans PostgreSQL')
        if sqlite_path:
            print('    Conseil : archivez ou supprimez instance/database.db après sauvegarde')
        sys.exit(0)

    print('>>> PostgreSQL vide — lancez init_db() ou importez une sauvegarde')
    sys.exit(1)


if __name__ == '__main__':
    main()
