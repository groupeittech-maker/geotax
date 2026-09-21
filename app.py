from flask import Flask, render_template, request, jsonify, send_file, url_for, session, redirect, has_request_context
from functools import wraps
from models import (
    db,
    Institut,
    Taxe,
    Boutique,
    BoutiqueTaxe,
    Paiement,
    Configuration,
    Commercant,
    User,
    Pays,
    Departement,
    Commune,
    QuartierVillage,
    Marche,
    TypeCommerce,
    NaturePoi,
    ChampPoi,
    SecteurActivite,
    DEFAULT_NATURES_POI,
    DEFAULT_SECTEURS_ACTIVITE,
    POI_STATUTS_VALIDATION,
    CollecteTerrain,
    MapFeature,
)
from geo_metrics import (
    MAP_FEATURE_TYPES,
    parse_geometry,
    validate_geometry,
    validate_feature_properties,
    compute_metrics,
    geometry_bounds,
    bboxes_intersect,
    geometry_centroid,
)
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import os
import re
import requests
import base64
from datetime import datetime
import openpyxl
from io import BytesIO
from werkzeug.utils import secure_filename
import json
import unicodedata
import secrets
import string

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _env_bool(name, default=False):
    value = os.environ.get(name, '').strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('0', 'false', 'no', 'off'):
        return False
    return default


def _default_sqlite_uri():
    instance_dir = os.environ.get('INSTANCE_PATH', os.path.join(BASE_DIR, 'instance'))
    os.makedirs(instance_dir, exist_ok=True)
    db_path = os.path.join(instance_dir, 'database.db').replace('\\', '/')
    return f'sqlite:///{db_path}'


IS_PRODUCTION = _env_bool('FLASK_PRODUCTION') or os.environ.get('FLASK_ENV', '').strip().lower() == 'production'


def _normalize_database_url(url):
    url = url.strip()
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    # Driver psycopg3 (moderne) si disponible
    if url.startswith('postgresql://') and '+psycopg' not in url.split('://', 1)[0]:
        try:
            import psycopg  # noqa: F401
            url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        except ImportError:
            pass
    return url


def _resolve_database_uri():
    url = os.environ.get('DATABASE_URL', '').strip()
    if url:
        return _normalize_database_url(url)
    if IS_PRODUCTION:
        raise RuntimeError(
            'DATABASE_URL must be set in production (PostgreSQL). '
            'See .env.example and DEPLOY.md'
        )
    # Fallback dev sans DATABASE_URL — déconseillé ; préférez PostgreSQL local
    return _default_sqlite_uri()


