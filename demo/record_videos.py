# -*- coding: utf-8 -*-
"""
Enregistrement de clips vidéo GeoTax (~35 s) — un scénario complet par fonctionnalité.

Prérequis :
    pip install playwright && playwright install chromium
    Données démo : python demo/seed_demo.py
    App : DATABASE_URL=sqlite:///demo.db FLASK_DEBUG=0 PORT=5001 python app.py

Usage :
    python demo/record_videos.py            # tous les clips
    python demo/record_videos.py 05         # un clip par préfixe
"""
import os
import sys
import shutil
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = 'http://127.0.0.1:5001'
OUT_DIR = os.path.join(BASE_DIR, 'videos')
RAW_DIR = os.path.join(OUT_DIR, '_raw')
VIEWPORT = {'width': 1366, 'height': 768}

ADMIN = ('admin', 'admin123')
AGENT = ('agent.terrain', 'demo123')
CONSEILLER = ('conseiller', 'demo123')
COMMERCANT = ('069876543', 'demo123')


# ---------------- Helpers ----------------

def shot(page, ms):
    page.wait_for_timeout(ms)


def type_slow(page, selector, text, delay=70):
    loc = page.locator(selector).first
    loc.click()
    loc.press_sequentially(text, delay=delay)


def smooth_scroll(page, total_ms=12000, step=150, pause=300):
    elapsed = 0
    while elapsed < total_ms:
        page.mouse.wheel(0, step)
        page.wait_for_timeout(pause)
        elapsed += pause


def login(page, username, password):
    page.goto(f'{BASE}/login')
    page.fill('#username', username)
    shot(page, 500)
    page.fill('#password', password)
    shot(page, 500)
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    shot(page, 1000)


def try_click(page, selector, timeout=2500):
    try:
        page.locator(selector).first.click(timeout=timeout)
        return True
    except Exception:
        return False


def select_when_ready(page, selector, value=None, label=None, contains=None,
                      index=None, timeout=8000):
    """Sélectionne une option après chargement AJAX de la liste."""
    page.wait_for_function(
        "sel => document.querySelector(sel) && document.querySelector(sel).options.length > 1",
        arg=selector, timeout=timeout)
    if contains:
        page.eval_on_selector(selector, """(sel, txt) => {
            for (const o of sel.options) {
                if (o.textContent.toLowerCase().includes(txt.toLowerCase())) {
                    sel.value = o.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return;
                }
            }
        }""", contains)
    elif label:
        page.select_option(selector, label=label)
    elif index is not None:
        page.select_option(selector, index=index)
    else:
        page.select_option(selector, value=value)
    shot(page, 700)


def click_first_visible(page, selectors, timeout=2500):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=timeout):
                el.click()
                return True
        except Exception:
            continue
    return False


def a_paiement_id():
    """ID d'un paiement confirmé de la base démo (pour les pages reçu)."""
    db_path = os.path.join(BASE_DIR, 'instance', 'demo.db')
    if not os.path.exists(db_path):
        db_path = os.path.join(BASE_DIR, 'demo.db')
    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT id FROM paiements WHERE statut='confirme' ORDER BY id LIMIT 1").fetchone()
    con.close()
    return row[0] if row else 1


def wizard_create_poi(page, categorie_btn_text, shape, form_filler):
    """Flux wizard : catégorie → forme → clic carte → marquer → continuer → formulaire."""
    page.click(f'button:has-text("{categorie_btn_text}")')
    shot(page, 1200)
    page.click(f'.poi-shape-card[data-shape="{shape}"]')
    page.wait_for_url('**/carte**', timeout=10000)
    page.wait_for_load_state('networkidle')
    shot(page, 2500)                                    # carte chargée + panneau position
    focus_map(page)
    # Position de départ : clic carte si possible, sinon saisie directe des GPS
    box = page.locator('#map').bounding_box()
    if box:
        page.mouse.click(box['x'] + box['width'] * 0.6, box['y'] + box['height'] * 0.55)
        shot(page, 1200)
    try:
        lat_val = page.input_value('#poiStartLat')
    except Exception:
        lat_val = ''
    if not lat_val:
        type_slow(page, '#poiStartLat', '-4.2638', delay=60)
        type_slow(page, '#poiStartLng', '15.2455', delay=60)
    shot(page, 800)
    page.click('button:has-text("Marquer le départ")')
    shot(page, 2000)                                    # zoom sur le point
    page.click('button:has-text("Continuer")')
    page.wait_for_url('**/pois**', timeout=10000)
    page.wait_for_load_state('networkidle')
    shot(page, 2000)                                    # formulaire caractéristiques ouvert
    form_filler(page)


