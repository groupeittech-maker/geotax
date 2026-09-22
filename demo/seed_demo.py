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
    SecteurActivite, TypeCommerce, ChampPoi, Institut, Taxe, Boutique, BoutiqueTaxe,
    Paiement, User, Commercant, CollecteTerrain,
)
from werkzeug.security import generate_password_hash  # noqa: E402

random.seed(42)


def main():
    with app.app_context():
        init_db()

        # ---------- Hiérarchie géographique (idempotent) ----------
        congo = Pays.query.filter_by(code='CG').first()
        if not congo:
            congo = Pays(code='CG', nom='Congo', code_iso='COG',
                         center_lat=-4.2634, center_lng=15.2429, default_zoom=12)
            db.session.add(congo)
            db.session.flush()

        bzv = Departement.query.filter_by(pays_id=congo.id, code='BZV').first()
        if not bzv:
            bzv = Departement(pays_id=congo.id, code='BZV', nom='Brazzaville')
            db.session.add(bzv)
            db.session.flush()

        communes = {}
        for code, nom in [('PTP', 'Poto-Poto'), ('BCG', 'Bacongo'), ('MGL', 'Moungali')]:
            c = Commune.query.filter_by(departement_id=bzv.id, code=code).first()
            if not c:
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
                code = f'{communes[cname].code}-Q{i}'
                q = QuartierVillage.query.filter_by(commune_id=communes[cname].id,
                                                    code=code).first()
                if not q:
                    q = QuartierVillage(commune_id=communes[cname].id,
                                      code=code, nom=qnom, type='quartier')
                    db.session.add(q)
                    db.session.flush()
                quartiers[qnom] = q

        marches = []
        for nom, q in [('Marché Total', quartiers['Marché Total']),
                       ('Marché Poto-Poto', quartiers['Centre Poto-Poto']),
                       ('Marché Moungali', quartiers['Ouenzé'])]:
            m = Marche.query.filter_by(nom=nom).first()
            if not m:
                m = Marche(quartier_village_id=q.id,
                           code=f'MCH-{nom.split()[-1].upper()[:5]}',
                           nom=nom, adresse=f'{nom}, Brazzaville')
                db.session.add(m)
                db.session.flush()
            marches.append(m)

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
            tc = TypeCommerce.query.filter_by(code=code).first()
            if not tc:
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
            ('Poissonnerie du Marché', 'Claver Mbemba', 'Ouenzé', 'BOUT', -4.2510, 15.2822, 'valide', True),
            ('Cybercafé Connexion+', 'Kevin Onguéné', 'Centre Poto-Poto', 'TELESHOP', -4.2655, 15.2455, 'valide', False),
            ('Pharmacie Saint-Joseph', 'Dr. Lydie Itoua', 'Moungali Nord', 'PHARM', -4.2593, 15.2578, 'valide', False),
            ('Maquis Chez Tantine', 'Bernadette Foumbou', 'Diata', 'RESTO', -4.2765, 15.2741, 'valide', False),
            ('Boutique Okemba Frères', 'Jules Okemba', 'Ouenzé', 'BOUT', -4.2518, 15.2834, 'en_attente', True),
            ('Kiosque Presse Avenue', 'Sonia Mpaka', 'Centre Poto-Poto', 'BOUT', -4.2641, 15.2425, 'en_attente', False),
            ('Atelier Mécanique Rapide', 'Brice Kiala', 'Diata', 'QUINC', -4.2761, 15.2775, 'en_attente', False),
            ('Pressing La Perle', 'Olga Massamba', 'Marché Total', 'COIFF', -4.2708, 15.2690, 'en_attente', True),
            ('Boutique Sainte-Anne', 'Paulette Ndinga', 'Talangaï', 'BOUT', -4.2460, 15.2910, 'en_attente', False),
            ('Dépot Boissons du Coin', 'Henri Ngoma', 'Talangaï', 'BOUT', -4.2452, 15.2905, 'rejete', False),
            ('Épicerie du Centre', 'Flore Okouma', 'Centre Poto-Poto', 'BOUT', -4.2635, 15.2445, 'valide', False),
            ('Boutique La Lumière', 'Thomas Iloki', 'Moungali Nord', 'BOUT', -4.2590, 15.2575, 'valide', False),
        ]

        def get_or_create_user(username, nom, role):
            u = User.query.filter_by(username=username).first()
            if not u:
                u = User(username=username, nom=nom, role=role, actif=True,
                         password_hash=generate_password_hash('demo123'))
                db.session.add(u)
                db.session.flush()
            return u

        agent = get_or_create_user('agent.terrain', 'Serge Mfouka', 'agent_terrain')
        financier = get_or_create_user('agent.financier', 'Clarisse Bounda', 'agent_financier')
        conseiller = get_or_create_user('conseiller', 'M. le Conseiller Municipal',
                                        'conseiller_municipal')

        boutiques = []
        for i, (nom, prop, qnom, tcode, lat, lng, statut, au_marche) in enumerate(contribuables, 1):
            existing = Boutique.query.filter_by(code_unique=f'POI-{i:04d}').first()
            if existing:
                boutiques.append(existing)
                continue
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
        txn = Paiement.query.count()
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

        # Mois couverts : juin → septembre 2026 (idempotent : on ignore les POI déjà payés)
        mois_liste = [(6, 2026), (7, 2026), (8, 2026), (9, 2026)]
        taxe_f, taxe_m, taxe_mk = taxes['TAXE_FISCALE'], taxes['TAXE_MUNICIPALE'], taxes['TAXE_MARCHE']

        for idx, b in enumerate(boutiques):
            if Paiement.query.filter_by(boutique_id=b.id).first():
                continue
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

        if not Paiement.query.filter_by(statut='en_attente').first():
            for b in boutiques[:3]:
                pay(b, taxe_m, 9, 2026, taxe_m.montant_attendu, statut='en_attente')
            p_annule = pay(boutiques[10], taxe_f, 8, 2026, taxe_f.montant_attendu, statut='annule')
            p_annule.notes = 'Paiement annulé — doublon saisi par erreur'

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
            if Boutique.query.filter_by(code_unique=f'GEO-{i:04d}').first():
                continue
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

        # ---------- Types métier avec champs personnalisés ----------
        def ensure_type(code, nom, secteur_code):
            tc = TypeCommerce.query.filter_by(code=code).first()
            if not tc:
                tc = TypeCommerce(code=code, nom=nom,
                                  secteur_id=secteur(secteur_code).id if secteur(secteur_code) else None)
                db.session.add(tc)
                db.session.flush()
            return tc

        def ensure_champ(tc, code, libelle, type_champ='str', placeholder=None, ordre=0):
            ch = ChampPoi.query.filter_by(type_commerce_id=tc.id, code=code).first()
            if not ch:
                ch = ChampPoi(type_commerce_id=tc.id, code=code, libelle=libelle,
                              type_champ=type_champ, placeholder=placeholder, ordre=ordre)
                db.session.add(ch)
            return ch

        ecole_type = ensure_type('ECOLE_INFRA', 'École', 'EDUCATION')
        for code, lib, typ, ph, o in [
            ('nb_eleves', "Nombre d'élèves", 'int', 'ex. 320', 1),
            ('nb_classes', 'Nombre de classes', 'int', 'ex. 8', 2),
            ('nb_filles', 'Nombre de filles', 'int', 'ex. 170', 3),
            ('nb_garcons', 'Nombre de garçons', 'int', 'ex. 150', 4),
            ('superficie_ha', 'Superficie de la parcelle (ha)', 'float', 'ex. 1.5', 5),
            ('agree', 'École agréée', 'radio', 'Oui, Non', 6),
            ('numero_agrement', "Numéro d'agrément", 'str', "ex. AGR-2015-0456", 7),
        ]:
            ensure_champ(ecole_type, code, lib, typ, ph, o)

        agri_type = ensure_type('AGRICOLE', 'Espace agricole', 'AUTRE')
        for code, lib, typ, ph, o in [
            ('superficie_ha', 'Superficie (ha)', 'float', 'ex. 12.5', 1),
            ('culture_principale', 'Culture principale', 'str', 'ex. Manioc, maïs…', 2),
            ('exploitant', 'Exploitant / coopérative', 'str', 'Nom du responsable', 3),
            ('irrigation', 'Irrigation', 'radio', 'Oui, Non', 4),
        ]:
            ensure_champ(agri_type, code, lib, typ, ph, o)

        foret_type = ensure_type('FORET', 'Espace protégé / Forêt', 'AUTRE')
        for code, lib, typ, ph, o in [
            ('superficie_ha', 'Superficie (ha)', 'float', 'ex. 2500', 1),
            ('statut_protection', 'Statut de protection', 'select', 'Classée, Protégée, Réserve', 2),
            ('gestionnaire', 'Gestionnaire', 'str', 'ex. Ministère des Eaux et Forêts', 3),
        ]:
            ensure_champ(foret_type, code, lib, typ, ph, o)
        db.session.flush()

        # ---------- Écoles (parcelles avec caractéristiques) ----------
        ecoles = [
            ('École Primaire Moungali II', 'Ouenzé', -4.2505, 15.2820,
             {'nb_eleves': 320, 'nb_classes': 8, 'nb_filles': 170, 'nb_garcons': 150,
              'superficie_ha': 1.5, 'agree': 'Oui', 'numero_agrement': 'AGR-2015-0456'}),
            ('École Saint-Exupéry', 'Centre Poto-Poto', -4.2642, 15.2450,
             {'nb_eleves': 540, 'nb_classes': 14, 'nb_filles': 260, 'nb_garcons': 280,
              'superficie_ha': 2.1, 'agree': 'Oui', 'numero_agrement': 'AGR-2009-0112'}),
            ('Collège de Diata', 'Diata', -4.2758, 15.2755,
             {'nb_eleves': 410, 'nb_classes': 12, 'nb_filles': 230, 'nb_garcons': 180,
              'superficie_ha': 1.8, 'agree': 'Oui', 'numero_agrement': 'AGR-2018-0301'}),
            ('École Talangaï Centre', 'Talangaï', -4.2458, 15.2900,
             {'nb_eleves': 215, 'nb_classes': 6, 'nb_filles': 120, 'nb_garcons': 95,
              'superficie_ha': 0.9, 'agree': 'Non', 'numero_agrement': ''}),
            ('École Les Lauriers', 'Marché Total', -4.2715, 15.2705,
             {'nb_eleves': 380, 'nb_classes': 10, 'nb_filles': 195, 'nb_garcons': 185,
              'superficie_ha': 1.2, 'agree': 'Oui', 'numero_agrement': 'AGR-2021-0078'}),
            ('Groupe Scolaire Moungali Nord', 'Moungali Nord', -4.2595, 15.2570,
             {'nb_eleves': 460, 'nb_classes': 12, 'nb_filles': 225, 'nb_garcons': 235,
              'superficie_ha': 2.4, 'agree': 'Oui', 'numero_agrement': 'AGR-2013-0220'}),
        ]

        def square(lng, lat, d=0.0018):
            return {'type': 'Polygon', 'coordinates': [[
                [lng - d, lat - d], [lng + d, lat - d],
                [lng + d, lat + d], [lng - d, lat + d], [lng - d, lat - d]]]}

        for i, (nom, qnom, lat, lng, donnees) in enumerate(ecoles, 1):
            code = f'GEO-E{i:03d}'
            if Boutique.query.filter_by(code_unique=code).first():
                continue
            q = quartiers[qnom]
            b = Boutique(
                code_unique=code, nom=nom, categorie='infrastructure',
                feature_type='parcel', geometry=json.dumps(square(lng, lat)),
                donnees_administratives=json.dumps(donnees),
                description=f'École — {donnees["nb_eleves"]} élèves, {donnees["nb_classes"]} classes',
                pays_id=congo.id, quartier_village_id=q.id,
                type_commerce_id=ecole_type.id, nature_poi='education',
                statut_validation='valide',
                date_creation=datetime.utcnow() - timedelta(days=random.randint(30, 180)))
            b.sync_coords_from_geometry()
            db.session.add(b)

        # ---------- Espaces agricoles ----------
        agri = [
            ('Champ de manioc — Ouenzé', 'Ouenzé', -4.235, 15.295,
             {'superficie_ha': 12.5, 'culture_principale': 'Manioc',
              'exploitant': 'Coopérative Mavioka', 'irrigation': 'Non'}),
            ('Périmètre maraîcher de Talangaï', 'Talangaï', -4.238, 15.305,
             {'superficie_ha': 8.2, 'culture_principale': 'Légumes',
              'exploitant': 'Association des maraîchers', 'irrigation': 'Oui'}),
            ('Plantation de bananes — Diata', 'Diata', -4.285, 15.268,
             {'superficie_ha': 5.6, 'culture_principale': 'Banane',
              'exploitant': 'Famille Nzamba', 'irrigation': 'Non'}),
            ('Parcelle agricole Moungali', 'Moungali Nord', -4.248, 15.265,
             {'superficie_ha': 15.0, 'culture_principale': 'Maïs',
              'exploitant': 'Coopérative Espérance', 'irrigation': 'Non'}),
            ('Champ collectif Bacongo Sud', 'Marché Total', -4.280, 15.258,
             {'superficie_ha': 6.8, 'culture_principale': 'Arachide',
              'exploitant': 'Groupement Femmes Actives', 'irrigation': 'Oui'}),
        ]
        for i, (nom, qnom, lat, lng, donnees) in enumerate(agri, 1):
            code = f'GEO-A{i:03d}'
            if Boutique.query.filter_by(code_unique=code).first():
                continue
            q = quartiers[qnom]
            b = Boutique(
                code_unique=code, nom=nom, categorie='infrastructure',
                feature_type='parcel', geometry=json.dumps(square(lng, lat, 0.003)),
                donnees_administratives=json.dumps(donnees),
                description=f"Espace agricole — {donnees['culture_principale']}, {donnees['superficie_ha']} ha",
                pays_id=congo.id, quartier_village_id=q.id,
                type_commerce_id=agri_type.id, nature_poi='autre',
                statut_validation='valide',
                date_creation=datetime.utcnow() - timedelta(days=random.randint(30, 180)))
            b.sync_coords_from_geometry()
            db.session.add(b)

        # ---------- Forêt protégée (Cuvette-Ouest, nord du pays) ----------
        if not Boutique.query.filter_by(code_unique='GEO-F001').first():
            foret_geom = {'type': 'Polygon', 'coordinates': [[
                [14.55, 0.75], [15.05, 0.75], [15.05, 1.10],
                [14.55, 1.10], [14.55, 0.75]]]}
            b = Boutique(
                code_unique='GEO-F001', nom='Forêt protégée de Cuvette-Ouest',
                categorie='infrastructure', feature_type='parcel',
                geometry=json.dumps(foret_geom),
                donnees_administratives=json.dumps({
                    'superficie_ha': 2750, 'statut_protection': 'Protégée',
                    'gestionnaire': 'Ministère des Eaux et Forêts'}),
                description='Zone forestière protégée — Département de la Cuvette-Ouest',
                pays_id=congo.id, type_commerce_id=foret_type.id, nature_poi='autre',
                statut_validation='valide',
                date_creation=datetime.utcnow() - timedelta(days=120))
            b.sync_coords_from_geometry()
            db.session.add(b)

        db.session.flush()

        # ---------- Commerçant ----------
        # Boutique La Lumière (idx 24 → impayée en septembre) — compte pour la démo paiement
        boutique_lumiere = boutiques[23]
        boutique_lumiere.telephone = '065555444'
        if not Commercant.query.filter_by(telephone='065555444').first():
            db.session.add(Commercant(boutique_id=boutique_lumiere.id, telephone='065555444',
                                      mot_de_passe_hash=generate_password_hash('demo123'),
                                      must_change_password=False, actif=True))
        # Salon Élégance (idx 4 → impayée en septembre) pour démonter le paiement
        boutique_salon = boutiques[3]
        boutique_salon.telephone = '069876543'
        if not Commercant.query.filter_by(telephone='069876543').first():
            db.session.add(Commercant(boutique_id=boutique_salon.id, telephone='069876543',
                                      mot_de_passe_hash=generate_password_hash('demo123'),
                                      must_change_password=False, actif=True))
        # Second compte commerçant (boutique à jour) pour variété
        boutique_marie = boutiques[0]
        boutique_marie.telephone = '061234567'
        if not Commercant.query.filter_by(telephone='061234567').first():
            db.session.add(Commercant(boutique_id=boutique_marie.id, telephone='061234567',
                                      mot_de_passe_hash=generate_password_hash('demo123'),
                                      must_change_password=False, actif=True))

        # ---------- Journal des collectes ----------
        if not CollecteTerrain.query.first():
            for i, b in enumerate(random.sample(boutiques, 12)):
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