DATABASE_URI = _resolve_database_uri()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
if DATABASE_URI.startswith('postgresql'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
app.config['UPLOAD_FOLDER'] = os.environ.get('QR_CODES_PATH', os.path.join(BASE_DIR, 'qr_codes'))
app.config['POI_UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads', 'poi')
app.config['GOOGLE_MAPS_API_KEY'] = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()

_secret_key = os.environ.get('SECRET_KEY', '').strip()
if IS_PRODUCTION:
    if not _secret_key or _secret_key == 'changez-cette-cle-secrete':
        raise RuntimeError('SECRET_KEY must be set to a strong value in production (see .env.example)')
    app.config['SECRET_KEY'] = _secret_key
    app.config['SESSION_COOKIE_SECURE'] = _env_bool('SESSION_COOKIE_SECURE', default=True)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
else:
    app.config['SECRET_KEY'] = _secret_key or 'paiement-fisc-congo-2024-secret-key'

# Initialiser la base de données
db.init_app(app)

from flask_migrate import Migrate
from logging_config import setup_logging

setup_logging(app)
migrate = Migrate(app, db)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['POI_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, 'static'), exist_ok=True)

# Permissions par rôle
ROLE_PERMISSIONS = {
    'agent_terrain': ['/pois', '/carte', '/scan'],
    'agent_financier': ['/', '/dashboard', '/paiements', '/balances'],
    'conseiller_municipal': ['/', '/dashboard', '/pois', '/paiements', '/carte', '/scan', '/balances', '/statistiques', '/commercant', '/parametrage', '/users', '/validation'],
    'admin': ['/', '/dashboard', '/pois', '/paiements', '/carte', '/scan', '/balances', '/statistiques', '/commercant', '/parametrage', '/users', '/journal-collectes', '/validation'],
}

NAV_ITEMS = [
    ('/dashboard', 'Tableau de bord'),
    ('/pois', 'POI'),
    ('/validation', 'Validation'),
    ('/paiements', 'Paiements'),
    ('/carte', 'Carte'),
    ('/scan', 'Scanner QR'),
    ('/balances', 'Balances'),
    ('/statistiques', 'Statistiques'),
    ('/parametrage', 'Paramétrage'),
    ('/commercant', 'Contribuable'),
    ('/users', 'Utilisateurs'),
    ('/journal-collectes', 'Journal'),
]

ROLE_LABELS = {
    'admin': 'Administrateur',
    'conseiller_municipal': 'Conseiller municipal',
    'agent_financier': 'Agent financier',
    'agent_terrain': 'Agent terrain',
}

# Types de champs administratifs POI (paramétrage → formulaire POI)
CHAMP_POI_TYPES = (
    'str', 'int', 'float', 'textarea',
    'checkbox', 'select', 'radio',
    'date', 'time', 'email', 'tel', 'url',
)


def get_nav_items_for_role(role):
    """Retourne les items de navigation pour un rôle"""
    allowed = set(ROLE_PERMISSIONS.get(role, []))
    return [(url, label) for url, label in NAV_ITEMS if url in allowed]


def get_home_url_for_role(role):
    """Page d'accueil selon le rôle (sans tableau de bord pour agent terrain)."""
    perms = ROLE_PERMISSIONS.get(role, [])
    if '/dashboard' in perms or '/' in perms:
        return url_for('dashboard_page')
    for url, _label in NAV_ITEMS:
        if url in perms:
            return url
    return url_for('login_page')


def is_path_allowed_for_role(role, path):
    """Vérifie si un chemin est autorisé pour le rôle."""
    if not path:
        return False
    allowed = ROLE_PERMISSIONS.get(role, [])
    if path in allowed:
        return True
    aliases = {'/boutiques': '/pois', '/commerces': '/pois'}
    alias = aliases.get(path)
    return alias in allowed if alias else False


def login_required(f):
    """Décorateur : connexion requise"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Connexion requise'}), 401
            return redirect(url_for('login_page', next=request.url))
        return f(*args, **kwargs)
    return decorated


def role_required(*allowed_roles):
    """Décorateur : rôle requis"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('user_id'):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Connexion requise'}), 401
                return redirect(url_for('login_page', next=request.url))
            user = User.query.get(session.get('user_id'))
            if not user or not user.actif:
                session.clear()
                return redirect(url_for('login_page'))
            if user.role not in allowed_roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Accès refusé'}), 403
                return render_template('error.html', error='Accès refusé'), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def route_access(path):
    """Vérifie si l'utilisateur connecté a accès à ce chemin"""
    role = session.get('user_role')
    if not role:
        return False
    allowed = ROLE_PERMISSIONS.get(role, [])
    if path in allowed:
        return True
    # Alias : anciennes URLs / permissions
    aliases = {'/boutiques': '/pois', '/commerces': '/pois'}
    return aliases.get(path) in allowed


def resolve_pays_id():
    """Pays actif : paramètre de requête prioritaire, sinon session utilisateur."""
    if not has_request_context():
        return None
    arg = request.args.get('pays_id')
    if arg is not None and str(arg).strip() != '':
        try:
            return int(arg)
        except (TypeError, ValueError):
            return None
    pays_id = session.get('pays_id')
    return int(pays_id) if pays_id else None


def _get_pays_gps_bbox(pays):
    """BBox approximative (min_lat, min_lng, max_lat, max_lng) pour filtrage GPS."""
    if not pays:
        return None
    code = (pays.code_iso or pays.code or '').upper()
    return PAYS_GPS_BBOX.get(code) or PAYS_GPS_BBOX.get((pays.code or '').upper())


def _boutique_admin_pays_id(boutique):
    """Pays via quartier → commune → département (source de vérité admin)."""
    qv = boutique.quartier_village
    if not qv or not qv.commune or not qv.commune.departement:
        return None
    return qv.commune.departement.pays_id


def _filter_boutiques_by_pays(query, pays_id):
    """Filtre strict : pays_id explicite ou rattachement administratif au pays."""
    if not pays_id:
        return query
    pid = int(pays_id)
    admin_filter = Boutique.quartier_village.has(
        QuartierVillage.commune.has(
            Commune.departement.has(Departement.pays_id == pid)
        )
    )
    direct_filter = Boutique.pays_id == pid
    return query.filter(db.or_(admin_filter, direct_filter))


def _get_pays_session_payload(pays_id=None):
    """Métadonnées du pays sélectionné pour l'API session."""
    pid = pays_id if pays_id is not None else resolve_pays_id()
    map_view = _pays_map_view(pid)
    if not pid:
        return {'pays_id': None, 'pays': None, 'map_view': map_view}
    pays = Pays.query.get(pid)
    if not pays or not pays.active:
        return {'pays_id': None, 'pays': None, 'map_view': _pays_map_view(None)}
    pays_dict = pays.to_dict()
    pays_dict['map_view'] = map_view
    return {'pays_id': pays.id, 'pays': pays_dict, 'map_view': map_view}


PAYS_MAP_DEFAULTS = {
    # République centrafricaine (Bangui)
    'CF': {'lat': 4.394, 'lng': 18.558, 'zoom': 6},
    'CAF': {'lat': 4.394, 'lng': 18.558, 'zoom': 6},
    'RCA': {'lat': 4.394, 'lng': 18.558, 'zoom': 6},
    # République du Congo (Brazzaville)
    'CG': {'lat': -4.2634, 'lng': 15.2429, 'zoom': 6},
    'COG': {'lat': -4.2634, 'lng': 15.2429, 'zoom': 6},
    # RDC (Kinshasa)
    'CD': {'lat': -4.325, 'lng': 15.322, 'zoom': 6},
    'COD': {'lat': -4.325, 'lng': 15.322, 'zoom': 6},
    'RDC': {'lat': -4.325, 'lng': 15.322, 'zoom': 6},
    'CM': {'lat': 4.05, 'lng': 9.7, 'zoom': 6},
    'CMR': {'lat': 4.05, 'lng': 9.7, 'zoom': 6},
    'FR': {'lat': 46.6, 'lng': 2.2, 'zoom': 6},
    'GA': {'lat': -0.7, 'lng': 11.6, 'zoom': 7},
}

# Zone approximative pour filtrer les POI GPS sans rattachement admin
PAYS_GPS_BBOX = {
    'CF': (2.0, 11.0, 11.5, 27.5),
    'CAF': (2.0, 11.0, 11.5, 27.5),
    'RCA': (2.0, 11.0, 11.5, 27.5),
    'CG': (-5.5, 11.0, -0.5, 18.5),
    'COG': (-5.5, 11.0, -0.5, 18.5),
    'CD': (-13.5, 12.0, 5.5, 31.5),
    'COD': (-13.5, 12.0, 5.5, 31.5),
    'RDC': (-13.5, 12.0, 5.5, 31.5),
}


PAYS_DEFAULT_MAP_VIEW = {'lat': 0.5, 'lng': 18.0, 'zoom': 4}


def _resolve_pays_map_default(pays):
    """Coordonnées carte par code ISO, code ou nom du pays."""
    if not pays:
        return None
    for code in filter(None, [(pays.code or '').upper(), (pays.code_iso or '').upper()]):
        if code in PAYS_MAP_DEFAULTS:
            return dict(PAYS_MAP_DEFAULTS[code])
    nom = (pays.nom or '').lower()
    if any(k in nom for k in ('centrafric', 'rca')) and 'congo' not in nom:
        return dict(PAYS_MAP_DEFAULTS['CF'])
    if any(k in nom for k in ('démocratique', 'democratique', 'rdc', 'kinshasa')):
        return dict(PAYS_MAP_DEFAULTS['CD'])
    if 'congo' in nom and 'centrafric' not in nom and 'democratique' not in nom:
        return dict(PAYS_MAP_DEFAULTS['CG'])
    return None


def _classify_pays_region(pays):
    """Retourne CG, CF, CD ou None selon le code/nom du pays."""
    if not pays:
        return None
    code = (pays.code or '').upper()
    code_iso = (pays.code_iso or '').upper()
    nom = (pays.nom or '').lower()
    if code in ('CG', 'COG') or code_iso in ('CG', 'COG'):
        return 'CG'
    if code in ('CF', 'CAF', 'RCA') or code_iso in ('CF', 'CAF'):
        return 'CF'
    if code in ('CD', 'COD', 'RDC') or code_iso in ('CD', 'COD'):
        return 'CD'
    if any(k in nom for k in ('centrafric', 'rca')) and 'congo' not in nom:
        return 'CF'
    if any(k in nom for k in ('démocratique', 'democratique', 'rdc')):
        return 'CD'
    if 'congo' in nom and 'centrafric' not in nom:
        return 'CG'
    return None


def _normalize_pays_metadata(pays):
    """Libellés et centre carte cohérents par pays (sans fusionner les pays)."""
    region = _classify_pays_region(pays)
    if region == 'CG':
        pays.nom = 'République du Congo'
        pays.code = 'CG'
        pays.code_iso = pays.code_iso or 'COG'
        defaults = PAYS_MAP_DEFAULTS['CG']
    elif region == 'CF':
        pays.nom = 'République centrafricaine'
        pays.code = 'CF'
        pays.code_iso = pays.code_iso or 'CAF'
        defaults = PAYS_MAP_DEFAULTS['CF']
    elif region == 'CD':
        defaults = PAYS_MAP_DEFAULTS['CD']
    else:
        defaults = _resolve_pays_map_default(pays)
    if defaults and (pays.center_lat is None or pays.center_lng is None):
        pays.center_lat = defaults['lat']
        pays.center_lng = defaults['lng']
        pays.default_zoom = pays.default_zoom or defaults['zoom']


def _count_pois_in_bbox(pays_id, bbox):
    """Nombre de POI actifs du pays (admin ou GPS) dans une bbox."""
    if not bbox:
        return 0
    min_lat, min_lng, max_lat, max_lng = bbox
    admin_q = Boutique.query.filter(
        Boutique.active.is_(True),
        Boutique.latitude.isnot(None),
        Boutique.longitude.isnot(None),
        Boutique.latitude >= min_lat,
        Boutique.latitude <= max_lat,
        Boutique.longitude >= min_lng,
        Boutique.longitude <= max_lng,
        Boutique.quartier_village.has(
            QuartierVillage.commune.has(
                Commune.departement.has(Departement.pays_id == int(pays_id))
            )
        ),
    )
    return admin_q.count()


def _infer_pays_region_from_data(pays):
    """Infère CG vs CF depuis la répartition GPS des POI rattachés au pays."""
    cg = _count_pois_in_bbox(pays.id, PAYS_GPS_BBOX.get('CG'))
    cf = _count_pois_in_bbox(pays.id, PAYS_GPS_BBOX.get('CF'))
    if cg > cf and cg > 0:
        return 'CG'
    if cf > cg and cf > 0:
        return 'CF'
    return _classify_pays_region(pays)


def _pois_in_gps_bbox(pays):
    """POI localisés par GPS dans la bbox du pays (sans lien administratif)."""
    bbox = _get_pays_gps_bbox(pays)
    if not bbox:
        return []
    min_lat, min_lng, max_lat, max_lng = bbox
    rows = Boutique.query.filter(
        Boutique.active.is_(True),
        Boutique.latitude.isnot(None),
        Boutique.longitude.isnot(None),
        Boutique.latitude >= min_lat,
        Boutique.latitude <= max_lat,
        Boutique.longitude >= min_lng,
        Boutique.longitude <= max_lng,
    ).all()
    return rows


def _map_view_from_coords(lats, lngs):
    if not lats or not lngs:
        return None
    min_lat, max_lat = min(lats), max(lats)
    min_lng, max_lng = min(lngs), max(lngs)
    if len(lats) == 1:
        return {'lat': lats[0], 'lng': lngs[0], 'zoom': 13}
    return {
        'lat': round((min_lat + max_lat) / 2, 6),
        'lng': round((min_lng + max_lng) / 2, 6),
        'zoom': 8,
        'bounds': [[min_lat, min_lng], [max_lat, max_lng]],
    }


def _pays_map_view(pays_id=None):
    """Vue carte recommandée : centroïde des POI du pays, coordonnées paramétrées ou défaut régional."""
    pays = Pays.query.get(int(pays_id)) if pays_id else None

    query = Boutique.query.filter(
        Boutique.active.is_(True),
        Boutique.latitude.isnot(None),
        Boutique.longitude.isnot(None),
    )
    if pays_id:
        query = _filter_boutiques_by_pays(query, pays_id)

    pois = query.all()
    if pays_id and not pois and pays:
        pois = _pois_in_gps_bbox(pays)

    lats = []
    lngs = []
    for poi in pois:
        try:
            lat = float(poi.latitude)
            lng = float(poi.longitude)
        except (TypeError, ValueError):
            continue
        if lat == 0 and lng == 0:
            continue
        lats.append(lat)
        lngs.append(lng)

    view = _map_view_from_coords(lats, lngs)
    if view:
        return view

    if pays:
        if pays.center_lat is not None and pays.center_lng is not None:
            return {
                'lat': float(pays.center_lat),
                'lng': float(pays.center_lng),
                'zoom': int(pays.default_zoom or 6),
            }
        resolved = _resolve_pays_map_default(pays)
        if resolved:
            return resolved

    active = Pays.query.filter_by(active=True).order_by(Pays.nom).all()
    if len(active) == 1:
        return _pays_map_view(active[0].id)

    return dict(PAYS_DEFAULT_MAP_VIEW)


def _resolve_boutique_pays_id(quartier_village_id=None, latitude=None, longitude=None, explicit_pays_id=None):
    """Détermine le pays d'un POI (admin > session > GPS sans ambiguïté)."""
    if quartier_village_id:
        qv = QuartierVillage.query.get(int(quartier_village_id))
        if qv and qv.commune and qv.commune.departement:
            return qv.commune.departement.pays_id
    if explicit_pays_id not in (None, '', 0, '0'):
        try:
            return int(explicit_pays_id)
        except (TypeError, ValueError):
            pass
    session_pid = resolve_pays_id()
    if session_pid:
        return session_pid
    if latitude is not None and longitude is not None:
        try:
            lat, lng = float(latitude), float(longitude)
        except (TypeError, ValueError):
            return None
        matches = []
        for pays in Pays.query.filter_by(active=True).all():
            bbox = _get_pays_gps_bbox(pays)
            if not bbox:
                continue
            min_lat, min_lng, max_lat, max_lng = bbox
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                matches.append(pays.id)
        if len(matches) == 1:
            return matches[0]
    return None


def _sync_boutique_pays_id(boutique, explicit_pays_id=None):
    """Met à jour boutiques.pays_id (admin > explicite > session > GPS)."""
    target = _resolve_boutique_pays_id(
        quartier_village_id=boutique.quartier_village_id,
        latitude=boutique.latitude,
        longitude=boutique.longitude,
        explicit_pays_id=explicit_pays_id,
    )
    if target:
        boutique.pays_id = target


def _reconcile_boutique_pays_ids():
    """Aligne boutiques.pays_id sur la hiérarchie admin ou le GPS (sans double comptage)."""
    updated = 0
    last_id = 0
    while True:
        rows = (
            Boutique.query.filter(
                Boutique.active.is_(True),
                Boutique.id > last_id,
            )
            .order_by(Boutique.id)
            .limit(300)
            .all()
        )
        if not rows:
            break
        batch = 0
        for boutique in rows:
            last_id = boutique.id
            admin_pid = _boutique_admin_pays_id(boutique)
            if admin_pid:
                target = admin_pid
            else:
                target = _resolve_boutique_pays_id(
                    latitude=boutique.latitude,
                    longitude=boutique.longitude,
                )
            if target and boutique.pays_id != target:
                boutique.pays_id = target
                batch += 1
        if batch:
            db.session.commit()
            updated += batch
    return updated


def _ensure_default_pays_session():
    """Sélectionne automatiquement le pays s'il n'y en a qu'un seul actif."""
    if session.get('pays_id'):
        return
    active = Pays.query.filter_by(active=True).order_by(Pays.nom).all()
    if len(active) == 1:
        session['pays_id'] = active[0].id


def require_access(*allowed_paths):
    """Décorateur : la page est autorisée si l'un des chemins est permis pour le rôle."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get('user_id'):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Connexion requise'}), 401
                return redirect(url_for('login_page', next=request.url))
            user = User.query.get(session.get('user_id'))
            if not user or not user.actif:
                session.clear()
                return redirect(url_for('login_page'))
            perms = ROLE_PERMISSIONS.get(user.role, [])
            if not any(p in perms for p in allowed_paths):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Accès refusé'}), 403
                return render_template('error.html', error='Accès refusé'), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def _normalize_nature_poi(val):
    return NaturePoi.normalize_code(val)


def get_effective_champs_objs(tc):
    """Champs techniques du type, avec repli sur la nature POI liée ou déduite."""
    if not tc:
        return []
    champs = tc.get_champs_actifs()
    if champs:
        return _dedupe_champ_objs(champs)
    if tc.nature_poi_ref and tc.nature_poi_ref.active:
        nat_champs = tc.nature_poi_ref.get_champs_actifs()
        if nat_champs:
            return _dedupe_champ_objs(nat_champs)
    nature_code = infer_nature_poi_from_type_commerce(tc)
    nature = NaturePoi.get_by_code(nature_code)
    if nature:
        return _dedupe_champ_objs(nature.get_champs_actifs())
    return []


def _dedupe_champ_objs(champs):
    """Un seul champ actif par code (ordre puis id)."""
    by_code = {}
    for c in champs:
        if not c or not c.active:
            continue
        code = (c.code or '').strip()
        if not code:
            continue
        prev = by_code.get(code)
        if not prev:
            by_code[code] = c
            continue
        prev_key = (prev.ordre or 0, prev.id or 0)
        cur_key = (c.ordre or 0, c.id or 0)
        if cur_key < prev_key:
            by_code[code] = c
    result = list(by_code.values())
    result.sort(key=lambda x: (x.ordre or 0, x.id or 0))
    return result


POI_CATEGORIES = ('contribuable', 'infrastructure')
POI_CATEGORY_CONTRIBUABLE = 'contribuable'
POI_CATEGORY_INFRASTRUCTURE = 'infrastructure'


def _normalize_poi_categorie(val):
    v = (val or POI_CATEGORY_CONTRIBUABLE).strip().lower()
    return v if v in POI_CATEGORIES else POI_CATEGORY_CONTRIBUABLE


def _normalize_poi_feature_type(val):
    ft = (val or 'point').strip().lower()
    if ft == 'point':
        return 'point'
    return ft if ft in MAP_FEATURE_TYPES else 'point'


def _apply_poi_geometry_fields(boutique, geometry, properties=None):
    """Valide la géométrie, calcule les métriques et synchronise lat/lng."""
    if not geometry:
        return
    ft = boutique.feature_type or 'point'
    props = properties if isinstance(properties, dict) else {}
    if ft != 'point':
        validate_geometry(geometry, ft)
        validate_feature_properties(ft, props)
        metrics = compute_metrics(geometry, ft, props)
        boutique.length_m = metrics.get('length_m')
        boutique.area_ha = metrics.get('area_ha')
        boutique.perimeter_m = metrics.get('perimeter_m')
        boutique.radius_m = metrics.get('radius_m')
    boutique.geometry = json.dumps(geometry)
    boutique.sync_coords_from_geometry()
    if boutique.id:
        try:
            from spatial_utils import sync_boutique_geom
            sync_boutique_geom(db.session, boutique)
        except Exception:
            pass


def migrate_unified_poi_schema():
    """Colonnes POI unifié sur boutiques + migration map_features."""
    from sqlalchemy import text
    from db_utils import add_column_if_missing, is_sqlite

    engine = db.engine
    if is_sqlite(engine):
        for col, ddl in [
            ('categorie', "VARCHAR(20) DEFAULT 'contribuable'"),
            ('feature_type', "VARCHAR(20) DEFAULT 'point'"),
            ('geometry', 'TEXT'),
            ('description', 'TEXT'),
            ('properties', 'TEXT'),
            ('length_m', 'FLOAT'),
            ('area_ha', 'FLOAT'),
            ('perimeter_m', 'FLOAT'),
            ('radius_m', 'FLOAT'),
            ('legacy_map_feature_id', 'INTEGER'),
        ]:
            add_column_if_missing(engine, db.session, 'boutiques', col, ddl)
        db.session.commit()

    db.session.execute(text(
        "UPDATE boutiques SET categorie = 'contribuable' WHERE categorie IS NULL OR categorie = ''"
    ))
    db.session.execute(text(
        "UPDATE boutiques SET feature_type = 'point' WHERE feature_type IS NULL OR feature_type = ''"
    ))
    db.session.commit()

    # Ne pas re-scanner toute la table map_features si déjà migré (évite blocage au démarrage).
    pending = (
        MapFeature.query.filter_by(active=True)
        .filter(
            ~Boutique.query.filter(
                Boutique.legacy_map_feature_id == MapFeature.id
            ).correlate(MapFeature).exists(),
            ~Boutique.query.filter(
                Boutique.code_unique == MapFeature.code_unique
            ).correlate(MapFeature).exists(),
        )
        .limit(1)
        .first()
    )
    if not pending:
        return 0

    migrated = 0
    for mf in MapFeature.query.filter_by(active=True).all():
        if Boutique.query.filter_by(code_unique=mf.code_unique).first():
            continue
        if Boutique.query.filter_by(legacy_map_feature_id=mf.id).first():
            continue
        props = dict(mf.get_properties_parsed())
        donnees = props.pop('donnees_administratives', None)
        don_json = None
        if donnees:
            don_json = json.dumps(donnees, ensure_ascii=False) if isinstance(donnees, dict) else donnees
        boutique = Boutique(
            code_unique=mf.code_unique,
            nom=mf.name,
            categorie=POI_CATEGORY_INFRASTRUCTURE,
            feature_type=mf.feature_type,
            geometry=mf.geometry,
            properties=json.dumps(props, ensure_ascii=False) if props else None,
            description=mf.description,
            type_commerce_id=mf.type_commerce_id,
            donnees_administratives=don_json,
            statut_validation=mf.statut_validation,
            collector_id=mf.collector_id,
            validated_by=mf.validated_by,
            validated_at=mf.validated_at,
            validation_comment=mf.validation_comment,
            submitted_at=mf.submitted_at,
            date_creation=mf.date_creation,
            length_m=mf.length_m,
            area_ha=mf.area_ha,
            perimeter_m=mf.perimeter_m,
            radius_m=mf.radius_m,
            legacy_map_feature_id=mf.id,
            active=True,
        )
        boutique.sync_coords_from_geometry()
        _sync_boutique_pays_id(boutique)
        db.session.add(boutique)
        migrated += 1
    if migrated:
        db.session.commit()
    return migrated


def _sync_geo_poi_coordinates():
    """Recalcule latitude/longitude depuis geometry pour les POI géométriques."""
    updated = 0
    last_id = 0
    while True:
        rows = (
            Boutique.query.filter(
                Boutique.active.is_(True),
                Boutique.geometry.isnot(None),
                Boutique.id > last_id,
                db.or_(
                    Boutique.latitude.is_(None),
                    Boutique.longitude.is_(None),
                ),
            )
            .order_by(Boutique.id)
            .limit(200)
            .all()
        )
        if not rows:
            break
        batch_updated = 0
        for boutique in rows:
            boutique.sync_coords_from_geometry()
            last_id = boutique.id
            if boutique.latitude is not None and boutique.longitude is not None:
                batch_updated += 1
        if batch_updated:
            db.session.commit()
            updated += batch_updated
    return updated


def _resolve_geo_poi(poi_id):
    """Retourne un POI (Boutique) pour l'API cartographie, avec repli legacy."""
    boutique = Boutique.query.get(poi_id)
    if boutique and boutique.active:
        return boutique
    boutique = Boutique.query.filter_by(legacy_map_feature_id=poi_id, active=True).first()
    if boutique:
        return boutique
    mf = MapFeature.query.get(poi_id)
    if mf and mf.active:
        return mf
    return None


def _query_geo_shape_pois():
    """POI avec géométrie avancée (toutes catégories)."""
    return Boutique.query.filter(
        Boutique.active.is_(True),
        Boutique.feature_type != 'point',
    )


def _boutique_to_legacy_map_dict(boutique):
    """Compatibilité API map-features / carte."""
    d = boutique.to_dict()
    meta = boutique.get_feature_type_meta()
    d['name'] = boutique.nom
    d['feature_type'] = boutique.feature_type or 'point'
    d['feature_type_label'] = meta.get('label', d['feature_type'])
    d['feature_type_icon'] = meta.get('icon', '📍')
    d['feature_type_color'] = meta.get('color', '#607d8b')
    d['source'] = 'poi'
    return d


def _poi_localisation_label(poi):
    """Localisation lisible (administrative ou GPS)."""
    if isinstance(poi, Boutique):
        if poi.quartier_village or poi.arrondissement or poi.adresse:
            admin = _boutique_localisation_label(poi)
            if admin:
                return admin
        parts = []
        if poi.description and str(poi.description).strip():
            parts.append(str(poi.description).strip())
        geom = poi.get_geometry_parsed()
        if geom:
            centroid = geometry_centroid(geom)
            if centroid:
                lat, lng = centroid
                parts.append(_format_coords_label(lat, lng))
        elif poi.latitude is not None and poi.longitude is not None:
            parts.append(_format_coords_label(poi.latitude, poi.longitude))
        if parts:
            return ' — '.join(parts)
        return '—'
    return _map_feature_localisation_label(poi)


def dedupe_champ_poi_duplicates():
    """Désactive les doublons actifs (même type + code), garde le plus ancien."""
    from sqlalchemy import func
    dupes = (
        db.session.query(
            ChampPoi.type_commerce_id,
            ChampPoi.code,
            func.min(ChampPoi.id).label('keep_id'),
        )
        .filter(ChampPoi.active.is_(True), ChampPoi.type_commerce_id.isnot(None))
        .group_by(ChampPoi.type_commerce_id, ChampPoi.code)
        .having(func.count(ChampPoi.id) > 1)
        .all()
    )
    if not dupes:
        return 0
    deactivated = 0
    for type_id, code, keep_id in dupes:
        rows = ChampPoi.query.filter_by(
            type_commerce_id=type_id, code=code, active=True
        ).filter(ChampPoi.id != keep_id).all()
        for row in rows:
            row.active = False
            deactivated += 1
    if deactivated:
        db.session.commit()
    return deactivated


def _enrich_type_commerce_dict(tc, data, include_champs=False):
    """Ajoute champs_effectifs au dict type d'activité."""
    if not include_champs:
        data['champs_effectifs_count'] = len(get_effective_champs_objs(tc))
        return data
    own = tc.get_champs_actifs()
    effective = get_effective_champs_objs(tc)
    data['champs'] = [c.to_dict() for c in own]
    data['champs_effectifs'] = [c.to_dict() for c in effective]
    data['champs_effectifs_count'] = len(effective)
    data['champs_source'] = 'type' if own else ('nature' if effective else 'none')
    return data


def _get_admin_fields_for_type(type_commerce_id):
    """Champs techniques d'un type d'activité (fallback nature legacy)."""
    if not type_commerce_id:
        return []
    tc = TypeCommerce.query.get(type_commerce_id)
    if not tc:
        return []
    return [(c.code, c.type_champ) for c in get_effective_champs_objs(tc)]


def _get_admin_fields_for_nature(nature_code):
    """Retourne [(code, type_champ), ...] pour une nature depuis la base."""
    nature = NaturePoi.get_by_code(nature_code)
    if not nature:
        nature = NaturePoi.get_by_code('autre')
    if not nature:
        return []
    return [(c.code, c.type_champ) for c in nature.get_champs_actifs()]


def infer_nature_poi_from_type_commerce(tc):
    """
    Déduit nature_poi depuis le type d'activité paramétrable (GeoTax).
    Priorité : nature liée au type → mots-clés paramétrés → autre.
    """
    if not tc:
        return _normalize_nature_poi(None)
    if tc.nature_poi_id and tc.nature_poi_ref and tc.nature_poi_ref.active:
        return tc.nature_poi_ref.code
    code = _fold_ascii_lower(tc.code).strip()
    nom = _fold_ascii_lower(tc.nom).strip()
    blob = f' {code} {nom} '
    for nature in NaturePoi.query.filter_by(active=True).order_by(NaturePoi.ordre).all():
        for kw in nature.get_mots_cles_list():
            if kw == code:
                return nature.code
            if f' {kw} ' in blob or blob.strip().startswith(kw) or blob.strip().endswith(kw):
                return nature.code
            if kw in blob:
                return nature.code
    return 'autre'


def normalize_donnees_administratives(nature_poi, raw, type_commerce_id=None):
    if type_commerce_id:
        fields = _get_admin_fields_for_type(type_commerce_id)
    else:
        nature_poi = _normalize_nature_poi(nature_poi)
        fields = _get_admin_fields_for_nature(nature_poi)
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, typ in fields:
        if key not in raw:
            continue
        v = _coerce_admin_field(raw.get(key), typ)
        if v is not None:
            out[key] = v
    return out


def seed_secteurs_activite_defaults():
    """Initialise les secteurs d'activité par défaut."""
    if SecteurActivite.query.first():
        return
    for item in DEFAULT_SECTEURS_ACTIVITE:
        db.session.add(SecteurActivite(
            code=item['code'],
            nom=item['nom'],
            icon=item.get('icon'),
            color=item.get('color', '#0d9668'),
            ordre=item.get('ordre', 0),
            active=True,
        ))
    db.session.commit()


def migrate_champs_to_types_commerce():
    """Copie les champs nature → type pour chaque type lié (migration GéoRéf)."""
    for tc in TypeCommerce.query.filter_by(active=True).all():
        if ChampPoi.query.filter_by(type_commerce_id=tc.id, active=True).first():
            continue
        source_champs = []
        if tc.nature_poi_id:
            source_champs = ChampPoi.query.filter_by(
                nature_poi_id=tc.nature_poi_id, active=True
            ).order_by(ChampPoi.ordre).all()
        if not source_champs:
            nature_code = infer_nature_poi_from_type_commerce(tc)
            nature = NaturePoi.get_by_code(nature_code)
            if nature:
                source_champs = ChampPoi.query.filter_by(
                    nature_poi_id=nature.id, active=True
                ).order_by(ChampPoi.ordre).all()
        for ch in source_champs:
            db.session.add(ChampPoi(
                type_commerce_id=tc.id,
                nature_poi_id=ch.nature_poi_id or tc.nature_poi_id,
                code=ch.code,
                libelle=ch.libelle,
                type_champ=ch.type_champ,
                placeholder=ch.placeholder,
                ordre=ch.ordre,
                pleine_largeur=ch.pleine_largeur,
                active=True,
            ))
    db.session.commit()


def _default_statut_validation_for_create():
    """Agents terrain → brouillon ; autres rôles → validé directement."""
    user_id = session.get('user_id')
    if not user_id:
        return 'valide'
    user = User.query.get(user_id)
    if user and user.role == 'agent_terrain':
        return 'brouillon'
    return 'valide'


def _apply_poi_validation_on_create(boutique, draft=False):
    """
    Statut initial à la création d'un POI.
    Agent terrain : en_attente (soumis) sauf brouillon explicite (save_as_draft).
    Autres rôles : validé directement.
    """
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None
    if user and user.role == 'agent_terrain':
        if draft:
            boutique.statut_validation = 'brouillon'
            boutique.submitted_at = None
        else:
            boutique.statut_validation = 'en_attente'
            boutique.submitted_at = datetime.utcnow()
    else:
        boutique.statut_validation = 'valide'
        boutique.submitted_at = None


def _submit_poi_for_validation(boutique):
    """Passe un POI brouillon/rejeté en file de validation."""
    if boutique.statut_validation not in ('brouillon', 'rejete'):
        raise ValueError('Ce POI ne peut pas être soumis à validation')
    boutique.statut_validation = 'en_attente'
    boutique.submitted_at = datetime.utcnow()


def _statut_validation_label(code):
    labels = {
        'brouillon': 'Brouillon',
        'en_attente': 'En attente',
        'valide': 'Validé',
        'rejete': 'Rejeté',
    }
    return labels.get(code, code or '—')


def seed_natures_poi_defaults():
    """Initialise les natures POI et leurs champs si la table est vide."""
    if NaturePoi.query.first():
        return
    for item in DEFAULT_NATURES_POI:
        nature = NaturePoi(
            code=item['code'],
            nom=item['nom'],
            ordre=item.get('ordre', 0),
            active=True,
        )
        nature.set_mots_cles_list(item.get('mots_cles', []))
        db.session.add(nature)
        db.session.flush()
        for ch in item.get('champs', []):
            db.session.add(ChampPoi(
                nature_poi_id=nature.id,
                code=ch['code'],
                libelle=ch['libelle'],
                type_champ=ch.get('type_champ', 'str'),
                placeholder=ch.get('placeholder'),
                ordre=ch.get('ordre', 0),
                pleine_largeur=bool(ch.get('pleine_largeur', False)),
                active=True,
            ))
    db.session.commit()


def _fold_ascii_lower(s):
    """Normalise accents pour la recherche mot-clés (codes / noms TypeCommerce)."""
    if s is None:
        return ''
    s = unicodedata.normalize('NFD', str(s))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.lower()


def _coerce_admin_field(val, typ):
    if typ == 'checkbox':
        if isinstance(val, bool):
            return val
        if val is None or val == '':
            return False
        s = str(val).strip().lower()
        if s in ('1', 'true', 'oui', 'yes', 'on'):
            return True
        if s in ('0', 'false', 'non', 'no', 'off'):
            return False
        return bool(val)
    if val is None or val == '':
        return None
    if typ == 'int':
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return None
    if typ == 'float':
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    s = str(val).strip()
    return s or None


def generer_numero_transaction():
    """Génère un numéro de transaction unique au format TXN-YYYY-NNNNNN"""
    annee = datetime.utcnow().year
    prefix = f'TXN-{annee}-'
    last = Paiement.query.filter(Paiement.numero_transaction.isnot(None)).filter(
        Paiement.numero_transaction.like(f'{prefix}%')
    ).order_by(Paiement.id.desc()).first()
    if last and last.numero_transaction:
        try:
            num = int(last.numero_transaction.split('-')[-1]) + 1
        except (ValueError, IndexError):
            num = 1
    else:
        num = 1
    return f'TXN-{annee}-{num:06d}'


def _run_sqlite_legacy_migrations():
    """Migrations incrémentielles pour bases SQLite existantes (dev / anciennes installs)."""
    from sqlalchemy import text
    from db_utils import add_column_if_missing, column_exists, is_sqlite, table_exists

    engine = db.engine
    if not is_sqlite(engine):
        return

    try:
        if add_column_if_missing(engine, db.session, 'paiements', 'numero_transaction', 'VARCHAR(30)'):
            db.session.commit()
        for p in Paiement.query.filter(Paiement.numero_transaction.is_(None)).order_by(Paiement.id):
            annee = p.date_paiement.year if p.date_paiement else datetime.utcnow().year
            p.numero_transaction = f"TXN-{annee}-{p.id:06d}"
        db.session.commit()
    except Exception as mig_err:
        db.session.rollback()
        print(f"Migration numero_transaction: {mig_err}")

    try:
        if not table_exists(engine, 'collectes_terrain'):
            db.create_all()
            db.session.commit()
    except Exception as mig_err:
        db.session.rollback()
        print(f"Migration collectes_terrain: {mig_err}")

    try:
        add_column_if_missing(engine, db.session, 'boutiques', 'nature_poi', "VARCHAR(40) DEFAULT 'autre'")
        add_column_if_missing(engine, db.session, 'boutiques', 'donnees_administratives', 'TEXT')
        db.session.commit()
    except Exception as mig_err:
        db.session.rollback()
        print(f"Migration boutiques GeoTax: {mig_err}")

    try:
        if add_column_if_missing(engine, db.session, 'types_commerce', 'nature_poi_id', 'INTEGER'):
            db.session.commit()
    except Exception as mig_err:
        db.session.rollback()
        print(f"Migration types_commerce nature_poi_id: {mig_err}")

    try:
        db.create_all()
        for col, ddl in [
            ('secteur_id', 'INTEGER'),
            ('icon', 'VARCHAR(20)'),
            ('color', 'VARCHAR(7)'),
            ('map_line_style', "VARCHAR(30) DEFAULT 'solid'"),
            ('map_fill_pattern', "VARCHAR(30) DEFAULT 'solid'"),
            ('ordre', 'INTEGER DEFAULT 0'),
        ]:
            add_column_if_missing(engine, db.session, 'types_commerce', col, ddl)
        add_column_if_missing(engine, db.session, 'champs_poi', 'type_commerce_id', 'INTEGER')

        if column_exists(engine, 'champs_poi', 'nature_poi_id'):
            r_ch_info = db.session.execute(text("PRAGMA table_info(champs_poi)")).fetchall()
            nature_col = next((c for c in r_ch_info if c[1] == 'nature_poi_id'), None)
            if nature_col and nature_col[3] == 1:
                db.session.execute(text("""
                    CREATE TABLE IF NOT EXISTS champs_poi_new (
                        id INTEGER PRIMARY KEY,
                        nature_poi_id INTEGER,
                        type_commerce_id INTEGER,
                        code VARCHAR(60) NOT NULL,
                        libelle VARCHAR(200) NOT NULL,
                        type_champ VARCHAR(20),
                        placeholder VARCHAR(300),
                        ordre INTEGER,
                        pleine_largeur BOOLEAN,
                        active BOOLEAN
                    )
                """))
                db.session.execute(text("""
                    INSERT INTO champs_poi_new
                    SELECT id, nature_poi_id, type_commerce_id, code, libelle, type_champ,
                           placeholder, ordre, pleine_largeur, active FROM champs_poi
                """))
                db.session.execute(text("DROP TABLE champs_poi"))
                db.session.execute(text("ALTER TABLE champs_poi_new RENAME TO champs_poi"))

        for col, ddl in [
            ('statut_validation', "VARCHAR(20) DEFAULT 'valide'"),
            ('photo_path', 'VARCHAR(500)'),
            ('collector_id', 'INTEGER'),
            ('validated_by', 'INTEGER'),
            ('validated_at', 'DATETIME'),
            ('validation_comment', 'TEXT'),
            ('submitted_at', 'DATETIME'),
        ]:
            add_column_if_missing(engine, db.session, 'boutiques', col, ddl)
        db.session.commit()

        db.session.execute(text(
            "UPDATE boutiques SET statut_validation = 'valide' "
            "WHERE statut_validation IS NULL OR statut_validation = ''"
        ))
        db.session.commit()
    except Exception as mig_err:
        db.session.rollback()
        print(f"Migration secteurs/validation: {mig_err}")


def _migrate_pays_map_metadata():
    """Colonnes centre carte + métadonnées pays (multi-pays, sans fusion CG/RCA)."""
    from db_utils import add_column_if_missing

    engine = db.engine
    changed = False
    for col, col_type in (
        ('center_lat', 'FLOAT'),
        ('center_lng', 'FLOAT'),
        ('default_zoom', 'INTEGER DEFAULT 6'),
    ):
        try:
            if add_column_if_missing(engine, db.session, 'pays', col, col_type):
                changed = True
        except Exception as col_err:
            db.session.rollback()
            print(f'Migration pays.{col}: {col_err}')

    try:
        if add_column_if_missing(engine, db.session, 'boutiques', 'pays_id', 'INTEGER'):
            changed = True
    except Exception as col_err:
        db.session.rollback()
        print(f'Migration boutiques.pays_id: {col_err}')

    for pays in Pays.query.filter_by(active=True).order_by(Pays.id).all():
        region = _infer_pays_region_from_data(pays)
        if region == 'CG' and _classify_pays_region(pays) == 'CF':
            pays.code = 'CG'
            pays.code_iso = 'COG'
        _normalize_pays_metadata(pays)
        changed = True

    if changed:
        db.session.commit()

    try:
        n = _dedupe_pays_same_region()
        if n:
            print(f'Dédoublonnage pays (même zone): {n} enregistrement(s) fusionné(s)')
    except Exception as dedupe_err:
        db.session.rollback()
        print(f'Dédoublonnage pays: {dedupe_err}')

    try:
        n = _consolidate_admin_hierarchy_to_keeper()
        if n:
            print(f'Consolidation hiérarchie admin → pays keeper: {n} entité(s) (dept/commune/quartier)')
    except Exception as admin_err:
        db.session.rollback()
        print(f'Consolidation hiérarchie admin: {admin_err}')

    try:
        n = _backfill_boutique_pays_id()
        if n:
            print(f'Rattachement POI → pays: {n} POI(s)')
    except Exception as backfill_err:
        db.session.rollback()
        print(f'Rattachement POI pays: {backfill_err}')

    try:
        n = _reconcile_boutique_pays_ids()
        if n:
            print(f'Réconciliation pays_id POI: {n} POI(s)')
    except Exception as recon_err:
        db.session.rollback()
        print(f'Réconciliation pays_id: {recon_err}')


def _dedupe_pays_same_region():
    """Fusionne uniquement les doublons du même pays (ex. deux fiches RCA), jamais CG avec CF."""
    merged = 0
    for region in ('CG', 'CF', 'CD'):
        candidates = [
            p for p in Pays.query.filter_by(active=True).order_by(Pays.id).all()
            if _classify_pays_region(p) == region
        ]
        if len(candidates) <= 1:
            continue
        candidates.sort(key=lambda p: (
            -Departement.query.filter_by(pays_id=p.id).count(),
            -Boutique.query.filter_by(pays_id=p.id, active=True).count(),
            p.id,
        ))
        keeper = candidates[0]
        _normalize_pays_metadata(keeper)
        for dup in candidates[1:]:
            for dept in Departement.query.filter_by(pays_id=dup.id).all():
                existing = Departement.query.filter_by(pays_id=keeper.id, code=dept.code).first()
                if existing:
                    Commune.query.filter_by(departement_id=dept.id).update(
                        {'departement_id': existing.id}
                    )
                    db.session.delete(dept)
                else:
                    dept.pays_id = keeper.id
            Boutique.query.filter_by(pays_id=dup.id).update({'pays_id': keeper.id})
            dup.active = False
            merged += 1
    if merged:
        db.session.commit()
    return merged


def _get_keeper_pays_for_region(region):
    """Pays actif de référence pour une zone (CG, CF, CD)."""
    actives = [
        p for p in Pays.query.filter_by(active=True).order_by(Pays.id).all()
        if _classify_pays_region(p) == region
    ]
    if not actives:
        return None
    return max(
        actives,
        key=lambda p: (
            Departement.query.filter_by(pays_id=p.id, active=True).count(),
            -p.id,
        ),
    )


def _backfill_boutique_pays_id():
    """Remplit boutiques.pays_id manquant (admin prioritaire)."""
    updated = 0
    last_id = 0
    while True:
        rows = (
            Boutique.query.filter(
                Boutique.active.is_(True),
                Boutique.pays_id.is_(None),
                Boutique.id > last_id,
            )
            .order_by(Boutique.id)
            .limit(300)
            .all()
        )
        if not rows:
            break
        batch_updated = 0
        for boutique in rows:
            last_id = boutique.id
            pid = _resolve_boutique_pays_id(
                quartier_village_id=boutique.quartier_village_id,
                latitude=boutique.latitude,
                longitude=boutique.longitude,
            )
            if pid:
                boutique.pays_id = pid
                batch_updated += 1
        if batch_updated:
            db.session.commit()
            updated += batch_updated
    return updated


def _run_schema_migrations():
    """Migrations légères SQLite / PostgreSQL."""
    from db_utils import add_column_if_missing, is_postgresql

    engine = db.engine
    if is_postgresql(engine):
        try:
            db.session.execute(db.text("SET lock_timeout = '8s'"))
        except Exception:
            pass
    try:
        if add_column_if_missing(engine, db.session, 'commercants', 'must_change_password', 'BOOLEAN DEFAULT false'):
            db.session.commit()
    except Exception as mig_err:
        db.session.rollback()
        print(f'Migration commercants.must_change_password: {mig_err}')

    try:
        _migrate_pays_map_metadata()
    except Exception as mig_err:
        db.session.rollback()
        print(f'Migration pays (centre carte): {mig_err}')


def _find_mirror_departement(dept):
    """Département équivalent sur le pays keeper (même code région)."""
    if not dept:
        return None
    pays = Pays.query.get(dept.pays_id) if dept.pays_id else None
    region = _classify_pays_region(pays) if pays else None
    keeper = _get_keeper_pays_for_region(region) if region else None
    if not keeper or keeper.id == dept.pays_id:
        return dept
    mirror = Departement.query.filter_by(
        pays_id=keeper.id, code=dept.code, active=True
    ).first()
    return mirror or dept


def _find_mirror_commune(commune):
    """Commune équivalente sur le département keeper (même code)."""
    if not commune:
        return None
    dept = Departement.query.get(commune.departement_id)
    mirror_dept = _find_mirror_departement(dept)
    if not mirror_dept or mirror_dept.id == commune.departement_id:
        return commune
    mirror = Commune.query.filter_by(
        departement_id=mirror_dept.id, code=commune.code, active=True
    ).first()
    return mirror or commune


def _merge_quartier_into(target_qv, source_qv):
    """Fusionne source_qv dans target_qv (POI, marchés)."""
    Boutique.query.filter_by(quartier_village_id=source_qv.id).update(
        {'quartier_village_id': target_qv.id}
    )
    Marche.query.filter_by(quartier_village_id=source_qv.id).update(
        {'quartier_village_id': target_qv.id}
    )
    if source_qv.id != target_qv.id:
        db.session.delete(source_qv)


def _merge_commune_into(target_commune, source_commune):
    """Fusionne source_commune dans target_commune."""
    moved = 0
    for qv in QuartierVillage.query.filter_by(commune_id=source_commune.id).all():
        existing = QuartierVillage.query.filter_by(
            commune_id=target_commune.id, code=qv.code
        ).first()
        if existing:
            _merge_quartier_into(existing, qv)
        else:
            qv.commune_id = target_commune.id
        moved += 1
    if source_commune.id != target_commune.id:
        db.session.delete(source_commune)
    return moved


def _merge_departement_into(target_dept, source_dept):
    """Fusionne source_dept dans target_dept."""
    moved = 0
    for commune in Commune.query.filter_by(departement_id=source_dept.id).all():
        existing = Commune.query.filter_by(
            departement_id=target_dept.id, code=commune.code
        ).first()
        if existing:
            moved += _merge_commune_into(existing, commune)
        else:
            commune.departement_id = target_dept.id
            moved += 1
    if source_dept.id != target_dept.id:
        db.session.delete(source_dept)
    return moved


def _consolidate_admin_hierarchy_to_keeper():
    """Rattache départements/communes/quartiers des doublons au pays actif keeper."""
    moved = 0
    for region in ('CG', 'CF', 'CD'):
        keeper = _get_keeper_pays_for_region(region)
        if not keeper:
            continue
        _normalize_pays_metadata(keeper)
        keeper_depts = {
            d.code: d for d in Departement.query.filter_by(pays_id=keeper.id, active=True).all()
        }
        for pays in Pays.query.order_by(Pays.id).all():
            if _classify_pays_region(pays) != region:
                continue
            for dept in Departement.query.filter_by(pays_id=pays.id).all():
                keeper_dept = keeper_depts.get(dept.code)
                if keeper_dept and keeper_dept.id != dept.id:
                    moved += _merge_departement_into(keeper_dept, dept)
                elif pays.id != keeper.id:
                    dept.pays_id = keeper.id
                    keeper_depts[dept.code] = dept
                    moved += 1
                elif dept.code not in keeper_depts:
                    keeper_depts[dept.code] = dept
            if pays.active and pays.id != keeper.id:
                if (
                    Departement.query.filter_by(pays_id=pays.id).count() == 0
                    and Boutique.query.filter_by(pays_id=pays.id, active=True).count() == 0
                ):
                    pays.active = False
    if moved:
        db.session.commit()
    return moved


def init_db():
    """Créer les tables de la base de données"""
    with app.app_context():
        try:
            db.create_all()
            _run_sqlite_legacy_migrations()
            _run_schema_migrations()

            seed_natures_poi_defaults()
            seed_secteurs_activite_defaults()
            migrate_champs_to_types_commerce()
            try:
                n = dedupe_champ_poi_duplicates()
                if n:
                    print(f'Dédoublonnage champs POI : {n} doublon(s) désactivé(s)')
            except Exception as dedupe_err:
                db.session.rollback()
                print(f'Dédoublonnage champs POI : {dedupe_err}')

            try:
                n_poi = migrate_unified_poi_schema()
                if n_poi:
                    print(f'Migration POI unifié : {n_poi} infrastructure(s) migrée(s) depuis map_features')
            except Exception as poi_mig_err:
                db.session.rollback()
                print(f'Migration POI unifié : {poi_mig_err}')

            try:
                n_sync = _sync_geo_poi_coordinates()
                if n_sync:
                    print(f'Sync coordonnées POI géométriques : {n_sync} POI(s) mis à jour')
                    try:
                        from cache_utils import cache_delete_pattern
                        cache_delete_pattern('map_features')
                        cache_delete_pattern('boutiques_map')
                    except Exception:
                        pass
            except Exception as sync_err:
                db.session.rollback()
                print(f'Sync coordonnées POI : {sync_err}')
            
            # Créer les institutions par défaut si aucune n'existe
            if not Institut.query.first():
                instituts_default = [
                    Institut(code='IMPOTS', nom='Direction Générale des Impôts', type='impots', description='Paiement des impôts'),
                    Institut(code='POLICE', nom='Police Municipale', type='police', description='Paiement des taxes de police'),
                    Institut(code='MAIRIE', nom='Mairie', type='mairie', description='Paiement des taxes municipales')
                ]
                for inst in instituts_default:
                    db.session.add(inst)
                db.session.commit()
                
                # Créer les taxes par défaut
                impots = Institut.query.filter_by(code='IMPOTS').first()
                police = Institut.query.filter_by(code='POLICE').first()
                mairie = Institut.query.filter_by(code='MAIRIE').first()
                
                taxes_default = [
                    Taxe(institut_id=impots.id, code='TAXE_FISCALE', nom='Taxe Fiscale Mensuelle', montant_attendu=5000, periodicite='mensuel', description='Taxe fiscale mensuelle pour les points d\'intérêt'),
                    Taxe(institut_id=police.id, code='TAXE_POLICE', nom='Taxe de Police', montant_attendu=3000, periodicite='mensuel', description='Taxe de police municipale'),
                    Taxe(institut_id=mairie.id, code='TAXE_MUNICIPALE', nom='Taxe Municipale', montant_attendu=2000, periodicite='mensuel', description='Taxe municipale mensuelle')
                ]
                for taxe in taxes_default:
                    db.session.add(taxe)
                db.session.commit()
            
            # Initialiser les configurations par défaut
            configs_default = [
                ('montant_fiscal_mensuel', '5000', 'Montant fiscal mensuel par défaut'),
                ('code_ussd', '*123#', 'Code USSD pour les paiements'),
                ('repartition_institution', '80', 'Pourcentage pour les institutions (%)'),
                ('repartition_partenaire_technique', '17', 'Pourcentage pour le partenaire technique (%)'),
                ('repartition_mtn', '3', 'Pourcentage pour MTN (%)'),
            ]
            for cle, valeur, desc in configs_default:
                if not Configuration.query.filter_by(cle=cle).first():
                    Configuration.set(cle, valeur, desc)
            
            # Créer l'utilisateur admin par défaut
            if not User.query.first():
                admin = User(
                    username='admin',
                    password_hash=generate_password_hash('admin123'),
                    nom='Administrateur',
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
        except Exception as e:
            print(f"Erreur lors de l'initialisation de la base de données: {e}")


@app.errorhandler(500)
def handle_500_error(e):
    """Gestionnaire d'erreur pour les erreurs 500"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Erreur serveur', 'message': str(e)}), 500
    return render_template('error.html', error=str(e)), 500


@app.before_request
def require_auth():
    """Vérification d'authentification pour les routes protégées"""
    path = request.path
    # Routes publiques
    if path in ('/', '/login', '/logout') or path.startswith('/commercant') or path.startswith('/static'):
        return None
    if path == '/health' or path.startswith('/health/'):
        return None
    if path.startswith('/verifier-receipt'):
        return None
    # Webhooks externes (pas d'auth session)
    if path in ('/api/paiements/ussd', '/api/paiements/mobile-money'):
        return None
    if path.startswith('/api/commercant'):
        return None
    # Vérifier la session
    if not session.get('user_id'):
        if path.startswith('/api/'):
            return jsonify({'error': 'Connexion requise'}), 401
        return redirect(url_for('login_page', next=request.url))
    # Vérifier que l'utilisateur existe et est actif
    user = User.query.get(session.get('user_id'))
    if not user or not user.actif:
        session.clear()
        return redirect(url_for('login_page'))
    # Mettre à jour le rôle en session si nécessaire
    if session.get('user_role') != user.role:
        session['user_role'] = user.role
    return None


@app.route('/favicon.ico')
def favicon():
    """Évite les 404 sur la requête favicon du navigateur"""
    return '', 204


@app.errorhandler(404)
def handle_404_error(e):
    """Gestionnaire d'erreur pour les erreurs 404"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Ressource non trouvée'}), 404
    return render_template('error.html', error='Page non trouvée'), 404


@app.context_processor
def inject_nav():
    """Injecte les variables de navigation dans les templates"""
    role = session.get('user_role')
    nav_items = get_nav_items_for_role(role) if role else []
    home_url = get_home_url_for_role(role) if role else url_for('login_page')
    try:
        pays_ctx = _get_pays_session_payload()
    except Exception as exc:
        import logging
        logging.getLogger('geotax').warning('Contexte pays indisponible: %s', exc)
        pays_ctx = {
            'pays_id': None,
            'pays': None,
            'map_view': dict(PAYS_DEFAULT_MAP_VIEW),
        }
    return dict(
        nav_items=nav_items,
        current_user_role=role,
        current_user_role_label=ROLE_LABELS.get(role, role or ''),
        home_url=home_url,
        selected_pays_id=pays_ctx['pays_id'],
        selected_pays_nom=pays_ctx['pays']['nom'] if pays_ctx.get('pays') else '',
    )


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """Page de connexion"""
    if session.get('user_id'):
        role = session.get('user_role')
        return redirect(get_home_url_for_role(role))
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            return render_template('login.html', error='Identifiants requis')
        user = User.query.filter_by(username=username, actif=True).first()
        if not user or not check_password_hash(user.password_hash, password):
            return render_template('login.html', error='Identifiants incorrects')
        session['user_id'] = user.id
        session['user_role'] = user.role
        session['user_nom'] = user.nom or user.username
        _ensure_default_pays_session()
        next_path = request.args.get('next')
        if next_path and is_path_allowed_for_role(user.role, next_path):
            next_url = next_path
        else:
            next_url = get_home_url_for_role(user.role)
        return redirect(next_url)
    return render_template('login.html')


@app.route('/logout')
def logout_page():
    """Déconnexion"""
    session.clear()
    return redirect(url_for('index'))


@app.route('/')
def index():
    """Landing page publique ; redirige vers l'accueil du rôle si connecté"""
    if session.get('user_id'):
        return redirect(get_home_url_for_role(session.get('user_role')))
    return render_template('landing.html')


@app.route('/dashboard')
@require_access('/', '/dashboard')
def dashboard_page():
    """Tableau de bord"""
    return render_template('dashboard.html')


def parse_periode_params(args=None):
    """Extrait un intervalle de mois depuis les paramètres de requête."""
    args = args or request.args
    now = datetime.utcnow()

    mois_debut = args.get('mois_debut', type=int)
    annee_debut = args.get('annee_debut', type=int)
    mois_fin = args.get('mois_fin', type=int)
    annee_fin = args.get('annee_fin', type=int)

    mois = args.get('mois', type=int)
    annee = args.get('annee', type=int)

    if mois_debut is None and mois is not None:
        mois_debut = mois
    if annee_debut is None and annee is not None:
        annee_debut = annee
    if mois_fin is None and mois is not None:
        mois_fin = mois
    if annee_fin is None and annee is not None:
        annee_fin = annee

    if mois_fin is None:
        mois_fin = now.month
    if annee_fin is None:
        annee_fin = now.year
    if mois_debut is None:
        mois_debut = mois_fin
    if annee_debut is None:
        annee_debut = annee_fin

    if (annee_debut, mois_debut) > (annee_fin, mois_fin):
        mois_debut, annee_debut, mois_fin, annee_fin = mois_fin, annee_fin, mois_debut, annee_debut

    return mois_debut, annee_debut, mois_fin, annee_fin


def filter_paiements_periode(query, mois_debut, annee_debut, mois_fin, annee_fin):
    """Filtre une requête Paiement sur un intervalle de mois inclus."""
    from sqlalchemy import and_, or_
    return query.filter(
        or_(
            Paiement.annee > annee_debut,
            and_(Paiement.annee == annee_debut, Paiement.mois >= mois_debut),
        ),
        or_(
            Paiement.annee < annee_fin,
            and_(Paiement.annee == annee_fin, Paiement.mois <= mois_fin),
        ),
    )


def _get_boutiques_balance_data():
    """Charge les POI actifs, leurs taxes assignées et paiements confirmés."""
    from collections import defaultdict

    boutiques = Boutique.query.filter_by(active=True).all()
    boutique_ids = [b.id for b in boutiques]
    bt_by_boutique = defaultdict(list)
    paiements_by_boutique = defaultdict(list)

    if boutique_ids:
        boutique_taxes_all = BoutiqueTaxe.query.filter(
            BoutiqueTaxe.boutique_id.in_(boutique_ids),
            BoutiqueTaxe.active.is_(True),
        ).all()
        for bt in boutique_taxes_all:
            bt_by_boutique[bt.boutique_id].append(bt)

        paiements_all = Paiement.query.filter(
            Paiement.boutique_id.in_(boutique_ids),
            Paiement.statut == 'confirme',
        ).all()
        for p in paiements_all:
            paiements_by_boutique[p.boutique_id].append(p)

    return boutiques, bt_by_boutique, paiements_by_boutique


def _compute_balance_par_institut(mois_debut, annee_debut, mois_fin, annee_fin, institut_id=None, taxe_id=None):
    """Balance par institution alignée sur Boutique.get_montants_periode() (taxes assignées, périodicité)."""
    from collections import defaultdict

    instituts_q = Institut.query.filter_by(active=True)
    if institut_id:
        instituts_q = instituts_q.filter_by(id=institut_id)
    instituts = {i.id: i for i in instituts_q.all()}

    stats = defaultdict(lambda: {
        'montant_attendu': 0.0,
        'montant_recouvre': 0.0,
        'commerces_concernes': set(),
        'commerces_a_jour': set(),
        'taxe_ids': set(),
        'nombre_paiements': 0,
    })

    boutiques, bt_by_boutique, paiements_by_boutique = _get_boutiques_balance_data()
    if not boutiques:
        return []

    for boutique in boutiques:
        debut_boutique = boutique.date_creation or datetime.utcnow()
        paiements_map = {
            (p.taxe_id, p.mois, p.annee): p.montant
            for p in paiements_by_boutique.get(boutique.id, [])
            if p.taxe_id
        }
        montants_par_institut = defaultdict(lambda: {'attendu': 0.0, 'recouvre': 0.0})

        for bt in bt_by_boutique.get(boutique.id, []):
            taxe = bt.taxe
            if not taxe or not taxe.active:
                continue
            if institut_id and taxe.institut_id != institut_id:
                continue
            if taxe_id and taxe.id != taxe_id:
                continue
            inst_id = taxe.institut_id
            if inst_id not in instituts:
                continue

            montant = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu
            debut = bt.date_application or debut_boutique
            if debut_boutique > debut:
                debut = debut_boutique
            debut_m, debut_a = debut.month, debut.year

            for m, a in Boutique._iter_mois_periodes(mois_debut, annee_debut, mois_fin, annee_fin):
                if not Boutique._taxe_est_due(taxe, m, a, debut_m, debut_a):
                    continue
                montants_par_institut[inst_id]['attendu'] += montant
                montants_par_institut[inst_id]['recouvre'] += paiements_map.get((taxe.id, m, a), 0.0)
                stats[inst_id]['taxe_ids'].add(taxe.id)

        for inst_id, montants in montants_par_institut.items():
            attendu = montants['attendu']
            recouvre = montants['recouvre']
            if attendu <= 0:
                continue
            stats[inst_id]['montant_attendu'] += attendu
            stats[inst_id]['montant_recouvre'] += recouvre
            stats[inst_id]['commerces_concernes'].add(boutique.id)
            if recouvre >= attendu:
                stats[inst_id]['commerces_a_jour'].add(boutique.id)

    paiements_q = Paiement.query.filter_by(statut='confirme')
    if institut_id:
        paiements_q = paiements_q.filter_by(institut_id=institut_id)
    if taxe_id:
        paiements_q = paiements_q.filter(Paiement.taxe_id == taxe_id)
    paiements_q = filter_paiements_periode(
        paiements_q, mois_debut, annee_debut, mois_fin, annee_fin,
    )
    for p in paiements_q.all():
        if p.institut_id in stats:
            stats[p.institut_id]['nombre_paiements'] += 1

    result = []
    for inst_id, institut in instituts.items():
        taxes = Taxe.query.filter_by(institut_id=inst_id, active=True).all()
        if taxe_id:
            taxes = [t for t in taxes if t.id == taxe_id]
            if not taxes:
                continue

        s = stats[inst_id]
        montant_attendu = round(s['montant_attendu'], 2)
        montant_recouvre = round(s['montant_recouvre'], 2)
        montant_non_recouvre = round(max(0.0, montant_attendu - montant_recouvre), 2)
        taux_recouvrement = round(
            (montant_recouvre / montant_attendu * 100) if montant_attendu > 0 else 0, 2,
        )
        commerces_actifs = len(s['commerces_concernes'])
        commerces_a_jour = len(s['commerces_a_jour'])
        commerces_non_a_jour = commerces_actifs - commerces_a_jour

        result.append({
            'institut_id': institut.id,
            'institut_code': institut.code,
            'institut_nom': institut.nom,
            'institut_type': institut.type,
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
            'montant_attendu': montant_attendu,
            'montant_recouvre': montant_recouvre,
            'montant_non_recouvre': montant_non_recouvre,
            'taux_recouvrement': taux_recouvrement,
            'commerces_actifs': commerces_actifs,
            'commerces_a_jour': commerces_a_jour,
            'commerces_non_a_jour': commerces_non_a_jour,
            'commerces_ayant_paye': commerces_a_jour,
            'commerces_n_ayant_pas_paye': commerces_non_a_jour,
            'nombre_taxes': len(s['taxe_ids']) if s['taxe_ids'] else len(taxes),
            'nombre_paiements': s['nombre_paiements'],
        })

    return result


def _compute_balance_par_taxe(mois_debut, annee_debut, mois_fin, annee_fin, taxe_id=None):
    """Balance par taxe alignée sur Boutique.get_montants_periode() (taxes assignées, périodicité)."""
    from collections import defaultdict

    taxes_q = Taxe.query.filter_by(active=True)
    if taxe_id:
        taxes_q = taxes_q.filter_by(id=taxe_id)
    taxes = {t.id: t for t in taxes_q.all()}

    stats = defaultdict(lambda: {
        'montant_attendu': 0.0,
        'montant_recouvre': 0.0,
        'poi_concernes': set(),
        'nombre_paiements': 0,
    })

    boutiques, bt_by_boutique, paiements_by_boutique = _get_boutiques_balance_data()

    for boutique in boutiques:
        debut_boutique = boutique.date_creation or datetime.utcnow()
        paiements_map = {
            (p.taxe_id, p.mois, p.annee): p.montant
            for p in paiements_by_boutique.get(boutique.id, [])
            if p.taxe_id
        }

        for bt in bt_by_boutique.get(boutique.id, []):
            taxe = bt.taxe
            if not taxe or not taxe.active or taxe.id not in taxes:
                continue

            montant = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu
            debut = bt.date_application or debut_boutique
            if debut_boutique > debut:
                debut = debut_boutique
            debut_m, debut_a = debut.month, debut.year

            attendu_boutique = 0.0
            for m, a in Boutique._iter_mois_periodes(mois_debut, annee_debut, mois_fin, annee_fin):
                if not Boutique._taxe_est_due(taxe, m, a, debut_m, debut_a):
                    continue
                attendu_boutique += montant
                stats[taxe.id]['montant_recouvre'] += paiements_map.get((taxe.id, m, a), 0.0)

            if attendu_boutique > 0:
                stats[taxe.id]['montant_attendu'] += attendu_boutique
                stats[taxe.id]['poi_concernes'].add(boutique.id)

    paiements_q = Paiement.query.filter_by(statut='confirme')
    if taxe_id:
        paiements_q = paiements_q.filter(Paiement.taxe_id == taxe_id)
    paiements_q = filter_paiements_periode(
        paiements_q, mois_debut, annee_debut, mois_fin, annee_fin,
    )
    for p in paiements_q.all():
        if p.taxe_id in stats:
            stats[p.taxe_id]['nombre_paiements'] += 1

    result = []
    for tid, taxe in taxes.items():
        s = stats[tid]
        montant_attendu = round(s['montant_attendu'], 2)
        montant_recouvre = round(s['montant_recouvre'], 2)
        if montant_attendu <= 0 and montant_recouvre <= 0 and s['nombre_paiements'] == 0:
            continue

        montant_non_recouvre = round(max(0.0, montant_attendu - montant_recouvre), 2)
        taux_recouvrement = round(
            (montant_recouvre / montant_attendu * 100) if montant_attendu > 0 else 0, 2,
        )
        result.append({
            'taxe_id': taxe.id,
            'taxe_nom': taxe.nom,
            'taxe_code': taxe.code,
            'institut_id': taxe.institut_id,
            'institut_nom': taxe.institut.nom if taxe.institut else None,
            'montant_attendu': montant_attendu,
            'montant_recouvre': montant_recouvre,
            'montant_non_recouvre': montant_non_recouvre,
            'taux_recouvrement': taux_recouvrement,
            'nombre_paiements': s['nombre_paiements'],
            'poi_concernes': len(s['poi_concernes']),
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
        })

    result.sort(key=lambda r: r['montant_attendu'], reverse=True)
    return result


def _format_admin_field_display(val, typ):
    """Valeur affichable pour un champ administratif POI."""
    if typ == 'checkbox':
        if val in (True, 'true', '1', 1, 'oui', 'Oui'):
            return 'Oui'
        if val in (False, 'false', '0', 0, 'non', 'Non'):
            return 'Non'
        return '—'
    if val is None or val == '':
        return '—'
    return str(val)


def _boutique_localisation_label(boutique):
    if boutique.quartier_village:
        parts = [boutique.quartier_village.nom or '']
        if boutique.quartier_village.commune:
            parts.append(boutique.quartier_village.commune.nom)
        return ', '.join(p for p in parts if p)
    return boutique.arrondissement or boutique.adresse or ''


def _format_coords_label(lat, lng, precision=5):
    return f'{lat:.{precision}f}, {lng:.{precision}f}'


def _map_feature_localisation_label(mf):
    """Localisation lisible pour une infrastructure (description + coordonnées GPS)."""
    parts = []
    if mf.description and str(mf.description).strip():
        parts.append(str(mf.description).strip())
    geom = mf.get_geometry_parsed()
    if geom:
        centroid = geometry_centroid(geom)
        if centroid:
            lat, lng = centroid
            parts.append(_format_coords_label(lat, lng))
    if parts:
        return ' — '.join(parts)
    meta = mf.get_type_meta()
    return meta.get('label', mf.feature_type or '—')


def _get_champs_techniques_for_type(type_commerce_id):
    """Retourne la liste des champs techniques (dict) pour un type d'activité."""
    if not type_commerce_id:
        return [], None
    tc = TypeCommerce.query.get(type_commerce_id)
    if not tc:
        return [], None
    champs_objs = get_effective_champs_objs(tc)
    champs = [
        {
            'id': c.id,
            'code': c.code,
            'libelle': c.libelle,
            'type_champ': c.type_champ,
            'ordre': c.ordre or 0,
        }
        for c in champs_objs
    ]
    champs.sort(key=lambda x: x['ordre'])
    return champs, tc


def _poi_matches_technical_search(b, champs, q):
    """Filtre texte sur un POI pour le tableau données techniques."""
    if not q:
        return True
    donnees = b.get_donnees_admin_parsed()
    meta = b.get_feature_type_meta()
    cat_label = 'Contribuable' if b.is_contribuable() else 'Infrastructure'
    tc = b.type_commerce
    type_label = tc.nom if tc else '—'
    if (b.feature_type or 'point') != 'point':
        type_label = f'{type_label} ({meta.get("label", b.feature_type)})'
    searchable = [
        b.code_unique or '', b.nom or '', b.proprietaire or '',
        b.telephone or '', _poi_localisation_label(b), type_label, cat_label,
    ]
    for c in champs:
        raw = donnees.get(c['code'])
        if raw is not None and raw != '':
            searchable.append(str(raw))
    blob = ' '.join(str(x).lower() for x in searchable)
    words = q.split()
    return all(w in blob for w in words)


def _compute_technical_stats(pois, champs, filtered_pois=None):
    """Agrégats pour l'onglet données techniques."""
    from collections import defaultdict

    total = len(pois)
    filtered_total = len(filtered_pois) if filtered_pois is not None else total
    par_categorie = {'contribuable': 0, 'infrastructure': 0}
    par_forme = defaultdict(int)
    champs_stats = {}
    for c in champs:
        champs_stats[c['code']] = {
            'id': c['id'],
            'code': c['code'],
            'label': c['libelle'],
            'type_champ': c['type_champ'],
            'rempli': 0,
            'valeurs_numeriques': [],
        }

    poi_avec_donnees = 0
    poi_complet = 0
    n_champs = len(champs)

    for b in pois:
        if b.is_contribuable():
            par_categorie['contribuable'] += 1
        else:
            par_categorie['infrastructure'] += 1
        par_forme[b.feature_type or 'point'] += 1

        donnees = b.get_donnees_admin_parsed()
        filled = 0
        for c in champs:
            raw = donnees.get(c['code'])
            is_filled = raw is not None and raw != '' and raw is not False
            if is_filled:
                champs_stats[c['code']]['rempli'] += 1
                filled += 1
                if c['type_champ'] in ('int', 'float'):
                    try:
                        champs_stats[c['code']]['valeurs_numeriques'].append(float(raw))
                    except (TypeError, ValueError):
                        pass
        if filled > 0:
            poi_avec_donnees += 1
        if n_champs > 0 and filled == n_champs:
            poi_complet += 1

    champs_list = []
    for c in champs:
        cs = champs_stats[c['code']]
        entry = {
            'id': cs['id'],
            'code': cs['code'],
            'label': cs['label'],
            'type_champ': cs['type_champ'],
            'rempli': cs['rempli'],
            'taux_remplissage': round(cs['rempli'] / total * 100, 1) if total else 0,
        }
        nums = cs['valeurs_numeriques']
        if nums:
            entry['numeric'] = {
                'min': min(nums),
                'max': max(nums),
                'avg': round(sum(nums) / len(nums), 2),
                'sum': round(sum(nums), 2),
                'count': len(nums),
            }
        champs_list.append(entry)

    champs_list.sort(key=lambda x: x['taux_remplissage'], reverse=True)

    return {
        'total_poi': total,
        'total_filtre': filtered_total,
        'par_categorie': par_categorie,
        'par_forme': dict(par_forme),
        'poi_avec_donnees': poi_avec_donnees,
        'poi_complet': poi_complet,
        'poi_vide': total - poi_avec_donnees,
        'taux_completude_globale': round(poi_complet / total * 100, 1) if total else 0,
        'taux_remplissage_moyen': round(
            sum(c['taux_remplissage'] for c in champs_list) / len(champs_list), 1
        ) if champs_list else 0,
        'champs': champs_list,
    }


@app.route('/api/pois/donnees-techniques', methods=['GET'])
@require_access('/pois')
def get_pois_donnees_techniques():
    """Tableau des données techniques POI filtré par type d'activité."""
    try:
        type_commerce_id = request.args.get('type_commerce_id', type=int)
        q = (request.args.get('q') or '').strip().lower()
        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(max(1, request.args.get('per_page', 20, type=int)), 100)

        if not type_commerce_id:
            types = TypeCommerce.query.filter_by(active=True).order_by(TypeCommerce.nom).all()
            return jsonify({
                'columns': [],
                'rows': [],
                'pagination': {'page': 1, 'per_page': per_page, 'total': 0, 'total_pages': 0},
                'types_commerce': [{'id': t.id, 'nom': t.nom, 'code': t.code} for t in types],
            })

        champs, tc = _get_champs_techniques_for_type(type_commerce_id)
        if not tc:
            return jsonify({'error': 'Type d\'activité introuvable'}), 404

        base_columns = [
            {'key': 'code_unique', 'label': 'Code', 'group': 'base', 'default': True, 'locked': True},
            {'key': 'nom', 'label': 'Nom', 'group': 'base', 'default': True},
            {'key': 'proprietaire', 'label': 'Responsable', 'group': 'base', 'default': True},
            {'key': 'telephone', 'label': 'Téléphone', 'group': 'base', 'default': False},
            {'key': 'localisation', 'label': 'Localisation', 'group': 'base', 'default': False},
            {'key': 'type_activite', 'label': 'Type d\'activité', 'group': 'base', 'default': False},
        ]
        tech_columns = [
            {
                'key': f'tech_{c["id"]}',
                'field_code': c['code'],
                'field_id': c['id'],
                'label': c['libelle'],
                'group': 'technique',
                'type_champ': c['type_champ'],
                'default': True,
            }
            for c in champs
        ]
        columns = base_columns + tech_columns

        query = Boutique.query.filter_by(active=True, type_commerce_id=type_commerce_id)
        pois = query.order_by(Boutique.nom).all()
        filtered_pois = [b for b in pois if _poi_matches_technical_search(b, champs, q)] if q else pois

        rows = []
        for b in filtered_pois:
            donnees = b.get_donnees_admin_parsed()
            meta = b.get_feature_type_meta()
            cat_label = 'Contribuable' if b.is_contribuable() else 'Infrastructure'
            type_label = tc.nom
            if (b.feature_type or 'point') != 'point':
                type_label = f'{tc.nom} ({meta.get("label", b.feature_type)})'
            row = {
                'id': b.id if b.is_contribuable() else f'poi-{b.id}',
                'code_unique': b.code_unique,
                'nom': b.nom,
                'proprietaire': b.proprietaire or '—',
                'telephone': b.telephone or '—',
                'localisation': _poi_localisation_label(b),
                'type_activite': f'{type_label} · {cat_label}',
            }
            for c in champs:
                raw = donnees.get(c['code'])
                display = _format_admin_field_display(raw, c['type_champ'])
                key = f'tech_{c["id"]}'
                row[key] = display
            rows.append(row)

        total = len(rows)
        stats = _compute_technical_stats(pois, champs, filtered_pois)
        total_pages = max(1, (total + per_page - 1) // per_page) if total else 0
        if page > total_pages and total_pages:
            page = total_pages
        start = (page - 1) * per_page
        page_rows = rows[start:start + per_page]

        return jsonify({
            'columns': columns,
            'rows': page_rows,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
            },
            'type_commerce_id': type_commerce_id,
            'type_commerce_nom': tc.nom,
            'nature_poi': infer_nature_poi_from_type_commerce(tc),
            'stats': stats,
        })
    except Exception as e:
        print(f'Erreur get_pois_donnees_techniques: {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/boutiques', methods=['GET'])
def get_boutiques():
    """Récupérer la liste des commerces avec filtres"""
    try:
        from cache_utils import cache_get, cache_set, cache_key
        from spatial_utils import apply_bbox_filter_query

        arrondissement = request.args.get('arrondissement')
        zone = request.args.get('zone')
        marche = request.args.get('marche')
        statut = request.args.get('statut')  # 'a_jour', 'non_a_jour', 'tous'
        statut_validation = request.args.get('statut_validation')
        type_commerce_id = request.args.get('type_commerce_id', type=int)
        secteur_id = request.args.get('secteur_id', type=int)
        with_coords = request.args.get('with_coords', 'false').lower() == 'true'
        map_view = request.args.get('map_view', 'false').lower() == 'true'
        categorie = request.args.get('categorie', '').strip().lower()
        bbox = _parse_bbox_param()
        limit = min(int(request.args.get('limit', 5000)), 10000)

        cache_ck = None
        if map_view and bbox:
            cache_ck = cache_key(
                'boutiques_map', bbox, categorie,
                statut_validation, type_commerce_id, secteur_id,
                request.args.get('all_categories'),
                resolve_pays_id(),
            )
            cached = cache_get(cache_ck)
            if cached is not None:
                return jsonify(cached)

        query = Boutique.query.filter_by(active=True)

        pays_id = resolve_pays_id()
        if pays_id:
            query = _filter_boutiques_by_pays(query, pays_id)

        if categorie in POI_CATEGORIES:
            query = query.filter_by(categorie=categorie)
        elif not request.args.get('all_categories'):
            query = query.filter_by(categorie=POI_CATEGORY_CONTRIBUABLE)

        if statut_validation:
            query = query.filter_by(statut_validation=statut_validation)
        if type_commerce_id:
            query = query.filter_by(type_commerce_id=type_commerce_id)
        if secteur_id:
            query = query.join(TypeCommerce).filter(TypeCommerce.secteur_id == secteur_id)

        if with_coords:
            query = query.filter(Boutique.latitude.isnot(None), Boutique.longitude.isnot(None))
            if map_view:
                query = query.filter(
                    db.or_(Boutique.feature_type.is_(None), Boutique.feature_type == 'point')
                )

        if bbox:
            query, _ = apply_bbox_filter_query(query, bbox)

        if arrondissement:
            query = query.filter_by(arrondissement=arrondissement)
        if zone:
            query = query.filter_by(zone=zone)
        if marche:
            query = query.filter_by(marche=marche)

        boutiques = query.limit(limit).all()

        result = []
        mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()

        for boutique in boutiques:
            try:
                if map_view:
                    boutique_dict = boutique.to_dict()
                    result.append(boutique_dict)
                    continue

                a_jour = True
                if boutique.is_contribuable():
                    a_jour = boutique.get_statut_paiement_periode(mois_debut, annee_debut, mois_fin, annee_fin)

                if statut == 'a_jour' and not a_jour:
                    continue
                if statut == 'non_a_jour' and a_jour:
                    continue

                boutique_dict = boutique.to_dict()
                boutique_dict['a_jour'] = a_jour
                if boutique.is_contribuable():
                    montants = boutique.get_montants_periode(mois_debut, annee_debut, mois_fin, annee_fin)
                    boutique_dict.update(montants)
                    boutique_dict['a_compte_commercant'] = hasattr(boutique, 'commercant') and boutique.commercant is not None
                    try:
                        dernier_paiement = boutique.get_dernier_paiement()
                        boutique_dict['dernier_paiement'] = dernier_paiement.to_dict() if dernier_paiement else None
                    except Exception:
                        boutique_dict['dernier_paiement'] = None
                else:
                    boutique_dict['montant_a_recouvrer'] = 0
                    boutique_dict['montant_recouvre'] = 0
                    boutique_dict['a_compte_commercant'] = False
                    boutique_dict['dernier_paiement'] = None
                result.append(boutique_dict)
            except Exception as e:
                print(f"Erreur lors du traitement de la boutique {boutique.id}: {e}")
                continue

        payload = {
            'boutiques': result,
            'meta': {
                'count': len(result),
                'bbox': list(bbox) if bbox else None,
                'limit': limit,
            },
        }
        if not map_view:
            payload['periode'] = {
                'mois_debut': mois_debut,
                'annee_debut': annee_debut,
                'mois_fin': mois_fin,
                'annee_fin': annee_fin,
            }

        if cache_ck:
            cache_set(cache_ck, payload, ttl_seconds=45)

        return jsonify(payload)
    except Exception as e:
        print(f"Erreur dans get_boutiques: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération des POI', 'message': str(e)}), 500


@app.route('/api/boutiques', methods=['POST'])
def create_boutique():
    """Créer un POI unifié (contribuable ou infrastructure)."""
    data = request.json or {}

    categorie = _normalize_poi_categorie(data.get('categorie'))
    feature_type = _normalize_poi_feature_type(data.get('feature_type'))
    is_contribuable = categorie == POI_CATEGORY_CONTRIBUABLE
    code_prefix = 'POI-' if is_contribuable else 'GEO-'
    code_unique = data.get('code_unique') or f"{code_prefix}{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    if Boutique.query.filter_by(code_unique=code_unique).first():
        return jsonify({'error': 'Ce code existe déjà pour un autre POI'}), 400
    
    # Récupérer le quartier_village_id si fourni
    quartier_village_id = data.get('quartier_village_id')
    if quartier_village_id:
        # Vérifier que le quartier existe
        if not QuartierVillage.query.get(quartier_village_id):
            return jsonify({'error': 'Quartier/Village non trouvé'}), 404
    
    # Récupérer le marche_id si fourni
    marche_id = data.get('marche_id')
    if marche_id:
        # Vérifier que le marché existe
        if not Marche.query.get(marche_id):
            return jsonify({'error': 'Marché non trouvé'}), 404
    
    type_commerce_id = data.get('type_commerce_id')
    tc_obj = TypeCommerce.query.get(type_commerce_id) if type_commerce_id else None
    if type_commerce_id and not tc_obj:
        return jsonify({'error': 'Type de commerce non trouvé'}), 404
    
    if tc_obj:
        nature = infer_nature_poi_from_type_commerce(tc_obj)
    else:
        nature = _normalize_nature_poi(data.get('nature_poi'))
    donnees = normalize_donnees_administratives(
        nature, data.get('donnees_administratives') or {}, type_commerce_id=type_commerce_id
    )
    don_json = json.dumps(donnees, ensure_ascii=False) if donnees else None

    statut = data.get('statut_validation')
    if statut in POI_STATUTS_VALIDATION and statut != 'brouillon':
        # Statut explicite (hors brouillon auto) — réservé aux rôles non agents
        user = User.query.get(session.get('user_id')) if session.get('user_id') else None
        if not user or user.role != 'agent_terrain':
            pass  # appliqué après instanciation
        else:
            statut = None
    else:
        statut = None
    user_id = session.get('user_id')

    description = (data.get('description') or '').strip() or None
    properties = data.get('properties') if isinstance(data.get('properties'), dict) else {}
    
    boutique = Boutique(
        code_unique=code_unique,
        nom=data.get('nom', ''),
        proprietaire=data.get('proprietaire', ''),
        telephone=data.get('telephone', ''),
        adresse=data.get('adresse', ''),
        type_commerce_id=type_commerce_id,
        pays_id=_resolve_boutique_pays_id(
            quartier_village_id=quartier_village_id,
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            explicit_pays_id=data.get('pays_id'),
        ),
        quartier_village_id=quartier_village_id,
        marche_id=marche_id,
        marche_nom=data.get('marche_nom', ''),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        arrondissement=data.get('arrondissement', ''),
        zone=data.get('zone', ''),
        marche=data.get('marche', ''),
        nature_poi=nature,
        donnees_administratives=don_json,
        collector_id=user_id,
        categorie=categorie,
        feature_type=feature_type,
        description=description,
    )

    draft = bool(data.get('save_as_draft'))
    if statut in POI_STATUTS_VALIDATION:
        boutique.statut_validation = statut
    else:
        _apply_poi_validation_on_create(boutique, draft=draft)

    geometry_raw = data.get('geometry')
    if geometry_raw:
        geometry = parse_geometry(geometry_raw)
        _apply_poi_geometry_fields(boutique, geometry, properties)
    elif feature_type == 'point' and boutique.latitude and boutique.longitude:
        boutique.geometry = json.dumps({
            'type': 'Point',
            'coordinates': [float(boutique.longitude), float(boutique.latitude)],
        })

    if properties:
        boutique.properties = json.dumps(properties, ensure_ascii=False)

    _sync_boutique_pays_id(boutique, explicit_pays_id=data.get('pays_id'))

    taxes_data = data.get('taxes', []) if is_contribuable else []
    if is_contribuable and not taxes_data:
        return jsonify({'error': 'Au moins une taxe doit être sélectionnée pour un contribuable'}), 400
    if is_contribuable and not normalize_phone(data.get('telephone', '')):
        return jsonify({
            'error': 'Le numéro de téléphone est obligatoire pour un contribuable (création du compte).',
        }), 400
    
    db.session.add(boutique)
    db.session.flush()

    try:
        from spatial_utils import sync_boutique_geom
        sync_boutique_geom(db.session, boutique)
    except Exception:
        pass
    
    for taxe_data in taxes_data:
        taxe_id = taxe_data.get('taxe_id')
        if taxe_id:
            # Vérifier que la taxe existe
            taxe = Taxe.query.get(taxe_id)
            if taxe:
                boutique_taxe = BoutiqueTaxe(
                    boutique_id=boutique.id,
                    taxe_id=taxe_id,
                    montant_personnalise=taxe_data.get('montant_personnalise')
                )
                db.session.add(boutique_taxe)
    
    # Générer le QR code si POI validé
    if boutique.statut_validation == 'valide':
        qr_path = generate_qr_code(boutique.id, code_unique)
        boutique.qr_code_path = os.path.basename(qr_path)
    
    # Journaliser la collecte terrain (enregistrement POI)
    try:
        secteur = _get_secteur_boutique(boutique)
    except Exception:
        secteur = boutique.zone or boutique.arrondissement or 'Non renseigné'
    collecte = CollecteTerrain(
        date_heure=datetime.utcnow(),
        secteur=secteur or 'Non renseigné',
        collecteur_id=user_id,
        boutique_id=boutique.id
    )
    db.session.add(collecte)
    
    commercant_access = _attach_commercant_account(boutique)
    
    db.session.commit()
    try:
        from cache_utils import cache_delete_pattern
        cache_delete_pattern('boutiques_map')
        cache_delete_pattern('map_features')
    except Exception:
        pass
    
    payload = boutique.to_dict()
    if commercant_access:
        payload['commercant_access'] = commercant_access
    elif is_contribuable and not normalize_phone(boutique.telephone):
        payload['commercant_warning'] = (
            'Compte contribuable non créé : renseignez un numéro de téléphone sur la fiche POI.'
        )
    return jsonify(payload), 201


def _resolve_qr_filepath(stored_path):
    """Résout un chemin QR (legacy Windows / relatif) vers un fichier existant."""
    if not stored_path:
        return None
    stored = stored_path.strip().replace('\\', '/')
    upload_dir = app.config['UPLOAD_FOLDER']
    basename = os.path.basename(stored)
    candidates = []
    if os.path.isabs(stored):
        candidates.append(stored)
    candidates.extend([
        os.path.join(upload_dir, basename),
        os.path.join(BASE_DIR, stored),
        os.path.join(BASE_DIR, 'qr_codes', basename),
        os.path.join(upload_dir, stored.removeprefix('qr_codes/').removeprefix('qr_codes\\')),
    ])
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            return path
    return None


def ensure_boutique_qr_code(boutique, persist=True):
    """Retourne le chemin du QR code, le régénère si absent sur disque."""
    existing = _resolve_qr_filepath(boutique.qr_code_path)
    if existing:
        expected = os.path.basename(existing)
        if boutique.qr_code_path != expected:
            boutique.qr_code_path = expected
            if persist:
                db.session.commit()
        return existing
    if not boutique.code_unique:
        return None
    filepath = generate_qr_code(boutique.id, boutique.code_unique)
    boutique.qr_code_path = os.path.basename(filepath)
    if persist:
        db.session.commit()
    return filepath


def generate_qr_code(boutique_id, code_unique):
    """Générer un QR code pour une boutique"""
    # URL ou données à encoder dans le QR code
    qr_data = f"FISCAL:{code_unique}"
    
    # Créer le QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    
    # Créer l'image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Sauvegarder
    filename = f"boutique_{boutique_id}_{code_unique}.png"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img.save(filepath)
    
    return filepath


@app.route('/api/boutiques/<int:boutique_id>', methods=['GET'])
def get_boutique(boutique_id):
    """Récupérer une boutique spécifique"""
    boutique = Boutique.query.get_or_404(boutique_id)
    return jsonify(boutique.to_dict())


@app.route('/api/boutiques/<int:boutique_id>', methods=['PUT'])
def update_boutique(boutique_id):
    """Mettre à jour une boutique"""
    boutique = Boutique.query.get_or_404(boutique_id)
    data = request.json
    
    if 'nom' in data:
        boutique.nom = data['nom']
    if 'proprietaire' in data:
        boutique.proprietaire = data['proprietaire']
    if 'telephone' in data:
        boutique.telephone = data['telephone']
    if 'adresse' in data:
        boutique.adresse = data['adresse']
    if 'quartier_village_id' in data:
        boutique.quartier_village_id = data['quartier_village_id']
    if 'marche_id' in data:
        marche_id = data['marche_id']
        if marche_id:
            if not Marche.query.get(marche_id):
                return jsonify({'error': 'Marché non trouvé'}), 404
        boutique.marche_id = marche_id
    if 'marche_nom' in data:
        boutique.marche_nom = data['marche_nom']
    if 'latitude' in data:
        latitude = data['latitude']
        boutique.latitude = float(latitude) if latitude else None
    if 'longitude' in data:
        longitude = data['longitude']
        boutique.longitude = float(longitude) if longitude else None
    if 'type_commerce_id' in data:
        type_commerce_id = data['type_commerce_id'] or None
        if type_commerce_id:
            tc_upd = TypeCommerce.query.get(type_commerce_id)
            if not tc_upd:
                return jsonify({'error': 'Type de commerce non trouvé'}), 404
            boutique.type_commerce_id = type_commerce_id
            boutique.nature_poi = infer_nature_poi_from_type_commerce(tc_upd)
        else:
            boutique.type_commerce_id = None
            if 'nature_poi' in data:
                boutique.nature_poi = _normalize_nature_poi(data['nature_poi'])
    elif 'nature_poi' in data and not boutique.type_commerce_id:
        boutique.nature_poi = _normalize_nature_poi(data['nature_poi'])
    if 'taxes' in data:
        if not boutique.is_contribuable():
            pass
        else:
            BoutiqueTaxe.query.filter_by(boutique_id=boutique.id).delete()
            for taxe_data in data['taxes']:
                taxe_id = taxe_data.get('taxe_id')
                if taxe_id:
                    taxe = Taxe.query.get(taxe_id)
                    if taxe:
                        boutique_taxe = BoutiqueTaxe(
                            boutique_id=boutique.id,
                            taxe_id=taxe_id,
                            montant_personnalise=taxe_data.get('montant_personnalise')
                        )
                        db.session.add(boutique_taxe)
    if 'arrondissement' in data:
        boutique.arrondissement = data['arrondissement']
    if 'zone' in data:
        boutique.zone = data['zone']
    if 'marche' in data:
        boutique.marche = data['marche']
    if 'active' in data:
        boutique.active = data['active']
    if 'donnees_administratives' in data:
        donnees = normalize_donnees_administratives(
            boutique.nature_poi,
            data.get('donnees_administratives') or {},
            type_commerce_id=boutique.type_commerce_id,
        )
        boutique.donnees_administratives = (
            json.dumps(donnees, ensure_ascii=False) if donnees else None
        )
    if 'categorie' in data:
        boutique.categorie = _normalize_poi_categorie(data['categorie'])
    if 'feature_type' in data:
        boutique.feature_type = _normalize_poi_feature_type(data['feature_type'])
    if 'description' in data:
        boutique.description = (data.get('description') or '').strip() or None
    if 'statut_validation' in data:
        new_statut = data.get('statut_validation')
        if new_statut in POI_STATUTS_VALIDATION:
            user = User.query.get(session.get('user_id')) if session.get('user_id') else None
            if user and user.role == 'agent_terrain' and new_statut == 'valide':
                pass  # un agent ne peut pas auto-valider
            else:
                boutique.statut_validation = new_statut
                if new_statut == 'en_attente':
                    boutique.submitted_at = datetime.utcnow()
    if 'geometry' in data:
        geometry = parse_geometry(data['geometry']) if data['geometry'] else None
        properties = data.get('properties') if isinstance(data.get('properties'), dict) else boutique.get_properties_parsed()
        if geometry:
            _apply_poi_geometry_fields(boutique, geometry, properties)
        elif data['geometry'] is None:
            boutique.geometry = None
    elif 'properties' in data and isinstance(data['properties'], dict):
        props = data['properties']
        boutique.properties = json.dumps(props, ensure_ascii=False)
        if boutique.feature_type == 'pylon' and props.get('radius_m') is not None:
            boutique.radius_m = float(props['radius_m'])

    if 'pays_id' in data:
        _sync_boutique_pays_id(boutique, explicit_pays_id=data.get('pays_id'))
    else:
        _sync_boutique_pays_id(boutique)

    try:
        from spatial_utils import sync_boutique_geom
        sync_boutique_geom(db.session, boutique)
    except Exception:
        pass

    db.session.commit()
    try:
        from cache_utils import cache_delete_pattern
        cache_delete_pattern('boutiques_map')
        cache_delete_pattern('map_features')
    except Exception:
        pass
    return jsonify(boutique.to_dict())


@app.route('/api/boutiques/<int:boutique_id>', methods=['DELETE'])
def delete_boutique(boutique_id):
    """Désactiver un POI (préserve l'historique)"""
    boutique = Boutique.query.get_or_404(boutique_id)
    
    # Désactiver au lieu de supprimer pour préserver l'historique
    boutique.active = False
    db.session.commit()
    try:
        from cache_utils import cache_delete_pattern
        cache_delete_pattern('boutiques_map')
        cache_delete_pattern('map_features')
    except Exception:
        pass
    
    return jsonify({'message': 'POI désactivé'}), 200


@app.route('/api/boutiques/<int:boutique_id>/qr', methods=['GET'])
def get_qr_code(boutique_id):
    """Récupérer l'image du QR code d'un commerce"""
    boutique = Boutique.query.get_or_404(boutique_id)
    filepath = ensure_boutique_qr_code(boutique)
    if filepath and os.path.isfile(filepath):
        return send_file(filepath, mimetype='image/png')
    return jsonify({'error': 'QR code non trouvé'}), 404


@app.route('/api/boutiques/<int:boutique_id>/paiements', methods=['GET'])
def get_boutique_paiements(boutique_id):
    """Récupérer les paiements d'un commerce par institution"""
    boutique = Boutique.query.get_or_404(boutique_id)
    mois = request.args.get('mois', type=int)
    annee = request.args.get('annee', type=int)
    
    query = Paiement.query.filter_by(boutique_id=boutique_id, statut='confirme')
    
    if mois:
        query = query.filter_by(mois=mois)
    if annee:
        query = query.filter_by(annee=annee)
    
    paiements = query.order_by(Paiement.date_paiement.desc()).all()
    
    # Grouper par institution
    paiements_par_institut = {}
    for paiement in paiements:
        institut_code = paiement.institut.code if paiement.institut else 'INCONNU'
        if institut_code not in paiements_par_institut:
            paiements_par_institut[institut_code] = {
                'institut_nom': paiement.institut.nom if paiement.institut else 'Inconnu',
                'paiements': []
            }
        paiement_dict = paiement.to_dict()
        # Les informations de taxe sont déjà incluses dans to_dict()
        paiements_par_institut[institut_code]['paiements'].append(paiement_dict)
    
    return jsonify({
        'boutique': boutique.to_dict(),
        'paiements_par_institut': paiements_par_institut
    })


@app.route('/api/paiements/ussd', methods=['POST'])
def receive_ussd_payment():
    """Recevoir un paiement via USSD"""
    data = request.json or request.form
    
    # Format attendu : *123*IDBOUTIQUE*Montant#
    # Exemple : *123*BOUTIQUE-57891*5000#
    
    code_boutique = data.get('code_boutique') or data.get('boutique_id')
    montant = float(data.get('montant', 0))
    numero_telephone = data.get('numero_telephone', '')
    reference = data.get('reference_transaction', f"USSD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    institut_code = data.get('institut_code', 'IMPOTS')  # Par défaut: Impôts
    
    if not code_boutique:
        return jsonify({'error': 'Code boutique manquant'}), 400
    
    boutique = Boutique.query.filter_by(code_unique=code_boutique).first()
    if not boutique:
        return jsonify({'error': 'Boutique non trouvée'}), 404
    
    # Trouver l'institution
    institut = Institut.query.filter_by(code=institut_code.upper(), active=True).first()
    if not institut:
        return jsonify({'error': f'Institution "{institut_code}" non trouvée'}), 404
    
    # Trouver la taxe si spécifiée
    taxe = None
    taxe_code = data.get('taxe_code')
    if taxe_code:
        taxe = Taxe.query.filter_by(institut_id=institut.id, code=taxe_code.upper(), active=True).first()
        if not taxe:
            return jsonify({'error': f'Taxe "{taxe_code}" non trouvée pour cette institution'}), 404
    
    # Créer le paiement
    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year
    
    paiement = Paiement(
        boutique_id=boutique.id,
        institut_id=institut.id,
        taxe_id=taxe.id if taxe else None,
        montant=montant,
        mois=mois_actuel,
        annee=annee_actuelle,
        methode='USSD',
        numero_transaction=generer_numero_transaction(),
        reference_transaction=reference,
        numero_telephone=numero_telephone,
        statut='confirme'  # En production, pourrait être 'en_attente' jusqu'à confirmation
    )
    
    db.session.add(paiement)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Paiement enregistré',
        'paiement': paiement.to_dict()
    }), 201


@app.route('/api/paiements/mobile-money', methods=['POST'])
def receive_mobile_money_payment():
    """Recevoir un paiement via Mobile Money (webhook)"""
    data = request.json
    
    code_boutique = data.get('code_boutique') or data.get('boutique_id')
    montant = float(data.get('montant', 0))
    numero_telephone = data.get('numero_telephone', '')
    reference = data.get('reference_transaction', '')
    operateur = data.get('operateur', 'MTN')  # MTN ou AIRTEL
    institut_code = data.get('institut_code', 'IMPOTS')  # Par défaut: Impôts
    
    if not code_boutique:
        return jsonify({'error': 'Code boutique manquant'}), 400
    
    boutique = Boutique.query.filter_by(code_unique=code_boutique).first()
    if not boutique:
        return jsonify({'error': 'Boutique non trouvée'}), 404
    
    # Trouver l'institution
    institut = Institut.query.filter_by(code=institut_code.upper(), active=True).first()
    if not institut:
        return jsonify({'error': f'Institution "{institut_code}" non trouvée'}), 404
    
    # Trouver la taxe si spécifiée
    taxe = None
    taxe_code = data.get('taxe_code')
    if taxe_code:
        taxe = Taxe.query.filter_by(institut_id=institut.id, code=taxe_code.upper(), active=True).first()
        if not taxe:
            return jsonify({'error': f'Taxe "{taxe_code}" non trouvée pour cette institution'}), 404
    
    # Vérifier si la référence existe déjà
    if reference and Paiement.query.filter_by(reference_transaction=reference).first():
        return jsonify({'error': 'Transaction déjà enregistrée'}), 400
    
    # Créer le paiement
    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year
    
    paiement = Paiement(
        boutique_id=boutique.id,
        institut_id=institut.id,
        taxe_id=taxe.id if taxe else None,
        montant=montant,
        mois=mois_actuel,
        annee=annee_actuelle,
        methode=f'{operateur}_MONEY',
        numero_transaction=generer_numero_transaction(),
        reference_transaction=reference or f"{operateur}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        numero_telephone=numero_telephone,
        statut='confirme'
    )
    
    db.session.add(paiement)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Paiement enregistré',
        'paiement': paiement.to_dict()
    }), 201


def _get_secteur_boutique(boutique):
    """Construit le secteur (quartier, commune, zone) à partir de la boutique"""
    parts = []
    if boutique.quartier_village:
        parts.append(boutique.quartier_village.nom)
    if boutique.quartier_village and boutique.quartier_village.commune:
        parts.append(boutique.quartier_village.commune.nom)
    if boutique.arrondissement and boutique.arrondissement not in (p for p in parts):
        parts.append(boutique.arrondissement)
    if boutique.zone and boutique.zone not in (p for p in parts):
        parts.append(boutique.zone)
    return ' / '.join(parts) if parts else (boutique.zone or boutique.arrondissement or 'Non renseigné')


@app.route('/api/scan/<code_boutique>', methods=['GET'])
def scan_boutique(code_boutique):
    """Scanner un QR code et retourner le statut de la boutique"""
    boutique = Boutique.query.filter_by(code_unique=code_boutique).first()
    
    if not boutique:
        return jsonify({'error': 'Boutique non trouvée'}), 404
    
    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year
    
    # Récupérer uniquement les taxes associées à ce commerce via BoutiqueTaxe
    taxes_status = []
    boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=boutique.id, active=True).all()
    
    if not boutique_taxes:
        # Si aucune taxe n'est associée, retourner un message
        return jsonify({
            'boutique': boutique.to_dict(),
            'statut_paiement': 'NON_PAYE',
            'mois': mois_actuel,
            'annee': annee_actuelle,
            'taxes_status': [],
            'dernier_paiement': boutique.get_dernier_paiement().to_dict() if boutique.get_dernier_paiement() else None,
            'message': 'Aucune taxe configurée pour ce commerce'
        })
    
    for boutique_taxe in boutique_taxes:
        taxe = boutique_taxe.taxe
        if not taxe or not taxe.active:
            continue
        
        # Utiliser le montant personnalisé si défini, sinon le montant attendu de la taxe
        montant_attendu = boutique_taxe.montant_personnalise if boutique_taxe.montant_personnalise else taxe.montant_attendu
        
        paiement = Paiement.query.filter_by(
            boutique_id=boutique.id,
            taxe_id=taxe.id,
            mois=mois_actuel,
            annee=annee_actuelle,
            statut='confirme'
        ).first()
        
        taxes_status.append({
            'taxe': taxe.to_dict(),
            'institut_nom': taxe.institut.nom if taxe.institut else 'Inconnu',
            'payee': paiement is not None,
            'paiement': paiement.to_dict() if paiement else None,
            'montant_attendu': montant_attendu,
            'montant_paye': paiement.montant if paiement else 0,
            'difference': (paiement.montant - montant_attendu) if paiement else -montant_attendu
        })
    
    # Statut global : aucune taxe exigible impayée depuis la création du POI
    toutes_taxes_payees = boutique.get_statut_paiement_global()
    dernier_paiement = boutique.get_dernier_paiement()
    
    return jsonify({
        'boutique': boutique.to_dict(),
        'statut_paiement': 'PAYE' if toutes_taxes_payees else 'NON_PAYE',
        'mois': mois_actuel,
        'annee': annee_actuelle,
        'taxes_status': taxes_status,
        'dernier_paiement': dernier_paiement.to_dict() if dernier_paiement else None
    })