def fill_poi_form(page, nom, proprietaire, telephone, type_label=None,
                  quartier_label=None, adresse=None, taxes_count=2):
    """Remplit le formulaire caractéristiques du wizard POI."""
    type_slow(page, '#nom', nom)
    shot(page, 400)
    if type_label:
        select_when_ready(page, '#type_commerce_id', contains=type_label)
    type_slow(page, '#proprietaire', proprietaire)
    type_slow(page, '#telephone', telephone)
    shot(page, 400)
    # Onglet géolocalisation
    page.click('#tabBtnGeoloc')
    shot(page, 800)
    select_when_ready(page, '#pays_id', contains='Congo')
    select_when_ready(page, '#departement_id', contains='Brazzaville')
    select_when_ready(page, '#commune_id', contains='Poto-Poto')
    if quartier_label:
        select_when_ready(page, '#quartier_village_id', contains=quartier_label)
    if adresse:
        type_slow(page, '#adresse', adresse)
    shot(page, 600)
    # Retour onglet administratif + taxes
    page.click('#tabBtnAdmin')
    shot(page, 600)
    if taxes_count:
        try:
            boxes = page.locator('#taxes-list input[type=checkbox]')
            for i in range(min(taxes_count, boxes.count())):
                boxes.nth(i).check()
                shot(page, 500)
        except Exception:
            pass


# ============================ CLIPS ============================

def clip_01_landing(page):
    """Landing page — présentation du produit."""
    page.goto(BASE)
    shot(page, 4500)
    smooth_scroll(page, 18000, step=170, pause=290)
    shot(page, 4000)


def clip_02_creation_poi_terrain(page):
    """Agent terrain : création complète d'un contribuable (wizard carte → formulaire → soumission)."""
    login(page, *AGENT)
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    shot(page, 2500)

    def fill(p):
        fill_poi_form(
            p, 'Boutique Horizon Plus', 'Arsène Makita', '065511223',
            type_label='Boutique',
            quartier_label='Centre Poto-Poto',
            adresse='Av. de la Paix, face à la pharmacie',
            taxes_count=2)

    wizard_create_poi(page, 'Ajouter un contribuable', 'point', fill)
    shot(page, 800)
    # Enregistrer le POI (chez un agent → statut « en_attente », validé ensuite)
    click_first_visible(page, ['#submitBtn', 'button:has-text("Enregistrer le POI")',
                               'button:has-text("Ajouter le POI")'])
    shot(page, 4500)                                    # toast de confirmation / retour liste


