from flask import Flask, render_template, request, jsonify, send_file, url_for, session, redirect
from functools import wraps
from models import db, Institut, Taxe, Boutique, BoutiqueTaxe, Paiement, Configuration, Commercant, User, Pays, Departement, Commune, QuartierVillage, Marche, TypeCommerce
from werkzeug.security import generate_password_hash, check_password_hash
import qrcode
import os
import re
import base64
from datetime import datetime
import openpyxl
from io import BytesIO
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'qr_codes'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'paiement-fisc-congo-2024-secret-key')

# Initialiser la base de données
db.init_app(app)

# Créer le dossier pour les QR codes
os.makedirs('qr_codes', exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs('templates', exist_ok=True)

# Permissions par rôle
ROLE_PERMISSIONS = {
    'agent_terrain': ['/', '/boutiques', '/carte', '/scan'],
    'agent_financier': ['/', '/paiements', '/balances'],
    'conseiller_municipal': ['/', '/boutiques', '/paiements', '/carte', '/scan', '/balances', '/commercant'],
    'admin': ['/', '/boutiques', '/paiements', '/carte', '/scan', '/balances', '/commercant', '/parametrage', '/users']
}

NAV_ITEMS = [
    ('/', 'Tableau de Bord'),
    ('/boutiques', 'Commerces'),
    ('/paiements', 'Paiements'),
    ('/carte', 'Carte'),
    ('/scan', 'Scanner QR Code'),
    ('/balances', 'Balances'),
    ('/parametrage', 'Paramétrage'),
    ('/commercant', 'Espace Commerçant'),
    ('/users', 'Utilisateurs'),
]


def get_nav_items_for_role(role):
    """Retourne les items de navigation pour un rôle"""
    allowed = set(ROLE_PERMISSIONS.get(role, []))
    return [(url, label) for url, label in NAV_ITEMS if url in allowed]


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
    return path in ROLE_PERMISSIONS.get(role, [])


def require_access(path):
    """Décorateur : accès à la page selon le rôle"""
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
            if path not in ROLE_PERMISSIONS.get(user.role, []):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Accès refusé'}), 403
                return render_template('error.html', error='Accès refusé'), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


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


def init_db():
    """Créer les tables de la base de données"""
    with app.app_context():
        try:
            db.create_all()
            
            # Migration : ajouter numero_transaction si la colonne n'existe pas
            try:
                from sqlalchemy import text
                result = db.session.execute(text("PRAGMA table_info(paiements)"))
                columns = [row[1] for row in result.fetchall()]
                if 'numero_transaction' not in columns:
                    db.session.execute(text("ALTER TABLE paiements ADD COLUMN numero_transaction VARCHAR(30)"))
                    db.session.commit()
                # Attribuer un numéro aux paiements existants sans numéro
                for p in Paiement.query.filter(Paiement.numero_transaction.is_(None)).order_by(Paiement.id):
                    annee = p.date_paiement.year if p.date_paiement else datetime.utcnow().year
                    p.numero_transaction = f"TXN-{annee}-{p.id:06d}"
                db.session.commit()
            except Exception as mig_err:
                db.session.rollback()
                print(f"Migration numero_transaction: {mig_err}")
            
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
                    Taxe(institut_id=impots.id, code='TAXE_FISCALE', nom='Taxe Fiscale Mensuelle', montant_attendu=5000, periodicite='mensuel', description='Taxe fiscale mensuelle pour les commerces'),
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
    if path in ('/login', '/logout') or path.startswith('/commercant') or path.startswith('/static'):
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
    return dict(nav_items=nav_items, current_user_role=role)


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """Page de connexion"""
    if session.get('user_id'):
        return redirect(url_for('index'))
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
        next_url = request.args.get('next') or url_for('index')
        return redirect(next_url)
    return render_template('login.html')


@app.route('/logout')
def logout_page():
    """Déconnexion"""
    session.clear()
    return redirect(url_for('login_page'))


@app.route('/')
@require_access('/')
def index():
    """Page d'accueil - Tableau de bord"""
    return render_template('dashboard.html')


@app.route('/api/boutiques', methods=['GET'])
def get_boutiques():
    """Récupérer la liste des commerces avec filtres"""
    try:
        arrondissement = request.args.get('arrondissement')
        zone = request.args.get('zone')
        marche = request.args.get('marche')
        statut = request.args.get('statut')  # 'a_jour', 'non_a_jour', 'tous'
        with_coords = request.args.get('with_coords', 'false').lower() == 'true'
        
        query = Boutique.query.filter_by(active=True)
        
        # Filtrer par coordonnées si demandé
        if with_coords:
            query = query.filter(Boutique.latitude.isnot(None), Boutique.longitude.isnot(None))
        
        if arrondissement:
            query = query.filter_by(arrondissement=arrondissement)
        if zone:
            query = query.filter_by(zone=zone)
        if marche:
            query = query.filter_by(marche=marche)
        
        boutiques = query.all()
        
        result = []
        mois_actuel = datetime.utcnow().month
        annee_actuelle = datetime.utcnow().year
        
        for boutique in boutiques:
            try:
                a_jour = boutique.get_statut_paiement_mois(mois_actuel, annee_actuelle)
                
                if statut == 'a_jour' and not a_jour:
                    continue
                if statut == 'non_a_jour' and a_jour:
                    continue
                
                boutique_dict = boutique.to_dict()
                boutique_dict['a_jour'] = a_jour
                boutique_dict['a_compte_commercant'] = hasattr(boutique, 'commercant') and boutique.commercant is not None
                try:
                    dernier_paiement = boutique.get_dernier_paiement()
                    boutique_dict['dernier_paiement'] = dernier_paiement.to_dict() if dernier_paiement else None
                except:
                    boutique_dict['dernier_paiement'] = None
                result.append(boutique_dict)
            except Exception as e:
                print(f"Erreur lors du traitement de la boutique {boutique.id}: {e}")
                continue
        
        return jsonify(result)
    except Exception as e:
        print(f"Erreur dans get_boutiques: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération des commerces', 'message': str(e)}), 500


@app.route('/api/boutiques', methods=['POST'])
def create_boutique():
    """Créer une nouvelle boutique et générer son QR code"""
    data = request.json
    
    # Générer un code unique
    code_unique = data.get('code_unique') or f"BOUTIQUE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    # Vérifier l'unicité
    if Boutique.query.filter_by(code_unique=code_unique).first():
        return jsonify({'error': 'Ce code boutique existe déjà'}), 400
    
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
    
    # Récupérer le type_commerce_id si fourni
    type_commerce_id = data.get('type_commerce_id')
    if type_commerce_id:
        # Vérifier que le type de commerce existe
        if not TypeCommerce.query.get(type_commerce_id):
            return jsonify({'error': 'Type de commerce non trouvé'}), 404
    
    boutique = Boutique(
        code_unique=code_unique,
        nom=data.get('nom', ''),
        proprietaire=data.get('proprietaire', ''),
        telephone=data.get('telephone', ''),
        adresse=data.get('adresse', ''),
        type_commerce_id=type_commerce_id,
        quartier_village_id=quartier_village_id,
        marche_id=marche_id,
        marche_nom=data.get('marche_nom', ''),  # Conservé pour compatibilité
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        # Anciens champs pour compatibilité
        arrondissement=data.get('arrondissement', ''),
        zone=data.get('zone', ''),
        marche=data.get('marche', '')
    )
    
    db.session.add(boutique)
    db.session.flush()
    
    # Associer les taxes au commerce
    taxes_data = data.get('taxes', [])
    if not taxes_data:
        return jsonify({'error': 'Au moins une taxe doit être sélectionnée'}), 400
    
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
    
    # Générer le QR code
    qr_path = generate_qr_code(boutique.id, code_unique)
    boutique.qr_code_path = qr_path
    
    db.session.commit()
    
    return jsonify(boutique.to_dict()), 201


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
        type_commerce_id = data['type_commerce_id']
        if type_commerce_id:
            if not TypeCommerce.query.get(type_commerce_id):
                return jsonify({'error': 'Type de commerce non trouvé'}), 404
        boutique.type_commerce_id = type_commerce_id
    if 'taxes' in data:
        # Supprimer les anciennes associations
        BoutiqueTaxe.query.filter_by(boutique_id=boutique.id).delete()
        # Ajouter les nouvelles associations
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
    if 'latitude' in data:
        boutique.latitude = data['latitude']
    if 'longitude' in data:
        boutique.longitude = data['longitude']
    if 'arrondissement' in data:
        boutique.arrondissement = data['arrondissement']
    if 'zone' in data:
        boutique.zone = data['zone']
    if 'marche' in data:
        boutique.marche = data['marche']
    if 'active' in data:
        boutique.active = data['active']
    
    db.session.commit()
    return jsonify(boutique.to_dict())


@app.route('/api/boutiques/<int:boutique_id>', methods=['DELETE'])
def delete_boutique(boutique_id):
    """Supprimer un commerce (désactivation)"""
    boutique = Boutique.query.get_or_404(boutique_id)
    
    # Désactiver au lieu de supprimer pour préserver l'historique
    boutique.active = False
    db.session.commit()
    
    return jsonify({'message': 'Boutique désactivée'}), 200


@app.route('/api/boutiques/<int:boutique_id>/qr', methods=['GET'])
def get_qr_code(boutique_id):
    """Récupérer l'image du QR code d'un commerce"""
    boutique = Boutique.query.get_or_404(boutique_id)
    if boutique.qr_code_path and os.path.exists(boutique.qr_code_path):
        return send_file(boutique.qr_code_path, mimetype='image/png')
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
    
    # Statut global (toutes les taxes payées)
    toutes_taxes_payees = all(t['payee'] for t in taxes_status) if taxes_status else False
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
def get_statistiques():
    """Récupérer les statistiques globales"""
    try:
        total_boutiques = Boutique.query.filter_by(active=True).count()
        
        mois_actuel = datetime.utcnow().month
        annee_actuelle = datetime.utcnow().year
        
        boutiques_a_jour = 0
        boutiques_non_a_jour = 0
        total_paiements_mois = 0
        
        for boutique in Boutique.query.filter_by(active=True).all():
            if boutique.get_statut_paiement_mois(mois_actuel, annee_actuelle):
                boutiques_a_jour += 1
            else:
                boutiques_non_a_jour += 1
        
        paiements_mois = Paiement.query.filter_by(
            mois=mois_actuel,
            annee=annee_actuelle,
            statut='confirme'
        ).all()
        
        total_paiements_mois = sum(p.montant for p in paiements_mois)
        
        # Statistiques par arrondissement
        arrondissements = {}
        for boutique in Boutique.query.filter_by(active=True).all():
            try:
                arr = boutique.arrondissement or 'Non spécifié'
                if arr not in arrondissements:
                    arrondissements[arr] = {'total': 0, 'a_jour': 0, 'non_a_jour': 0}
                arrondissements[arr]['total'] += 1
                if boutique.get_statut_paiement_mois(mois_actuel, annee_actuelle):
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
            'total_paiements_mois': total_paiements_mois,
            'mois': mois_actuel,
            'annee': annee_actuelle,
            'par_arrondissement': arrondissements
        })
    except Exception as e:
        print(f"Erreur dans get_statistiques: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération des statistiques', 'message': str(e)}), 500


@app.route('/api/balance-instituts', methods=['GET'])
def get_balance_instituts():
    """Récupérer la balance des montants recouvrés et non recouvrés par institution"""
    try:
        mois = request.args.get('mois', type=int) or datetime.utcnow().month
        annee = request.args.get('annee', type=int) or datetime.utcnow().year
        
        result = []
        
        # Pour chaque institution active
        for institut in Institut.query.filter_by(active=True).all():
            # Récupérer toutes les taxes actives de cette institution
            taxes = Taxe.query.filter_by(institut_id=institut.id, active=True).all()
            
            # Calculer les montants attendus
            # Pour chaque commerce actif, on doit payer chaque taxe mensuelle
            commerces_actifs = Boutique.query.filter_by(active=True).count()
            montant_attendu_total = 0
            
            for taxe in taxes:
                # Si la taxe est mensuelle, on compte pour ce mois
                if taxe.periodicite == 'mensuel':
                    montant_attendu_total += taxe.montant_attendu * commerces_actifs
                elif taxe.periodicite == 'trimestriel':
                    # Pour un trimestriel, on divise par 3 (approximation)
                    montant_attendu_total += (taxe.montant_attendu / 3) * commerces_actifs
                elif taxe.periodicite == 'annuel':
                    # Pour un annuel, on divise par 12
                    montant_attendu_total += (taxe.montant_attendu / 12) * commerces_actifs
                # Pour ponctuel, on ne compte pas dans le mensuel
            
            # Calculer les montants recouvrés (paiements confirmés pour ce mois)
            paiements = Paiement.query.filter_by(
                institut_id=institut.id,
                mois=mois,
                annee=annee,
                statut='confirme'
            ).all()
            
            montant_recouvre = sum(p.montant for p in paiements)
            montant_non_recouvre = max(0, montant_attendu_total - montant_recouvre)
            
            # Calculer le taux de recouvrement
            taux_recouvrement = (montant_recouvre / montant_attendu_total * 100) if montant_attendu_total > 0 else 0
            
            # Nombre de commerces ayant payé
            commerces_ayant_paye = len(set(p.boutique_id for p in paiements))
            
            result.append({
                'institut_id': institut.id,
                'institut_code': institut.code,
                'institut_nom': institut.nom,
                'institut_type': institut.type,
                'mois': mois,
                'annee': annee,
                'montant_attendu': round(montant_attendu_total, 2),
                'montant_recouvre': round(montant_recouvre, 2),
                'montant_non_recouvre': round(montant_non_recouvre, 2),
                'taux_recouvrement': round(taux_recouvrement, 2),
                'commerces_actifs': commerces_actifs,
                'commerces_ayant_paye': commerces_ayant_paye,
                'commerces_n_ayant_pas_paye': commerces_actifs - commerces_ayant_paye,
                'nombre_taxes': len(taxes),
                'nombre_paiements': len(paiements)
            })
        
        return jsonify({
            'balance_par_institut': result,
            'total_attendu': round(sum(r['montant_attendu'] for r in result), 2),
            'total_recouvre': round(sum(r['montant_recouvre'] for r in result), 2),
            'total_non_recouvre': round(sum(r['montant_non_recouvre'] for r in result), 2),
            'mois': mois,
            'annee': annee
        })
    except Exception as e:
        print(f"Erreur dans get_balance_instituts: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Erreur lors de la récupération de la balance', 'message': str(e)}), 500


@app.route('/api/balance-par-taxes', methods=['GET'])
def get_balance_par_taxes():
    """Balance financière par taxe (montants recouvrés)"""
    try:
        mois = request.args.get('mois', type=int) or datetime.utcnow().month
        annee = request.args.get('annee', type=int) or datetime.utcnow().year
        
        from sqlalchemy import func
        result = db.session.query(
            Taxe.id, Taxe.nom, Taxe.code, Taxe.institut_id,
            func.sum(Paiement.montant).label('montant_recouvre'),
            func.count(Paiement.id).label('nombre_paiements')
        ).join(Paiement, Paiement.taxe_id == Taxe.id).filter(
            Paiement.mois == mois,
            Paiement.annee == annee,
            Paiement.statut == 'confirme',
            Taxe.active == True
        ).group_by(Taxe.id).all()
        
        balance_taxes = []
        for r in result:
            taxe = Taxe.query.get(r.id)
            balance_taxes.append({
                'taxe_id': r.id,
                'taxe_nom': r.nom,
                'taxe_code': r.code,
                'institut_id': r.institut_id,
                'institut_nom': taxe.institut.nom if taxe and taxe.institut else None,
                'montant_recouvre': round(float(r.montant_recouvre or 0), 2),
                'nombre_paiements': r.nombre_paiements or 0
            })
        
        total_recouvre = sum(t['montant_recouvre'] for t in balance_taxes)
        
        return jsonify({
            'balance_par_taxe': balance_taxes,
            'total_recouvre': round(total_recouvre, 2),
            'mois': mois,
            'annee': annee
        })
    except Exception as e:
        print(f"Erreur get_balance_par_taxes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/balance-repartition', methods=['GET'])
def get_balance_repartition():
    """Répartition du montant recouvré entre les partenaires"""
    try:
        mois = request.args.get('mois', type=int) or datetime.utcnow().month
        annee = request.args.get('annee', type=int) or datetime.utcnow().year
        
        paiements = Paiement.query.filter_by(
            mois=mois, annee=annee, statut='confirme'
        ).all()
        total_recouvre = sum(p.montant for p in paiements)
        
        pct_institution = float(Configuration.get('repartition_institution', 80))
        pct_partenaire = float(Configuration.get('repartition_partenaire_technique', 17))
        pct_mtn = float(Configuration.get('repartition_mtn', 3))
        
        montant_institution = round(total_recouvre * (pct_institution / 100), 2)
        montant_partenaire = round(total_recouvre * (pct_partenaire / 100), 2)
        montant_mtn = round(total_recouvre * (pct_mtn / 100), 2)
        
        return jsonify({
            'total_recouvre': round(total_recouvre, 2),
            'mois': mois,
            'annee': annee,
            'repartition': {
                'institution': {
                    'pourcentage': pct_institution,
                    'montant': montant_institution
                },
                'partenaire_technique': {
                    'pourcentage': pct_partenaire,
                    'montant': montant_partenaire
                },
                'mtn': {
                    'pourcentage': pct_mtn,
                    'montant': montant_mtn
                }
            }
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
@role_required('admin')
def get_users():
    """Liste des utilisateurs (admin)"""
    users = User.query.order_by(User.username).all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/users', methods=['POST'])
@role_required('admin')
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
@role_required('admin')
def get_user(user_id):
    """Récupérer un utilisateur (admin)"""
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@role_required('admin')
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
    ws.title = "Commerces"
    
    # En-têtes
    headers = ['Code', 'Nom', 'Propriétaire', 'Téléphone', 'Adresse', 'Arrondissement', 'Zone', 'Marché', 'Statut Paiement', 'Dernier Paiement']
    ws.append(headers)
    
    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year
    
    # Données
    for boutique in boutiques:
        a_jour = boutique.get_statut_paiement_mois(mois_actuel, annee_actuelle)
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
    
    filename = f"rapport_commerces_{datetime.utcnow().strftime('%Y%m%d')}.xlsx"
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=filename)


@app.route('/scan')
@require_access('/scan')
def scan_page():
    """Page de scan QR code pour les contrôleurs"""
    return render_template('scan.html')


@app.route('/boutiques')
@app.route('/commerces')
@require_access('/boutiques')
def boutiques_page():
    """Page de gestion des commerces"""
    return render_template('commerces.html')


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


@app.route('/carte')
@require_access('/carte')
def carte_page():
    """Page de visualisation des boutiques sur la carte"""
    commerce_id = request.args.get('commerce_id')
    commerce_code = request.args.get('commerce_code')
    return render_template('carte.html', commerce_id=commerce_id, commerce_code=commerce_code)


# ========== ESPACE COMMERÇANT ==========

def normalize_phone(phone):
    """Normalise un numéro de téléphone pour la comparaison"""
    if not phone:
        return ''
    return re.sub(r'[\s\-\.\(\)]', '', str(phone)).strip()


def commercant_required(f):
    """Décorateur pour les routes nécessitant une connexion commerçant"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('commercant_id'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Connexion requise'}), 401
            return redirect(url_for('commercant_connexion'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/commercant')
def commercant_index():
    """Tableau de bord commerçant - redirige vers connexion ou dashboard"""
    if session.get('commercant_id'):
        return redirect(url_for('commercant_dashboard'))
    return redirect(url_for('commercant_connexion'))


@app.route('/commercant/connexion')
def commercant_connexion():
    """Page de connexion commerçant"""
    if session.get('commercant_id'):
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
    
    if normalize_phone(boutique.telephone) != telephone:
        return jsonify({'error': 'Le numéro de téléphone ne correspond pas à celui enregistré pour ce commerce.'}), 400
    
    if Commercant.query.filter_by(boutique_id=boutique.id).first():
        return jsonify({'error': 'Un compte existe déjà pour ce commerce. Connectez-vous.'}), 400
    
    commerçant = Commercant(
        boutique_id=boutique.id,
        telephone=telephone,
        mot_de_passe_hash=generate_password_hash(mot_de_passe)
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
    """Connexion commerçant"""
    data = request.get_json() or {}
    code_unique = (data.get('code_unique') or '').strip().upper()
    mot_de_passe = data.get('mot_de_passe', '')
    
    if not code_unique or not mot_de_passe:
        return jsonify({'error': 'Code boutique et mot de passe requis'}), 400
    
    boutique = Boutique.query.filter_by(code_unique=code_unique, active=True).first()
    if not boutique:
        return jsonify({'error': 'Code boutique ou mot de passe incorrect'}), 401
    
    commerçant = Commercant.query.filter_by(boutique_id=boutique.id, actif=True).first()
    if not commerçant:
        return jsonify({'error': 'Aucun compte pour ce commerce. Inscrivez-vous d\'abord.'}), 401
    
    if not check_password_hash(commerçant.mot_de_passe_hash, mot_de_passe):
        return jsonify({'error': 'Code boutique ou mot de passe incorrect'}), 401
    
    session['commercant_id'] = commerçant.id
    session['boutique_id'] = boutique.id
    return jsonify({
        'success': True,
        'message': 'Connexion réussie',
        'commercant': commerçant.to_dict()
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
    mois_actuel = datetime.utcnow().month
    annee_actuelle = datetime.utcnow().year
    boutique_dict['a_jour'] = boutique.get_statut_paiement_mois(mois_actuel, annee_actuelle)
    dernier_paiement = boutique.get_dernier_paiement()
    boutique_dict['dernier_paiement'] = dernier_paiement.to_dict() if dernier_paiement else None
    return jsonify(boutique_dict)


@app.route('/api/commercant/mes-taxes-a-payer', methods=['GET'])
@commercant_required
def api_commercant_mes_taxes_a_payer():
    """Taxes à payer pour le commerce du commerçant connecté (mois courant)"""
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
    
    if pays_id:
        query = query.filter_by(pays_id=pays_id)
    
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
    
    if departement_id:
        query = query.filter_by(departement_id=departement_id)
    
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
    
    if commune_id:
        query = query.filter_by(commune_id=commune_id)
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


# ========== API ROUTES POUR LES TYPES DE COMMERCE ==========

@app.route('/api/types-commerce', methods=['GET'])
def get_types_commerce():
    """Récupérer la liste des types de commerce"""
    try:
        types = TypeCommerce.query.filter_by(active=True).all()
        return jsonify([t.to_dict() for t in types])
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
            description=data.get('description', '').strip() if data.get('description') else ''
        )
        
        db.session.add(type_commerce)
        db.session.commit()
        
        return jsonify(type_commerce.to_dict()), 201
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
    return jsonify(type_commerce.to_dict())


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
    if 'active' in data:
        type_commerce.active = data['active']
    
    db.session.commit()
    return jsonify(type_commerce.to_dict())


@app.route('/api/types-commerce/<int:type_id>', methods=['DELETE'])
def delete_type_commerce(type_id):
    """Supprimer un type de commerce (désactivation)"""
    type_commerce = TypeCommerce.query.get_or_404(type_id)
    if Boutique.query.filter_by(type_commerce_id=type_id).first():
        return jsonify({'error': 'Impossible de supprimer un type de commerce lié à des commerces. Désactivez-le plutôt.'}), 400
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
        return jsonify({'message': 'Marché désactivé (des commerces y sont associés)'}), 200
    
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
        institut_id = request.args.get('institut_id', type=int)
        query = Taxe.query.filter_by(active=True)
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


if __name__ == '__main__':
    # Initialiser la base de données avant de démarrer
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)