@app.route('/api/scan/<code_boutique>/simuler-paiement', methods=['POST'])
def simuler_paiement_scan(code_boutique):
    """Simuler un paiement pour une boutique (mode test - en attendant USSD/Mobile Money)"""
    boutique = Boutique.query.filter_by(code_unique=code_boutique).first()
    if not boutique:
        return jsonify({'error': 'Boutique non trouvée'}), 404

    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year

    # Trouver la première taxe non payée
    boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=boutique.id, active=True).all()
    for bt in boutique_taxes:
        taxe = bt.taxe
        if not taxe or not taxe.active:
            continue
        montant = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu
        existing = Paiement.query.filter_by(
            boutique_id=boutique.id, taxe_id=taxe.id,
            mois=mois_actuel, annee=annee_actuelle, statut='confirme'
        ).first()
        if not existing:
            ref = f'SIM-SCAN-{datetime.utcnow().strftime("%Y%m%d%H%M%S")}'
            paiement = Paiement(
                boutique_id=boutique.id,
                institut_id=taxe.institut_id,
                taxe_id=taxe.id,
                montant=montant,
                mois=mois_actuel,
                annee=annee_actuelle,
                methode='SIMULATION',
                numero_transaction=generer_numero_transaction(),
                reference_transaction=ref,
                statut='confirme'
            )
            db.session.add(paiement)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'Paiement simulé pour {taxe.nom}',
                'paiement': paiement.to_dict()
            }), 201

    return jsonify({'error': 'Toutes les taxes sont déjà payées pour ce mois'}), 400