def clip_03_validation(page):
    """Conseiller : file de validation — examiner une collecte et la valider."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/validation')
    page.wait_for_load_state('networkidle')
    shot(page, 4000)
    try_click(page, 'button:has-text("Examiner")', 3000)
    shot(page, 4000)                                    # modal détail
    try:
        page.fill('#validationComment', 'Collecte conforme — fiche complète.', timeout=2500)
    except Exception:
        pass
    shot(page, 1500)
    try_click(page, '#btnValidatePoi', 3000)
    shot(page, 4500)                                    # retour file d'attente


def clip_04_pois_releve(page):
    """Liste contribuables → recherche → relevé des paiements → reçu."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    shot(page, 3000)
    type_slow(page, '#searchCommerce', 'Marie')
    shot(page, 2200)
    # Menu d'actions de la ligne → Voir paiements
    try:
        sel = page.locator('#boutiquesTableBody .poi-action-select').first
        sel.select_option('paiements', timeout=3000)
        shot(page, 4000)                                # relevé ouvert
        try_click(page, 'button[data-filter="recouvre"]', 2000)
        shot(page, 3000)
        try_click(page, 'button[data-filter="non_recouvre"]', 2000)
        shot(page, 2500)
        try_click(page, 'button[data-filter="all"]', 1500)
        shot(page, 1500)
        # Lien reçu (nouvel onglet) → on navigue dans le même onglet
        href = page.locator('a.releve-receipt-link').first.get_attribute('href', timeout=5000)
        if href:
            page.goto(f'{BASE}{href}')
            shot(page, 5500)                            # reçu imprimable
    except Exception as e:
        print('   relevé:', e)


def clip_05_carte(page):
    """Carte fiscale : marqueurs, popup, filtres, fonds de carte."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/carte')
    shot(page, 5500)                                    # tuiles + clusters
    focus_map(page)
    try_click(page, '.leaflet-marker-icon', 2500)       # popup d'un POI
    shot(page, 4000)
    try_click(page, '.leaflet-marker-icon >> nth=2', 2500)
    shot(page, 3500)
    # Filtres
    try:
        page.select_option('#mapFilterFiscal', index=1, timeout=2000)
        shot(page, 3000)
        page.select_option('#mapFilterFiscal', index=0, timeout=2000)
    except Exception:
        pass
    # Changement de fond de carte
    try_click(page, '#btnOsm', 1500) or try_click(page, '#btnSatellite', 1500)
    shot(page, 4000)


def clip_06_scan(page):
    """Contrôle terrain : saisie du code → statut à jour puis impayé."""
    login(page, *AGENT)
    page.goto(f'{BASE}/scan')
    shot(page, 3000)
    click_first_visible(page, ['text=/saisie manuelle/i', 'text=/manuel/i'], 1500)
    type_slow(page, '#codeInput', 'POI-0001', delay=90)
    shot(page, 800)
    page.click('button:has-text("Vérifier")')
    shot(page, 7000)                                    # À JOUR
    page.fill('#codeInput', '')
    type_slow(page, '#codeInput', 'POI-0004', delay=90)
    shot(page, 600)
    page.click('button:has-text("Vérifier")')
    shot(page, 8000)                                    # IMPAYÉ + proposition d'encaissement


def clip_07_encaissement(page):
    """Agent financier : encaisser une taxe due depuis la file des impayés."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/paiements')
    page.wait_for_load_state('networkidle')
    shot(page, 3500)                                    # onglet "en attente" (taxes dues)
    smooth_scroll(page, 4000, step=140, pause=280)
    try_click(page, 'button.btn-encaisser', 3000)       # 💵 Encaisser
    shot(page, 2500)                                    # modal récapitulatif
    try:
        page.select_option('#encaisserMethode', 'ESPECE', timeout=2000)
        page.fill('#encaisserReference', 'RECU-GUICHET-0042', timeout=2000)
    except Exception:
        pass
    shot(page, 1500)
    try_click(page, '#encaisserForm button[type=submit]', 2500)
    shot(page, 4500)                                    # confirmation + ligne retirée
    try_click(page, '#tabTous', 1500)
    shot(page, 3500)                                    # paiement visible dans l'historique


def clip_08_recu_verification(page):
    """Reçu de paiement + page publique de vérification."""
    login(page, *ADMIN)
    pid = a_paiement_id()
    page.goto(f'{BASE}/paiements/{pid}/receipt')
    shot(page, 6000)                                    # reçu imprimable
    page.goto(f'{BASE}/verifier-receipt/{pid}')
    shot(page, 8000)                                    # « Reçu vérifié » public
    # Vérification d'un reçu invalide
    page.goto(f'{BASE}/verifier-receipt/999999')
    shot(page, 5000)


