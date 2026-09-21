#!/usr/bin/env python3
"""
Vérification post-migration PostgreSQL (et régression SQLite dev).

Usage :
  python deploy/verify_postgres.py
  DATABASE_URL=postgresql://... python deploy/verify_postgres.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, '.env'))
except ImportError:
    pass

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f'  OK  {msg}')


def fail(msg, exc=None):
    global FAIL
    FAIL += 1
    print(f'  FAIL {msg}')
    if exc:
        print(f'       {exc}')


def test_sqlite_dev():
    print('\n=== SQLite (développement) ===')
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'test.db').replace('\\', '/')
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('FLASK_ENV', None)
    os.environ.pop('FLASK_PRODUCTION', None)
    os.environ['INSTANCE_PATH'] = tmp

    # Recharger l'application avec SQLite
    for mod in list(sys.modules):
        if mod in ('app', 'models', 'db_utils') or mod.startswith('app.'):
            del sys.modules[mod]

    try:
        import app as app_module
        ok('Import app.py (SQLite)')
        with app_module.app.app_context():
            app_module.init_db()
            ok('init_db() SQLite')
            from models import User, Institut, Boutique, Paiement, NaturePoi, TypeCommerce
            assert User.query.first(), 'admin manquant'
            ok('Utilisateur admin créé')
            assert Institut.query.count() >= 3, 'instituts manquants'
            ok(f'Instituts : {Institut.query.count()}')
            assert NaturePoi.query.count() >= 1, 'natures POI manquantes'
            ok(f'Natures POI : {NaturePoi.query.count()}')
            tc = TypeCommerce(code='TEST-SQLITE', nom='Test SQLite', active=True)
            from app import db
            db.session.add(tc)
            db.session.commit()
            assert TypeCommerce.query.filter_by(code='TEST-SQLITE').first()
            ok('CRUD TypeCommerce SQLite')
    except Exception as e:
        fail('SQLite', traceback.format_exc())


def test_postgres(database_url: str):
    print('\n=== PostgreSQL ===')
    os.environ['DATABASE_URL'] = database_url
    os.environ['FLASK_ENV'] = 'development'
    os.environ.pop('FLASK_PRODUCTION', None)

    for mod in list(sys.modules):
        if mod in ('app', 'models', 'db_utils') or mod.startswith('app.'):
            del sys.modules[mod]

    try:
        import app as app_module
        ok('Import app.py (PostgreSQL)')
        assert app_module.DATABASE_URI.startswith('postgresql'), 'URI incorrecte'
        ok(f'URI : {app_module.DATABASE_URI.split("@")[-1]}')

        with app_module.app.app_context():
            app_module.init_db()
            ok('init_db() PostgreSQL')

            from models import (
                User, Institut, Taxe, Boutique, Paiement, NaturePoi,
                TypeCommerce, SecteurActivite, Configuration, CollecteTerrain,
            )
            from app import db, generer_numero_transaction
            from werkzeug.security import check_password_hash
            from datetime import datetime

            admin = User.query.filter_by(username='admin').first()
            assert admin and check_password_hash(admin.password_hash, 'admin123')
            ok('Admin + mot de passe')

            assert Institut.query.count() >= 3
            ok(f'Instituts : {Institut.query.count()}')

            assert Taxe.query.count() >= 3
            ok(f'Taxes : {Taxe.query.count()}')

            assert SecteurActivite.query.count() >= 1
            ok(f'Secteurs : {SecteurActivite.query.count()}')

            tc = TypeCommerce(code='TEST-PG', nom='Test PostgreSQL', active=True)
            db.session.add(tc)
            db.session.commit()
            tc_id = tc.id
            ok(f'INSERT types_commerce (id={tc_id})')

            secteur = SecteurActivite.query.first()
            boutique = Boutique(
                code_unique='BOUTIQUE-PG-TEST',
                nom='Boutique Test PG',
                type_commerce_id=tc_id,
                statut_validation='valide',
                active=True,
            )
            db.session.add(boutique)
            db.session.commit()
            ok(f'INSERT boutiques (id={boutique.id})')

            institut = Institut.query.first()
            taxe = Taxe.query.first()
            paiement = Paiement(
                boutique_id=boutique.id,
                institut_id=institut.id,
                taxe_id=taxe.id,
                montant=5000,
                mois=datetime.utcnow().month,
                annee=datetime.utcnow().year,
                numero_transaction=generer_numero_transaction(),
                reference_transaction=f'REF-PG-{datetime.utcnow().timestamp()}',
                statut='confirme',
            )
            db.session.add(paiement)
            db.session.commit()
            ok(f'INSERT paiements (id={paiement.id})')

            assert boutique.get_statut_paiement_mois() in (True, False)
            ok('Méthode boutique.get_statut_paiement_mois()')

            assert Configuration.get('code_ussd')
            ok('Configuration.get()')

            # Test client Flask
            client = app_module.app.test_client()
            r = client.get('/login')
            assert r.status_code == 200
            ok('GET /login')

            r = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=False)
            assert r.status_code in (302, 200)
            ok('POST /login admin')

            r = client.get('/api/boutiques')
            assert r.status_code == 200
            data = r.get_json()
            assert isinstance(data, dict) and 'boutiques' in data
            ok(f'GET /api/boutiques ({len(data["boutiques"])} POI)')

            r = client.get('/favicon.ico')
            assert r.status_code == 204
            ok('GET /favicon.ico')

            # Nettoyage
            db.session.delete(paiement)
            db.session.delete(boutique)
            db.session.delete(tc)
            db.session.commit()
            ok('DELETE test rows')

    except Exception as e:
        fail('PostgreSQL', traceback.format_exc())


def test_migration_from_temp_sqlite(postgres_url: str):
    """Crée une base SQLite temporaire avec données, puis migre vers PostgreSQL."""
    print('\n=== Migration SQLite → PostgreSQL ===')
    import subprocess
    import shutil

    tmp = tempfile.mkdtemp()
    try:
        db_file = os.path.join(tmp, 'database.db')
        os.environ.pop('DATABASE_URL', None)
        os.environ.pop('FLASK_ENV', None)
        os.environ['INSTANCE_PATH'] = tmp

        for mod in list(sys.modules):
            if mod in ('app', 'models', 'db_utils') or mod.startswith('app.'):
                del sys.modules[mod]

        import app as app_module
        with app_module.app.app_context():
            app_module.init_db()
            from models import Boutique
            from app import db
            db.session.add(Boutique(
                code_unique='BOUTIQUE-MIG-TEST',
                nom='Boutique migration',
                statut_validation='valide',
                active=True,
            ))
            db.session.commit()
            assert Boutique.query.count() >= 1

        env = os.environ.copy()
        env['DATABASE_URL'] = postgres_url
        env['FLASK_ENV'] = 'development'
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'deploy', 'migrate_sqlite_to_postgres.py'),
             '--sqlite', db_file, '--postgres-url', postgres_url, '--skip-empty-check'],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            fail('Script migration', result.stderr or result.stdout)
            return

        ok('Script migrate_sqlite_to_postgres.py')

        for mod in list(sys.modules):
            if mod in ('app', 'models', 'db_utils') or mod.startswith('app.'):
                del sys.modules[mod]

        os.environ['DATABASE_URL'] = postgres_url
        os.environ['FLASK_ENV'] = 'development'
        import app as app_module2
        with app_module2.app.app_context():
            from models import Boutique, User
            n_b = Boutique.query.filter_by(code_unique='BOUTIQUE-MIG-TEST').count()
            assert n_b == 1, f'boutique migrée introuvable (count={n_b})'
            assert User.query.filter_by(username='admin').first()
            ok(f'Données migrées : {Boutique.query.count()} boutique(s), admin présent')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_migration_script(sqlite_path: str, postgres_url: str):
    """Migration depuis un fichier SQLite existant sur disque."""
    print('\n=== Migration fichier SQLite existant ===')
    import subprocess
    env = os.environ.copy()
    env['DATABASE_URL'] = postgres_url
    env['FLASK_ENV'] = 'development'
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, 'deploy', 'migrate_sqlite_to_postgres.py'),
         '--sqlite', sqlite_path, '--postgres-url', postgres_url, '--skip-empty-check'],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        ok(f'Migration depuis {sqlite_path}')
    else:
        fail('Script migration fichier', result.stderr or result.stdout)


def test_production_mode(pg_url: str):
    print('\n=== Mode production (FLASK_ENV=production) ===')
    os.environ['DATABASE_URL'] = pg_url
    os.environ['FLASK_ENV'] = 'production'
    os.environ['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'verify-production-secret-key')

    for mod in list(sys.modules):
        if mod in ('app', 'models', 'db_utils') or mod.startswith('app.'):
            del sys.modules[mod]

    try:
        import app as app_module
        assert app_module.IS_PRODUCTION
        ok('IS_PRODUCTION=True')
        client = app_module.app.test_client()
        r = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        assert r.status_code == 200
        ok('Login admin en mode production')
        r = client.get('/dashboard')
        assert r.status_code == 200
        ok('GET /dashboard')
        r = client.get('/api/pays')
        assert r.status_code == 200
        ok('GET /api/pays')
    except Exception as e:
        fail('Mode production', traceback.format_exc())


def main():
    print('Vérification Paiement Fiscal — PostgreSQL')
    pg_url = os.environ.get('DATABASE_URL', '').strip()
    if pg_url.startswith('postgres://'):
        pg_url = pg_url.replace('postgres://', 'postgresql://', 1)

    test_sqlite_dev()

    if pg_url.startswith('postgresql'):
        test_postgres(pg_url)
        test_migration_from_temp_sqlite(pg_url)
        test_production_mode(pg_url)

        sqlite_candidates = [
            os.path.join(ROOT, 'instance', 'database.db'),
            os.path.join(ROOT, 'database.db'),
        ]
        for sp in sqlite_candidates:
            if os.path.isfile(sp):
                test_migration_script(sp, pg_url)
                break
    else:
        print('\n=== PostgreSQL ===')
        print('  SKIP  DATABASE_URL PostgreSQL non définie')
        print('        Lancez : docker run -d --name paiement-fisc-pg -e POSTGRES_PASSWORD=test -e POSTGRES_USER=paiement_fisc -e POSTGRES_DB=paiement_fisc -p 5432:5432 postgres:16')
        print('        Puis   : set DATABASE_URL=postgresql://paiement_fisc:test@localhost:5432/paiement_fisc')

    print(f'\n{"=" * 40}')
    print(f'Résultat : {PASS} OK, {FAIL} échec(s)')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