@app.route('/api/statistiques', methods=['GET'])
@require_access('/', '/dashboard')
def get_statistiques():
    """Statistiques POI sur la période sélectionnée (même logique que les relevés)."""
    try:
        mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
        pays_id = resolve_pays_id()
        query = Boutique.query.filter_by(active=True)
        if pays_id:
            query = _filter_boutiques_by_pays(query, pays_id)
        boutiques = query.all()
        total_boutiques = len(boutiques)

        boutiques_a_jour = 0
        boutiques_non_a_jour = 0

        for boutique in boutiques:
            if boutique.get_statut_paiement_periode(mois_debut, annee_debut, mois_fin, annee_fin):
                boutiques_a_jour += 1
            else:
                boutiques_non_a_jour += 1

        paiements_periode = filter_paiements_periode(
            Paiement.query.filter_by(statut='confirme'),
            mois_debut, annee_debut, mois_fin, annee_fin,
        ).all()
        total_paiements_periode = sum(p.montant for p in paiements_periode)

        arrondissements = {}
        for boutique in boutiques:
            try:
                arr = boutique.arrondissement or 'Non spécifié'
                if arr not in arrondissements:
                    arrondissements[arr] = {'total': 0, 'a_jour': 0, 'non_a_jour': 0}
                arrondissements[arr]['total'] += 1
                if boutique.get_statut_paiement_periode(mois_debut, annee_debut, mois_fin, annee_fin):
                    arrondissements[arr]['a_jour'] += 1
                else:
                    arrondissements[arr]['non_a_jour'] += 1
            except Exception as e:
                print(f"Erreur lors du traitement de la boutique {boutique.id} pour arrondissement: {e}")
                continue

        return jsonify({
            'total_boutiques': total_boutiques,
            'boutiques_a_jour': boutiques_a_jour,
            'boutiques_non_a_jour': boutiques_non_a_jour,
            'taux_paiement': round((boutiques_a_jour / total_boutiques * 100) if total_boutiques > 0 else 0, 2),
            'total_paiements_mois': total_paiements_periode,
            'total_paiements_periode': total_paiements_periode,
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
            'mois': mois_fin,
            'annee': annee_fin,
            'par_arrondissement': arrondissements,
        })
    except Exception as e:
        print(f"Erreur dans get_statistiques: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération des statistiques', 'message': str(e)}), 500


def _arrondissement_label(boutique):
    """Libellé arrondissement/commune pour agrégations."""
    if boutique.arrondissement:
        return boutique.arrondissement
    try:
        if boutique.quartier_village and boutique.quartier_village.commune:
            return boutique.quartier_village.commune.nom
    except Exception:
        pass
    return 'Non spécifié'


def _quartier_label(boutique):
    try:
        return boutique.quartier_village.nom if boutique.quartier_village else 'Non spécifié'
    except Exception:
        return 'Non spécifié'


def _build_technical_analysis_stats(pays_id=None):
    """Analyse des champs techniques par type d'activité (données administratives POI)."""
    types = TypeCommerce.query.filter_by(active=True).order_by(TypeCommerce.nom).all()
    par_type = []
    champs_globaux = {}

    for tc in types:
        champs, _ = _get_champs_techniques_for_type(tc.id)
        if not champs:
            continue
        pois_query = Boutique.query.filter(
            Boutique.active.is_(True),
            Boutique.type_commerce_id == tc.id,
        )
        if pays_id:
            pois_query = _filter_boutiques_by_pays(pois_query, pays_id)
        pois = pois_query.all()
        if not pois:
            continue
        stats = _compute_technical_stats(pois, champs)
        champs_resume = []
        for c in stats.get('champs') or []:
            champs_resume.append({
                'code': c['code'],
                'label': c['label'],
                'type_champ': c['type_champ'],
                'rempli': c['rempli'],
                'taux_remplissage': c['taux_remplissage'],
                'numeric': c.get('numeric'),
            })
            key = c['code']
            if key not in champs_globaux:
                champs_globaux[key] = {
                    'code': key,
                    'label': c['label'],
                    'type_champ': c['type_champ'],
                    'types': [],
                    'total_rempli': 0,
                    'total_poi': 0,
                    'valeurs_numeriques': [],
                }
            champs_globaux[key]['types'].append(tc.nom)
            champs_globaux[key]['total_rempli'] += c['rempli']
            champs_globaux[key]['total_poi'] += stats['total_poi']
            if c.get('numeric'):
                champs_globaux[key]['valeurs_numeriques'].extend(
                    [c['numeric']['min'], c['numeric']['max'], c['numeric']['avg']],
                )

        par_type.append({
            'type_id': tc.id,
            'type_nom': tc.nom,
            'secteur': tc.secteur.nom if tc.secteur else None,
            'total_poi': stats['total_poi'],
            'poi_avec_donnees': stats['poi_avec_donnees'],
            'poi_complet': stats['poi_complet'],
            'poi_vide': stats['poi_vide'],
            'taux_completude_globale': stats['taux_completude_globale'],
            'taux_remplissage_moyen': stats['taux_remplissage_moyen'],
            'par_categorie': stats['par_categorie'],
            'champs': champs_resume,
        })

    par_type.sort(key=lambda x: x['total_poi'], reverse=True)

    champs_populaires = []
    for entry in champs_globaux.values():
        total = entry['total_poi']
        nums = entry['valeurs_numeriques']
        item = {
            'code': entry['code'],
            'label': entry['label'],
            'type_champ': entry['type_champ'],
            'types_count': len(set(entry['types'])),
            'total_rempli': entry['total_rempli'],
            'taux_remplissage': round(entry['total_rempli'] / total * 100, 1) if total else 0,
        }
        if nums and entry['type_champ'] in ('int', 'float'):
            item['numeric'] = {
                'min': min(nums),
                'max': max(nums),
                'avg': round(sum(nums) / len(nums), 2),
            }
        champs_populaires.append(item)
    champs_populaires.sort(key=lambda x: x['taux_remplissage'], reverse=True)

    return {
        'types_analysables': len(par_type),
        'total_poi_avec_champs': sum(t['total_poi'] for t in par_type),
        'par_type': par_type,
        'champs_populaires': champs_populaires[:25],
    }


def _build_conseiller_statistiques(mois_debut, annee_debut, mois_fin, annee_fin, pays_id=None):
    """Agrégats statistiques conseiller municipal, structurés par thème."""
    from collections import defaultdict
    from geo_metrics import MAP_FEATURE_TYPES

    boutiques_query = Boutique.query.filter_by(active=True)
    if pays_id:
        boutiques_query = _filter_boutiques_by_pays(boutiques_query, pays_id)
    boutiques = boutiques_query.all()
    contribuables = [b for b in boutiques if b.is_contribuable()]
    infrastructures = [b for b in boutiques if not b.is_contribuable()]

    par_type = defaultdict(int)
    par_type_contrib = defaultdict(int)
    par_secteur = defaultdict(int)
    par_categorie = {'contribuable': len(contribuables), 'infrastructure': len(infrastructures)}
    par_forme = defaultdict(int)
    par_validation = defaultdict(int)
    par_validation_contrib = defaultdict(int)
    par_validation_infra = defaultdict(int)
    par_arrondissement = defaultdict(int)
    par_quartier = defaultdict(int)
    par_type_arrondissement_quartier = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    infra_par_forme = defaultdict(int)
    infra_par_type = defaultdict(int)
    infra_par_validation = defaultdict(int)
    total_length_m = 0.0
    total_area_ha = 0.0
    total_perimeter_m = 0.0
    infra_pipelines = 0
    infra_parcelles = 0
    infra_perimetres = 0
    infra_pylons = 0
    sans_localisation = 0

    fiscal_par_arr = defaultdict(lambda: {
        'total': 0, 'a_jour': 0, 'non_a_jour': 0,
        'montant_attendu': 0.0, 'montant_recouvre': 0.0,
    })

    contrib_a_jour = 0
    contrib_non_a_jour = 0
    montant_attendu_global = 0.0
    montant_recouvre_global = 0.0

    for b in boutiques:
        nom_type = b.type_commerce.nom if b.type_commerce else 'Non spécifié'
        secteur = (
            b.type_commerce.secteur.nom
            if b.type_commerce and b.type_commerce.secteur else 'Non spécifié'
        )
        forme = b.feature_type or 'point'
        forme_label = MAP_FEATURE_TYPES.get(forme, {}).get('label', forme.capitalize())
        statut = b.statut_validation or 'brouillon'
        arr = _arrondissement_label(b)
        quart = _quartier_label(b)

        par_type[nom_type] += 1
        par_secteur[secteur] += 1
        par_forme[forme_label] += 1
        par_validation[statut] += 1
        par_arrondissement[arr] += 1
        par_quartier[quart] += 1
        par_type_arrondissement_quartier[nom_type][arr][quart] += 1

        if b.is_contribuable():
            par_validation_contrib[statut] += 1
            if (b.statut_validation or 'valide') == 'valide':
                par_type_contrib[nom_type] += 1
            a_jour = b.get_statut_paiement_periode(mois_debut, annee_debut, mois_fin, annee_fin)
            if a_jour:
                contrib_a_jour += 1
            else:
                contrib_non_a_jour += 1
            montants = b.get_montants_periode(mois_debut, annee_debut, mois_fin, annee_fin)
            attendu = montants.get('montant_a_recouvrer') or 0
            recouvre = montants.get('montant_recouvre') or 0
            montant_attendu_global += attendu
            montant_recouvre_global += recouvre
            fa = fiscal_par_arr[arr]
            fa['total'] += 1
            fa['montant_attendu'] += attendu
            fa['montant_recouvre'] += recouvre
            if a_jour:
                fa['a_jour'] += 1
            else:
                fa['non_a_jour'] += 1
        else:
            par_validation_infra[statut] += 1
            infra_par_forme[forme_label] += 1
            infra_par_type[nom_type] += 1
            infra_par_validation[statut] += 1
            has_coords = (
                b.latitude is not None and b.longitude is not None
                and b.latitude != 0 and b.longitude != 0
            )
            has_geom = bool(b.get_geometry_parsed())
            if not has_coords and not has_geom:
                sans_localisation += 1
            if forme == 'pipeline':
                infra_pipelines += 1
                total_length_m += float(b.length_m or 0)
            if forme == 'parcel':
                infra_parcelles += 1
                total_area_ha += float(b.area_ha or 0)
            if forme == 'perimeter':
                infra_perimetres += 1
                total_perimeter_m += float(b.perimeter_m or 0)
            if forme == 'pylon':
                infra_pylons += 1

    par_type_arr_serial = {}
    for type_nom, arr_dict in par_type_arrondissement_quartier.items():
        par_type_arr_serial[type_nom] = {
            arr_nom: dict(quart_dict) for arr_nom, quart_dict in arr_dict.items()
        }

    balance_instituts = _compute_balance_par_institut(
        mois_debut, annee_debut, mois_fin, annee_fin,
    )
    balance_taxes = _compute_balance_par_taxe(
        mois_debut, annee_debut, mois_fin, annee_fin,
    )

    paiements_periode = filter_paiements_periode(
        Paiement.query.filter_by(statut='confirme'),
        mois_debut, annee_debut, mois_fin, annee_fin,
    ).all()
    by_month = defaultdict(float)
    for p in paiements_periode:
        by_month[(p.annee, p.mois)] += float(p.montant or 0)

    paiements_par_mois = []
    mois_labels = [
        'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
        'Juil', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc',
    ]
    for m, a in Boutique._iter_mois_periodes(mois_debut, annee_debut, mois_fin, annee_fin):
        paiements_par_mois.append({
            'key': f'{a}-{m:02d}',
            'label': f'{mois_labels[m - 1]} {a}',
            'montant': round(by_month.get((a, m), 0.0), 2),
        })

    reste_global = max(0.0, montant_attendu_global - montant_recouvre_global)
    n_contrib = len(contribuables)

    pois_sans_pays = sum(
        1 for b in boutiques
        if not _boutique_admin_pays_id(b) and not b.pays_id
    )

    fiscal_arr_list = []
    for arr, data in sorted(fiscal_par_arr.items(), key=lambda x: x[1]['montant_attendu'], reverse=True):
        fiscal_arr_list.append({
            'arrondissement': arr,
            **data,
            'montant_attendu': round(data['montant_attendu'], 2),
            'montant_recouvre': round(data['montant_recouvre'], 2),
        })

    n_contrib_valide = sum(
        1 for b in contribuables if (b.statut_validation or 'valide') == 'valide'
    )

    top_quartiers = sorted(par_quartier.items(), key=lambda x: x[1], reverse=True)[:15]

    pylon_coverage = {'pylons': [], 'summary': {'count': 0}}
    try:
        from spatial_utils import compute_pylon_coverage
        pylon_coverage = compute_pylon_coverage(db.session, db.engine, pays_id=pays_id)
    except Exception as exc:
        print(f'Avertissement couverture pylônes (stats): {exc}')

    analyse_technique = {'types_analysables': 0, 'total_poi_avec_champs': 0, 'par_type': [], 'champs_populaires': []}
    try:
        analyse_technique = _build_technical_analysis_stats(pays_id=pays_id)
    except Exception as exc:
        print(f'Avertissement analyse technique (stats): {exc}')

    return {
        'periode': {
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
        },
        'pays': _get_pays_session_payload(pays_id),
        'vue_ensemble': {
            'total_poi': len(boutiques),
            'contribuables': n_contrib,
            'infrastructures': len(infrastructures),
            'pois_sans_pays': pois_sans_pays if not pays_id else 0,
            'contribuables_a_jour': contrib_a_jour,
            'contribuables_non_a_jour': contrib_non_a_jour,
            'taux_paiement': round(contrib_a_jour / n_contrib * 100, 1) if n_contrib else 0,
            'montant_attendu': round(montant_attendu_global, 2),
            'montant_recouvre': round(montant_recouvre_global, 2),
            'montant_reste': round(reste_global, 2),
            'taux_recouvrement': round(
                montant_recouvre_global / montant_attendu_global * 100, 1,
            ) if montant_attendu_global > 0 else 0,
            'validations_en_attente': par_validation.get('en_attente', 0),
            'validations_rejetees': par_validation.get('rejete', 0),
        },
        'referentiel': {
            'par_type': dict(sorted(par_type.items(), key=lambda x: x[1], reverse=True)),
            'par_secteur': dict(sorted(par_secteur.items(), key=lambda x: x[1], reverse=True)),
            'par_categorie': par_categorie,
            'par_forme': dict(par_forme),
        },
        'geographie': {
            'par_arrondissement': dict(sorted(par_arrondissement.items(), key=lambda x: x[1], reverse=True)),
            'par_quartier': dict(top_quartiers),
            'par_type_arrondissement_quartier': par_type_arr_serial,
        },
        'fiscal': {
            'par_arrondissement': fiscal_arr_list,
            'par_institut': [
                {
                    'nom': r['institut_nom'],
                    'montant_attendu': r['montant_attendu'],
                    'montant_recouvre': r['montant_recouvre'],
                    'montant_non_recouvre': r['montant_non_recouvre'],
                    'taux_recouvrement': r['taux_recouvrement'],
                }
                for r in balance_instituts if r['montant_attendu'] > 0
            ],
            'par_taxe': [
                {
                    'nom': r['taxe_nom'],
                    'montant_attendu': r['montant_attendu'],
                    'montant_recouvre': r['montant_recouvre'],
                    'montant_non_recouvre': r['montant_non_recouvre'],
                }
                for r in balance_taxes if r['montant_attendu'] > 0
            ],
            'paiements_par_mois': paiements_par_mois,
            'statut_paiement': {
                'a_jour': contrib_a_jour,
                'non_a_jour': contrib_non_a_jour,
            },
        },
        'infrastructures': {
            'total': len(infrastructures),
            'par_forme': dict(infra_par_forme),
            'par_type': dict(sorted(infra_par_type.items(), key=lambda x: x[1], reverse=True)),
            'par_validation': dict(infra_par_validation),
            'total_length_m': round(total_length_m, 1),
            'total_area_ha': round(total_area_ha, 3),
            'total_perimeter_m': round(total_perimeter_m, 1),
            'pipelines': infra_pipelines,
            'parcelles': infra_parcelles,
            'perimetres': infra_perimetres,
            'pylons': infra_pylons,
            'sans_localisation': sans_localisation,
            'couverture_pylons': pylon_coverage,
            'metriques_spatiales': {
                'pipelines': {
                    'count': infra_pipelines,
                    'total_length_m': round(total_length_m, 1),
                },
                'parcelles': {
                    'count': infra_parcelles,
                    'total_area_ha': round(total_area_ha, 3),
                },
                'perimetres': {
                    'count': infra_perimetres,
                    'total_perimeter_m': round(total_perimeter_m, 1),
                },
                'pylons': pylon_coverage.get('summary') or {},
            },
        },
        'analyse_technique': analyse_technique,
        'contribuables': {
            'total': n_contrib_valide,
            'par_type': dict(sorted(par_type_contrib.items(), key=lambda x: x[1], reverse=True)),
            'par_validation': dict(par_validation_contrib),
        },
        'validation': {
            'par_statut': dict(par_validation),
            'contribuables': dict(par_validation_contrib),
            'infrastructures': dict(par_validation_infra),
        },
        # Compatibilité ancienne page
        'total_commerces': len(boutiques),
        'par_type': dict(par_type),
        'par_arrondissement': dict(par_arrondissement),
        'par_quartier': dict(par_quartier),
        'par_type_arrondissement_quartier': par_type_arr_serial,
    }


@app.route('/api/statistiques/conseiller', methods=['GET'])
@require_access('/statistiques')
def get_statistiques_conseiller():
    """Statistiques conseiller municipal : KPI, référentiel, géo, fiscal, infra, validation."""
    try:
        mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
        pays_id = resolve_pays_id()
        data = _build_conseiller_statistiques(mois_debut, annee_debut, mois_fin, annee_fin, pays_id=pays_id)
        return jsonify(data)
    except Exception as e:
        print(f"Erreur dans get_statistiques_conseiller: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération des statistiques', 'message': str(e)}), 500


@app.route('/api/balance-instituts', methods=['GET'])
@require_access('/', '/dashboard')
def get_balance_instituts():
    """Récupérer la balance des montants recouvrés et non recouvrés par institution"""
    try:
        mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
        institut_id = request.args.get('institut_id', type=int)
        taxe_id = request.args.get('taxe_id', type=int)

        result = _compute_balance_par_institut(
            mois_debut, annee_debut, mois_fin, annee_fin,
            institut_id=institut_id, taxe_id=taxe_id,
        )

        return jsonify({
            'balance_par_institut': result,
            'total_attendu': round(sum(r['montant_attendu'] for r in result), 2),
            'total_recouvre': round(sum(r['montant_recouvre'] for r in result), 2),
            'total_non_recouvre': round(sum(r['montant_non_recouvre'] for r in result), 2),
            'institut_id': institut_id,
            'taxe_id': taxe_id,
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
        })
    except Exception as e:
        print(f"Erreur dans get_balance_instituts: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération de la balance', 'message': str(e)}), 500


@app.route('/api/balance-par-taxes', methods=['GET'])
@require_access('/balances', '/dashboard')
def get_balance_par_taxes():
    """Balance financière par taxe (montants attendus et recouvrés)"""
    try:
        mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
        taxe_id = request.args.get('taxe_id', type=int)

        balance_taxes = _compute_balance_par_taxe(
            mois_debut, annee_debut, mois_fin, annee_fin, taxe_id=taxe_id,
        )

        total_attendu = round(sum(t['montant_attendu'] for t in balance_taxes), 2)
        total_recouvre = round(sum(t['montant_recouvre'] for t in balance_taxes), 2)
        total_non_recouvre = round(sum(t['montant_non_recouvre'] for t in balance_taxes), 2)

        return jsonify({
            'balance_par_taxe': balance_taxes,
            'total_attendu': total_attendu,
            'total_recouvre': total_recouvre,
            'total_non_recouvre': total_non_recouvre,
            'taxe_id': taxe_id,
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
        })
    except Exception as e:
        print(f"Erreur get_balance_par_taxes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/balance-repartition', methods=['GET'])
@require_access('/balances', '/dashboard')
def get_balance_repartition():
    """Répartition du montant recouvré entre les partenaires (base = balance alignée POI)."""
    try:
        mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
        taxe_id = request.args.get('taxe_id', type=int)

        balance_taxes = _compute_balance_par_taxe(
            mois_debut, annee_debut, mois_fin, annee_fin, taxe_id=taxe_id,
        )
        total_attendu = round(sum(t['montant_attendu'] for t in balance_taxes), 2)
        total_recouvre = round(sum(t['montant_recouvre'] for t in balance_taxes), 2)

        pct_institution = float(Configuration.get('repartition_institution', 80))
        pct_partenaire = float(Configuration.get('repartition_partenaire_technique', 17))
        pct_mtn = float(Configuration.get('repartition_mtn', 3))
        pct_total = round(pct_institution + pct_partenaire + pct_mtn, 2)

        parts = [
            ('institution', pct_institution, 'Institution'),
            ('partenaire_technique', pct_partenaire, 'Partenaire technique'),
            ('mtn', pct_mtn, 'MTN'),
        ]
        repartition = {}
        remaining = total_recouvre
        for idx, (key, pct, label) in enumerate(parts):
            if idx == len(parts) - 1:
                montant = round(remaining, 2)
            else:
                montant = round(total_recouvre * (pct / 100), 2)
                remaining -= montant
            repartition[key] = {
                'label': label,
                'pourcentage': pct,
                'montant': montant,
                'part_du_recouvrement': round(
                    (montant / total_recouvre * 100) if total_recouvre > 0 else 0, 1,
                ),
            }

        return jsonify({
            'total_attendu': total_attendu,
            'total_recouvre': total_recouvre,
            'total_non_recouvre': round(max(0.0, total_attendu - total_recouvre), 2),
            'pct_total': pct_total,
            'pct_valid': abs(pct_total - 100) < 0.01,
            'taxe_id': taxe_id,
            'mois_debut': mois_debut,
            'annee_debut': annee_debut,
            'mois_fin': mois_fin,
            'annee_fin': annee_fin,
            'repartition': repartition,
        })
    except Exception as e:
        print(f"Erreur get_balance_repartition: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/configurations', methods=['GET'])
def get_configurations():
    """Récupérer toutes les configurations"""
    configs = Configuration.query.all()
    return jsonify({c.cle: {'valeur': c.valeur, 'description': c.description} for c in configs})


@app.route('/api/users', methods=['GET'])
@role_required('admin', 'conseiller_municipal')
def get_users():
    """Liste des utilisateurs (admin)"""
    users = User.query.order_by(User.username).all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/users', methods=['POST'])
@role_required('admin', 'conseiller_municipal')
def create_user():
    """Créer un utilisateur (admin)"""
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    if not username:
        return jsonify({'error': 'Identifiant requis'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Mot de passe minimum 6 caractères'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Cet identifiant existe déjà'}), 400
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        nom=data.get('nom'),
        role=data.get('role', 'agent_terrain'),
        actif=data.get('actif', True)
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@app.route('/api/users/<int:user_id>', methods=['GET'])
@role_required('admin', 'conseiller_municipal')
def get_user(user_id):
    """Récupérer un utilisateur (admin)"""
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@role_required('admin', 'conseiller_municipal')
def update_user(user_id):
    """Modifier un utilisateur (admin)"""
    user = User.query.get_or_404(user_id)
    data = request.get_json() or {}
    if 'nom' in data:
        user.nom = data['nom']
    if 'role' in data:
        user.role = data['role']
    if 'actif' in data:
        user.actif = data['actif']
    if data.get('password'):
        user.password_hash = generate_password_hash(data['password'])
    db.session.commit()
    return jsonify(user.to_dict())


@app.route('/api/configurations', methods=['PUT'])
def update_configurations():
    """Mettre à jour les configurations"""
    data = request.get_json() or {}
    for cle, valeur in data.items():
        if isinstance(valeur, dict):
            valeur = valeur.get('valeur', str(valeur))
        Configuration.set(cle, str(valeur))
    return jsonify({'success': True})


@app.route('/api/export/excel', methods=['GET'])
def export_excel():
    """Exporter les données en Excel"""
    arrondissement = request.args.get('arrondissement')
    zone = request.args.get('zone')
    
    query = Boutique.query.filter_by(active=True)
    if arrondissement:
        query = query.filter_by(arrondissement=arrondissement)
    if zone:
        query = query.filter_by(zone=zone)
    
    boutiques = query.all()
    
    # Créer un workbook Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "POI GeoTax"
    
    # En-têtes
    headers = ['Code', 'Nom', 'Propriétaire', 'Téléphone', 'Adresse', 'Arrondissement', 'Zone', 'Marché', 'Statut Paiement', 'Dernier Paiement']
    ws.append(headers)
    
    for boutique in boutiques:
        a_jour = boutique.get_statut_paiement_global()
        dernier_paiement = boutique.get_dernier_paiement()
        
        ws.append([
            boutique.code_unique,
            boutique.nom,
            boutique.proprietaire or '',
            boutique.telephone or '',
            boutique.adresse or '',
            boutique.arrondissement or '',
            boutique.zone or '',
            boutique.marche or '',
            'PAYÉ' if a_jour else 'NON PAYÉ',
            dernier_paiement.date_paiement.strftime('%d/%m/%Y') if dernier_paiement else 'Aucun'
        ])
    
    # Sauvegarder en mémoire
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"rapport_poi_geotax_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)


@app.route('/scan')
@require_access('/scan')
def scan_page():
    """Page de scan QR code pour les contrôleurs"""
    return render_template('scan.html')


@app.route('/pois')
@app.route('/boutiques')
@app.route('/commerces')
@require_access('/pois')
def pois_page():
    """Page GeoTax — gestion des points d'intérêt (POI)."""
    return render_template('pois.html')


@app.route('/parametrage')
@require_access('/parametrage')
def parametrage_page():
    """Page de paramétrage géographique"""
    return render_template('parametrage.html')


@app.route('/balances')
@require_access('/balances')
def balances_page():
    """Page des balances financières"""
    return render_template('balances.html')


@app.route('/statistiques')
@require_access('/statistiques')
def statistiques_page():
    """Page statistiques pour conseiller municipal"""
    return render_template('statistiques.html')


@app.route('/carte')
@require_access('/carte')
def carte_page():
    """Page de visualisation des POI sur la carte"""
    commerce_id = request.args.get('poi_id') or request.args.get('commerce_id')
    commerce_code = request.args.get('commerce_code')
    add_mode = request.args.get('add') == '1'
    lat = request.args.get('lat')
    lng = request.args.get('lng')
    return render_template(
        'carte.html',
        commerce_id=commerce_id,
        commerce_code=commerce_code,
        add_mode=add_mode,
        add_lat=lat,
        add_lng=lng,
        google_maps_api_key=app.config['GOOGLE_MAPS_API_KEY'],
    )


@app.route('/api/geocode', methods=['GET'])
@require_access('/carte', '/pois')
def geocode_address():
    """Géocodage d'adresse via Nominatim (OpenStreetMap)."""
    query = request.args.get('q', '').strip()
    if len(query) < 3:
        return jsonify([])

    try:
        params = {
            'format': 'json',
            'q': query,
            'limit': 8,
            'addressdetails': 1,
            'countrycodes': 'cg',
        }
        viewbox = request.args.get('viewbox', '').strip()
        if viewbox:
            params['viewbox'] = viewbox
            params['bounded'] = 1

        response = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params=params,
            headers={'User-Agent': 'GeoTax/1.0 (gestion fiscale POI)'},
            timeout=10,
        )
        response.raise_for_status()

        results = []
        for item in response.json():
            try:
                results.append({
                    'lat': float(item['lat']),
                    'lng': float(item['lon']),
                    'label': item.get('display_name', query),
                    'type': item.get('type') or item.get('class') or '',
                })
            except (KeyError, TypeError, ValueError):
                continue

        if not results:
            response = requests.get(
                'https://nominatim.openstreetmap.org/search',
                params={
                    'format': 'json',
                    'q': f'{query}, Brazzaville, Congo',
                    'limit': 8,
                    'addressdetails': 1,
                },
                headers={'User-Agent': 'GeoTax/1.0 (gestion fiscale POI)'},
                timeout=10,
            )
            response.raise_for_status()
            for item in response.json():
                try:
                    results.append({
                        'lat': float(item['lat']),
                        'lng': float(item['lon']),
                        'label': item.get('display_name', query),
                        'type': item.get('type') or item.get('class') or '',
                    })
                except (KeyError, TypeError, ValueError):
                    continue

        return jsonify(results)
    except requests.RequestException as e:
        print(f'Erreur géocodage Nominatim: {e}')
        return jsonify({'error': 'Service de géocodage indisponible'}), 502
    except Exception as e:
        print(f'Erreur geocode_address: {e}')
        return jsonify({'error': 'Erreur lors du géocodage'}), 500


def _apply_map_feature_metrics(feature, geometry, properties):
    validate_geometry(geometry, feature.feature_type)
    validate_feature_properties(feature.feature_type, properties or {})
    metrics = compute_metrics(geometry, feature.feature_type, properties or {})
    feature.length_m = metrics.get('length_m')
    feature.area_ha = metrics.get('area_ha')
    feature.perimeter_m = metrics.get('perimeter_m')
    feature.radius_m = metrics.get('radius_m')


def _parse_bbox_param():
    bbox = request.args.get('bbox', '').strip()
    if not bbox:
        return None
    try:
        parts = [float(x.strip()) for x in bbox.split(',')]
        if len(parts) != 4:
            return None
        return tuple(parts)
    except (TypeError, ValueError):
        return None


@app.route('/api/map-features', methods=['GET', 'POST'])
@require_access('/carte', '/pois', '/validation')
def map_features_api():
    """GeoJSON des POI à géométrie avancée (toutes catégories)."""
    if request.method == 'GET':
        try:
            types_param = request.args.get('types', '').strip()
            type_filter = [t.strip() for t in types_param.split(',') if t.strip()] if types_param else None
            statut = request.args.get('statut_validation', '').strip()
            bbox = _parse_bbox_param()
            categorie = request.args.get('categorie', '').strip().lower()

            from cache_utils import cache_get, cache_set, cache_key
            from spatial_utils import apply_bbox_filter_query, filter_rows_by_bbox_python

            pays_id = resolve_pays_id()
            cache_ck = None
            if bbox:
                cache_ck = cache_key(
                    'map_features', bbox, types_param, statut, categorie, pays_id,
                )
                cached = cache_get(cache_ck)
                if cached is not None:
                    return jsonify(cached)

            query = _query_geo_shape_pois()
            if pays_id:
                query = _filter_boutiques_by_pays(query, pays_id)
            if categorie in POI_CATEGORIES:
                query = query.filter(Boutique.categorie == categorie)
            if type_filter:
                query = query.filter(Boutique.feature_type.in_(type_filter))
            if statut:
                query = query.filter(Boutique.statut_validation == statut)

            limit = min(int(request.args.get('limit', 2000)), 5000)
            if bbox:
                query, _ = apply_bbox_filter_query(query, bbox, include_missing_geom=True)

            rows = query.order_by(Boutique.date_creation.desc()).limit(limit).all()
            if bbox:
                rows = filter_rows_by_bbox_python(rows, bbox, lambda r: r.get_geometry_parsed())

            features = [row.to_geojson_feature() for row in rows]

            # Repli legacy map_features non migrés (ou migrés sans coordonnées sync)
            if not features:
                legacy_q = MapFeature.query.filter_by(active=True)
                if type_filter:
                    legacy_q = legacy_q.filter(MapFeature.feature_type.in_(type_filter))
                for row in legacy_q.all():
                    if Boutique.query.filter_by(legacy_map_feature_id=row.id, active=True).first():
                        continue
                    geom = row.get_geometry_parsed()
                    if bbox and geom:
                        bounds = geometry_bounds(geom)
                        if bounds and not bboxes_intersect(bounds, bbox):
                            continue
                    features.append(row.to_geojson_feature())

            payload = {
                'type': 'FeatureCollection',
                'features': features,
                'meta': {
                    'types': MAP_FEATURE_TYPES,
                    'count': len(features),
                    'bbox': list(bbox) if bbox else None,
                },
            }
            if cache_ck:
                cache_set(cache_ck, payload, ttl_seconds=45)
            return jsonify(payload)
        except Exception as e:
            print(f'Erreur GET map-features: {e}')
            return jsonify({'error': str(e)}), 500

    try:
        data = request.get_json() or {}
        feature_type = _normalize_poi_feature_type(data.get('feature_type'))
        if feature_type == 'point':
            return jsonify({'error': 'Utilisez /api/boutiques pour un POI point'}), 400

        name = (data.get('name') or data.get('nom') or '').strip()
        if not name:
            return jsonify({'error': 'Le nom est obligatoire'}), 400

        geometry = parse_geometry(data.get('geometry'))
        properties = data.get('properties') or {}
        if not isinstance(properties, dict):
            properties = {}

        type_commerce_id = data.get('type_commerce_id')
        categorie = _normalize_poi_categorie(data.get('categorie', POI_CATEGORY_INFRASTRUCTURE))
        is_contribuable = categorie == POI_CATEGORY_CONTRIBUABLE

        tc_obj = TypeCommerce.query.get(type_commerce_id) if type_commerce_id else None
        if type_commerce_id and not tc_obj:
            return jsonify({'error': 'Type d\'activité introuvable'}), 404

        donnees = {}
        if type_commerce_id:
            donnees = normalize_donnees_administratives(
                None, data.get('donnees_administratives') or {}, type_commerce_id=type_commerce_id
            )
        don_json = json.dumps(donnees, ensure_ascii=False) if donnees else None

        code_unique = data.get('code_unique') or f"GEO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        if Boutique.query.filter_by(code_unique=code_unique).first():
            return jsonify({'error': 'Ce code existe déjà'}), 400

        boutique = Boutique(
            code_unique=code_unique,
            nom=name,
            categorie=categorie,
            feature_type=feature_type,
            description=(data.get('description') or '').strip() or None,
            type_commerce_id=type_commerce_id,
            donnees_administratives=don_json,
            collector_id=session.get('user_id'),
            active=True,
        )
        draft = bool(data.get('save_as_draft'))
        _apply_poi_validation_on_create(boutique, draft=draft)
        _apply_poi_geometry_fields(boutique, geometry, properties)
        if properties:
            boutique.properties = json.dumps(properties, ensure_ascii=False)
        _sync_boutique_pays_id(boutique, explicit_pays_id=data.get('pays_id'))

        db.session.add(boutique)
        db.session.flush()

        if is_contribuable:
            taxes_data = data.get('taxes') or []
            if not taxes_data:
                db.session.rollback()
                return jsonify({'error': 'Au moins une taxe requise pour un contribuable'}), 400
            for taxe_data in taxes_data:
                taxe_id = taxe_data.get('taxe_id')
                if taxe_id and Taxe.query.get(taxe_id):
                    db.session.add(BoutiqueTaxe(
                        boutique_id=boutique.id,
                        taxe_id=taxe_id,
                        montant_personnalise=taxe_data.get('montant_personnalise'),
                    ))

        db.session.commit()
        return jsonify(_boutique_to_legacy_map_dict(boutique)), 201
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        print(f'Erreur POST map-features: {e}')
        return jsonify({'error': 'Erreur lors de la création'}), 500


@app.route('/api/map-features/<int:feature_id>', methods=['GET', 'PATCH', 'DELETE'])
@require_access('/carte', '/pois', '/validation')
def map_feature_detail(feature_id):
    poi = _resolve_geo_poi(feature_id)
    if not poi:
        return jsonify({'error': 'POI introuvable'}), 404

    if isinstance(poi, Boutique):
        if request.method == 'GET':
            return jsonify(_boutique_to_legacy_map_dict(poi))

        if request.method == 'DELETE':
            if session.get('role') not in ('admin', 'conseiller_municipal') and poi.collector_id != session.get('user_id'):
                return jsonify({'error': 'Non autorisé'}), 403
            poi.active = False
            db.session.commit()
            return jsonify({'success': True})

        try:
            data = request.get_json() or {}
            if 'name' in data or 'nom' in data:
                poi.nom = (data.get('name') or data.get('nom') or '').strip() or poi.nom
            if 'description' in data:
                poi.description = (data.get('description') or '').strip() or None
            if 'type_commerce_id' in data:
                poi.type_commerce_id = data.get('type_commerce_id')
            if 'statut_validation' in data:
                poi.statut_validation = data.get('statut_validation')
            if 'categorie' in data:
                poi.categorie = _normalize_poi_categorie(data.get('categorie'))

            tc_id = poi.type_commerce_id
            if 'donnees_administratives' in data and tc_id:
                donnees = normalize_donnees_administratives(
                    None, data.get('donnees_administratives') or {}, type_commerce_id=tc_id
                )
                poi.donnees_administratives = json.dumps(donnees, ensure_ascii=False) if donnees else None

            properties = poi.get_properties_parsed()
            if 'properties' in data and isinstance(data.get('properties'), dict):
                properties = {**properties, **data['properties']}
                poi.properties = json.dumps(properties, ensure_ascii=False)

            geometry = poi.get_geometry_parsed()
            if 'geometry' in data:
                geometry = parse_geometry(data.get('geometry'))
            if geometry:
                _apply_poi_geometry_fields(poi, geometry, properties)

            db.session.commit()
            return jsonify(_boutique_to_legacy_map_dict(poi))
        except ValueError as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            db.session.rollback()
            print(f'Erreur PATCH map-feature/poi: {e}')
            return jsonify({'error': 'Erreur lors de la mise à jour'}), 500

    # Legacy MapFeature
    feature = poi
    if request.method == 'GET':
        return jsonify(feature.to_dict())

    if request.method == 'DELETE':
        if session.get('role') not in ('admin', 'conseiller_municipal') and feature.collector_id != session.get('user_id'):
            return jsonify({'error': 'Non autorisé'}), 403
        feature.active = False
        db.session.commit()
        return jsonify({'success': True})

    try:
        data = request.get_json() or {}
        if 'name' in data:
            feature.name = (data.get('name') or '').strip() or feature.name
        if 'description' in data:
            feature.description = (data.get('description') or '').strip() or None
        if 'type_commerce_id' in data:
            feature.type_commerce_id = data.get('type_commerce_id')
        if 'statut_validation' in data:
            feature.statut_validation = data.get('statut_validation')

        tc_id = feature.type_commerce_id
        if 'donnees_administratives' in data and tc_id:
            properties = feature.get_properties_parsed()
            donnees = normalize_donnees_administratives(
                None, data.get('donnees_administratives') or {}, type_commerce_id=tc_id
            )
            properties['donnees_administratives'] = donnees
            feature.properties = json.dumps(properties)

        geometry = feature.get_geometry_parsed()
        properties = feature.get_properties_parsed()
        if 'geometry' in data:
            geometry = parse_geometry(data.get('geometry'))
            feature.geometry = json.dumps(geometry)
        if 'properties' in data and isinstance(data.get('properties'), dict):
            properties = {**properties, **data['properties']}
            feature.properties = json.dumps(properties)

        _apply_map_feature_metrics(feature, geometry, properties)
        db.session.commit()
        return jsonify(feature.to_dict())
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        print(f'Erreur PATCH map-feature: {e}')
        return jsonify({'error': 'Erreur lors de la mise à jour'}), 500


@app.route('/api/map-features/types', methods=['GET'])
@require_access('/carte', '/pois')
def map_feature_types():
    return jsonify(MAP_FEATURE_TYPES)


@app.route('/api/pylons/coverage', methods=['GET'])
@require_access('/carte', '/pois', '/validation')
def pylons_coverage_api():
    """Pylônes avec rayons d'influence et surface de couverture (union PostGIS)."""
    try:
        ids_param = request.args.get('ids', '').strip()
        pylon_ids = None
        if ids_param:
            try:
                pylon_ids = [int(x.strip()) for x in ids_param.split(',') if x.strip()]
            except ValueError:
                return jsonify({'error': 'Paramètre ids invalide'}), 400
            if not pylon_ids:
                pylon_ids = None

        from spatial_utils import compute_pylon_coverage

        result = compute_pylon_coverage(db.session, db.engine, pylon_ids=pylon_ids)
        return jsonify(result)
    except Exception as e:
        print(f'Erreur couverture pylônes: {e}')
        return jsonify({'error': 'Erreur lors du calcul de couverture'}), 500


@app.route('/validation')
@require_access('/validation')
def validation_page():
    """File de validation des POI collectés"""
    return render_template('validation.html')


@app.route('/uploads/poi/<path:filename>')
def serve_poi_photo(filename):
    """Servir les photos POI"""
    directory = app.config['POI_UPLOAD_FOLDER']
    return send_file(os.path.join(directory, filename))


# ========== API SECTEURS D'ACTIVITÉ ==========

@app.route('/api/secteurs-activite', methods=['GET'])
@require_access('/parametrage', '/pois', '/carte')
def get_secteurs_activite():
    try:
        include_types = request.args.get('include_types', 'false').lower() == 'true'
        all_rows = request.args.get('all', 'false').lower() == 'true'
        query = SecteurActivite.query
        if not all_rows:
            query = query.filter_by(active=True)
        secteurs = query.order_by(SecteurActivite.ordre, SecteurActivite.nom).all()
        return jsonify([s.to_dict(include_types=include_types) for s in secteurs])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/secteurs-activite', methods=['POST'])
@require_access('/parametrage')
def create_secteur_activite():
    data = request.json or {}
    code = (data.get('code') or '').strip().upper()
    nom = (data.get('nom') or '').strip()
    if not code or not nom:
        return jsonify({'error': 'Code et nom requis'}), 400
    if SecteurActivite.query.filter_by(code=code).first():
        return jsonify({'error': 'Ce code secteur existe déjà'}), 400
    secteur = SecteurActivite(
        code=code,
        nom=nom,
        description=(data.get('description') or '').strip(),
        icon=data.get('icon'),
        color=data.get('color') or '#0d9668',
        ordre=int(data.get('ordre') or 0),
        active=True,
    )
    db.session.add(secteur)
    db.session.commit()
    return jsonify(secteur.to_dict()), 201


@app.route('/api/secteurs-activite/<int:secteur_id>', methods=['PUT'])
@require_access('/parametrage')
def update_secteur_activite(secteur_id):
    secteur = SecteurActivite.query.get_or_404(secteur_id)
    data = request.json or {}
    if 'code' in data:
        new_code = data['code'].strip().upper()
        existing = SecteurActivite.query.filter_by(code=new_code).first()
        if existing and existing.id != secteur_id:
            return jsonify({'error': 'Code déjà utilisé'}), 400
        secteur.code = new_code
    if 'nom' in data:
        secteur.nom = data['nom'].strip()
    if 'description' in data:
        secteur.description = (data.get('description') or '').strip()
    if 'icon' in data:
        secteur.icon = data.get('icon')
    if 'color' in data:
        secteur.color = data.get('color')
    if 'ordre' in data:
        secteur.ordre = int(data['ordre'])
    if 'active' in data:
        secteur.active = bool(data['active'])
    db.session.commit()
    return jsonify(secteur.to_dict())


@app.route('/api/secteurs-activite/<int:secteur_id>', methods=['DELETE'])
@require_access('/parametrage')
def delete_secteur_activite(secteur_id):
    secteur = SecteurActivite.query.get_or_404(secteur_id)
    if TypeCommerce.query.filter_by(secteur_id=secteur_id, active=True).first():
        return jsonify({'error': 'Secteur lié à des types actifs. Désactivez-le plutôt.'}), 400
    secteur.active = False
    db.session.commit()
    return jsonify({'message': 'Secteur désactivé'})


# ========== API VALIDATION POI ==========

@app.route('/api/pois/validation-queue', methods=['GET'])
@require_access('/validation')
def get_poi_validation_queue():
    try:
        statut = request.args.get('statut', 'a_traiter')
        categorie = request.args.get('categorie', '').strip().lower()
        feature_type = request.args.get('feature_type', '').strip().lower()

        query = Boutique.query.filter_by(active=True)
        if statut == 'a_traiter':
            query = query.filter(Boutique.statut_validation.in_(['en_attente', 'brouillon']))
        elif statut:
            query = query.filter_by(statut_validation=statut)
        else:
            query = query.filter(Boutique.statut_validation.in_(['en_attente', 'brouillon']))
        if categorie in POI_CATEGORIES:
            query = query.filter(Boutique.categorie == categorie)
        if feature_type:
            query = query.filter(Boutique.feature_type == feature_type)

        pois = query.order_by(
            Boutique.submitted_at.desc().nullslast(),
            Boutique.date_creation.desc(),
        ).all()

        result = []
        for p in pois:
            d = p.to_dict()
            d['localisation_label'] = _poi_localisation_label(p)
            d['categorie_label'] = 'Contribuable' if p.is_contribuable() else 'Infrastructure'
            result.append(d)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/boutiques/<int:boutique_id>/submit-validation', methods=['POST'])
@require_access('/pois')
def submit_boutique_validation(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    try:
        _submit_poi_for_validation(boutique)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    db.session.commit()
    return jsonify(boutique.to_dict())


@app.route('/api/boutiques/<int:boutique_id>/validate', methods=['POST'])
@require_access('/validation')
def validate_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    data = request.json or {}
    if boutique.statut_validation not in ('en_attente', 'brouillon'):
        return jsonify({'error': 'POI non éligible à la validation'}), 400
    boutique.statut_validation = 'valide'
    boutique.validated_by = session.get('user_id')
    boutique.validated_at = datetime.utcnow()
    boutique.validation_comment = (data.get('comment') or '').strip() or None
    if not boutique.qr_code_path or not _resolve_qr_filepath(boutique.qr_code_path):
        qr_path = generate_qr_code(boutique.id, boutique.code_unique)
        boutique.qr_code_path = os.path.basename(qr_path)
    commercant_access = _attach_commercant_account(boutique)
    db.session.commit()
    payload = boutique.to_dict()
    if commercant_access:
        payload['commercant_access'] = commercant_access
    return jsonify(payload)


@app.route('/api/boutiques/<int:boutique_id>/reject', methods=['POST'])
@require_access('/validation')
def reject_boutique(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    data = request.json or {}
    comment = (data.get('comment') or '').strip()
    if not comment:
        return jsonify({'error': 'Un commentaire est requis pour le rejet'}), 400
    if boutique.statut_validation not in ('en_attente', 'brouillon'):
        return jsonify({'error': 'POI non éligible au rejet'}), 400
    boutique.statut_validation = 'rejete'
    boutique.validated_by = session.get('user_id')
    boutique.validated_at = datetime.utcnow()
    boutique.validation_comment = comment
    db.session.commit()
    return jsonify(boutique.to_dict())


@app.route('/api/boutiques/<int:boutique_id>/photo', methods=['POST'])
@require_access('/pois')
def upload_boutique_photo(boutique_id):
    boutique = Boutique.query.get_or_404(boutique_id)
    if 'photo' not in request.files:
        return jsonify({'error': 'Aucun fichier photo'}), 400
    file = request.files['photo']
    if not file.filename:
        return jsonify({'error': 'Fichier vide'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        return jsonify({'error': 'Format non supporté (jpg, png, webp)'}), 400
    safe_name = secure_filename(f"poi_{boutique_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}")
    directory = app.config['POI_UPLOAD_FOLDER']
    os.makedirs(directory, exist_ok=True)
    filepath = os.path.join(directory, safe_name)
    file.save(filepath)
    boutique.photo_path = filepath
    db.session.commit()
    return jsonify({'photo_path': filepath, 'photo_url': f'/uploads/poi/{safe_name}'})


# ========== ESPACE COMMERÇANT ==========

def normalize_phone(phone):
    """Normalise un numéro de téléphone (Congo +242) pour comparaison fiable."""
    if not phone:
        return ''
    digits = re.sub(r'\D', '', str(phone))
    if not digits:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('0') and len(digits) == 9:
        digits = '242' + digits
    elif not digits.startswith('242') and len(digits) == 8 and digits[0] in '456789':
        digits = '2420' + digits
    elif not digits.startswith('242') and len(digits) == 9 and digits[0] in '456789':
        digits = '2420' + digits[1:]
    if digits.startswith('242') and len(digits) == 11 and digits[3] != '0':
        digits = '2420' + digits[3:]
    return digits


def phones_match(stored_phone, input_phone):
    """Compare deux numéros après normalisation."""
    a = normalize_phone(stored_phone)
    b = normalize_phone(input_phone)
    return bool(a and b and a == b)


def generate_temp_password(length=8):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def create_commercant_for_boutique(boutique, plain_password=None):
    """
    Crée un compte contribuable lié au POI.
    Retourne (commercant, mot_de_passe_clair) ou (None, None).
    """
    if boutique.categorie != POI_CATEGORY_CONTRIBUABLE:
        return None, None
    if not normalize_phone(boutique.telephone):
        return None, None
    if Commercant.query.filter_by(boutique_id=boutique.id).first():
        return None, None

    plain = plain_password or generate_temp_password()
    commerçant = Commercant(
        boutique_id=boutique.id,
        telephone=(boutique.telephone or '').strip(),
        mot_de_passe_hash=generate_password_hash(plain),
        must_change_password=True,
    )
    db.session.add(commerçant)
    return commerçant, plain


def _commercant_access_payload(boutique, plain_password):
    """Identifiants à remettre au commerçant (mot de passe temporaire)."""
    return {
        'boutique_code': boutique.code_unique,
        'boutique_nom': boutique.nom,
        'telephone': boutique.telephone,
        'identifiant_connexion': boutique.telephone,
        'mot_de_passe_temporaire': plain_password,
        'must_change_password': True,
        'url_connexion': url_for('commercant_connexion', _external=False),
    }


def _attach_commercant_account(boutique):
    """Crée le compte contribuable si possible. Retourne le dict d'accès ou None."""
    commerçant, plain = create_commercant_for_boutique(boutique)
    if not commerçant or not plain:
        return None
    return _commercant_access_payload(boutique, plain)


def find_commercant_by_login(identifiant):
    """Recherche un commerçant par code POI ou numéro de téléphone."""
    raw = (identifiant or '').strip()
    if not raw:
        return None, None

    upper = raw.upper()
    if upper.startswith(('POI-', 'BOUTIQUE-', 'GEO-')):
        boutique = Boutique.query.filter_by(code_unique=upper, active=True).first()
        if not boutique:
            return None, 'Code POI inconnu'
        commerçant = Commercant.query.filter_by(boutique_id=boutique.id, actif=True).first()
        if not commerçant:
            return None, 'Aucun compte pour ce POI. Contactez l\'administration.'
        return commerçant, None

    norm = normalize_phone(raw)
    if not norm:
        return None, 'Identifiant invalide'

    matches = [
        c for c in Commercant.query.filter_by(actif=True).all()
        if normalize_phone(c.telephone) == norm
    ]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, 'Plusieurs comptes pour ce numéro — connectez-vous avec votre code POI.'
    return None, 'Téléphone ou mot de passe incorrect'


def commercant_required(f):
    """Décorateur pour les routes nécessitant une connexion commerçant"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        commercant_id = session.get('commercant_id')
        if not commercant_id:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Connexion requise'}), 401
            return redirect(url_for('commercant_connexion'))
        commerçant = Commercant.query.get(commercant_id)
        if not commerçant or not commerçant.actif:
            session.pop('commercant_id', None)
            session.pop('boutique_id', None)
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Session expirée'}), 401
            return redirect(url_for('commercant_connexion'))
        if not session.get('boutique_id') and commerçant.boutique_id:
            session['boutique_id'] = commerçant.boutique_id

        exempt_endpoints = {
            'commercant_changer_mot_de_passe',
            'api_commercant_changer_mot_de_passe',
            'commercant_deconnexion',
        }
        if commerçant.must_change_password and request.endpoint not in exempt_endpoints:
            if request.path.startswith('/api/'):
                return jsonify({
                    'error': 'Vous devez changer votre mot de passe provisoire.',
                    'must_change_password': True,
                }), 403
            return redirect(url_for('commercant_changer_mot_de_passe'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/commercant')
def commercant_index():
    """Tableau de bord commerçant - redirige vers connexion ou dashboard"""
    if session.get('commercant_id'):
        commerçant = Commercant.query.get(session.get('commercant_id'))
        if commerçant and commerçant.must_change_password:
            return redirect(url_for('commercant_changer_mot_de_passe'))
        return redirect(url_for('commercant_dashboard'))
    return redirect(url_for('commercant_connexion'))


@app.route('/commercant/connexion')
def commercant_connexion():
    """Page de connexion commerçant"""
    if session.get('commercant_id'):
        commerçant = Commercant.query.get(session.get('commercant_id'))
        if commerçant and commerçant.must_change_password:
            return redirect(url_for('commercant_changer_mot_de_passe'))
        return redirect(url_for('commercant_dashboard'))
    return render_template('commercant_connexion.html')


@app.route('/commercant/inscription')
def commercant_inscription():
    """Page d'inscription commerçant"""
    if session.get('commercant_id'):
        return redirect(url_for('commercant_dashboard'))
    code = request.args.get('code', '')
    telephone = request.args.get('telephone', '')
    return render_template('commercant_inscription.html', code_prefill=code, telephone_prefill=telephone)


@app.route('/commercant/changer-mot-de-passe')
def commercant_changer_mot_de_passe():
    """Changement obligatoire ou volontaire du mot de passe contribuable."""
    if not session.get('commercant_id'):
        return redirect(url_for('commercant_connexion'))
    commerçant = Commercant.query.get(session.get('commercant_id'))
    if not commerçant or not commerçant.actif:
        return redirect(url_for('commercant_connexion'))
    return render_template(
        'commercant_changer_mot_de_passe.html',
        obligatoire=bool(commerçant.must_change_password),
    )


@app.route('/commercant/dashboard')
@commercant_required
def commercant_dashboard():
    """Tableau de bord commerçant avec historique des paiements"""
    return render_template('commercant_dashboard.html')


@app.route('/commercant/deconnexion')
def commercant_deconnexion():
    """Déconnexion du commerçant"""
    session.pop('commercant_id', None)
    session.pop('boutique_id', None)
    return redirect(url_for('commercant_connexion'))


@app.route('/api/commercant/inscription', methods=['POST'])
def api_commercant_inscription():
    """Créer un compte commerçant"""
    data = request.get_json() or {}
    code_unique = (data.get('code_unique') or '').strip().upper()
    telephone = normalize_phone(data.get('telephone', ''))
    mot_de_passe = data.get('mot_de_passe', '')
    
    if not code_unique:
        return jsonify({'error': 'Le code boutique est requis'}), 400
    if not telephone:
        return jsonify({'error': 'Le numéro de téléphone est requis'}), 400
    if len(mot_de_passe) < 6:
        return jsonify({'error': 'Le mot de passe doit contenir au moins 6 caractères'}), 400
    
    boutique = Boutique.query.filter_by(code_unique=code_unique, active=True).first()
    if not boutique:
        return jsonify({'error': 'Commerce non trouvé. Vérifiez votre code boutique.'}), 404
    
    if not phones_match(boutique.telephone, telephone):
        return jsonify({'error': 'Le numéro de téléphone ne correspond pas à celui enregistré pour ce commerce.'}), 400
    
    if Commercant.query.filter_by(boutique_id=boutique.id).first():
        return jsonify({'error': 'Un compte existe déjà pour ce commerce. Connectez-vous.'}), 400
    
    commerçant = Commercant(
        boutique_id=boutique.id,
        telephone=telephone,
        mot_de_passe_hash=generate_password_hash(mot_de_passe),
        must_change_password=False,
    )
    db.session.add(commerçant)
    db.session.commit()
    
    session['commercant_id'] = commerçant.id
    session['boutique_id'] = boutique.id
    return jsonify({
        'success': True,
        'message': 'Compte créé avec succès',
        'commercant': commerçant.to_dict()
    })


@app.route('/api/commercant/connexion', methods=['POST'])
def api_commercant_connexion():
    """Connexion commerçant (code POI ou téléphone + mot de passe)."""
    data = request.get_json() or {}
    identifiant = (data.get('identifiant') or data.get('code_unique') or data.get('telephone') or '').strip()
    mot_de_passe = data.get('mot_de_passe', '')

    if not identifiant or not mot_de_passe:
        return jsonify({'error': 'Identifiant et mot de passe requis'}), 400

    commerçant, err = find_commercant_by_login(identifiant)
    if err:
        return jsonify({'error': err}), 401
    if not commerçant:
        return jsonify({'error': 'Identifiant ou mot de passe incorrect'}), 401

    if not check_password_hash(commerçant.mot_de_passe_hash, mot_de_passe):
        return jsonify({'error': 'Identifiant ou mot de passe incorrect'}), 401

    session['commercant_id'] = commerçant.id
    session['boutique_id'] = commerçant.boutique_id
    return jsonify({
        'success': True,
        'message': 'Connexion réussie',
        'must_change_password': bool(commerçant.must_change_password),
        'commercant': commerçant.to_dict(),
    })


@app.route('/api/commercant/changer-mot-de-passe', methods=['POST'])
def api_commercant_changer_mot_de_passe():
    """Change le mot de passe du contribuable connecté."""
    commercant_id = session.get('commercant_id')
    if not commercant_id:
        return jsonify({'error': 'Connexion requise'}), 401

    commerçant = Commercant.query.get(commercant_id)
    if not commerçant or not commerçant.actif:
        return jsonify({'error': 'Session expirée'}), 401

    data = request.get_json() or {}
    ancien = data.get('ancien_mot_de_passe', '')
    nouveau = data.get('nouveau_mot_de_passe', '')
    confirmation = data.get('confirmation', '')

    if len(nouveau) < 6:
        return jsonify({'error': 'Le nouveau mot de passe doit contenir au moins 6 caractères'}), 400
    if nouveau != confirmation:
        return jsonify({'error': 'Les mots de passe ne correspondent pas'}), 400
    if commerçant.must_change_password:
        if not check_password_hash(commerçant.mot_de_passe_hash, ancien):
            return jsonify({'error': 'Mot de passe provisoire incorrect'}), 400
    elif not check_password_hash(commerçant.mot_de_passe_hash, ancien):
        return jsonify({'error': 'Mot de passe actuel incorrect'}), 400
    if check_password_hash(commerçant.mot_de_passe_hash, nouveau):
        return jsonify({'error': 'Choisissez un mot de passe différent du provisoire'}), 400

    commerçant.mot_de_passe_hash = generate_password_hash(nouveau)
    commerçant.must_change_password = False
    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Mot de passe mis à jour',
        'commercant': commerçant.to_dict(),
    })


@app.route('/api/commercant/mes-paiements', methods=['GET'])
@commercant_required
def api_commercant_mes_paiements():
    """Historique des paiements du commerçant connecté"""
    boutique_id = session.get('boutique_id')
    if not boutique_id:
        return jsonify({'error': 'Session invalide'}), 401
    
    paiements = Paiement.query.filter_by(boutique_id=boutique_id).order_by(
        Paiement.date_paiement.desc()
    ).all()
    
    return jsonify([p.to_dict() for p in paiements])


@app.route('/api/commercant/mon-commerce', methods=['GET'])
@commercant_required
def api_commercant_mon_commerce():
    """Informations du commerce du commerçant connecté"""
    boutique_id = session.get('boutique_id')
    if not boutique_id:
        return jsonify({'error': 'Session invalide'}), 401
    
    boutique = Boutique.query.get(boutique_id)
    if not boutique:
        return jsonify({'error': 'Commerce non trouvé'}), 404
    
    boutique_dict = boutique.to_dict()
    boutique_dict['a_jour'] = boutique.get_statut_paiement_global()
    dernier_paiement = boutique.get_dernier_paiement()
    boutique_dict['dernier_paiement'] = dernier_paiement.to_dict() if dernier_paiement else None
    return jsonify(boutique_dict)


@app.route('/api/commercant/mes-taxes-a-payer', methods=['GET'])
@commercant_required
def api_commercant_mes_taxes_a_payer():
    """Taxes à payer pour le POI du contribuable connecté (période sélectionnée)"""
    boutique_id = session.get('boutique_id')
    if not boutique_id:
        return jsonify({'error': 'Session invalide'}), 401
    
    mois = request.args.get('mois', type=int) or datetime.utcnow().month
    annee = request.args.get('annee', type=int) or datetime.utcnow().year
    
    boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=boutique_id, active=True).all()
    result = []
    
    for boutique_taxe in boutique_taxes:
        taxe = boutique_taxe.taxe
        if not taxe or not taxe.active:
            continue
        
        montant_attendu = boutique_taxe.montant_personnalise if boutique_taxe.montant_personnalise else taxe.montant_attendu
        
        paiement = Paiement.query.filter_by(
            boutique_id=boutique_id,
            taxe_id=taxe.id,
            mois=mois,
            annee=annee,
            statut='confirme'
        ).first()
        
        result.append({
            'taxe': taxe.to_dict(),
            'institut_nom': taxe.institut.nom if taxe.institut else 'Inconnu',
            'institut_id': taxe.institut_id,
            'payee': paiement is not None,
            'paiement': paiement.to_dict() if paiement else None,
            'montant_attendu': montant_attendu,
            'taxe_id': taxe.id
        })
    
    code_ussd = Configuration.get('code_ussd', '*123#')
    boutique = Boutique.query.get(boutique_id)
    
    return jsonify({
        'taxes': result,
        'mois': mois,
        'annee': annee,
        'code_boutique': boutique.code_unique if boutique else None,
        'code_ussd': code_ussd
    })


@app.route('/api/commercant/payer', methods=['POST'])
@commercant_required
def api_commercant_payer():
    """Enregistrer un paiement depuis l'espace commerçant"""
    boutique_id = session.get('boutique_id')
    if not boutique_id:
        return jsonify({'error': 'Session invalide'}), 401
    
    data = request.get_json() or {}
    taxe_id = data.get('taxe_id')
    montant = float(data.get('montant', 0))
    reference_transaction = (data.get('reference_transaction') or '').strip()
    numero_telephone = (data.get('numero_telephone') or '').strip()
    methode = data.get('methode', 'MOBILE_MONEY')
    
    if not taxe_id:
        return jsonify({'error': 'Taxe requise'}), 400
    if montant <= 0:
        return jsonify({'error': 'Montant invalide'}), 400
    
    boutique = Boutique.query.get(boutique_id)
    if not boutique:
        return jsonify({'error': 'Commerce non trouvé'}), 404
    
    taxe = Taxe.query.get(taxe_id)
    if not taxe:
        return jsonify({'error': 'Taxe non trouvée'}), 404
    
    # Vérifier que la taxe est bien associée à ce commerce
    boutique_taxe = BoutiqueTaxe.query.filter_by(boutique_id=boutique_id, taxe_id=taxe_id, active=True).first()
    if not boutique_taxe:
        return jsonify({'error': 'Cette taxe n\'est pas associée à votre commerce'}), 400
    
    montant_attendu = boutique_taxe.montant_personnalise if boutique_taxe.montant_personnalise else taxe.montant_attendu
    
    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year
    
    # Vérifier si déjà payé
    existing = Paiement.query.filter_by(
        boutique_id=boutique_id,
        taxe_id=taxe_id,
        mois=mois_actuel,
        annee=annee_actuelle,
        statut='confirme'
    ).first()
    if existing:
        return jsonify({'error': 'Cette taxe a déjà été payée pour ce mois'}), 400
    
    # Générer une référence unique si non fournie
    if not reference_transaction:
        reference_transaction = f"COMM-{boutique.code_unique}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    if Paiement.query.filter_by(reference_transaction=reference_transaction).first():
        return jsonify({'error': 'Cette référence de transaction existe déjà'}), 400
    
    if not numero_telephone and boutique.telephone:
        numero_telephone = boutique.telephone
    
    paiement = Paiement(
        boutique_id=boutique_id,
        institut_id=taxe.institut_id,
        taxe_id=taxe_id,
        montant=montant,
        mois=mois_actuel,
        annee=annee_actuelle,
        methode=methode,
        numero_transaction=generer_numero_transaction(),
        reference_transaction=reference_transaction,
        numero_telephone=numero_telephone,
        statut='confirme'
    )
    db.session.add(paiement)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Paiement enregistré avec succès',
        'paiement': paiement.to_dict()
    }), 201


# ========== API POUR PAYS ==========

@app.route('/api/pays', methods=['GET'])
def get_pays():
    """Récupérer la liste des pays"""
    pays_list = Pays.query.filter_by(active=True).order_by(Pays.nom).all()
    return jsonify([p.to_dict() for p in pays_list])


@app.route('/api/session/pays', methods=['GET', 'POST'])
def session_pays():
    """Lire ou définir le pays actif de la session utilisateur."""
    if not session.get('user_id'):
        return jsonify({'error': 'Connexion requise'}), 401

    if request.method == 'GET':
        payload = _get_pays_session_payload()
        payload['available'] = [p.to_dict() for p in Pays.query.filter_by(active=True).order_by(Pays.nom).all()]
        return jsonify(payload)

    data = request.get_json(silent=True) or {}
    pays_id = data.get('pays_id')
    if pays_id in (None, '', 0, '0'):
        session.pop('pays_id', None)
        return jsonify(_get_pays_session_payload())

    try:
        pays_id = int(pays_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'Identifiant pays invalide'}), 400

    pays = Pays.query.filter_by(id=pays_id, active=True).first()
    if not pays:
        return jsonify({'error': 'Pays non trouvé'}), 404

    session['pays_id'] = pays.id
    return jsonify(_get_pays_session_payload(pays.id))


@app.route('/api/pays', methods=['POST'])
def create_pays():
    """Créer un nouveau pays"""
    data = request.json
    code = data.get('code', '').upper()
    nom = data.get('nom', '').strip()
    
    if not code or not nom:
        return jsonify({'error': 'Code et nom sont requis'}), 400
    
    if Pays.query.filter_by(code=code).first():
        return jsonify({'error': 'Ce code pays existe déjà'}), 400
    
    pays = Pays(code=code, nom=nom, code_iso=data.get('code_iso', '').upper())
    if data.get('center_lat') not in (None, '') and data.get('center_lng') not in (None, ''):
        pays.center_lat = float(data['center_lat'])
        pays.center_lng = float(data['center_lng'])
        pays.default_zoom = int(data.get('default_zoom') or 6)
    else:
        defaults = _resolve_pays_map_default(pays)
        if defaults:
            pays.center_lat = defaults['lat']
            pays.center_lng = defaults['lng']
            pays.default_zoom = defaults['zoom']
    db.session.add(pays)
    db.session.commit()
    
    return jsonify(pays.to_dict()), 201


@app.route('/api/pays/<int:pays_id>', methods=['PUT'])
def update_pays(pays_id):
    """Mettre à jour un pays"""
    pays = Pays.query.get_or_404(pays_id)
    data = request.json
    
    if 'nom' in data:
        pays.nom = data['nom'].strip()
    if 'code_iso' in data:
        pays.code_iso = data['code_iso'].upper()
    if 'active' in data:
        pays.active = data['active']
    if 'center_lat' in data:
        pays.center_lat = float(data['center_lat']) if data['center_lat'] not in (None, '') else None
    if 'center_lng' in data:
        pays.center_lng = float(data['center_lng']) if data['center_lng'] not in (None, '') else None
    if 'default_zoom' in data:
        pays.default_zoom = int(data['default_zoom']) if data['default_zoom'] not in (None, '') else 6

    db.session.commit()
    return jsonify(pays.to_dict())


@app.route('/api/pays/<int:pays_id>', methods=['DELETE'])
def delete_pays(pays_id):
    """Supprimer un pays (désactivation)"""
    pays = Pays.query.get_or_404(pays_id)
    pays.active = False
    db.session.commit()
    return jsonify({'message': 'Pays désactivé'}), 200


# ========== API POUR DÉPARTEMENTS ==========

@app.route('/api/departements', methods=['GET'])
def get_departements():
    """Récupérer la liste des départements"""
    pays_id = request.args.get('pays_id')
    query = Departement.query.filter_by(active=True)

    if pays_id not in (None, ''):
        try:
            pid = int(pays_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'pays_id invalide'}), 400
        query = query.filter_by(pays_id=pid)
        departements = query.order_by(Departement.nom).all()
        if not departements:
            pays = Pays.query.get(pid)
            region = _classify_pays_region(pays) if pays else None
            keeper = _get_keeper_pays_for_region(region) if region else None
            if keeper and keeper.id != pid:
                departements = (
                    Departement.query.filter_by(active=True, pays_id=keeper.id)
                    .order_by(Departement.nom)
                    .all()
                )
        return jsonify([d.to_dict() for d in departements])

    departements = query.order_by(Departement.nom).all()
    return jsonify([d.to_dict() for d in departements])


@app.route('/api/departements', methods=['POST'])
def create_departement():
    """Créer un nouveau département"""
    data = request.json
    pays_id = data.get('pays_id')
    code = data.get('code', '').strip()
    nom = data.get('nom', '').strip()
    
    if not pays_id or not code or not nom:
        return jsonify({'error': 'Pays, code et nom sont requis'}), 400
    
    if not Pays.query.get(pays_id):
        return jsonify({'error': 'Pays non trouvé'}), 404
    
    if Departement.query.filter_by(pays_id=pays_id, code=code).first():
        return jsonify({'error': 'Ce code département existe déjà pour ce pays'}), 400
    
    departement = Departement(pays_id=pays_id, code=code, nom=nom)
    db.session.add(departement)
    db.session.commit()
    
    return jsonify(departement.to_dict()), 201


@app.route('/api/departements/<int:departement_id>', methods=['PUT'])
def update_departement(departement_id):
    """Mettre à jour un département"""
    departement = Departement.query.get_or_404(departement_id)
    data = request.json
    
    if 'nom' in data:
        departement.nom = data['nom'].strip()
    if 'code' in data:
        departement.code = data['code'].strip()
    if 'active' in data:
        departement.active = data['active']
    
    db.session.commit()
    return jsonify(departement.to_dict())


@app.route('/api/departements/<int:departement_id>', methods=['DELETE'])
def delete_departement(departement_id):
    """Supprimer un département (désactivation)"""
    departement = Departement.query.get_or_404(departement_id)
    departement.active = False
    db.session.commit()
    return jsonify({'message': 'Département désactivé'}), 200


# ========== API POUR COMMUNES ==========

@app.route('/api/communes', methods=['GET'])
def get_communes():
    """Récupérer la liste des communes"""
    departement_id = request.args.get('departement_id')
    query = Commune.query.filter_by(active=True)

    if departement_id not in (None, ''):
        try:
            did = int(departement_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'departement_id invalide'}), 400
        communes = query.filter_by(departement_id=did).order_by(Commune.nom).all()
        if not communes:
            dept = Departement.query.get(did)
            mirror_dept = _find_mirror_departement(dept) if dept else None
            if mirror_dept and mirror_dept.id != did:
                communes = (
                    Commune.query.filter_by(active=True, departement_id=mirror_dept.id)
                    .order_by(Commune.nom)
                    .all()
                )
        return jsonify([c.to_dict() for c in communes])

    communes = query.order_by(Commune.nom).all()
    return jsonify([c.to_dict() for c in communes])