def clip_09_dashboard(page):
    """Tableau de bord : KPIs, filtres de période, synthèse."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/dashboard')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)                                    # KPIs mois courant
    # Élargir la période : juin → septembre
    try:
        page.select_option('#periodeMoisDebut', '6', timeout=2500)
        shot(page, 4000)                                # stats recalculées
    except Exception:
        pass
    smooth_scroll(page, 12000, step=150, pause=300)
    try:
        page.select_option('#filterInstitut', index=1, timeout=2000)
        shot(page, 3500)
    except Exception:
        pass


def clip_10_statistiques(page):
    """Statistiques territoriales : répartitions, validation, spatial."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/statistiques')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)
    smooth_scroll(page, 19000, step=150, pause=300)
    shot(page, 3500)


def clip_11_balances(page):
    """Balances : recettes par institut, par taxe, répartition."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/balances')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)
    try:
        page.select_option('#periodeMoisDebut', '6', timeout=2000)
        shot(page, 3500)
    except Exception:
        pass
    smooth_scroll(page, 14000, step=150, pause=300)
    shot(page, 3000)


def clip_12_commercant(page):
    """Espace contribuable : connexion → taxes à payer → paiement → historique."""
    page.goto(f'{BASE}/commercant')
    shot(page, 2500)
    page.goto(f'{BASE}/commercant/connexion')
    shot(page, 1200)
    type_slow(page, '#identifiant', COMMERCANT[0], delay=80)
    type_slow(page, '#mot_de_passe', COMMERCANT[1], delay=80)
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    shot(page, 4000)                                    # résumé du commerce
    try_click(page, '#tabBtnPayer', 2000)
    shot(page, 3500)                                    # taxes à payer
    try_click(page, '.taxe-a-payer-card button:has-text("Payer")', 3000)
    shot(page, 3000)                                    # modal instructions USSD/MM
    try_click(page, 'button.btn-simulation', 2500)      # 🧪 Simuler le paiement
    shot(page, 4500)
    try_click(page, '#tabBtnHistorique', 2000)
    shot(page, 4000)                                    # paiement dans l'historique


def clip_13_parametrage(page):
    """Paramétrage : navigation par onglets + création d'une taxe."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/parametrage')
    page.wait_for_load_state('networkidle')
    shot(page, 2500)
    for tab, label in [('departements', 'Départements'), ('communes', 'Communes'),
                       ('quartiers', 'Quartiers'), ('marches', 'Marchés'),
                       ('types-commerce', "Types"), ('instituts', 'Instituts')]:
        try_click(page, f'button:has-text("{label}")', 1500)
        shot(page, 1800)
    try_click(page, 'button:has-text("Taxes")', 1500)
    shot(page, 2000)
    try_click(page, 'button:has-text("Ajouter une Taxe")', 2000)
    shot(page, 1200)
    try:
        page.select_option('#taxe-institut-id', index=1, timeout=2500)
        type_slow(page, '#taxe-code', 'TAXE_SALUBRITE', delay=60)
        type_slow(page, '#taxe-nom', 'Taxe de salubrité', delay=60)
        page.fill('#taxe-montant', '1000')
        page.select_option('#taxe-periodicite', 'mensuel')
        page.fill('#taxe-description', 'Taxe mensuelle de salubrité publique')
        shot(page, 1000)
        page.click('#form-taxes button[type=submit]')
        shot(page, 3500)                                # taxe ajoutée à la liste
    except Exception as e:
        print('   taxes:', e)


