# -*- coding: utf-8 -*-
"""
Enregistrement des clips vidéo de démonstration GeoTax (Playwright).
Chaque clip dure ~25 secondes et présente une fonctionnalité.

Prérequis :
    pip install playwright && playwright install chromium
    App lancée sur http://127.0.0.1:5001 avec la base démo :
        DATABASE_URL=sqlite:///demo.db FLASK_DEBUG=0 PORT=5001 python app.py
    Données : python demo/seed_demo.py

Usage :
    python demo/record_videos.py            # tous les clips
    python demo/record_videos.py 04_carte   # un seul clip
"""
import os
import sys
import shutil
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = 'http://127.0.0.1:5001'
OUT_DIR = os.path.join(BASE_DIR, 'videos')
RAW_DIR = os.path.join(OUT_DIR, '_raw')
VIEWPORT = {'width': 1366, 'height': 768}

ADMIN_USER = 'admin'
ADMIN_PASS = 'admin123'


def wait(page, ms):
    page.wait_for_timeout(ms)


def smooth_scroll(page, total_ms=12000, step=140, pause=260):
    """Défilement doux vers le bas pendant ~total_ms."""
    elapsed = 0
    while elapsed < total_ms:
        page.mouse.wheel(0, step)
        page.wait_for_timeout(pause)
        elapsed += pause


def scroll_to_bottom_then_top(page, down_ms=12000, up_ms=0):
    smooth_scroll(page, down_ms)
    if up_ms:
        page.evaluate("window.scrollTo({top:0, behavior:'smooth'})")
        page.wait_for_timeout(up_ms)


def login(page, username=ADMIN_USER, password=ADMIN_PASS):
    page.goto(f'{BASE}/login')
    page.fill('#username', username)
    page.wait_for_timeout(600)
    page.fill('#password', password)
    page.wait_for_timeout(600)
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(1200)


def try_click(page, selector, timeout=2500):
    try:
        el = page.locator(selector).first
        el.click(timeout=timeout)
        return True
    except Exception:
        return False


def shot(page, ms=1500):
    page.wait_for_timeout(ms)


# ============================ CLIPS ============================

def clip_01_landing(page):
    page.goto(BASE)
    shot(page, 4000)                                   # hero
    smooth_scroll(page, 16000, step=170, pause=280)    # traversée des sections
    shot(page, 3500)                                   # CTA final


def clip_02_dashboard(page):
    login(page)
    page.goto(f'{BASE}/dashboard')
    page.wait_for_load_state('networkidle')
    shot(page, 4500)                                   # KPIs
    smooth_scroll(page, 12000, step=150, pause=300)    # stats + graphes
    try_click(page, '#filterTaxe')
    shot(page, 3000)


def clip_03_pois(page):
    login(page)
    page.goto(f'{BASE}/pois')
    page.wait_for_load_state('networkidle')
    shot(page, 3500)
    # Recherche
    for sel in ['#searchInput', 'input[type=search]', 'input[placeholder*="cherch"]',
                'input[placeholder*="recherch"]', '#filterCommerce']:
        try:
            page.fill(sel, 'Marie', timeout=1500)
            shot(page, 2200)
            page.fill(sel, '', timeout=1000)
            break
        except Exception:
            continue
    smooth_scroll(page, 7000, step=160, pause=300)
    # Ouvrir la fiche du premier POI si possible
    try_click(page, '#boutiquesTableBody tr', 2500)
    shot(page, 4000)
    page.keyboard.press('Escape')
    shot(page, 2500)


def clip_04_carte(page):
    login(page)
    page.goto(f'{BASE}/carte')
    shot(page, 6000)                                   # chargement tuiles + marqueurs
    for _ in range(2):
        try_click(page, '.leaflet-control-zoom-in', 1500)
        shot(page, 1500)
    # Déplacement de la carte
    box = page.locator('#map').bounding_box()
    if box:
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] / 2 + 160,
                        box['y'] + box['height'] / 2 + 80, steps=12)
        page.mouse.up()
    shot(page, 2500)
    # Clic au centre (marqueur éventuel → popup)
    if box:
        page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    shot(page, 4000)
    try_click(page, '.leaflet-marker-icon', 2000)      # ouvrir un marqueur
    shot(page, 5000)