@app.route('/api/communes', methods=['POST'])
def create_commune():
    """Créer une nouvelle commune"""
    data = request.json
    departement_id = data.get('departement_id')
    code = data.get('code', '').strip()
    nom = data.get('nom', '').strip()
    
    if not departement_id or not code or not nom:
        return jsonify({'error': 'Département, code et nom sont requis'}), 400
    
    if not Departement.query.get(departement_id):
        return jsonify({'error': 'Département non trouvé'}), 404
    
    if Commune.query.filter_by(departement_id=departement_id, code=code).first():
        return jsonify({'error': 'Ce code commune existe déjà pour ce département'}), 400
    
    commune = Commune(departement_id=departement_id, code=code, nom=nom)
    db.session.add(commune)
    db.session.commit()
    
    return jsonify(commune.to_dict()), 201


@app.route('/api/communes/<int:commune_id>', methods=['PUT'])
def update_commune(commune_id):
    """Mettre à jour une commune"""
    commune = Commune.query.get_or_404(commune_id)
    data = request.json
    
    if 'nom' in data:
        commune.nom = data['nom'].strip()
    if 'code' in data:
        commune.code = data['code'].strip()
    if 'active' in data:
        commune.active = data['active']
    
    db.session.commit()
    return jsonify(commune.to_dict())