def clip_14_users_journal(page):
    """Administration : création d'un utilisateur + journal des collectes."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/users')
    page.wait_for_load_state('networkidle')
    shot(page, 3000)
    try_click(page, 'button:has-text("Ajouter un utilisateur")', 2500)
    shot(page, 1500)
    try:
        type_slow(page, '#userUsername', 'agent.demo2', delay=60)
        type_slow(page, '#userNom', 'Agent Démo Deux', delay=60)
        page.select_option('#userRole', 'agent_terrain', timeout=2000)
        type_slow(page, '#userPassword', 'demo12345', delay=60)
        shot(page, 1000)
        page.click('#userForm button[type=submit]')
        shot(page, 3500)                                # utilisateur dans la liste
    except Exception as e:
        print('   users:', e)
    page.goto(f'{BASE}/journal-collectes')
    page.wait_for_load_state('networkidle')
    shot(page, 4500)                                    # journal des collectes
    smooth_scroll(page, 6000, step=150, pause=300)


def clip_15_infrastructure(page):
    """Référentiel : création d'une infrastructure (pylône) via le wizard."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    try_click(page, '#poiTabGeo', 2000)                 # onglet infrastructures
    shot(page, 2500)

    def fill(p):
        type_slow(p, '#nom', 'Pylône Démo Nord', delay=60)
        try:
            p.select_option('#pays_id', label='Congo', timeout=4000)
            shot(p, 600)
        except Exception:
            pass
        # Rayon d'influence propre au pylône
        try:
            p.fill('#poiRadius', '600', timeout=2000)
        except Exception:
            pass

    wizard_create_poi(page, 'Ajouter une infrastructure', 'pylon', fill)
    shot(page, 800)
    click_first_visible(page, ['#submitBtn', 'button:has-text("Ajouter")',
                               'button:has-text("Soumettre")'])
    shot(page, 4500)


def fill_tech_field(page, label_substr, value):
    """Remplit un champ technique du formulaire POI d'après son libellé."""
    grp = page.locator('.poi-admin-grid .form-group', has_text=label_substr).first
    try:
        radio = grp.locator('input[type=radio]')
        if radio.count():
            grp.locator(f'input[type=radio][value="{value}"]').check()
            shot(page, 500)
            return True
        sel = grp.locator('select')
        if sel.count():
            sel.select_option(label=value, timeout=3000)
            shot(page, 500)
            return True
        el = grp.locator('input, textarea').first
        el.click()
        el.press_sequentially(str(value), delay=60)
        shot(page, 400)
        return True
    except Exception as e:
        print(f'   champ "{label_substr}": {e}')
        return False


def focus_map(page):
    """Cale la carte dans le viewport : masque les éléments au-dessus de la
    carte (titre, recherche, légende, compteurs) pour qu'elle soit entièrement
    visible dans la vidéo."""
    page.evaluate("""() => {
        ['.page-header', '.map-search-bar', '.map-legend', '.map-info']
            .forEach(sel => {
                const el = document.querySelector(sel);
                if (el) el.style.display = 'none';
            });
        const mc = document.querySelector('.map-controls');
        if (mc) mc.scrollIntoView({block: 'start'});
    }""")
    shot(page, 800)


def click_map_at(page, lat, lng):
    """Clique la carte aux coordonnées géographiques données."""
    pt = page.evaluate(
        "([lat, lng]) => { const p = map.latLngToContainerPoint([lat, lng]);"
        " return {x: p.x, y: p.y}; }", [lat, lng])
    box = page.locator('#map').bounding_box()
    page.mouse.click(box['x'] + pt['x'], box['y'] + pt['y'])
    shot(page, 1500)


def open_feature_popup(page, code_unique, zoom=None):
    """Centre la carte sur un POI et ouvre son popup (marqueur ou forme)."""
    ok = page.evaluate("""([code, zoom]) => {
        let target = null;
        const visit = (l) => {
            if (target) return;
            if (l._popup && l._popup._content && String(l._popup._content).includes(code)) {
                target = l;
            }
            if (!target && l.getLayers) l.getLayers().forEach(visit);
        };
        map.eachLayer(visit);
        if (!target) return false;
        let ll = null;
        try { ll = target.getBounds ? target.getBounds().getCenter() : target.getLatLng(); }
        catch (e) {}
        if (!ll) return false;
        map.closePopup();
        map.flyTo(ll, zoom || Math.max(map.getZoom(), 13));
        target.openPopup(ll);
        return true;
    }""", [code_unique, zoom])
    if not ok:
        print(f'   popup {code_unique} introuvable sur la carte')
    shot(page, 3500)                                    # animation flyTo + popup
    return ok


