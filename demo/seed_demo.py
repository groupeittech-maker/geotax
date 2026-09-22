# -*- coding: utf-8 -*-
"""
Seed de données de démonstration pour les vidéos GeoTax.
Crée une base SQLite `demo.db` à la racine du projet avec :
- hiérarchie géographique Congo / Brazzaville
- types de commerce, taxes, POI contribuables et infrastructures
- paiements réalistes (à jour / partiels / impayés)
- utilisateurs par rôle, compte commerçant, journal de collectes

Usage : python demo/seed_demo.py
"""
import os
import sys
import json
import random
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

os.environ['DATABASE_URL'] = 'sqlite:///demo.db'
os.environ.setdefault('FLASK_ENV', 'development')

from app import app, init_db, generate_qr_code  # noqa: E402
from models import (  # noqa: E402
    db, Pays, Departement, Commune, QuartierVillage, Marche,
    SecteurActivite, TypeCommerce, Institut, Taxe, Boutique, BoutiqueTaxe,
    Paiement, User, Commercant, CollecteTerrain,
)
from werkzeug.security import generate_password_hash  # noqa: E402

random.seed(42)


def main():
    with app.app_context():
        init_db()

        # ---------- Hiérarchie géographique ----------
        congo = Pays.query.filter_by(code='CG').first() or Pays(
            code='CG', nom='Congo', code_iso='COG',
            center_lat=-4.2634, center_lng=15.2429, default_zoom=12)
        db.session.add(congo)
        db.session.flush()

        bzv = Departement(pays_id=congo.id, code='BZV', nom='Brazzaville')
        db.session.add(bzv)
        db.session.flush()

        communes = {}
        for code, nom in [('PTP', 'Poto-Poto'), ('BCG', 'Bacongo'), ('MGL', 'Moungali')]:
            c = Commune(departement_id=bzv.id, code=code, nom=nom)
            db.session.add(c)
            db.session.flush()
            communes[nom] = c

        quartiers = {}
        for cname, qs in {
            'Poto-Poto': ['Centre Poto-Poto', 'Moungali Nord'],
            'Bacongo': ['Marché Total', 'Diata'],
            'Moungali': ['Ouenzé', 'Talangaï'],
        }.items():
            for i, qnom in enumerate(qs, 1):
                q = QuartierVillage(commune_id=communes[cname].id,
                                  code=f'{communes[cname].code}-Q{i}',
                                  nom=qnom, type='quartier')
                db.session.add(q)
                db.session.flush()
                quartiers[qnom] = q

        marches = []
        for nom, q in [('Marché Total', quartiers['Marché Total']),
                       ('Marché Poto-Poto', quartiers['Centre Poto-Poto']),
                       ('Marché Moungali', quartiers['Ouenzé'])]:
            m = Marche(quartier_village_id=q.id, code=f'MCH-{nom.split()[-1].upper()[:5]}',
                       nom=nom, adresse=f'{nom}, Brazzaville')
            db.session.add(m)
            marches.append(m)
        db.session.flush()

        # ---------- Types de commerce ----------
        def secteur(code):
            return SecteurActivite.query.filter_by(code=code).first()

        types = {}
        for code, nom, s in [
            ('BOUT', 'Boutique / Commerce général', 'COMMERCE'),
            ('RESTO', 'Restaurant / Maquis', 'RESTAURATION'),
            ('PHARM', 'Pharmacie', 'SERVICES'),
            ('COIFF', 'Salon de coiffure', 'SERVICES'),
            ('QUINC', 'Quincaillerie', 'COMMERCE'),
            ('ECOLE', 'École privée', 'EDUCATION'),
            ('TELESHOP', 'Cabine télécom / Mobile Money', 'SERVICES'),
        ]:
            tc = TypeCommerce(code=code, nom=nom,
                              secteur_id=secteur(s).id if secteur(s) else None)
            db.session.add(tc)
            db.session.flush()
            types[code] = tc

        # ---------- Taxes ----------
        taxes = {t.code: t for t in Taxe.query.all()}
        mairie = Institut.query.filter_by(code='MAIRIE').first()
        if 'TAXE_MARCHE' not in taxes:
            tm = Taxe(institut_id=mairie.id, code='TAXE_MARCHE',
                      nom='Taxe de marché', montant_attendu=1500,
                      periodicite='mensuel',
                      description='Taxe mensuelle pour les commerces de marché')
            db.session.add(tm)
            db.session.flush()
            taxes['TAXE_MARCHE'] = tm

        # ---------- Contribuables ----------
        # (nom, propriétaire, quartier, type, lat, lng, statut, au_marché)
        contribuables = [
            ('Boutique Chez Marie', 'Marie Nkouka', 'Marché Total', 'BOUT', -4.2712, 15.2701, 'valide', True),
            ('Pharmacie du Centre', 'Dr. Alain Makosso', 'Centre Poto-Poto', 'PHARM', -4.2638, 15.2449, 'valide', False),
            ('Restaurant Le Palmier', 'Jean-Claude Bemba', 'Marché Total', 'RESTO', -4.2701, 15.2695, 'valide', True),
            ('Salon Élégance', 'Divine Oko', 'Diata', 'COIFF', -4.2755, 15.2768, 'valide', False),
            ('Quincaillerie Moderne', 'Patrick Goma', 'Centre Poto-Poto', 'QUINC', -4.2651, 15.2431, 'valide', False),
            ('École Les Petits Génies', 'Sr. Francine Itoua', 'Ouenzé', 'ECOLE', -4.2502, 15.2812, 'valide', False),
            ('Supérette Express', 'Rodrigue Bassiloua', 'Marché Total', 'BOUT', -4.2719, 15.2710, 'valide', True),
            ('Boulangerie Le Fournil', 'Paul Nzouba', 'Diata', 'RESTO', -4.2748, 15.2752, 'valide', False),
            ('Cabine Mobile Money Center', 'Grâce Malonga', 'Centre Poto-Poto', 'TELESHOP', -4.2644, 15.2462, 'valide', True),
            ('Librairie Nationale', 'Étienne Samba', 'Centre Poto-Poto', 'BOUT', -4.2629, 15.2438, 'valide', False),
            ('Bar Maquis La Paix', 'Victor Louzolo', 'Talangaï', 'RESTO', -4.2445, 15.2898, 'valide', False),
            ('Couture Chez Divine', 'Divine Mbani', 'Moungali Nord', 'COIFF', -4.2587, 15.2567, 'valide', False),
            ('Boutique Frères Okemba', 'Jules Okemba', 'Ouenzé', 'BOUT', -4.2518, 15.2834, 'en_attente', True),
            ('Kiosque Presse Avenue', 'Sonia Mpaka', 'Centre Poto-Poto', 'BOUT', -4.2641, 15.2425, 'en_attente', False),
            ('Atelier Mécanique Rapide', 'Brice Kiala', 'Diata', 'QUINC', -4.2761, 15.2775, 'en_attente', False),
            ('Dépot Boissons du Coin', 'Henri Ngoma', 'Talangaï', 'BOUT', -4.2452, 15.2905, 'rejete', False),
        ]

        agent = User(username='agent.terrain', nom='Serge Mfouka',
                     role='agent_terrain', actif=True,
                     password_hash=generate_password_hash('demo123'))
        financier = User(username='agent.financier', nom='Clarisse Bounda',
                         role='agent_financier', actif=True,
                         password_hash=generate_password_hash('demo123'))
        conseiller = User(username='conseiller', nom='M. le Conseiller Municipal',
                          role='conseiller_municipal', actif=True,
                          password_hash=generate_password_hash('demo123'))
        db.session.add_all([agent, financier, conseiller])
        db.session.flush()

        boutiques = []
        for i, (nom, prop, qnom, tcode, lat, lng, statut, au_marche) in enumerate(contribuables, 1):
            q = quartiers[qnom]
            b = Boutique(
                code_unique=f'POI-{i:04d}', nom=nom, proprietaire=prop,
                telephone=f'06{random.randint(1000000, 9999999)}',
                adresse=f'{qnom}, {q.commune.nom}, Brazzaville',
                categorie='contribuable', feature_type='point',
                latitude=lat, longitude=lng,
                pays_id=congo.id, quartier_village_id=q.id,
                marche_id=marches[0].id if au_marche else None,
                marche_nom='Marché Total' if au_marche else None,
                type_commerce_id=types[tcode].id,
                nature_poi='autre',
                statut_validation=statut,
                collector_id=agent.id if statut != 'valide' or random.random() < 0.6 else None,
                submitted_at=datetime.utcnow() - timedelta(days=random.randint(1, 10))
                             if statut in ('en_attente', 'rejete') else None,
                validated_at=datetime.utcnow() - timedelta(days=random.randint(1, 15)) if statut == 'valide' else None,
                date_creation=datetime.utcnow() - timedelta(days=random.randint(60, 300)),
            )
            db.session.add(b)
            db.session.flush()

            # Taxes : fiscale + municipale pour tous, taxe de marché si au marché
            for tcode in (['TAXE_FISCALE', 'TAXE_MUNICIPALE'] + (['TAXE_MARCHE'] if au_marche else [])):
                db.session.add(BoutiqueTaxe(boutique_id=b.id, taxe_id=taxes[tcode].id,
                                            date_application=b.date_creation))
            boutiques.append(b)

        # ---------- Paiements ----------
        now = datetime.utcnow()
        txn = 0
        methodes = ['USSD', 'MTN_MONEY', 'AIRTEL_MONEY', 'GUICHET']

        def pay(b, taxe, mois, annee, montant, statut='confirme', jour=None):
            nonlocal txn
            txn += 1
            p = Paiement(
                boutique_id=b.id, institut_id=taxe.institut_id, taxe_id=taxe.id,
                montant=montant, mois=mois, annee=annee,
                date_paiement=datetime(annee, mois, jour or random.randint(1, 25),
                                       random.randint(8, 17), random.randint(0, 59)),
                methode=random.choice(methodes),
                numero_transaction=f'TXN-{annee}-{txn:06d}',
                reference_transaction=f'REF-{b.code_unique}-{annee}{mois:02d}-{txn}',
                numero_telephone=b.telephone,
                statut=statut,
            )
            db.session.add(p)
            return p

        # Mois couverts : juin → septembre 2026
        mois_liste = [(6, 2026), (7, 2026), (8, 2026), (9, 2026)]
        taxe_f, taxe_m, taxe_mk = taxes['TAXE_FISCALE'], taxes['TAXE_MUNICIPALE'], taxes['TAXE_MARCHE']

        for idx, b in enumerate(boutiques):
            bts = [bt for bt in b.taxes if bt.active]
            for (m, a) in mois_liste:
                for bt in bts:
                    montant = bt.montant_personnalise or bt.taxe.montant_attendu
                    if m == 9:  # septembre = mois courant : varier les situations
                        if idx % 5 == 4:
                            continue  # impayé
                        if idx % 5 == 3:
                            if bt.taxe_id == taxe_f.id:
                                pay(b, bt.taxe, m, a, montant / 2)  # partiel
                            continue
                        pay(b, bt.taxe, m, a, montant)
                    else:
                        pay(b, bt.taxe, m, a, montant)

        # Quelques paiements en attente de confirmation
        for b in boutiques[:3]:
            pay(b, taxe_m, 9, 2026, taxe_m.montant_attendu, statut='en_attente')

        # ---------- Infrastructures ----------
        infras = [
            ('Pylône MTN Poto-Poto', 'pylon', 'point',
             {'type': 'Point', 'coordinates': [15.2480, -4.2600]},
             {'operateur': 'MTN', 'hauteur_m': 45, 'technologie': '4G'}),
            ('Pylône Airtel Bacongo', 'pylon', 'point',
             {'type': 'Point', 'coordinates': [15.2740, -4.2730]},
             {'operateur': 'Airtel', 'hauteur_m': 38, 'technologie': '4G'}),
            ('Pipeline eau Moungali', 'pipeline', 'pipeline',
             {'type': 'LineString', 'coordinates': [[15.280, -4.252], [15.285, -4.256], [15.290, -4.260]]},
             {'diametre_mm': 300, 'gestionnaire': 'SNDE'}),
            ('Parcelle communale Ouenzé', 'parcel', 'parcel',
             {'type': 'Polygon', 'coordinates': [[[15.279, -4.249], [15.283, -4.249],
              [15.283, -4.253], [15.279, -4.253], [15.279, -4.249]]]},
             {'usage': 'Réserve communale'}),
            ('Périmètre Marché Total', 'perimeter', 'perimeter',
             {'type': 'Polygon', 'coordinates': [[[15.269, -4.270], [15.272, -4.270],
              [15.272, -4.272], [15.269, -4.272], [15.269, -4.270]]]},
             {'surface_approx': '1.2 ha'}),
        ]
        for i, (nom, ftype, fshape, geom, props) in enumerate(infras, 1):
            b = Boutique(
                code_unique=f'GEO-{i:04d}', nom=nom,
                categorie='infrastructure', feature_type=ftype,
                geometry=json.dumps(geom), properties=json.dumps(props),
                description=f'Infrastructure — {nom}',
                pays_id=congo.id, nature_poi='autre',
                statut_validation='valide',
                date_creation=datetime.utcnow() - timedelta(days=random.randint(30, 200)),
            )
            b.sync_coords_from_geometry()
            db.session.add(b)

        # ---------- Commerçant ----------
        boutique_marie = boutiques[0]
        comm = Commercant(boutique_id=boutique_marie.id, telephone='061234567',
                          mot_de_passe_hash=generate_password_hash('demo123'),
                          must_change_password=False, actif=True)
        db.session.add(comm)

        # ---------- Journal des collectes ----------
        for i, b in enumerate(random.sample(boutiques, 8)):
            q = b.quartier_village
            db.session.add(CollecteTerrain(
                date_heure=datetime.utcnow() - timedelta(days=random.randint(0, 14),
                                                         hours=random.randint(0, 8)),
                secteur=f'{q.nom}, {q.commune.nom}' if q else 'Brazzaville',
                collecteur_id=agent.id, boutique_id=b.id))

        db.session.commit()

        # ---------- QR codes ----------
        for b in boutiques:
            try:
                path = generate_qr_code(b.id, b.code_unique)
                b.qr_code_path = os.path.basename(path)
            except Exception as e:
                print(f'QR {b.code_unique}: {e}')
        db.session.commit()

        print(f'Démo seedée : {len(boutiques)} contribuables, {len(infras)} infrastructures, '
              f'{Paiement.query.count()} paiements, {txn} transactions.')
        print('Comptes : admin/admin123 — agent.terrain/demo123 — '
              'agent.financier/demo123 — conseiller/demo123 — commerçant 061234567/demo123')


if __name__ == '__main__':
    main()