@app.route('/api/communes/<int:commune_id>', methods=['DELETE'])
def delete_commune(commune_id):
    """Supprimer une commune (désactivation)"""
    commune = Commune.query.get_or_404(commune_id)
    commune.active = False
    db.session.commit()
    return jsonify({'message': 'Commune désactivée'}), 200


# ========== API POUR QUARTIERS/VILLAGES ==========

@app.route('/api/quartiers-villages', methods=['GET'])
def get_quartiers_villages():
    """Récupérer la liste des quartiers/villages"""
    commune_id = request.args.get('commune_id')
    type_filter = request.args.get('type')  # 'quartier' ou 'village'
    query = QuartierVillage.query.filter_by(active=True)

    if commune_id not in (None, ''):
        try:
            cid = int(commune_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'commune_id invalide'}), 400
        quartiers = query.filter_by(commune_id=cid)
        if type_filter:
            quartiers = quartiers.filter_by(type=type_filter)
        quartiers = quartiers.order_by(QuartierVillage.nom).all()
        if not quartiers:
            commune = Commune.query.get(cid)
            mirror_commune = _find_mirror_commune(commune) if commune else None
            if mirror_commune and mirror_commune.id != cid:
                q = QuartierVillage.query.filter_by(active=True, commune_id=mirror_commune.id)
                if type_filter:
                    q = q.filter_by(type=type_filter)
                quartiers = q.order_by(QuartierVillage.nom).all()
        return jsonify([q.to_dict() for q in quartiers])

    if type_filter:
        query = query.filter_by(type=type_filter)
    quartiers = query.order_by(QuartierVillage.nom).all()
    return jsonify([q.to_dict() for q in quartiers])