def clip_v1_cycle_contribuable(page):
    """Cycle complet : création contribuable → liste → paiement mobile money → à jour."""
    # 1. Création par un admin
    login(page, *ADMIN)
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    shot(page, 2500)

    def fill(p):
        fill_poi_form(
            p, 'Boutique Nouvelle Aube', 'Cynthia Bissila', '067890123',
            type_label='Boutique', quartier_label='Centre Poto-Poto',
            adresse='Rue Matsoua', taxes_count=2)

    wizard_create_poi(page, 'Ajouter un contribuable', 'point', fill)
    shot(page, 800)
    click_first_visible(page, ['#submitBtn', 'button:has-text("Enregistrer le POI")'])
    shot(page, 4500)
    # Modale « accès contribuable » éventuelle → fermer
    try_click(page, '#commercantAccessModal button:has-text("Fermer")', 3000)
    shot(page, 1500)

    # 2. Liste des contribuables
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    shot(page, 3000)
    type_slow(page, '#searchCommerce', 'Lumière')
    shot(page, 2500)                                    # Boutique La Lumière — non à jour

    # 3. Le contribuable paie depuis son espace (mobile money simulé)
    page.goto(f'{BASE}/commercant/connexion')
    shot(page, 1200)
    page.fill('#identifiant', '065555444')
    page.fill('#mot_de_passe', 'demo123')
    shot(page, 600)
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    shot(page, 3500)                                    # résumé — situation non à jour
    try_click(page, '#tabBtnPayer', 2000)
    shot(page, 3000)                                    # taxes à payer
    # Paiement de la première taxe
    try_click(page, '.taxe-a-payer-card button:has-text("Payer")', 3000)
    shot(page, 2500)                                    # modal USSD / Mobile Money
    try_click(page, 'button.btn-simulation', 2500)      # 🧪 Simuler le paiement
    shot(page, 3500)
    try_click(page, '#paiementModal button:has-text("Annuler"), #paiementModal .modal-close', 2500)
    shot(page, 1500)
    # Paiement de la seconde taxe
    try_click(page, '.taxe-a-payer-card button:has-text("Payer")', 2500)
    shot(page, 2000)
    try_click(page, 'button.btn-simulation', 2500)
    shot(page, 3500)
    try_click(page, '#paiementModal button:has-text("Annuler"), #paiementModal .modal-close', 2500)
    shot(page, 1200)
    try_click(page, '#tabBtnHistorique', 2000)
    shot(page, 4000)                                    # historique des paiements

    # 4. Compte mis à jour — vérification côté administration
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    type_slow(page, '#searchCommerce', 'Lumière')
    shot(page, 3500)                                    # statut « à jour »