def clip_05_scan(page):
    login(page)
    page.goto(f'{BASE}/scan')
    shot(page, 3000)
    # Basculer sur la saisie manuelle si l'onglet existe
    for sel in ['text=/saisie manuelle/i', 'text=/manuel/i', '#tabManual', 'button:has-text("manuel")']:
        if try_click(page, sel, 1200):
            shot(page, 1000)
            break
    page.fill('#codeInput', 'POI-0001')
    shot(page, 1200)
    page.click('button:has-text("Vérifier")')
    shot(page, 7000)                                   # résultat "à jour"
    # Deuxième contrôle : contribuable impayé
    page.fill('#codeInput', 'POI-0004')
    shot(page, 800)
    page.click('button:has-text("Vérifier")')
    shot(page, 8000)                                   # résultat impayé


def clip_06_paiements(page):
    login(page)
    page.goto(f'{BASE}/paiements')
    page.wait_for_load_state('networkidle')
    shot(page, 3500)
    try:
        page.select_option('#filterStatut', 'confirme', timeout=2000)
        shot(page, 2500)
    except Exception:
        pass
    smooth_scroll(page, 9000, step=160, pause=300)
    # Ouvrir un reçu si le lien existe
    if try_click(page, 'a[href*="/receipt"], a:has-text("Reçu"), a:has-text("reçu")', 2500):
        shot(page, 6000)
        page.go_back()
        shot(page, 2500)


def clip_07_validation(page):
    login(page)
    page.goto(f'{BASE}/validation')
    page.wait_for_load_state('networkidle')
    shot(page, 4000)                                   # file d'attente
    smooth_scroll(page, 5000, step=150, pause=300)
    # Ouvrir une fiche en attente
    for sel in ['#validationTableBody tr', 'button:has-text("Valider")',
                'button:has-text("Examiner")', '.btn:has-text("Voir")']:
        if try_click(page, sel, 2500):
            shot(page, 4000)
            try_click(page, '#btnValidatePoi', 2000)
            shot(page, 4000)
            break
    page.keyboard.press('Escape')
    shot(page, 3000)


def clip_08_statistiques(page):
    login(page)
    page.goto(f'{BASE}/statistiques')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)                                   # KPIs contrib/infrastructure
    smooth_scroll(page, 16000, step=150, pause=300)    # tous les graphiques
    shot(page, 3000)


def clip_09_balances(page):
    login(page)
    page.goto(f'{BASE}/balances')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)
    smooth_scroll(page, 14000, step=150, pause=300)
    shot(page, 3500)


def clip_10_parametrage(page):
    login(page)
    page.goto(f'{BASE}/parametrage')
    page.wait_for_load_state('networkidle')
    shot(page, 4000)
    smooth_scroll(page, 16000, step=170, pause=300)    # pays, taxes, types…
    shot(page, 3000)


def clip_11_commercant(page):
    page.goto(f'{BASE}/commercant')
    shot(page, 2500)
    page.goto(f'{BASE}/commercant/connexion')
    shot(page, 1500)
    page.fill('#identifiant', '061234567')
    shot(page, 800)
    page.fill('#mot_de_passe', 'demo123')
    shot(page, 800)
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')
    shot(page, 4500)                                   # tableau de bord contribuable
    smooth_scroll(page, 11000, step=150, pause=300)    # relevé / paiements
    shot(page, 3000)


def clip_12_admin(page):
    login(page)
    page.goto(f'{BASE}/journal-collectes')
    page.wait_for_load_state('networkidle')
    shot(page, 5000)                                   # journal des collectes
    smooth_scroll(page, 5000, step=150, pause=300)
    page.goto(f'{BASE}/users')
    page.wait_for_load_state('networkidle')
    shot(page, 4500)                                   # gestion des utilisateurs
    smooth_scroll(page, 4000, step=150, pause=300)
    shot(page, 2500)


CLIPS = [
    ('01_landing', clip_01_landing),
    ('02_dashboard', clip_02_dashboard),
    ('03_pois', clip_03_pois),
    ('04_carte', clip_04_carte),
    ('05_scan', clip_05_scan),
    ('06_paiements', clip_06_paiements),
    ('07_validation', clip_07_validation),
    ('08_statistiques', clip_08_statistiques),
    ('09_balances', clip_09_balances),
    ('10_parametrage', clip_10_parametrage),
    ('11_commercant', clip_11_commercant),
    ('12_admin', clip_12_admin),
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
    # Nettoyage du dossier brut s'il est vide
    try:
        if os.path.isdir(RAW_DIR) and not os.listdir(RAW_DIR):
            os.rmdir(RAW_DIR)
    except OSError:
        pass
    print(f'\nTerminé — vidéos dans {OUT_DIR}')


if __name__ == '__main__':
    main()