@app.route('/api/quartiers-villages', methods=['POST'])
def create_quartier_village():
    """Créer un nouveau quartier/village"""
    data = request.json
    commune_id = data.get('commune_id')
    code = data.get('code', '').strip()
    nom = data.get('nom', '').strip()
    type_qv = data.get('type', 'quartier')
    
    if not commune_id or not code or not nom:
        return jsonify({'error': 'Commune, code et nom sont requis'}), 400
    
    if not Commune.query.get(commune_id):
        return jsonify({'error': 'Commune non trouvée'}), 404
    
    if QuartierVillage.query.filter_by(commune_id=commune_id, code=code).first():
        return jsonify({'error': 'Ce code quartier/village existe déjà pour cette commune'}), 400
    
    quartier = QuartierVillage(commune_id=commune_id, code=code, nom=nom, type=type_qv)
    db.session.add(quartier)
    db.session.commit()
    
    return jsonify(quartier.to_dict()), 201


@app.route('/api/quartiers-villages/<int:quartier_id>', methods=['PUT'])
def update_quartier_village(quartier_id):
    """Mettre à jour un quartier/village"""
    quartier = QuartierVillage.query.get_or_404(quartier_id)
    data = request.json
    
    if 'nom' in data:
        quartier.nom = data['nom'].strip()
    if 'code' in data:
        quartier.code = data['code'].strip()
    if 'type' in data:
        quartier.type = data['type']
    if 'active' in data:
        quartier.active = data['active']
    
    db.session.commit()
    return jsonify(quartier.to_dict())


@app.route('/api/quartiers-villages/<int:quartier_id>', methods=['DELETE'])
def delete_quartier_village(quartier_id):
    """Supprimer un quartier/village (désactivation)"""
    quartier = QuartierVillage.query.get_or_404(quartier_id)
    quartier.active = False
    db.session.commit()
    return jsonify({'message': 'Quartier/Village désactivé'}), 200


# ========== API ROUTES POUR LES NATURES POI ==========

def _parse_champs_poi_payload(champs_raw, nature_id=None):
    if not isinstance(champs_raw, list):
        return []
    parsed = []
    seen_codes = set()
    for idx, ch in enumerate(champs_raw):
        if not isinstance(ch, dict):
            continue
        code = (ch.get('code') or '').strip().lower().replace(' ', '_')
        libelle = (ch.get('libelle') or '').strip()
        if not code or not libelle:
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        type_champ = (ch.get('type_champ') or 'str').strip().lower()
        if type_champ not in CHAMP_POI_TYPES:
            type_champ = 'str'
        parsed.append({
            'id': ch.get('id'),
            'code': code,
            'libelle': libelle,
            'type_champ': type_champ,
            'placeholder': (ch.get('placeholder') or '').strip() or None,
            'ordre': ch.get('ordre', idx),
            'pleine_largeur': bool(ch.get('pleine_largeur', False)),
            'active': ch.get('active', True) if 'active' in ch else True,
        })
    return parsed


@app.route('/api/natures-poi', methods=['GET'])
def get_natures_poi():
    """Liste des natures POI actives avec leurs champs (formulaire POI)."""
    try:
        natures = NaturePoi.query.filter_by(active=True).order_by(NaturePoi.ordre, NaturePoi.nom).all()
        return jsonify([n.to_dict(include_champs=True) for n in natures])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/natures-poi/all', methods=['GET'])
@role_required('admin')
def get_natures_poi_all():
    """Liste complète pour le paramétrage (admin)."""
    natures = NaturePoi.query.order_by(NaturePoi.ordre, NaturePoi.nom).all()
    return jsonify([n.to_dict(include_champs=True) for n in natures])


@app.route('/api/natures-poi', methods=['POST'])
@role_required('admin')
def create_nature_poi():
    data = request.json or {}
    code = (data.get('code') or '').strip().lower().replace(' ', '_')
    nom = (data.get('nom') or '').strip()
    if not code or not nom:
        return jsonify({'error': 'Code et nom sont requis'}), 400
    if NaturePoi.query.filter_by(code=code).first():
        return jsonify({'error': 'Ce code nature existe déjà'}), 400
    nature = NaturePoi(
        code=code,
        nom=nom,
        description=(data.get('description') or '').strip() or None,
        ordre=int(data.get('ordre', 0) or 0),
        active=True,
    )
    nature.set_mots_cles_list(data.get('mots_cles') or [])
    db.session.add(nature)
    db.session.flush()
    for ch in _parse_champs_poi_payload(data.get('champs') or []):
        db.session.add(ChampPoi(nature_poi_id=nature.id, **ch))
    db.session.commit()
    return jsonify(nature.to_dict()), 201


@app.route('/api/natures-poi/<int:nature_id>', methods=['GET'])
def get_nature_poi(nature_id):
    nature = NaturePoi.query.get_or_404(nature_id)
    return jsonify(nature.to_dict(include_champs=True))


@app.route('/api/natures-poi/<int:nature_id>', methods=['PUT'])
@role_required('admin')
def update_nature_poi(nature_id):
    nature = NaturePoi.query.get_or_404(nature_id)
    data = request.json or {}
    if 'code' in data:
        new_code = (data['code'] or '').strip().lower().replace(' ', '_')
        if not new_code:
            return jsonify({'error': 'Code invalide'}), 400
        existing = NaturePoi.query.filter_by(code=new_code).first()
        if existing and existing.id != nature.id:
            return jsonify({'error': 'Ce code nature existe déjà'}), 400
        if nature.code == 'autre' and new_code != 'autre':
            return jsonify({'error': 'La nature « autre » ne peut pas être renommée'}), 400
        nature.code = new_code
    if 'nom' in data:
        nature.nom = (data['nom'] or '').strip()
    if 'description' in data:
        nature.description = (data['description'] or '').strip() or None
    if 'ordre' in data:
        nature.ordre = int(data['ordre'] or 0)
    if 'mots_cles' in data:
        nature.set_mots_cles_list(data.get('mots_cles') or [])
    if 'active' in data:
        if nature.code == 'autre' and not data['active']:
            return jsonify({'error': 'La nature « autre » doit rester active'}), 400
        nature.active = bool(data['active'])
    if 'champs' in data:
        incoming = _parse_champs_poi_payload(data.get('champs') or [], nature.id)
        kept_ids = set()
        for ch in incoming:
            if ch.get('id'):
                field = ChampPoi.query.filter_by(id=ch['id'], nature_poi_id=nature.id).first()
                if field:
                    field.code = ch['code']
                    field.libelle = ch['libelle']
                    field.type_champ = ch['type_champ']
                    field.placeholder = ch['placeholder']
                    field.ordre = ch['ordre']
                    field.pleine_largeur = ch['pleine_largeur']
                    field.active = ch['active']
                    kept_ids.add(field.id)
                    continue
            field = ChampPoi(nature_poi_id=nature.id, **{k: v for k, v in ch.items() if k != 'id'})
            db.session.add(field)
            db.session.flush()
            kept_ids.add(field.id)
        for field in list(nature.champs):
            if field.id not in kept_ids:
                db.session.delete(field)
    db.session.commit()
    return jsonify(nature.to_dict(include_champs=True))


@app.route('/api/natures-poi/<int:nature_id>', methods=['DELETE'])
@role_required('admin')
def delete_nature_poi(nature_id):
    nature = NaturePoi.query.get_or_404(nature_id)
    if nature.code == 'autre':
        return jsonify({'error': 'La nature « autre » ne peut pas être supprimée'}), 400
    if Boutique.query.filter_by(nature_poi=nature.code).first():
        return jsonify({'error': 'Impossible de supprimer : des POI utilisent cette nature'}), 400
    db.session.delete(nature)
    db.session.commit()
    return jsonify({'message': 'Nature supprimée'}), 200


# ========== API ROUTES POUR LES TYPES DE COMMERCE ==========