def clip_v2_ecole_parcelle(page):
    """Création d'une infrastructure École (parcelle tracée + caractéristiques)."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    try_click(page, '#poiTabGeo', 2000)
    shot(page, 2200)
    page.click('button:has-text("Ajouter une infrastructure")')
    shot(page, 1200)
    page.click('.poi-shape-card[data-shape="parcel"]')
    page.wait_for_url('**/carte**', timeout=10000)
    page.wait_for_load_state('networkidle')
    shot(page, 2500)
    focus_map(page)
    # Point de départ du tracé (quartier Ouenzé)
    type_slow(page, '#poiStartLat', '-4.2535', delay=60)
    type_slow(page, '#poiStartLng', '15.2865', delay=60)
    page.click('button:has-text("Marquer le départ")')
    shot(page, 2200)
    # Tracé du polygone : clic carte puis sommets saisis en GPS, puis fermeture
    box = page.locator('#map').bounding_box()
    page.mouse.click(box['x'] + box['width'] * 0.30, box['y'] + box['height'] * 0.65)
    shot(page, 1500)
    type_slow(page, '#poiTraceLat', '-4.2545', delay=50)
    type_slow(page, '#poiTraceLng', '15.2890', delay=50)
    page.click('button:has-text("Sommet intermédiaire")')
    shot(page, 1200)
    type_slow(page, '#poiTraceLat', '-4.2552', delay=50)
    type_slow(page, '#poiTraceLng', '15.2870', delay=50)
    page.click('button:has-text("Sommet intermédiaire")')
    shot(page, 1200)
    page.click('#poiTraceFinishBtn')
    page.wait_for_url('**/pois**', timeout=15000)
    page.wait_for_load_state('networkidle')
    shot(page, 2000)                                    # formulaire caractéristiques
    type_slow(page, '#nom', 'École Primaire Sainte-Famille', delay=55)
    select_when_ready(page, '#type_commerce_id', contains='École')
    shot(page, 1000)
    # Onglet géolocalisation : rattacher au pays
    page.click('#tabBtnGeoloc')
    shot(page, 700)
    try:
        select_when_ready(page, '#pays_id', contains='Congo', timeout=5000)
    except Exception:
        pass
    # Onglet technique : caractéristiques de l'école
    page.click('#tabBtnTechnique')
    shot(page, 1500)
    fill_tech_field(page, "Nombre d'élèves", '285')
    fill_tech_field(page, 'Nombre de classes', '9')
    fill_tech_field(page, 'Nombre de filles', '148')
    fill_tech_field(page, 'Nombre de garçons', '137')
    fill_tech_field(page, 'Superficie de la parcelle', '1.8')
    fill_tech_field(page, 'École agréée', 'Oui')
    fill_tech_field(page, "Numéro d'agrément", 'AGR-2022-0107')
    shot(page, 1000)
    click_first_visible(page, ['#submitBtn', 'button:has-text("Ajouter")'])
    shot(page, 4500)


def clip_v3_carte_pois(page):
    """Carte : école, contribuable, vue hybride, pylône + rayon, pipeline, forêt protégée."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/carte')
    shot(page, 5500)
    focus_map(page)
    try_click(page, '#btnCluster', 1500)                # désactiver le regroupement
    shot(page, 1500)
    # École parcelle → popup avec caractéristiques
    open_feature_popup(page, 'GEO-E001', zoom=15)       # École Primaire Moungali II
    shot(page, 3000)
    # Contribuable → popup avec statut fiscal
    open_feature_popup(page, 'POI-0001', zoom=15)       # Boutique Chez Marie
    shot(page, 3000)
    # Vue hybride
    try_click(page, '#btnHybrid', 1500)
    shot(page, 3500)
    # Pylône → popup avec rayon d'influence visible
    open_feature_popup(page, 'GEO-0001', zoom=14)       # Pylône MTN Poto-Poto
    shot(page, 3000)
    # Pipeline (canalisation d'eau) → popup longueur/diamètre
    open_feature_popup(page, 'GEO-0003', zoom=14)       # Pipeline eau Moungali
    shot(page, 3000)
    # Forêt protégée au nord (Cuvette-Ouest) : survol puis popup
    open_feature_popup(page, 'GEO-F001', zoom=8)
    shot(page, 4000)


def clip_v4_stats_ecoles(page):
    """Statistiques : écoles — effectifs, répartition, total de filles."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/statistiques')
    page.wait_for_load_state('networkidle')
    shot(page, 4500)
    # Graphiques de répartition (type × arrondissement)
    smooth_scroll(page, 9000, step=170, pause=320)
    # Section analyse technique → bloc « École »
    try:
        page.locator('#theme-analyse-technique').scroll_into_view_if_needed(timeout=3000)
        shot(page, 2500)
    except Exception:
        smooth_scroll(page, 6000, step=200, pause=300)
    try_click(page, '.stats-tech-type-block summary:has-text("École")', 3000)
    shot(page, 6000)                                    # détail : élèves, filles, garçons…
    smooth_scroll(page, 4000, step=120, pause=300)


def clip_v5_stats_agricoles(page):
    """Statistiques : espaces agricoles — superficies, cultures, exploitants."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/statistiques')
    page.wait_for_load_state('networkidle')
    shot(page, 3500)
    try:
        page.locator('#theme-analyse-technique').scroll_into_view_if_needed(timeout=3000)
        shot(page, 2500)
    except Exception:
        smooth_scroll(page, 8000, step=200, pause=300)
    try_click(page, '.stats-tech-type-block summary:has-text("agricole")', 3000)
    shot(page, 5000)                                    # superficies par espace
    # Vue carte des parcelles agricoles
    page.goto(f'{BASE}/carte')
    shot(page, 5000)
    focus_map(page)
    open_feature_popup(page, 'GEO-A002', zoom=14)       # Périmètre maraîcher de Talangaï
    shot(page, 3000)
    open_feature_popup(page, 'GEO-A001', zoom=14)       # Champ de manioc
    shot(page, 3500)


def clip_16_journal(page):
    """Journal des collectes : traçabilité terrain."""
    login(page, *ADMIN)
    page.goto(f'{BASE}/journal-collectes')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)
    try:
        page.select_option('#collecteurFilter', index=1, timeout=2000)
        shot(page, 3500)
    except Exception:
        pass
    smooth_scroll(page, 8000, step=150, pause=300)
    shot(page, 3000)


CLIPS = [
    ('01_landing', clip_01_landing),
    ('02_creation_poi_terrain', clip_02_creation_poi_terrain),
    ('03_validation', clip_03_validation),
    ('04_pois_releve', clip_04_pois_releve),
    ('05_carte', clip_05_carte),
    ('06_scan', clip_06_scan),
    ('07_encaissement', clip_07_encaissement),
    ('08_recu_verification', clip_08_recu_verification),
    ('09_dashboard', clip_09_dashboard),
    ('10_statistiques', clip_10_statistiques),
    ('11_balances', clip_11_balances),
    ('12_commercant', clip_12_commercant),
    ('13_parametrage', clip_13_parametrage),
    ('14_users_journal', clip_14_users_journal),
    ('15_infrastructure', clip_15_infrastructure),
    ('16_journal', clip_16_journal),
    # --- Scénarios détaillés (données démo enrichies) ---
    ('v1_cycle_contribuable', clip_v1_cycle_contribuable),
    ('v2_ecole_parcelle', clip_v2_ecole_parcelle),
    ('v3_carte_pois', clip_v3_carte_pois),
    ('v4_stats_ecoles', clip_v4_stats_ecoles),
    ('v5_stats_agricoles', clip_v5_stats_agricoles),
]


def record(browser, name, fn):
    os.makedirs(RAW_DIR, exist_ok=True)
    context = browser.new_context(
        viewport=VIEWPORT,
        record_video_dir=RAW_DIR,
        record_video_size=VIEWPORT,
        locale='fr-FR',
    )
    page = context.new_page()
    t0 = time.time()
    try:
        fn(page)
    except Exception as e:
        print(f'  ! {name}: erreur pendant le clip — {e}')
    duration = time.time() - t0
    video = page.video
    context.close()
    src = video.path()
    dst = os.path.join(OUT_DIR, f'{name}.webm')
    shutil.move(src, dst)
    # Nettoie les vidéos des pages secondaires éventuelles (popups)
    for f in os.listdir(RAW_DIR):
        try:
            os.remove(os.path.join(RAW_DIR, f))
        except OSError:
            pass
    print(f'  ✓ {name}.webm  ({duration:.0f}s de navigation)')


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for name, fn in CLIPS:
            if only and name != only and not name.startswith(only):
                continue
            print(f'● {name} …')
            record(browser, name, fn)
        browser.close()
    try:
        if os.path.isdir(RAW_DIR) and not os.listdir(RAW_DIR):
            os.rmdir(RAW_DIR)
    except OSError:
        pass
    print(f'\nTerminé — vidéos dans {OUT_DIR}')


if __name__ == '__main__':
    main()