@app.route('/api/types-commerce', methods=['GET'])
def get_types_commerce():
    """Récupérer la liste des types de commerce"""
    try:
        include_champs = request.args.get('include_champs', 'false').lower() == 'true'
        all_rows = request.args.get('all', 'false').lower() == 'true'
        secteur_id = request.args.get('secteur_id', type=int)
        query = TypeCommerce.query
        if not all_rows:
            query = query.filter_by(active=True)
        if secteur_id:
            query = query.filter_by(secteur_id=secteur_id)
        types = query.order_by(TypeCommerce.ordre, TypeCommerce.nom).all()
        return jsonify([
            _enrich_type_commerce_dict(t, t.to_dict(include_champs=include_champs), include_champs)
            for t in types
        ])
    except Exception as e:
        print(f"Erreur lors de la récupération des types de commerce: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/types-commerce', methods=['POST'])
def create_type_commerce():
    """Créer un nouveau type de commerce"""
    try:
        data = request.json
        
        if not data:
            return jsonify({'error': 'Aucune donnée fournie'}), 400
        
        code = data.get('code', '').strip().upper() if data.get('code') else ''
        nom = data.get('nom', '').strip() if data.get('nom') else ''
        
        if not code or not nom:
            return jsonify({'error': 'Code et nom sont requis'}), 400
        
        # Vérifier l'unicité du code
        if TypeCommerce.query.filter_by(code=code).first():
            return jsonify({'error': 'Ce code type de commerce existe déjà'}), 400
        
        type_commerce = TypeCommerce(
            code=code,
            nom=nom,
            description=data.get('description', '').strip() if data.get('description') else '',
            nature_poi_id=data.get('nature_poi_id') or None,
            secteur_id=data.get('secteur_id') or None,
            icon=data.get('icon'),
            color=data.get('color'),
            map_line_style=data.get('map_line_style') or 'solid',
            map_fill_pattern=data.get('map_fill_pattern') or 'solid',
            ordre=int(data.get('ordre') or 0),
        )
        
        db.session.add(type_commerce)
        db.session.flush()

        for ch in data.get('champs') or []:
            if not ch.get('code') or not ch.get('libelle'):
                continue
            nat_id = type_commerce.nature_poi_id
            if not nat_id:
                autre = NaturePoi.get_by_code('autre')
                nat_id = autre.id if autre else None
            db.session.add(ChampPoi(
                type_commerce_id=type_commerce.id,
                nature_poi_id=nat_id,
                code=ch['code'].strip(),
                libelle=ch['libelle'].strip(),
                type_champ=ch.get('type_champ', 'str'),
                placeholder=ch.get('placeholder'),
                ordre=int(ch.get('ordre') or 0),
                pleine_largeur=bool(ch.get('pleine_largeur', False)),
                active=True,
            ))
        
        db.session.commit()
        
        return jsonify(type_commerce.to_dict(include_champs=True)), 201
    except Exception as e:
        print(f"Erreur lors de la création du type de commerce: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la création: {str(e)}'}), 500


@app.route('/api/types-commerce/<int:type_id>', methods=['GET'])
def get_type_commerce(type_id):
    """Récupérer un type de commerce par son ID"""
    type_commerce = TypeCommerce.query.get_or_404(type_id)
    include_champs = request.args.get('include_champs', 'true').lower() == 'true'
    data = type_commerce.to_dict(include_champs=include_champs)
    return jsonify(_enrich_type_commerce_dict(type_commerce, data, include_champs))


@app.route('/api/types-commerce/<int:type_id>', methods=['PUT'])
def update_type_commerce(type_id):
    """Mettre à jour un type de commerce"""
    type_commerce = TypeCommerce.query.get_or_404(type_id)
    data = request.json
    
    if 'code' in data:
        new_code = data['code'].strip().upper()
        if new_code != type_commerce.code and TypeCommerce.query.filter_by(code=new_code).first():
            return jsonify({'error': 'Ce code type de commerce existe déjà'}), 400
        type_commerce.code = new_code
    if 'nom' in data:
        type_commerce.nom = data['nom'].strip()
    if 'description' in data:
        type_commerce.description = data['description'].strip()
    if 'nature_poi_id' in data:
        nid = data.get('nature_poi_id')
        if nid:
            if not NaturePoi.query.get(nid):
                return jsonify({'error': 'Nature POI introuvable'}), 400
            type_commerce.nature_poi_id = nid
        else:
            type_commerce.nature_poi_id = None
    if 'secteur_id' in data:
        sid = data.get('secteur_id')
        if sid and not SecteurActivite.query.get(sid):
            return jsonify({'error': 'Secteur introuvable'}), 400
        type_commerce.secteur_id = sid or None
    if 'icon' in data:
        type_commerce.icon = data.get('icon')
    if 'color' in data:
        type_commerce.color = data.get('color')
    if 'map_line_style' in data:
        type_commerce.map_line_style = data.get('map_line_style') or 'solid'
    if 'map_fill_pattern' in data:
        type_commerce.map_fill_pattern = data.get('map_fill_pattern') or 'solid'
    if 'ordre' in data:
        type_commerce.ordre = int(data['ordre'])
    if 'champs' in data:
        incoming = data.get('champs') or []
        seen_ids = set()
        for ch in incoming:
            if ch.get('id'):
                field = ChampPoi.query.filter_by(id=ch['id'], type_commerce_id=type_commerce.id).first()
                if field:
                    seen_ids.add(field.id)
                    if ch.get('_delete'):
                        field.active = False
                        continue
                    field.code = ch.get('code', field.code).strip()
                    field.libelle = ch.get('libelle', field.libelle).strip()
                    field.type_champ = ch.get('type_champ', field.type_champ)
                    field.placeholder = ch.get('placeholder', field.placeholder)
                    field.ordre = int(ch.get('ordre') or field.ordre)
                    field.pleine_largeur = bool(ch.get('pleine_largeur', field.pleine_largeur))
                    field.active = ch.get('active', True)
            elif ch.get('code') and ch.get('libelle') and not ch.get('_delete'):
                code = ch['code'].strip()
                existing = ChampPoi.query.filter_by(
                    type_commerce_id=type_commerce.id, code=code, active=True
                ).first()
                if existing:
                    seen_ids.add(existing.id)
                    existing.libelle = ch.get('libelle', existing.libelle).strip()
                    existing.type_champ = ch.get('type_champ', existing.type_champ)
                    existing.placeholder = ch.get('placeholder', existing.placeholder)
                    existing.ordre = int(ch.get('ordre') or existing.ordre)
                    existing.pleine_largeur = bool(ch.get('pleine_largeur', existing.pleine_largeur))
                    continue
                nat_id = type_commerce.nature_poi_id
                if not nat_id:
                    autre = NaturePoi.get_by_code('autre')
                    nat_id = autre.id if autre else None
                nf = ChampPoi(
                    type_commerce_id=type_commerce.id,
                    nature_poi_id=nat_id,
                    code=ch['code'].strip(),
                    libelle=ch['libelle'].strip(),
                    type_champ=ch.get('type_champ', 'str'),
                    placeholder=ch.get('placeholder'),
                    ordre=int(ch.get('ordre') or 0),
                    pleine_largeur=bool(ch.get('pleine_largeur', False)),
                    active=True,
                )
                db.session.add(nf)
                db.session.flush()
                seen_ids.add(nf.id)
    if 'active' in data:
        type_commerce.active = data['active']
    
    db.session.commit()
    data = type_commerce.to_dict(include_champs=True)
    return jsonify(_enrich_type_commerce_dict(type_commerce, data, include_champs=True))


@app.route('/api/types-commerce/<int:type_id>', methods=['DELETE'])
def delete_type_commerce(type_id):
    """Supprimer un type de commerce (désactivation)"""
    type_commerce = TypeCommerce.query.get_or_404(type_id)
    if Boutique.query.filter_by(type_commerce_id=type_id).first():
        return jsonify({'error': 'Impossible de supprimer un type lié à des POI. Désactivez-le plutôt.'}), 400
    type_commerce.active = False
    db.session.commit()
    return jsonify({'message': 'Type de commerce désactivé'}), 200


# ========== API ROUTES POUR LES MARCHÉS ==========

@app.route('/api/marches', methods=['GET'])
def get_marches():
    """Récupérer la liste des marchés"""
    try:
        quartier_id = request.args.get('quartier_id', type=int)
        query = Marche.query.filter_by(active=True)
        if quartier_id:
            query = query.filter_by(quartier_village_id=quartier_id)
        marches = query.all()
        return jsonify([marche.to_dict() for marche in marches])
    except Exception as e:
        print(f"Erreur lors de la récupération des marchés: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/marches', methods=['POST'])
def create_marche():
    """Créer un nouveau marché"""
    try:
        data = request.json
        
        if not data:
            return jsonify({'error': 'Aucune donnée fournie'}), 400
        
        code = data.get('code', '').strip() if data.get('code') else ''
        nom = data.get('nom', '').strip() if data.get('nom') else ''
        
        if not code or not nom:
            return jsonify({'error': 'Code et nom sont requis'}), 400
        
        # Vérifier l'unicité du code
        if Marche.query.filter_by(code=code).first():
            return jsonify({'error': 'Ce code marché existe déjà'}), 400
        
        marche = Marche(
            code=code,
            nom=nom,
            quartier_village_id=data.get('quartier_village_id') if data.get('quartier_village_id') else None,
            adresse=data.get('adresse', '').strip() if data.get('adresse') else '',
            description=data.get('description', '').strip() if data.get('description') else ''
        )
        
        db.session.add(marche)
        db.session.commit()
        
        return jsonify(marche.to_dict()), 201
    except Exception as e:
        print(f"Erreur lors de la création du marché: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        return jsonify({'error': f'Erreur lors de la création: {str(e)}'}), 500


@app.route('/api/marches/<int:marche_id>', methods=['GET'])
def get_marche(marche_id):
    """Récupérer un marché spécifique"""
    marche = Marche.query.get_or_404(marche_id)
    return jsonify(marche.to_dict())


@app.route('/api/marches/<int:marche_id>', methods=['PUT'])
def update_marche(marche_id):
    """Mettre à jour un marché"""
    marche = Marche.query.get_or_404(marche_id)
    data = request.json
    
    if 'nom' in data:
        marche.nom = data['nom'].strip()
    if 'code' in data:
        new_code = data['code'].strip()
        if new_code != marche.code:
            if Marche.query.filter_by(code=new_code).first():
                return jsonify({'error': 'Ce code marché existe déjà'}), 400
            marche.code = new_code
    if 'adresse' in data:
        marche.adresse = data['adresse']
    if 'description' in data:
        marche.description = data['description']
    if 'quartier_village_id' in data:
        marche.quartier_village_id = data['quartier_village_id'] if data['quartier_village_id'] else None
    if 'active' in data:
        marche.active = data['active']
    
    db.session.commit()
    return jsonify(marche.to_dict())


@app.route('/api/marches/<int:marche_id>', methods=['DELETE'])
def delete_marche(marche_id):
    """Supprimer un marché (désactivation)"""
    marche = Marche.query.get_or_404(marche_id)
    
    # Vérifier s'il y a des boutiques associées
    if Boutique.query.filter_by(marche_id=marche_id).first():
        # Désactiver au lieu de supprimer
        marche.active = False
        db.session.commit()
        return jsonify({'message': 'Marché désactivé (des POI y sont associés)'}), 200
    
    db.session.delete(marche)
    db.session.commit()
    return jsonify({'message': 'Marché supprimé'}), 200


# ========== API ROUTES POUR LES INSTITUTS ==========

@app.route('/api/instituts', methods=['GET'])
def get_instituts():
    """Récupérer la liste des instituts"""
    try:
        instituts = Institut.query.filter_by(active=True).all()
        return jsonify([institut.to_dict() for institut in instituts])
    except Exception as e:
        print(f"Erreur lors de la récupération des instituts: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/instituts', methods=['POST'])
def create_institut():
    """Créer un nouvel institut"""
    data = request.json
    
    code = data.get('code', '').strip().upper()
    nom = data.get('nom', '').strip()
    type_institut = data.get('type', 'autre')
    
    if not code or not nom:
        return jsonify({'error': 'Code et nom sont requis'}), 400
    
    # Vérifier l'unicité du code
    if Institut.query.filter_by(code=code).first():
        return jsonify({'error': 'Ce code institut existe déjà'}), 400
    
    institut = Institut(
        code=code,
        nom=nom,
        type=type_institut,
        description=data.get('description', '')
    )
    
    db.session.add(institut)
    db.session.commit()
    
    return jsonify(institut.to_dict()), 201


@app.route('/api/instituts/<int:institut_id>', methods=['GET'])
def get_institut(institut_id):
    """Récupérer un institut spécifique"""
    institut = Institut.query.get_or_404(institut_id)
    return jsonify(institut.to_dict())


@app.route('/api/instituts/<int:institut_id>', methods=['PUT'])
def update_institut(institut_id):
    """Mettre à jour un institut"""
    institut = Institut.query.get_or_404(institut_id)
    data = request.json
    
    if 'nom' in data:
        institut.nom = data['nom'].strip()
    if 'code' in data:
        new_code = data['code'].strip().upper()
        if new_code != institut.code:
            if Institut.query.filter_by(code=new_code).first():
                return jsonify({'error': 'Ce code institut existe déjà'}), 400
            institut.code = new_code
    if 'type' in data:
        institut.type = data['type']
    if 'description' in data:
        institut.description = data['description']
    if 'active' in data:
        institut.active = data['active']
    
    db.session.commit()
    return jsonify(institut.to_dict())


@app.route('/api/instituts/<int:institut_id>', methods=['DELETE'])
def delete_institut(institut_id):
    """Supprimer un institut (désactivation)"""
    institut = Institut.query.get_or_404(institut_id)
    
    # Vérifier s'il y a des paiements associés
    if Paiement.query.filter_by(institut_id=institut_id).first():
        # Désactiver au lieu de supprimer
        institut.active = False
        db.session.commit()
        return jsonify({'message': 'Institut désactivé (des paiements y sont associés)'}), 200
    
    db.session.delete(institut)
    db.session.commit()
    return jsonify({'message': 'Institut supprimé'}), 200


# ========== API ROUTES POUR LES TAXES ==========

@app.route('/api/taxes', methods=['GET'])
def get_taxes():
    """Récupérer la liste des taxes"""
    try:
        from sqlalchemy.orm import joinedload
        institut_id = request.args.get('institut_id', type=int)
        query = Taxe.query.options(joinedload(Taxe.institut)).filter_by(active=True)
        if institut_id:
            query = query.filter_by(institut_id=institut_id)
        taxes = query.all()
        return jsonify([taxe.to_dict() for taxe in taxes])
    except Exception as e:
        print(f"Erreur lors de la récupération des taxes: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/taxes', methods=['POST'])
def create_taxe():
    """Créer une nouvelle taxe"""
    data = request.json
    
    institut_id = data.get('institut_id')
    code = data.get('code', '').strip().upper()
    nom = data.get('nom', '').strip()
    montant_attendu = float(data.get('montant_attendu', 0))
    
    if not institut_id or not code or not nom or montant_attendu <= 0:
        return jsonify({'error': 'institut_id, code, nom et montant_attendu sont requis'}), 400
    
    # Vérifier que l'institut existe
    institut = Institut.query.get(institut_id)
    if not institut:
        return jsonify({'error': 'Institut non trouvé'}), 404
    
    # Vérifier l'unicité du code pour cet institut
    if Taxe.query.filter_by(institut_id=institut_id, code=code).first():
        return jsonify({'error': 'Ce code taxe existe déjà pour cet institut'}), 400
    
    taxe = Taxe(
        institut_id=institut_id,
        code=code,
        nom=nom,
        description=data.get('description', ''),
        montant_attendu=montant_attendu,
        periodicite=data.get('periodicite', 'mensuel')
    )
    
    db.session.add(taxe)
    db.session.commit()
    
    return jsonify(taxe.to_dict()), 201


@app.route('/api/taxes/<int:taxe_id>', methods=['GET'])
def get_taxe(taxe_id):
    """Récupérer une taxe spécifique"""
    taxe = Taxe.query.get_or_404(taxe_id)
    return jsonify(taxe.to_dict())


@app.route('/api/taxes/<int:taxe_id>', methods=['PUT'])
def update_taxe(taxe_id):
    """Mettre à jour une taxe"""
    taxe = Taxe.query.get_or_404(taxe_id)
    data = request.json
    
    if 'nom' in data:
        taxe.nom = data['nom'].strip()
    if 'code' in data:
        new_code = data['code'].strip().upper()
        if new_code != taxe.code:
            if Taxe.query.filter_by(institut_id=taxe.institut_id, code=new_code).first():
                return jsonify({'error': 'Ce code taxe existe déjà pour cet institut'}), 400
            taxe.code = new_code
    if 'description' in data:
        taxe.description = data['description']
    if 'montant_attendu' in data:
        taxe.montant_attendu = float(data['montant_attendu'])
    if 'periodicite' in data:
        taxe.periodicite = data['periodicite']
    if 'active' in data:
        taxe.active = data['active']
    
    db.session.commit()
    return jsonify(taxe.to_dict())


@app.route('/api/taxes/<int:taxe_id>', methods=['DELETE'])
def delete_taxe(taxe_id):
    """Supprimer une taxe (désactivation)"""
    taxe = Taxe.query.get_or_404(taxe_id)
    
    # Vérifier s'il y a des paiements associés
    if Paiement.query.filter_by(taxe_id=taxe_id).first():
        # Désactiver au lieu de supprimer
        taxe.active = False
        db.session.commit()
        return jsonify({'message': 'Taxe désactivée (des paiements y sont associés)'}), 200
    
    db.session.delete(taxe)
    db.session.commit()
    return jsonify({'message': 'Taxe supprimée'}), 200


# ========== API ROUTES POUR LA GESTION DES PAIEMENTS ==========

@app.route('/api/taxes-non-payees', methods=['GET'])
def get_taxes_non_payees():
    """Liste des taxes non payées (en retard) - pour l'onglet 'Paiements en attente'"""
    mois = request.args.get('mois', type=int) or datetime.utcnow().month
    annee = request.args.get('annee', type=int) or datetime.utcnow().year
    boutique_id = request.args.get('boutique_id', type=int)
    institut_id = request.args.get('institut_id', type=int)
    taxe_id = request.args.get('taxe_id', type=int)
    search = (request.args.get('search') or '').strip()

    result = []
    boutiques = Boutique.query.filter_by(active=True)
    if boutique_id:
        boutiques = boutiques.filter_by(id=boutique_id)

    for boutique in boutiques.all():
        boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=boutique.id, active=True).all()
        for bt in boutique_taxes:
            taxe = bt.taxe
            if not taxe or not taxe.active:
                continue
            if institut_id and taxe.institut_id != institut_id:
                continue
            if taxe_id and taxe.id != taxe_id:
                continue
            paiement = Paiement.query.filter_by(
                boutique_id=boutique.id, taxe_id=taxe.id,
                mois=mois, annee=annee, statut='confirme'
            ).first()
            if paiement:
                continue
            montant = bt.montant_personnalise if bt.montant_personnalise else taxe.montant_attendu
            item = {
                'boutique_id': boutique.id,
                'boutique_code': boutique.code_unique,
                'boutique_nom': boutique.nom,
                'proprietaire': boutique.proprietaire,
                'institut_id': taxe.institut_id,
                'institut_nom': taxe.institut.nom if taxe.institut else '',
                'taxe_id': taxe.id,
                'taxe_nom': taxe.nom,
                'taxe_code': taxe.code,
                'montant_attendu': montant,
                'mois': mois,
                'annee': annee
            }
            if search:
                term = search.lower()
                searchable = f"{item['boutique_code']} {item['boutique_nom']} {item['proprietaire'] or ''} {item['institut_nom']} {item['taxe_nom']}".lower()
                if term not in searchable:
                    continue
            result.append(item)
    return jsonify(result)


@app.route('/api/paiements', methods=['GET'])
def get_all_paiements():
    """Récupérer tous les paiements avec filtres et recherche"""
    try:
        boutique_id = request.args.get('boutique_id', type=int)
        institut_id = request.args.get('institut_id', type=int)
        taxe_id = request.args.get('taxe_id', type=int)
        mois = request.args.get('mois', type=int)
        annee = request.args.get('annee', type=int)
        statut = request.args.get('statut')  # 'en_attente', 'confirme', 'annule', 'tous'
        search = (request.args.get('search') or '').strip()
        
        query = Paiement.query.join(Boutique).join(Institut)
        
        if boutique_id:
            query = query.filter(Paiement.boutique_id == boutique_id)
        if institut_id:
            query = query.filter(Paiement.institut_id == institut_id)
        if taxe_id:
            query = query.filter(Paiement.taxe_id == taxe_id)
        if mois:
            query = query.filter(Paiement.mois == mois)
        if annee:
            query = query.filter(Paiement.annee == annee)
        if statut and statut != 'tous':
            query = query.filter(Paiement.statut == statut)
        
        if search:
            term = f'%{search}%'
            from sqlalchemy import or_
            query = query.outerjoin(Taxe, Paiement.taxe_id == Taxe.id)
            query = query.filter(
                or_(
                    Boutique.code_unique.ilike(term),
                    Boutique.nom.ilike(term),
                    Boutique.proprietaire.ilike(term),
                    Institut.nom.ilike(term),
                    Paiement.reference_transaction.ilike(term),
                    Taxe.nom.ilike(term)
                )
            ).distinct()
        
        paiements = query.order_by(Paiement.date_paiement.desc()).all()
        return jsonify([p.to_dict() for p in paiements])
    except Exception as e:
        print(f"Erreur lors de la récupération des paiements: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/paiements', methods=['POST'])
def create_paiement():
    """Créer un nouveau paiement manuellement"""
    try:
        data = request.json
        
        boutique_id = data.get('boutique_id')
        institut_id = data.get('institut_id')
        taxe_id = data.get('taxe_id')
        montant = float(data.get('montant', 0))
        mois = data.get('mois', datetime.utcnow().month)
        annee = data.get('annee', datetime.utcnow().year)
        methode = data.get('methode', 'AUTRE')
        reference_transaction = data.get('reference_transaction', f"MAN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
        numero_telephone = data.get('numero_telephone', '')
        statut = data.get('statut', 'confirme')
        notes = data.get('notes', '')
        
        # Validations
        if not boutique_id:
            return jsonify({'error': 'Commerce requis'}), 400
        if not institut_id:
            return jsonify({'error': 'Institution requise'}), 400
        if montant <= 0:
            return jsonify({'error': 'Montant doit être supérieur à 0'}), 400
        
        # Vérifier que le commerce existe
        boutique = Boutique.query.get(boutique_id)
        if not boutique:
            return jsonify({'error': 'Commerce non trouvé'}), 404
        
        # Vérifier que l'institution existe
        institut = Institut.query.get(institut_id)
        if not institut:
            return jsonify({'error': 'Institution non trouvée'}), 404
        
        # Vérifier que la taxe existe si fournie
        if taxe_id:
            taxe = Taxe.query.get(taxe_id)
            if not taxe:
                return jsonify({'error': 'Taxe non trouvée'}), 404
            if taxe.institut_id != institut_id:
                return jsonify({'error': 'La taxe n\'appartient pas à cette institution'}), 400
        
        # Vérifier l'unicité de la référence
        if Paiement.query.filter_by(reference_transaction=reference_transaction).first():
            return jsonify({'error': 'Cette référence de transaction existe déjà'}), 400
        
        # Créer le paiement
        paiement = Paiement(
            boutique_id=boutique_id,
            institut_id=institut_id,
            taxe_id=taxe_id,
            montant=montant,
            mois=mois,
            annee=annee,
            methode=methode,
            numero_transaction=generer_numero_transaction(),
            reference_transaction=reference_transaction,
            numero_telephone=numero_telephone,
            statut=statut,
            notes=notes
        )
        
        db.session.add(paiement)
        db.session.commit()
        
        return jsonify(paiement.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la création du paiement: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/paiements/<int:paiement_id>', methods=['GET'])
def get_paiement(paiement_id):
    """Récupérer un paiement par ID"""
    paiement = Paiement.query.get_or_404(paiement_id)
    return jsonify(paiement.to_dict())


def generate_receipt_qr_base64(paiement_id):
    """Génère un QR code pour la vérification du reçu (base64)"""
    verify_url = request.url_root.rstrip('/') + url_for('verifier_receipt', paiement_id=paiement_id)
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(verify_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


@app.route('/verifier-receipt/<int:paiement_id>')
def verifier_receipt(paiement_id):
    """Page publique de vérification d'un reçu (accessible via scan QR)"""
    paiement = Paiement.query.get_or_404(paiement_id)
    mois_noms = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    return render_template('verifier_receipt.html', paiement=paiement, mois_noms=mois_noms)


@app.route('/paiements/<int:paiement_id>/receipt')
@require_access('/paiements')
def receipt_paiement(paiement_id):
    """Afficher et imprimer le reçu de paiement (agents)"""
    paiement = Paiement.query.get_or_404(paiement_id)
    mois_noms = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    qr_base64 = generate_receipt_qr_base64(paiement_id)
    return render_template('receipt_paiement.html', paiement=paiement, mois_noms=mois_noms, now=datetime.utcnow(), qr_base64=qr_base64)


@app.route('/commercant/receipt/<int:paiement_id>')
@commercant_required
def receipt_paiement_commercant(paiement_id):
    """Afficher et imprimer le reçu de paiement (commerçant)"""
    boutique_id = session.get('boutique_id')
    if not boutique_id:
        return redirect(url_for('commercant_connexion'))
    paiement = Paiement.query.filter_by(id=paiement_id, boutique_id=boutique_id).first_or_404()
    mois_noms = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
                 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']
    qr_base64 = generate_receipt_qr_base64(paiement_id)
    return render_template('receipt_paiement.html', paiement=paiement, mois_noms=mois_noms, now=datetime.utcnow(), qr_base64=qr_base64)


@app.route('/api/paiements/<int:paiement_id>', methods=['PUT'])
def update_paiement(paiement_id):
    """Modifier un paiement"""
    try:
        paiement = Paiement.query.get_or_404(paiement_id)
        data = request.json
        
        if 'montant' in data:
            montant = float(data['montant'])
            if montant <= 0:
                return jsonify({'error': 'Montant doit être supérieur à 0'}), 400
            paiement.montant = montant
        
        if 'mois' in data:
            paiement.mois = int(data['mois'])
        if 'annee' in data:
            paiement.annee = int(data['annee'])
        if 'methode' in data:
            paiement.methode = data['methode']
        if 'statut' in data:
            paiement.statut = data['statut']
        if 'numero_telephone' in data:
            paiement.numero_telephone = data['numero_telephone']
        if 'notes' in data:
            paiement.notes = data['notes']
        if 'reference_transaction' in data:
            # Vérifier l'unicité si la référence change
            ref = data['reference_transaction']
            existing = Paiement.query.filter_by(reference_transaction=ref).first()
            if existing and existing.id != paiement_id:
                return jsonify({'error': 'Cette référence de transaction existe déjà'}), 400
            paiement.reference_transaction = ref
        
        db.session.commit()
        return jsonify(paiement.to_dict())
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de la modification du paiement: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/paiements/<int:paiement_id>', methods=['DELETE'])
def delete_paiement(paiement_id):
    """Supprimer ou annuler un paiement"""
    try:
        paiement = Paiement.query.get_or_404(paiement_id)
        
        # Au lieu de supprimer, on annule le paiement pour garder l'historique
        paiement.statut = 'annule'
        db.session.commit()
        
        return jsonify({'message': 'Paiement annulé', 'paiement': paiement.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Erreur lors de l'annulation du paiement: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/paiements')
@require_access('/paiements')
def paiements_page():
    """Page de gestion des paiements"""
    return render_template('paiements.html')


@app.route('/users')
@require_access('/users')
def users_page():
    """Page de gestion des utilisateurs (admin)"""
    return render_template('users.html')


@app.route('/journal-collectes')
@require_access('/journal-collectes')
def journal_collectes_page():
    """Page journal des collectes terrain (admin)"""
    return render_template('journal_collectes.html')


@app.route('/api/journal-collectes', methods=['GET'])
@role_required('admin')
def api_journal_collectes():
    """Liste des collectes terrain pour l'admin"""
    date_debut = request.args.get('date_debut')
    date_fin = request.args.get('date_fin')
    collecteur_id = request.args.get('collecteur_id', type=int)
    search = request.args.get('search', '').strip()
    
    q = CollecteTerrain.query
    
    if date_debut:
        try:
            dt = datetime.strptime(date_debut, '%Y-%m-%d')
            q = q.filter(CollecteTerrain.date_heure >= dt)
        except ValueError:
            pass
    if date_fin:
        try:
            dt = datetime.strptime(date_fin, '%Y-%m-%d')
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            q = q.filter(CollecteTerrain.date_heure <= dt)
        except ValueError:
            pass
    if collecteur_id:
        q = q.filter(CollecteTerrain.collecteur_id == collecteur_id)
    if search:
        from sqlalchemy import or_
        q = q.join(Boutique).outerjoin(User, CollecteTerrain.collecteur_id == User.id)
        q = q.filter(
            or_(
                Boutique.code_unique.ilike(f'%{search}%'),
                Boutique.nom.ilike(f'%{search}%'),
                CollecteTerrain.secteur.ilike(f'%{search}%'),
                User.nom.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%')
            )
        )
    
    collectes = q.order_by(CollecteTerrain.date_heure.desc()).all()
    return jsonify({
        'collectes': [c.to_dict() for c in collectes],
        'total': len(collectes)
    })


@app.route('/api/boutiques/<int:boutique_id>/releve', methods=['GET'])
def get_boutique_releve(boutique_id):
    """Relevé complet des paiements d'un POI (recouvrés, non recouvrés, en attente)."""
    boutique = Boutique.query.get_or_404(boutique_id)
    mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
    releve = boutique.get_releve_paiements(mois_fin, annee_fin, mois_debut, annee_debut)
    return jsonify({
        'boutique': boutique.to_dict(),
        **releve
    })


@app.route('/api/commercant/mon-releve', methods=['GET'])
@commercant_required
def api_commercant_mon_releve():
    """Relevé des paiements du POI du contribuable connecté."""
    boutique_id = session.get('boutique_id')
    if not boutique_id:
        return jsonify({'error': 'Session invalide'}), 401
    boutique = Boutique.query.get_or_404(boutique_id)
    mois_debut, annee_debut, mois_fin, annee_fin = parse_periode_params()
    releve = boutique.get_releve_paiements(mois_fin, annee_fin, mois_debut, annee_debut)
    return jsonify({
        'boutique': boutique.to_dict(),
        **releve
    })


@app.route('/api/boutiques/<int:boutique_id>/taxes', methods=['GET'])
def get_boutique_taxes_status(boutique_id):
    """Récupérer le statut des taxes pour une boutique (payées/non payées avec montants attendus)"""
    boutique = Boutique.query.get_or_404(boutique_id)
    mois = request.args.get('mois', type=int) or datetime.utcnow().month
    annee = request.args.get('annee', type=int) or datetime.utcnow().year
    
    # Récupérer uniquement les taxes associées à ce commerce via BoutiqueTaxe
    boutique_taxes = BoutiqueTaxe.query.filter_by(boutique_id=boutique_id, active=True).all()
    
    result = []
    for boutique_taxe in boutique_taxes:
        taxe = boutique_taxe.taxe
        if not taxe or not taxe.active:
            continue
        
        # Utiliser le montant personnalisé si défini, sinon le montant attendu de la taxe
        montant_attendu = boutique_taxe.montant_personnalise if boutique_taxe.montant_personnalise else taxe.montant_attendu
        
        # Vérifier si cette taxe a été payée pour ce mois
        paiement = Paiement.query.filter_by(
            boutique_id=boutique_id,
            taxe_id=taxe.id,
            mois=mois,
            annee=annee,
            statut='confirme'
        ).first()
        
        result.append({
            'taxe': taxe.to_dict(),
            'institut_nom': taxe.institut.nom if taxe.institut else 'Inconnu',
            'payee': paiement is not None,
            'paiement': paiement.to_dict() if paiement else None,
            'montant_attendu': montant_attendu,
            'montant_paye': paiement.montant if paiement else 0,
            'difference': (paiement.montant - montant_attendu) if paiement else -montant_attendu
        })
    
    return jsonify({
        'boutique': boutique.to_dict(),
        'mois': mois,
        'annee': annee,
        'taxes_status': result
    })


@app.route('/health')
def health():
    """Sonde légère pour load balancer / monitoring."""
    return jsonify({'status': 'ok', 'service': 'paiement-fisc'})


@app.route('/health/ready')
def health_ready():
    """Sonde readiness : base de données (+ Redis/PostGIS si configurés)."""
    checks = {'database': False, 'redis': None, 'postgis': None}
    try:
        db.session.execute(db.text('SELECT 1'))
        checks['database'] = True
    except Exception as exc:
        return jsonify({'status': 'error', 'checks': checks, 'error': str(exc)}), 503

    from cache_utils import get_redis
    redis_client = get_redis()
    if redis_client:
        try:
            redis_client.ping()
            checks['redis'] = True
        except Exception:
            checks['redis'] = False

    from spatial_utils import postgis_available
    if db.engine.dialect.name == 'postgresql':
        checks['postgis'] = postgis_available(db.engine)

    status = 200 if checks['database'] else 503
    return jsonify({'status': 'ready' if checks['database'] else 'error', 'checks': checks}), status


@app.after_request
def log_request_timing(response):
    """Journalise la durée des requêtes API en production."""
    import logging
    import time
    if not request.path.startswith('/api/') and request.path not in ('/health', '/health/ready'):
        return response
    start = getattr(request, '_start_time', None)
    if start is not None:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logging.getLogger('geotax.access').info(
            '%s %s %s',
            request.method,
            request.path,
            response.status_code,
            extra={'duration_ms': duration_ms, 'path': request.path, 'method': request.method, 'status': response.status_code},
        )
    return response


@app.before_request
def record_request_start():
    import time
    request._start_time = time.perf_counter()


if __name__ == '__main__':
    with app.app_context():
        init_db()
    debug = _env_bool('FLASK_DEBUG', default=not IS_PRODUCTION)
    port = int(os.environ.get('PORT', '5000'))
    app.run(debug=debug, host='0.0.0.0', port=port)

