import os
import functools
from flask import Flask, request, jsonify, render_template, send_from_directory, redirect, session, send_file
import tempfile
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from datetime import datetime, date
import uuid
import io
import json

# Import local modules
from models import db, Product, Client, Invoice, InvoiceItem, Config, ProjectConfirmation, MusicProject, ProjectFinance, Expense, ModuleConfig, Studio, User, ProjectTask, CalendarEvent, TimeLog, WorkLogReport
from utils.pdf_gen import create_invoice_pdf, create_confirmation_pdf, encrypt_pdf, encrypt_pdf_bytes, create_time_report_pdf
from utils.discord_notifier import (
    send_invoice_to_admin, 
    send_confirmation_to_contractors,
    send_invoice_update_to_admin,
    send_invoice_deletion_to_admin,
    send_payment_update_to_admin,
    send_expense_alert_to_admin,
    send_brief_notification,
    send_task_update_notification
)

# Load environment variables
load_dotenv()

# Detect Vercel environment
IS_VERCEL = os.getenv('VERCEL') == '1'

app = Flask(__name__)
# Database path: fallback to data/database.db
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    # Fix for SQLAlchemy/Heroku style postgres:// vs postgresql://
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # On Vercel, the local folder is read-only. Use /tmp for SQLite if no DATABASE_URL is provided.
    if IS_VERCEL:
        db_path = os.path.join('/tmp', 'database.db')
    else:
        db_path = os.path.join(os.getcwd(), 'data', 'database.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'noxtools-dev-secret-change-in-production')
CORS(app, supports_credentials=True)
db.init_app(app)

# Flask-Login setup
login_manager = LoginManager(app)
login_manager.session_protection = 'strong'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized', 'login_required': True}), 401
    return redirect('/login')

# Auth guard for all non-public routes
PUBLIC_PATHS = {'/login', '/api/auth/login', '/static'}

@app.before_request
def require_login_globally():
    # Allow public access to login, static files, and brief forms
    if request.path == '/login' or request.path.startswith('/static'):
        return None
    if request.path == '/api/auth/login':
        return None
    
    # [Brief Independence] Allow public access to brief forms and submission API
    if request.path.startswith('/brief/') or request.path.startswith('/api/public/brief/'):
        return None

    if not current_user.is_authenticated:
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized', 'login_required': True}), 401
        return redirect('/login')


    # Force profile/password update logic
    if current_user.is_authenticated and current_user.must_change_password:
        allowed_paths = [
            '/api/auth/me', 
            '/api/user/profile', 
            '/api/auth/logout',
            '/api/config', # Needed for settings UI
            '/api/modules',
            '/api/studios',
            '/static'
        ]
        is_allowed = any(request.path.startswith(p) for p in allowed_paths) or request.path == '/'
        if not is_allowed and request.path.startswith('/api/'):
            return jsonify({
                'error': 'Wymagana zmiana hasła i uzupełnienie danych profilu', 
                'must_change_password': True
            }), 403

# Ensure folders exist
if IS_VERCEL:
    # Use /tmp for ephemeral storage on Vercel
    PDF_FOLDER = os.path.join('/tmp', 'pdfs')
    COST_UPLOAD_FOLDER = os.path.join('/tmp', 'costs')
    DATA_FOLDER = os.path.join('/tmp', 'data')
else:
    PDF_FOLDER = os.path.join(os.getcwd(), 'static', 'pdfs')
    COST_UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads', 'costs')
    DATA_FOLDER = os.path.join(os.getcwd(), 'data')

os.makedirs(PDF_FOLDER, exist_ok=True)
os.makedirs(COST_UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)
app.config['COST_UPLOAD_FOLDER'] = COST_UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16 MB limit

with app.app_context():
    db.create_all()
    # Manual Migration for existing databases
    def add_column_if_not_exists(table, column, col_type):
        try:
            # Handle reserved words (especially 'user' in PostgreSQL)
            is_postgres = 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']
            quoted_table = f'"{table}"' if (is_postgres or table.lower() == 'user') else table
            
            # Simplified check using SQLAlchemy metadata if possible, but raw SQL is easier here
            # We just try to add it and ignore the "already exists" error
            db.session.execute(db.text(f"ALTER TABLE {quoted_table} ADD COLUMN {column} {col_type}"))
            db.session.commit()
            print(f"[Migration] Added column {column} to {table}")
        except Exception as e:
            db.session.rollback()
            # Ignore "already exists" errors (Postgres: 42701, SQLite: duplicate column name)
            error_msg = str(e).lower()
            if "already exists" in error_msg or "duplicate column name" in error_msg:
                pass 
            else:
                print(f"[Migration] Error adding {column} to {table}: {e}")
    
    # Invoice extensions
    add_column_if_not_exists('invoice', 'description', 'VARCHAR(500)')
    add_column_if_not_exists('invoice', 'contract_number', 'VARCHAR(100)')
    add_column_if_not_exists('invoice', 'document_type', "VARCHAR(20) DEFAULT 'FAKTURA'")
    add_column_if_not_exists('invoice', 'payment_method', "VARCHAR(20) DEFAULT 'PRZELEW'")
    # Product extensions
    add_column_if_not_exists('product', 'category', "VARCHAR(50) DEFAULT 'Produkcja'")
    add_column_if_not_exists('product', 'sort_order', 'INTEGER DEFAULT 0')
    # Studio extensions
    add_column_if_not_exists('studio', 'address', 'VARCHAR(500)')
    # lat/lng removed
    add_column_if_not_exists('studio', 'bank_account', 'VARCHAR(50)')
    # Client extensions
    add_column_if_not_exists('client', 'phone', 'VARCHAR(30)')
    add_column_if_not_exists('client', 'discord_id', 'VARCHAR(100)')
    add_column_if_not_exists('client', 'website', 'VARCHAR(200)')
    # Invoice flags
    add_column_if_not_exists('invoice', 'include_rights_clause', 'BOOLEAN DEFAULT TRUE')
    add_column_if_not_exists('invoice', 'include_qr_code', 'BOOLEAN DEFAULT TRUE')
    add_column_if_not_exists('invoice', 'metadata_json', 'TEXT')
    # CRM & Project extensions
    add_column_if_not_exists('client', 'ltv', 'FLOAT DEFAULT 0.0')
    add_column_if_not_exists('client', 'social_media_links', 'TEXT')
    add_column_if_not_exists('client', 'preferred_gear', 'TEXT')
    # User permissions
    add_column_if_not_exists('user', 'can_manage_catalog', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_history', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_dashboard', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_pos', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_crm', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_finance', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_settings', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_access_projects', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_manage_projects', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'can_manage_tasks', 'BOOLEAN DEFAULT FALSE')
    add_column_if_not_exists('user', 'full_name', 'VARCHAR(100)')
    add_column_if_not_exists('user', 'bank_account', 'VARCHAR(100)')
    
    # ── Calendar migration ──
    # If the table doesn't exist, create_all() would have done it, 
    # but we add manual check for is_public just in case.
    add_column_if_not_exists('music_project', 'assigned_user_id', 'INTEGER')
    add_column_if_not_exists('music_project', 'public_token', 'VARCHAR(36)')
    add_column_if_not_exists('music_project', 'brief_data', 'TEXT')
    add_column_if_not_exists('music_project', 'internal_notes', 'TEXT')
    
    add_column_if_not_exists('client', 'company_name', 'VARCHAR(200)')
    
    # ── Delivery / Map migrations removed (florist residual) ──


    # ── Time Tracking & WorkLogReport: ensured by db.create_all() 
    # but we can add manual checks if needed, db.create_all handles Postgres/Supabase fine.

    # ── Studio Isolation: ensure default studio exists, then migrate ──
    default_studio = Studio.query.first()
    if not default_studio:
        default_studio = Studio(name='Studio Główne', address='', bank_account='')
        db.session.add(default_studio)
        db.session.commit()
        default_studio = Studio.query.first()

    sid = default_studio.id
    add_column_if_not_exists('invoice',       'studio_id', f'INTEGER DEFAULT {sid}')
    add_column_if_not_exists('client',        'studio_id', f'INTEGER DEFAULT {sid}')
    add_column_if_not_exists('music_project', 'studio_id', f'INTEGER DEFAULT {sid}')
    add_column_if_not_exists('expense',       'studio_id', f'INTEGER DEFAULT {sid}')

    # Backfill NULL studio_ids on existing records
    for tbl in ['invoice', 'client', 'music_project', 'expense']:
        try:
            db.session.execute(db.text(f"UPDATE {tbl} SET studio_id={sid} WHERE studio_id IS NULL"))
        except:
            pass
    db.session.commit()

    # ── Default Admin User (first run only) ──
    if not User.query.first():
        admin = User(username='admin', role='ADMIN', assigned_studio_id=sid, 
                     can_manage_catalog=True, can_access_history=True,
                     can_access_dashboard=True, can_access_pos=True, can_access_crm=True,
                     can_access_finance=True, can_access_settings=True, can_access_projects=True)
        # Updated password to match documentation
        admin.set_password('NoxTools2024!')
        db.session.add(admin)
        db.session.commit()
        print("[NDG Shield] ✅ Stworzono konto admin (hasło: NoxTools2024!). Zmień hasło po pierwszym logowaniu!")

    # Initialize default config keys individually if they don't exist
    configs = {
        'ADMIN_WEBHOOK': os.getenv('ADMIN_WEBHOOK', ''),
        'EKIPA_WEBHOOK': os.getenv('EKIPA_WEBHOOK', ''),
        'CONTRACTOR_WEBHOOK': os.getenv('CONTRACTOR_WEBHOOK', ''),
        'MY_NIP': os.getenv('MY_NIP', ''),
        'MY_ACCOUNT': os.getenv('MY_ACCOUNT_NUMBER', ''),
        'MY_NAME': os.getenv('MY_FULL_NAME', 'Imię i Nazwisko'),
        'MY_CITY': os.getenv('MY_CITY', 'Warszawa'),
        'MY_ADDRESS': '',
        'LIMIT_TYPE': 'MONTHLY', # MONTHLY, QUARTERLY, DISABLED
        'LIMIT_VALUE': '3225.00',
        'COST_THRESHOLD_LIMIT': '1000.00',
        'EXPENSE_CATEGORIES': 'VAT,Sprzęt,Media,Podwykonawca,Inne'
    }
    
    for key, value in configs.items():
        if not Config.query.filter_by(key=key).first():
            db.session.add(Config(key=key, value=value))
    
    db.session.commit()

    # Initialize default modules
    DEFAULT_MODULES = [
        {'key': 'pos',     'display_name': 'Punkt Sprzedaży (POS)',   'icon': '🛒', 'is_core': True,  'sort_order': 1},
        {'key': 'crm',     'display_name': 'Klienci i CRM',            'icon': '👥', 'is_core': False, 'sort_order': 2},
        {'key': 'finance', 'display_name': 'Finanse i Koszty',         'icon': '💳', 'is_core': False, 'sort_order': 3},
        {'key': 'studio',  'display_name': 'Projekty Muzyczne (Studio)','icon': '🎤', 'is_core': False, 'sort_order': 4},
        {'key': 'orders_map', 'display_name': 'Logistyka i Mapa Dostaw', 'icon': '🗺️', 'is_core': False, 'sort_order': 5},
    ]

    for mod in DEFAULT_MODULES:
        if not ModuleConfig.query.filter_by(key=mod['key']).first():
            db.session.add(ModuleConfig(
                key=mod['key'],
                display_name=mod['display_name'],
                icon=mod['icon'],
                is_enabled=True,
                is_core=mod['is_core'],
                sort_order=mod['sort_order']
            ))
    db.session.commit()

# --- MODULE DECORATOR ---
def require_module(module_key):
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            mod = ModuleConfig.query.filter_by(key=module_key).first()
            if mod and not mod.is_enabled:
                return jsonify({
                    'error': f'Moduł "{mod.display_name}" jest wyłączony.',
                    'module_disabled': True,
                    'module_key': module_key
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- RBAC DECORATOR ---
def require_role(*roles):
    """Block request if logged-in user does not have one of the specified roles."""
    def decorator(f):
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            if current_user.role not in roles:
                return jsonify({'error': 'Brak uprawnień', 'required_roles': list(roles)}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

# --- STUDIO ISOLATION HELPERS ---
def get_studio_id_for_query():
    """Returns studio_id to filter queries by. Strictly scoped to current context or user assignment."""
    if current_user.role == 'ADMIN':
        sid = request.args.get('studio_id')
        if sid:
            return int(sid)
    
    # Non-admins or admins without override use their assigned studio
    if current_user.assigned_studio_id:
        return current_user.assigned_studio_id
        
    # Emergency fallback: first studio
    try:
        first = Studio.query.first()
        return first.id if first else 1
    except:
        return 1

def get_studio_id_for_create():
    """Returns the studio_id to stamp on newly created records."""
    sid = get_studio_id_for_query()
    return sid

def apply_studio_filter(query, model):
    """Always append studio_id WHERE clause for strict isolation."""
    sid = get_studio_id_for_query()
    return query.filter(model.studio_id == sid)

def get_config_val(key, default=None):
    """Fetch config value for current context studio. Strictly isolated."""
    try:
        sid = get_studio_id_for_query()
    except:
        sid = None
        
    if sid is not None:
        c_local = Config.query.filter_by(key=key, studio_id=sid).first()
        if c_local:
            return c_local.value
            
    # Fallback to hardcoded defaults or Global (studio_id=None) ONLY if local is missing
    # This preserves core system values that might not have been copied yet.
    c_global = Config.query.filter_by(key=key, studio_id=None).first()
    if c_global:
        return c_global.value
        
    return default

# ─────────────────────────────────────────────────────────────────────────────
@app.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect('/')
    return render_template('login.html')

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route('/')
def index():
    return render_template('index.html')

# --- AUTH API ---
@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    data = request.json or {}
    login_identifier = data.get('username', '').strip()
    password = data.get('password', '')
    
    # Check both username and email
    user = User.query.filter(
        (User.username == login_identifier) | (User.email == login_identifier)
    ).first()
    
    if not user or not user.check_password(password) or not user.is_active:
        return jsonify({'success': False, 'error': 'Nieprawidłowy login/e-mail lub hasło'}), 401
    login_user(user, remember=True)
    return jsonify({
        'success': True,
        'user': user.to_dict()
    })

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    logout_user()
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    d = current_user.to_dict()
    # Inject studio specific configurations quickly for frontend POS mode
    d['is_florist'] = get_config_val('IS_FLORIST', 'false').lower() == 'true'
    d['pos_mode'] = get_config_val('POS_MODE', 'AUTO')
    return jsonify(d)

@app.route('/api/auth/switch-studio', methods=['POST'])
@login_required
@require_role('ADMIN')
def auth_switch_studio():
    data = request.json
    studio_id = data.get('studio_id')
    if not studio_id:
        return jsonify({"error": "Studio ID jest wymagane"}), 400
        
    studio = db.session.get(Studio, studio_id)
    if not studio:
        return jsonify({"error": "Studio nie istnieje"}), 404
        
    current_user.assigned_studio_id = studio.id
    db.session.commit()
    return jsonify({"success": True, "studio_name": studio.name})

@app.route('/api/studios', methods=['GET'])
@login_required
@require_role('ADMIN')
def get_studios():
    studios = Studio.query.all()
    return jsonify([{"id": s.id, "name": s.name} for s in studios])


@app.route('/api/auth/change-password', methods=['POST'])
def change_password():
    data = request.json or {}
    if not current_user.check_password(data.get('current_password', '')):
        return jsonify({'success': False, 'error': 'Nieprawidłowe aktualne hasło'}), 400
    current_user.set_password(data['new_password'])
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/user/profile', methods=['POST'])
@login_required
def update_profile():
    data = request.json or {}
    user = current_user
    
    # Basic info
    if 'username' in data:
        new_username = data['username'].strip()
        if new_username and new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                return jsonify({'success': False, 'error': 'Ta nazwa użytkownika jest już zajęta'}), 400
            user.username = new_username

    if 'full_name' in data: user.full_name = data['full_name']
    
    if 'email' in data:
        new_email = data['email'].strip()
        if new_email and new_email != user.email:
            if User.query.filter_by(email=new_email).first():
                return jsonify({'success': False, 'error': 'Ten adres e-mail jest już przypisany do innego konta'}), 400
            user.email = new_email

    if 'nip' in data: user.nip = data['nip']
    if 'pesel' in data: user.pesel = data['pesel']
    if 'id_type' in data: user.id_type = data['id_type']
    if 'address' in data: user.address = data['address']
    
    # Encryption
    if 'pdf_encryption_enabled' in data: 
        user.pdf_encryption_enabled = bool(data['pdf_encryption_enabled'])
    if 'pdf_password' in data: 
        user.pdf_password = data['pdf_password']
        
    # Webhooks
    if 'discord_admin_webhook' in data: 
        user.discord_admin_webhook = data['discord_admin_webhook']
    if 'discord_contractor_webhook' in data: 
        user.discord_contractor_webhook = data['discord_contractor_webhook']
        
    # Password change
    password_changed = False
    if data.get('password'):
        user.set_password(data['password'])
        password_changed = True
        
    # Check if we can release the "must change password" flag
    requirement_met = False
    if user.must_change_password:
        # NEW SIMPLIFIED RULE: Must change password AND provide Full Name.
        if password_changed and user.full_name:
            user.must_change_password = False
            requirement_met = True
            
    db.session.commit()
    
    response = {'success': True, 'user': user.to_dict()}
    if user.must_change_password:
        missing = []
        if not password_changed: missing.append("nowe hasło")
        if not user.full_name: missing.append("imię i nazwisko")
        
        if missing:
            response['message'] = f"Profil zapisany, ale nadal brakuje: {', '.join(missing)}."
            response['requirements_pending'] = True
            
    return jsonify(response)

# --- STUDIOS API (ADMIN only) ---
@app.route('/api/studios', methods=['GET', 'POST'])
@require_role('ADMIN')
def handle_studios():
    if request.method == 'POST':
        data = request.json
        studio = Studio(
            name=data['name'], 
            address=data.get('address', ''), 
            lat=float(data['lat']) if data.get('lat') else None,
            lng=float(data['lng']) if data.get('lng') else None,
            bank_account=data.get('bank_account', '')
        )
        db.session.add(studio)
        db.session.commit()
        return jsonify({'success': True, 'id': studio.id})
    studios = Studio.query.all()
    return jsonify([{
        'id': s.id, 
        'name': s.name, 
        'address': s.address, 
        'lat': s.lat,
        'lng': s.lng,
        'bank_account': s.bank_account
    } for s in studios])

@app.route('/api/studios/<int:id>', methods=['PUT', 'DELETE'])
@require_role('ADMIN')
def handle_single_studio(id):
    studio = db.session.get(Studio, id)
    if not studio:
        return jsonify({'error': 'Studio nie istnieje'}), 404
    if request.method == 'DELETE':
        try:
            # Handle dependencies by setting to NULL or deleting
            User.query.filter_by(assigned_studio_id=id).update({"assigned_studio_id": None})
            Invoice.query.filter_by(studio_id=id).update({"studio_id": None})
            Expense.query.filter_by(studio_id=id).update({"studio_id": None})
            Client.query.filter_by(studio_id=id).update({"studio_id": None})
            MusicProject.query.filter_by(studio_id=id).update({"studio_id": None})
            
            # Delete strictly local records
            Config.query.filter_by(studio_id=id).delete()
            ModuleConfig.query.filter_by(studio_id=id).delete()
            CalendarEvent.query.filter_by(studio_id=id).delete()
            
            # Final check - ensure no objects are holding the studio
            db.session.flush()
            
            db.session.delete(studio)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Błąd podczas usuwania lokalu: {str(e)}'}), 500
    data = request.json
    studio.name = data.get('name', studio.name)
    studio.address = data.get('address', studio.address)
    studio.bank_account = data.get('bank_account', studio.bank_account)
    db.session.commit()
    return jsonify({'success': True})

# Lightweight user list for project assignment (accessible to project managers)
@app.route('/api/users/list', methods=['GET'])
@login_required
def list_users_for_assignment():
    if not (current_user.role == 'ADMIN' or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień'}), 403
    users = User.query.filter_by(is_active=True).all()
    return jsonify([{'id': u.id, 'username': u.username, 'role': u.role} for u in users])

# --- USERS API (ADMIN only) ---
@app.route('/api/users/create', methods=['POST'])
@app.route('/api/users', methods=['GET', 'POST'])
@require_role('ADMIN')
def handle_users():
    if request.method == 'POST':
        data = request.json
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'success': False, 'error': 'Użytkownik o tej nazwie już istnieje'}), 400
        if data.get('email') and User.query.filter_by(email=data['email']).first():
            return jsonify({'success': False, 'error': 'Ten e-mail jest już zajęty'}), 400
        user = User(
            username=data['username'],
            full_name=data.get('full_name'),
            role=data.get('role', 'PRODUCER'),
            assigned_studio_id=data.get('studio_id') or None,
            can_manage_catalog=True if data.get('role') == 'ADMIN' else data.get('can_manage_catalog', False),
            can_access_history=True if data.get('role') == 'ADMIN' else data.get('can_access_history', False),
            can_access_dashboard=True if data.get('role') == 'ADMIN' else data.get('can_access_dashboard', False),
            can_access_pos=True if data.get('role') == 'ADMIN' else data.get('can_access_pos', False),
            can_access_crm=True if data.get('role') == 'ADMIN' else data.get('can_access_crm', False),
            can_access_finance=True if data.get('role') == 'ADMIN' else data.get('can_access_finance', False),
            can_access_settings=True if data.get('role') == 'ADMIN' else data.get('can_access_settings', False),
            can_access_projects=True if data.get('role') == 'ADMIN' else data.get('can_access_projects', False),
            can_manage_projects=True if data.get('role') == 'ADMIN' else data.get('can_manage_projects', False),
            can_manage_tasks=True if data.get('role') == 'ADMIN' else data.get('can_manage_tasks', False),
            can_create_documents=True if data.get('role') == 'ADMIN' else data.get('can_create_documents', False)
        )
        user.set_password(data.get('password', 'changeme123'))
        db.session.add(user)
        db.session.commit()
        return jsonify({'success': True, 'id': user.id})
    return jsonify([u.to_dict() for u in User.query.all()])

@app.route('/api/users/<int:id>', methods=['PUT', 'DELETE'])
@require_role('ADMIN')
def handle_single_user(id):
    user = db.session.get(User, id)
    if not user:
        return jsonify({'error': 'Użytkownik nie istnieje'}), 404
    if request.method == 'DELETE':
        if user.id == current_user.id:
            return jsonify({'error': 'Nie możesz usunąć samego siebie'}), 400
            
        if user.role == 'ADMIN' and User.query.filter_by(role='ADMIN').count() <= 1:
            return jsonify({'error': 'Nie możesz usunąć ostatniego konta administratora.'}), 400
            
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True})
    
    data = request.json
    new_role = data.get('role', user.role)
    
    # Block demotion of the last admin
    if user.role == 'ADMIN' and new_role != 'ADMIN':
        if User.query.filter_by(role='ADMIN').count() <= 1:
            return jsonify({'error': 'Nie możesz odebrać uprawnień jedynemu administratorowi.'}), 400

    user.role = new_role
    
    # "0" from dropdown could mean global studio, ensure we parse properly
    sid = data.get('studio_id')
    user.assigned_studio_id = int(sid) if sid else None
    user.full_name = data.get('full_name', user.full_name)
    
    user.is_active = data.get('is_active', user.is_active)
    
    if new_role == 'ADMIN':
        user.can_manage_catalog = True
        user.can_access_history = True
        user.can_access_dashboard = True
        user.can_access_pos = True
        user.can_access_crm = True
        user.can_access_finance = True
        user.can_access_settings = True
        user.can_access_projects = True
        user.can_manage_projects = True
        user.can_manage_tasks = True
        user.can_create_documents = True

    else:
        user.can_manage_catalog = data.get('can_manage_catalog', user.can_manage_catalog)
        user.can_access_history = data.get('can_access_history', user.can_access_history)
        user.can_access_dashboard = data.get('can_access_dashboard', user.can_access_dashboard)
        user.can_access_pos = data.get('can_access_pos', user.can_access_pos)
        user.can_access_crm = data.get('can_access_crm', user.can_access_crm)
        user.can_access_finance = data.get('can_access_finance', user.can_access_finance)
        user.can_access_settings = data.get('can_access_settings', user.can_access_settings)
        user.can_access_projects = data.get('can_access_projects', user.can_access_projects)
        user.can_manage_projects = data.get('can_manage_projects', user.can_manage_projects)
        user.can_manage_tasks = data.get('can_manage_tasks', user.can_manage_tasks)
        user.can_create_documents = data.get('can_create_documents', user.can_create_documents)

        
    if data.get('password'):
        user.set_password(data['password'])
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/modules', methods=['GET'])
def get_modules():
    sid = get_studio_id_for_query()
    # Fetch modules. For those missing local overrides, use global default.
    all_modules = [
        {'key': 'pos',     'display_name': 'Punkt Sprzedaży (POS)',   'icon': '🛒', 'is_core': True,  'sort_order': 1},
        {'key': 'crm',     'display_name': 'Klienci i CRM',            'icon': '👥', 'is_core': False, 'sort_order': 2},
        {'key': 'finance', 'display_name': 'Finanse i Koszty',         'icon': '💳', 'is_core': False, 'sort_order': 3},
        {'key': 'studio',  'display_name': 'Projekty Muzyczne (Studio)','icon': '🎤', 'is_core': False, 'sort_order': 4},
    ]
    
    result = []
    for m in all_modules:
        mod_db = None
        if sid:
            mod_db = ModuleConfig.query.filter_by(key=m['key'], studio_id=sid).first()
        if not mod_db:
            mod_db = ModuleConfig.query.filter_by(key=m['key'], studio_id=None).first()
            
        result.append({
            'key': m['key'],
            'display_name': m['display_name'],
            'icon': m['icon'],
            'is_enabled': mod_db.is_enabled if mod_db else True,
            'is_core': m['is_core'],
            'sort_order': m['sort_order']
        })
    return jsonify(result)

@app.route('/api/modules/toggle', methods=['POST'])
def toggle_module():
    data = request.json
    key = data.get('key')
    sid = get_studio_id_for_query()
    
    mod = ModuleConfig.query.filter_by(key=key, studio_id=sid).first()
    if not mod:
        # Create a local override
        global_mod = ModuleConfig.query.filter_by(key=key, studio_id=None).first()
        if not global_mod:
             return jsonify({'error': 'Moduł bazowy nie istnieje'}), 404
        mod = ModuleConfig(
            key=key, display_name=global_mod.display_name, icon=global_mod.icon,
            is_enabled=global_mod.is_enabled, is_core=global_mod.is_core,
            sort_order=global_mod.sort_order, studio_id=sid
        )
        db.session.add(mod)
        db.session.commit()
        
    if mod.is_core:
        return jsonify({'error': 'Nie można wyłączyć modułu podstawowego (core)'}), 400
    mod.is_enabled = not mod.is_enabled
    db.session.commit()
    return jsonify({'success': True, 'key': mod.key, 'is_enabled': mod.is_enabled})

# --- API ENDPOINTS ---

@app.route('/api/dashboard', methods=['GET'])
@require_role('ADMIN', 'PRODUCER')
def get_dashboard():
    limit_type = get_config_val('LIMIT_TYPE', 'DISABLED')
    limit_val = float(get_config_val('LIMIT_VALUE', '0.0'))
    
    if limit_type == 'DISABLED':
        return jsonify({
            "monthly_sum": 0,
            "limit": 0,
            "warning": False,
            "critical": False,
            "invoice_count": 0,
            "limit_type": "DISABLED"
        })

    today = date.today()
    if limit_type == 'QUARTERLY':
        # Q1: Jan 1, Q2: Apr 1, Q3: Jul 1, Q4: Oct 1
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start_date = datetime(today.year, q_start_month, 1)
    else: # MONTHLY
        start_date = datetime(today.year, today.month, 1)
    
    invoices_query = Invoice.query.filter(
        Invoice.date >= start_date,
        Invoice.document_type.in_(['FAKTURA', 'PARAGON'])
    )
    invoices_query = apply_studio_filter(invoices_query, Invoice)
    invoices_in_period = invoices_query.all()
    
    total_in_period = sum(inv.total_amount for inv in invoices_in_period)
    
    return jsonify({
        "monthly_sum": total_in_period,
        "limit": limit_val,
        "warning": total_in_period > (limit_val * 0.9),
        "critical": total_in_period >= limit_val,
        "invoice_count": len(invoices_in_period),
        "limit_type": limit_type
    })

@app.route('/api/lookup-nip/<nip>', methods=['GET'])
def lookup_nip(nip):
    import requests
    # Clean NIP from dashes and spaces
    clean_nip = nip.replace('-', '').replace(' ', '').strip()
    
    if len(clean_nip) != 10 or not clean_nip.isdigit():
        return jsonify({"success": False, "error": "Nieprawidłowy format NIP (wymagane 10 cyfr)"}), 400

    # 1. Primary Source: MF White List (Biała Lista) - Keyless & Public
    try:
        today_str = date.today().strftime("%Y-%m-%d")
        url = f"https://wl-api.mf.gov.pl/api/search/nip/{clean_nip}?date={today_str}"
        res = requests.get(url, timeout=10) # 10s timeout as per spec
        
        if res.status_code == 429:
            return jsonify({"success": False, "error": "Przekroczono limit 30 zapytań na dobę dla API MF (Biała Lista). Spróbuj jutro."}), 429
            
        data = res.json()
        result = data.get('result', {})
        subj = result.get('subject')
        
        if not subj and result.get('subjects') and len(result['subjects']) > 0:
            subj = result['subjects'][0]
            
        if subj:
            return jsonify({
                "success": True,
                "name": subj.get('name', ''),
                "address": subj.get('workingAddress') or subj.get('residenceAddress') or "",
                "status_vat": subj.get('statusVat', 'Niezidentyfikowany'),
                "source": "MF"
            })
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "System MF nie odpowiada w terminie (Timeout). Spróbuj ponownie za chwilę."}), 504
    except Exception as e:
        print(f"MF API Error: {e}")

    # 2. Secondary Fallback Source: CEIDG (Requires private key)
    token = os.getenv('CEIDG_API_TOKEN')
    if token and token != 'your_jwt_token_here':
        try:
            url = f"https://dane.biznes.gov.pl/api/ceidg/v2/przedsiebiorcy?nip={clean_nip}"
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                items = data.get('przedsiebiorcy', [])
                if items:
                    biz = items[0]
                    name = biz.get('firma') or f"{biz.get('imie', '')} {biz.get('nazwisko', '')}"
                    addr = biz.get('adresDzialalnosci', {})
                    formatted_addr = f"{addr.get('ulica', '')} {addr.get('numerBudynku', '')}{'/' if addr.get('numerLokalu') else ''}{addr.get('numerLokalu', '')}, {addr.get('kodPocztowy', '')} {addr.get('miasto', '')}"
                    return jsonify({
                        "success": True,
                        "name": name.strip(),
                        "address": formatted_addr.strip(', '),
                        "status_vat": "Sprawdź w rejestrze (CEIDG)",
                        "source": "CEIDG"
                    })
        except Exception as e:
            print(f"CEIDG API Error: {e}")

    # 3. Final Fallback: Entity not found or API issues
    return jsonify({
        "success": False, 
        "error": "Podmiotu nie znaleziono w bazie VAT (Biała Lista). Uzupełnij dane ręcznie lub sprawdź klucz API CEIDG."
    }), 404

@app.route('/api/products', methods=['GET', 'POST'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_products():
    if request.method == 'POST':
        data = request.json
        new_prod = Product(
            name=data['name'], 
            default_price=data.get('price', 0.0),
            category=data.get('category', 'Produkcja'),
            sort_order=data.get('sort_order', 0)
        )
        db.session.add(new_prod)
        db.session.commit()
        return jsonify({"success": True, "id": new_prod.id})
    
    products_query = Product.query.order_by(Product.sort_order.asc(), Product.name.asc())
    # Products are global for now, but could be isolated
    products = products_query.all()

    return jsonify([{"id": p.id, "name": p.name, "price": p.default_price, "category": p.category, "sort_order": p.sort_order} for p in products])

@app.route('/api/clients', methods=['GET', 'POST'])
@require_module('crm')
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_clients():
    if request.method == 'POST':
        data = request.json
        new_client = Client(
            name=data['name'], 
            address=data.get('address'), 
            nip=data.get('nip'), 
            email=data.get('email'),
            phone=data.get('phone'),
            discord_id=data.get('discord_id'),
            website=data.get('website'),
            studio_id=get_studio_id_for_create()
        )
        db.session.add(new_client)
        db.session.commit()
        return jsonify({"success": True, "id": new_client.id})
    
    clients_query = Client.query
    clients_query = apply_studio_filter(clients_query, Client)
    clients = clients_query.all()
    return jsonify([{
        "id": c.id, 
        "name": c.name, 
        "nip": c.nip, 
        "address": c.address,
        "phone": c.phone,
        "discord": c.discord_id,
        "website": c.website
    } for c in clients])

@app.route('/api/products/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@require_role('ADMIN')
def handle_single_product(id):
    product = db.session.get(Product, id)
    if not product:
        return jsonify({"error": "Produkt nie istnieje"}), 404
        
    if request.method == 'DELETE':
        db.session.delete(product)
        db.session.commit()
    elif request.method == 'PUT':
        data = request.json
        product.name = data['name']
        product.default_price = data.get('price', 0.0)
        product.category = data.get('category', 'Produkcja')
        product.sort_order = data.get('sort_order', 0)
        db.session.commit()
    elif request.method == 'GET':
        return jsonify({
            "id": product.id, 
            "name": product.name, 
            "price": product.default_price,
            "category": product.category,
            "sort_order": product.sort_order
        })
    
    return jsonify({"success": True})

@app.route('/api/clients/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@require_module('crm')
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_single_client(id):
    client = db.session.get(Client, id)
    if not client:
        return jsonify({"error": "Klient nie istnieje"}), 404
        
    sid = get_studio_id_for_query()
    if sid is not None and client.studio_id != sid:
         return jsonify({"error": "Brak dostępu do tego klienta"}), 403
        
    if request.method == 'DELETE':
        db.session.delete(client)
        db.session.commit()
    elif request.method == 'PUT':
        data = request.json
        client.name = data['name']
        client.address = data.get('address')
        client.nip = data.get('nip')
        client.email = data.get('email')
        client.phone = data.get('phone')
        client.discord_id = data.get('discord_id')
        client.website = data.get('website')
        db.session.commit()
    elif request.method == 'GET':
        total_spent = sum(inv.total_amount for inv in client.invoices if inv.status == 'Paid')
        invoices = [{
            "id": i.id,
            "number": i.number,
            "total": i.total_amount,
            "date": i.date.strftime("%Y-%m-%d"),
            "status": i.status,
            "pdf": i.pdf_path
        } for i in client.invoices]
        
        return jsonify({
            "id": client.id, 
            "name": client.name, 
            "nip": client.nip, 
            "address": client.address, 
            "email": client.email,
            "phone": client.phone,
            "discord": client.discord_id,
            "website": client.website,
            "total_spent": total_spent,
            "invoices": invoices
        })
        
    return jsonify({"success": True})

# --- HELPERS FOR PDF DATA ---
def _prepare_pdf_data(invoice, user_context=None):
    """Refactored logic to prepare data for create_invoice_pdf."""
    # If no context provided, use the creator of the invoice
    creator = user_context or db.session.get(User, invoice.created_by_id)
    
    # Get global studio data from Config
    # Personal data is handled via 'is_worker_invoice' and 'worker_details' in pdf_gen.py
    my_data = {
        "name": get_config_val('MY_NAME', 'Imię i nazwisko'),
        "nip": get_config_val('MY_NIP', ''),
        "account": get_config_val('MY_ACCOUNT', ''),
        "city": get_config_val('MY_CITY', ''),
        "address": get_config_val('MY_ADDRESS', '')
    }
    
    items_for_pdf = [{
        "name": it.product_name,
        "price": it.unit_price,
        "quantity": it.quantity
    } for it in invoice.items]

    import json
    metadata = {}
    if invoice.metadata_json:
        try:
            metadata = json.loads(invoice.metadata_json)
        except:
            pass

    invoice_pdf_data = {
        "number": invoice.number,
        "date": invoice.date.strftime("%Y-%m-%d"),
        "client_name": invoice.client.name if invoice.client else "KLIENT DETALICZNY",
        "client_nip": invoice.client.nip if invoice.client else "",
        "client_address": invoice.client.address if invoice.client else "",
        "items": items_for_pdf,
        "total": invoice.total_amount,
        "description": invoice.description,
        "contract_number": invoice.contract_number,
        "document_type": invoice.document_type,
        "payment_method": invoice.payment_method,
        "include_rights_clause": invoice.include_rights_clause,
        "include_qr_code": invoice.include_qr_code,
        "is_worker_invoice": invoice.is_worker_invoice,
        "pdf_password": creator.pdf_password, # Added for Discord notice
        "worker_details": {
            "name": creator.full_name or creator.username,
            "nip": creator.nip,
            "pesel": creator.pesel,
            "id_type": creator.id_type,
            "address": creator.address or "",
            "bank_account": creator.bank_account or get_config_val('MY_ACCOUNT', '') 
        },
        "metadata": metadata
    }
    return invoice_pdf_data, my_data

@app.route('/api/invoices', methods=['POST'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_invoices_post():
    data = request.json
    client_id = data.get('client_id')
    new_client_data = data.get('new_client_data')
    document_type = data.get('document_type', 'FAKTURA')
    
    client = None
    
    # Logic: New Client > Existing Client > Anonymous (if Paragon)
    if new_client_data:
        # Try to find by NIP first to avoid duplicates
        if new_client_data.get('nip'):
            client = Client.query.filter_by(nip=new_client_data['nip']).first()
        
        if not client and new_client_data.get('name'):
            client = Client(
                name=new_client_data['name'],
                address=new_client_data.get('address'),
                nip=new_client_data.get('nip'),
                studio_id=get_studio_id_for_create()
            )
            db.session.add(client)
            db.session.commit()
    if not client:
        existing_c = None
        c_name = None
        if client_id:
            existing_c = db.session.get(Client, client_id)
        elif new_client_data.get('name'):
            c_name = new_client_data['name'].strip()
            existing_c = Client.query.filter_by(name=c_name, studio_id=get_studio_id_for_create()).first()
            
        if existing_c:
            client = existing_c
        elif c_name:
            client = Client(
                name=c_name,
                address=new_client_data.get('address'),
                nip=new_client_data.get('nip'),
                studio_id=get_studio_id_for_create()
            )
            db.session.add(client)
            db.session.commit()
            
    if not client and document_type != 'PARAGON':
        return jsonify({"error": "Klient jest wymagany dla tego typu dokumentu (Faktura/WZ/Wycena)"}), 400
            
    # Document Numbering based on type
    payment_method = data.get('payment_method', 'PRZELEW')
    
    prefix = "F"
    if document_type == 'PARAGON': prefix = "P"
    elif document_type == 'WYCENA': prefix = "W"
    elif document_type == 'WZ': prefix = "WZ"
    
    invoice_id_short = str(uuid.uuid4())[:8].upper()
    now = datetime.now()
    invoice_number = f"{prefix}/{now.year}/{now.month}/{invoice_id_short}"
    
    # Package metadata
    meta = data.get('metadata') or {}
    if isinstance(meta, str): 
        try: meta = json.loads(meta)
        except: meta = {}
    
    meta['delivery_comment'] = data.get('delivery_comment', '')
    meta['lat'] = data.get('lat')
    meta['lng'] = data.get('lng')

    new_invoice = Invoice(
        number=invoice_number,
        client_id=client.id if client else None,
        date=now,
        total_amount=0.0,
        description=data.get('description', ''),
        contract_number=data.get('contract_number', ''),
        document_type=document_type,
        payment_method=payment_method,
        include_rights_clause=data.get('include_rights_clause', True),
        include_qr_code=data.get('include_qr_code', True),
        created_by_id=current_user.id,
        is_worker_invoice=data.get('is_worker_invoice', False),
        metadata_json=json.dumps(meta),
        studio_id=get_studio_id_for_create()
    )

    db.session.add(new_invoice)
    db.session.flush() # Get ID
    
    total = 0.0
    items_for_pdf = []
    for item in data['items']:
        val = float(item['price']) * int(item['quantity'])
        total += val
        db.session.add(InvoiceItem(
            invoice_id=new_invoice.id,
            product_name=item['name'],
            unit_price=float(item['price']),
            quantity=int(item['quantity'])
        ))
        
    new_invoice.total_amount = total
    db.session.commit()
    
    # Integration: Send to Discord
    global_admin = get_config_val('ADMIN_WEBHOOK')
    global_ekipa = get_config_val('EKIPA_WEBHOOK')
    
    webhooks = []
    if document_type in ['WZ', 'WYCENA']:
        # Fallback to global admin if ekipa is not set
        if global_ekipa: webhooks.append(global_ekipa)
        elif global_admin: webhooks.append(global_admin)
        
        if current_user.discord_contractor_webhook: webhooks.append(current_user.discord_contractor_webhook)
    else:
        if global_admin: webhooks.append(global_admin)
        if current_user.discord_admin_webhook: webhooks.append(current_user.discord_admin_webhook)
    
    discord_sent = False
    invoice_pdf_data, my_data = _prepare_pdf_data(new_invoice, current_user)
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        create_invoice_pdf(tmp_path, invoice_pdf_data, my_data)
        if current_user.pdf_encryption_enabled and current_user.pdf_password:
            encrypt_pdf(tmp_path, current_user.pdf_password)
            invoice_pdf_data['is_encrypted'] = True
            
        print(f"DEBUG Discord: Webhooks to notify: {webhooks}")
        for wh in set(webhooks):
            if wh:
                print(f"DEBUG Discord: Attempting notify to {wh[:25]}...")
                if send_invoice_to_admin(wh, invoice_pdf_data, tmp_path):
                    discord_sent = True
                    print(f"DEBUG Discord: SUCCESS for {wh[:25]}")
                else:
                    print(f"DEBUG Discord: FAILED for {wh[:25]}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    return jsonify({
        "success": True, 
        "id": new_invoice.id, 
        "pdf_url": f"/api/pdf/invoice/{new_invoice.id}",
        "discord_sent": discord_sent
    })

@app.route('/api/invoices', methods=['GET'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_invoices_get():
    invoices_query = Invoice.query.order_by(Invoice.date.desc())
    invoices_query = apply_studio_filter(invoices_query, Invoice)
    
    if current_user.role != 'ADMIN' and not current_user.can_access_history:
        # If user can't see full history but can create documents, show only their own
        if current_user.can_create_documents:
            invoices_query = invoices_query.filter_by(created_by_id=current_user.id)
        else:
            return jsonify([]), 200

    invoices = invoices_query.all()
    return jsonify([{
        "id": i.id, 
        "number": i.number, 
        "client": i.client.name if i.client else "KLIENT DETALICZNY",
        "client_id": i.client_id,
        "total": i.total_amount,
        "date": i.date.strftime("%Y-%m-%d"),
        "status": i.status,
        "pdf": i.pdf_path,
        "type": i.document_type,
        "payment": i.payment_method,
        "has_confirmation": i.confirmation is not None
    } for i in invoices])

@app.route('/api/invoices/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_single_invoice(id):
    invoice = db.session.get(Invoice, id)
    if not invoice:
        return jsonify({"error": "Faktura nie istnieje"}), 404
        
    sid = get_studio_id_for_query()
    if sid is not None and invoice.studio_id != sid:
         return jsonify({"error": "Brak dostępu do tej faktury"}), 403

    if request.method == 'GET':
        items = [{"name": it.product_name, "price": it.unit_price, "quantity": it.quantity} for it in invoice.items]
        return jsonify({
            "id": invoice.id,
            "number": invoice.number,
            "client_id": invoice.client_id,
            "total": invoice.total_amount,
            "items": items,
            "description": invoice.description,
            "contract_number": invoice.contract_number,
            "include_rights_clause": invoice.include_rights_clause,
            "include_qr_code": invoice.include_qr_code
        })

    if request.method == 'DELETE':
        num = invoice.number
        total = invoice.total_amount
        db.session.delete(invoice)
        db.session.commit()
        
        # Notify Discord
        webhook_url = get_config_val('ADMIN_WEBHOOK')
        if webhook_url:
            send_invoice_deletion_to_admin(webhook_url, num, total)
        return jsonify({"success": True})

    if request.method == 'PUT':
        data = request.json
        client_id = data.get('client_id')
        new_client_data = data.get('new_client_data')
        
        if new_client_data:
            c_name = new_client_data.get('name', '').strip()
            c_nip = new_client_data.get('nip', '').strip()
            
            # Priority 1: Check by NIP
            if c_nip:
                client = Client.query.filter_by(nip=c_nip).first()
            
            # Priority 2: Check by Name in Studio
            if not client and c_name:
                client = Client.query.filter_by(name=c_name, studio_id=invoice.studio_id).first()
                
            if not client and c_name:
                client = Client(
                    name=c_name,
                    address=new_client_data.get('address'),
                    nip=c_nip,
                    studio_id=invoice.studio_id
                )
                db.session.add(client)
                db.session.commit()
        elif client_id:
            client = db.session.get(Client, client_id)

        document_type = data.get('document_type', invoice.document_type)
        if not client and document_type != 'PARAGON':
            return jsonify({"error": "Klient jest wymagany"}), 400

        # Clear old items
        for it in invoice.items:
            db.session.delete(it)
        
        total = 0.0
        items_for_pdf = []
        for item in data['items']:
            val = float(item['price']) * int(item['quantity'])
            total += val
            db.session.add(InvoiceItem(
                invoice_id=invoice.id,
                product_name=item['name'],
                unit_price=float(item['price']),
                quantity=int(item['quantity'])
            ))
            items_for_pdf.append({
                "name": item['name'],
                "price": float(item['price']),
                "quantity": int(item['quantity'])
            })
        
        invoice.total_amount = total
        invoice.client_id = client.id if client else None
        invoice.description = data.get('description', invoice.description)
        invoice.contract_number = data.get('contract_number', invoice.contract_number)
        invoice.document_type = document_type
        invoice.payment_method = data.get('payment_method', invoice.payment_method)
        invoice.include_rights_clause = data.get('include_rights_clause', True)
        invoice.include_qr_code = data.get('include_qr_code', True)
        if 'metadata' in data:
            invoice.metadata_json = data['metadata']
            
        db.session.commit()
        
        # Notify Discord
        global_admin = get_config_val('ADMIN_WEBHOOK')
        global_ekipa = get_config_val('EKIPA_WEBHOOK')
        
        webhooks = []
        if document_type in ['WZ', 'WYCENA']:
            if global_ekipa: webhooks.append(global_ekipa)
            elif global_admin: webhooks.append(global_admin)
            if current_user.discord_contractor_webhook: webhooks.append(current_user.discord_contractor_webhook)
        else:
            if global_admin: webhooks.append(global_admin)
            if current_user.discord_admin_webhook: webhooks.append(current_user.discord_admin_webhook)
        
        discord_sent = False
        invoice_pdf_data, my_data = _prepare_pdf_data(invoice, current_user)
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            
        try:
            create_invoice_pdf(tmp_path, invoice_pdf_data, my_data)
            if current_user.pdf_encryption_enabled and current_user.pdf_password:
                encrypt_pdf(tmp_path, current_user.pdf_password)
                
            for wh in set(webhooks):
                if wh:
                    if send_invoice_update_to_admin(wh, invoice_pdf_data, tmp_path):
                        discord_sent = True
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        
        return jsonify({"success": True, "discord_sent": discord_sent})

@app.route('/api/invoices/<int:id>/status', methods=['PATCH'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def toggle_invoice_status(id):
    invoice = db.session.get(Invoice, id)
    if not invoice: return jsonify({"error": "Faktura nie istnieje"}), 404
    invoice.status = 'Paid' if invoice.status != 'Paid' else 'Pending'
    db.session.commit()
    
    # Notify Discord
    global_admin = get_config_val('ADMIN_WEBHOOK')
    
    webhooks = []
    if global_admin: webhooks.append(global_admin)
    if current_user.discord_admin_webhook: webhooks.append(current_user.discord_admin_webhook)
    
    for wh in set(webhooks):
        if wh:
            send_payment_update_to_admin(wh, invoice.number, invoice.total_amount, invoice.status)
            
    return jsonify({"success": True, "status": invoice.status})

@app.route('/api/invoices/<int:id>/download-unlocked', methods=['GET'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def download_unlocked_pdf(id):
    invoice = db.session.get(Invoice, id)
    if not invoice: return jsonify({"error": "Faktura nie istnieje"}), 404
    
    sid = get_studio_id_for_query()
    if sid is not None and invoice.studio_id != sid:
         return jsonify({"error": "Brak dostępu"}), 403

    # Generate a one-off unencrypted PDF
    invoice_pdf_data, my_data = _prepare_pdf_data(invoice)
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        
    create_invoice_pdf(tmp_path, invoice_pdf_data, my_data)
    
    safe_num = invoice.number.replace("/", "_").replace("\\", "_")
    output_filename = f"{invoice.document_type}_{safe_num}_UNLOCKED.pdf"
    
    try:
        return send_file(tmp_path, as_attachment=True, download_name=output_filename)
    finally:
        pass

@app.route('/api/invoices/<int:id>/convert', methods=['POST'])
def convert_quote(id):
    quote = db.session.get(Invoice, id)
    if not quote or quote.document_type != 'WYCENA':
        return jsonify({"error": "Dokument nie istnieje lub nie jest wyceną"}), 404
        
    # Create new FAKTURA based on WYCENA
    invoice_id_short = str(uuid.uuid4())[:8].upper()
    now = datetime.now()
    invoice_number = f"F/{now.year}/{now.month}/{invoice_id_short}"
    
    new_inv = Invoice(
        number=invoice_number,
        client_id=quote.client_id,
        date=now,
        total_amount=quote.total_amount,
        description=quote.description,
        contract_number=quote.contract_number,
        document_type='FAKTURA',
        payment_method=quote.payment_method,
        include_rights_clause=quote.include_rights_clause,
        include_qr_code=quote.include_qr_code
    )
    db.session.add(new_inv)
    db.session.flush()
    
    items_for_pdf = []
    for item in quote.items:
        db.session.add(InvoiceItem(
            invoice_id=new_inv.id,
            product_name=item.product_name,
            unit_price=item.unit_price,
            quantity=item.quantity
        ))
        items_for_pdf.append({
            "name": item.product_name,
            "price": item.unit_price,
            "quantity": item.quantity
        })
        
    db.session.commit()
    
    # Notify Discord
    global_admin = get_config_val('ADMIN_WEBHOOK')
    
    webhooks = []
    if global_admin: webhooks.append(global_admin)
    if current_user.discord_admin_webhook: webhooks.append(current_user.discord_admin_webhook)
    
    discord_sent = False
    invoice_pdf_data, my_data = _prepare_pdf_data(new_inv, current_user)
    
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        create_invoice_pdf(tmp_path, invoice_pdf_data, my_data)
        for wh in set(webhooks):
            if wh:
                if send_invoice_to_admin(wh, invoice_pdf_data, tmp_path):
                    discord_sent = True
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    return jsonify({"success": True, "id": new_inv.id, "pdf_url": f"/api/pdf/invoice/{new_inv.id}", "discord_sent": discord_sent})

@app.route('/api/confirmations', methods=['POST'])
def create_confirmation():
    data = request.json
    invoice = db.session.get(Invoice, data['invoice_id'])
    if not invoice:
        return jsonify({"error": "Faktura nie istnieje"}), 404
        
    # Get Author from config
    author_val = get_config_val('AUTHOR_NAME', 'Dawid Blacharski')
    
    new_conf = ProjectConfirmation(
        invoice_id=invoice.id,
        title=data.get('title', 'Projekt bez nazwy'),
        author=author_val,
        deadline=data.get('deadline', 'Do ustalenia'),
        scope=data.get('scope', 'Zakres prac wg faktury')
    )
    db.session.add(new_conf)
    db.session.flush()
    
    # Save metadata
    db.session.commit()
    
    # Prepare metadata for Discord
    my_data = {
        "name": get_config_val('MY_NAME', 'Imię i Nazwisko')
    }
    project_pdf_data = {
        "title": new_conf.title,
        "author": new_conf.author,
        "deadline": new_conf.deadline,
        "scope": new_conf.scope
    }
    # Integration: Send to Discord
    global_ekipa = get_config_val('CONTRACTOR_WEBHOOK')
    
    webhooks = []
    if global_ekipa: webhooks.append(global_ekipa)
    if current_user.discord_contractor_webhook: webhooks.append(current_user.discord_contractor_webhook)
    
    discord_sent = False
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
        
    try:
        create_confirmation_pdf(tmp_path, project_pdf_data, my_data)
        for wh in set(webhooks):
            if wh:
                if send_confirmation_to_contractors(wh, project_pdf_data, tmp_path):
                    discord_sent = True
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    return jsonify({"success": True, "pdf_url": f"/api/pdf/confirmation/{new_conf.id}", "discord_sent": discord_sent})

@app.route('/api/pdf/invoice/<int:id>')
@login_required
def serve_dynamic_invoice_pdf(id):
    invoice = db.session.get(Invoice, id)
    if not invoice: return jsonify({"error": "Faktura nie istnieje"}), 404
    
    # Permission check
    sid = get_studio_id_for_query()
    if sid is not None and invoice.studio_id != sid:
         return jsonify({"error": "Brak dostępu"}), 403

    # Generate PDF in memory
    invoice_pdf_data, my_data = _prepare_pdf_data(invoice, current_user)
    
    output = io.BytesIO()
    create_invoice_pdf(output, invoice_pdf_data, my_data)
    pdf_bytes = output.getvalue()
    
    # Removed auto-encryption for browser view as requested.
    # Documents opened in browser are unencrypted.
    
    safe_num = invoice.number.replace("/", "_").replace("\\", "_")
    filename = f"{invoice.document_type}_{safe_num}.pdf"
    
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=filename
    )

@app.route('/api/pdf/confirmation/<int:id>')
@login_required
def serve_dynamic_confirmation_pdf(id):
    conf = db.session.get(ProjectConfirmation, id)
    if not conf: return jsonify({"error": "Potwierdzenie nie istnieje"}), 404
    
    # Prepare metadata
    my_data = {
        "name": get_config_val('MY_NAME', 'Imię i Nazwisko')
    }
    project_pdf_data = {
        "title": conf.title,
        "author": conf.author,
        "deadline": conf.deadline,
        "scope": conf.scope
    }
    
    output = io.BytesIO()
    create_confirmation_pdf(output, project_pdf_data, my_data)
    pdf_bytes = output.getvalue()
    
    filename = f"Confirmation_{conf.id}.pdf"
    
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=filename
    )

@app.route('/api/confirmations/<int:invoice_id>', methods=['DELETE'])
@login_required
def delete_confirmation_by_invoice(invoice_id):
    conf = ProjectConfirmation.query.filter_by(invoice_id=invoice_id).first()
    if not conf: return jsonify({"error": "Potwierdzenie nie istnieje"}), 404
    
    # Permission check (associated with invoice)
    invoice = conf.invoice
    sid = get_studio_id_for_query()
    if sid is not None and invoice.studio_id != sid:
         return jsonify({"error": "Brak dostępu"}), 403
         
    db.session.delete(conf)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/pdfs/<path:filename>')
def serve_pdf(filename):
    return send_from_directory(PDF_FOLDER, filename)

@app.route('/api/user/profile', methods=['GET', 'POST', 'PUT'])
@login_required
def handle_user_profile():
    if request.method in ['POST', 'PUT']:
        data = request.json
        user = db.session.get(User, current_user.id)
        
        # Profile Data
        if 'full_name' in data: user.full_name = data['full_name']
        if 'email' in data: user.email = data['email']
        if 'nip' in data: user.nip = data['nip']
        if 'pesel' in data: user.pesel = data['pesel']
        if 'id_type' in data: user.id_type = data['id_type']
        if 'bank_account' in data: user.bank_account = data['bank_account']
        if 'address' in data: user.address = data['address']
        
        # Security & Integrations
        if 'pdf_encryption_enabled' in data: user.pdf_encryption_enabled = data['pdf_encryption_enabled']
        if 'pdf_password' in data: user.pdf_password = data['pdf_password']
        if 'discord_admin_webhook' in data: user.discord_admin_webhook = data['discord_admin_webhook']
        if 'discord_contractor_webhook' in data: user.discord_contractor_webhook = data['discord_contractor_webhook']
        
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        
        db.session.commit()
        return jsonify({"success": True, "user": user.to_dict()})
    
    return jsonify(current_user.to_dict())

@app.route('/api/config', methods=['GET', 'POST'])
@require_role('ADMIN', 'PRODUCER') # Extended to Producer
def handle_config():
    sid = get_studio_id_for_query()
    
    if current_user.role == 'PRODUCER' and request.method == 'POST':
         return jsonify({"error": "Admin only"}), 403
         
    if request.method == 'POST':
        data = request.json
        studio = db.session.get(Studio, sid)
        
        for key, value in data.items():
            if key == 'STUDIO_LAT' and value:
                if studio: studio.lat = float(value)
            elif key == 'STUDIO_LNG' and value:
                if studio: studio.lng = float(value)
            
            conf = Config.query.filter_by(key=key, studio_id=sid).first()
            if conf:
                conf.value = value
            else:
                db.session.add(Config(key=key, value=value, studio_id=sid))
        db.session.commit()
        return jsonify({"success": True})
    
    # Merge global and local configs
    global_confs = Config.query.filter_by(studio_id=None).all()
    local_confs = Config.query.filter_by(studio_id=sid).all() if sid else []
    
    merged = {c.key: c.value for c in global_confs}
    for lc in local_confs:
        merged[lc.key] = lc.value
    
    # Also add context to config dict for UI
    if sid:
        studio = db.session.get(Studio, sid)
        if studio:
            # lat/lng removed
            pass
            
    return jsonify(merged)


# --- ANALYTICS LOGIC ---

def calculate_roi(project):
    """Oblicza ROI projektu: (Budżet - Koszty Zewnętrzne) * (1 - Podatek 12%)"""
    if not project.finance:
        return 0.0
    f = project.finance
    total_costs = f.external_costs_hw + f.external_costs_sw + f.external_costs_service
    gross_profit = f.budget - total_costs
    net_profit = gross_profit * 0.88 # 12% tax buffer
    return round(net_profit, 2)

def calculate_hourly_rate(project):
    """Oblicza realną stawkę godzinową"""
    if not project.finance or project.finance.time_logged <= 0:
        return 0.0
    net_profit = calculate_roi(project)
    return round(net_profit / project.finance.time_logged, 2)

@app.route('/api/analytics/dashboard', methods=['GET'])
@require_module('studio')
@require_role('ADMIN', 'PRODUCER')
def get_analytics_dashboard():
    top_clients_query = Client.query.order_by(Client.ltv.desc())
    top_clients_query = apply_studio_filter(top_clients_query, Client)
    top_clients = top_clients_query.limit(3).all()
    
    clients_data = [{
        "name": c.name,
        "ltv": c.ltv,
        "project_count": len(c.projects)
    } for c in top_clients]

    # 2. Spending Pie Chart (Total across all projects)
    finances_query = ProjectFinance.query.join(MusicProject)
    finances_query = apply_studio_filter(finances_query, MusicProject) # Scope by project's studio
    finances = finances_query.all()
    spending_pie = {
        "hardware": sum(f.external_costs_hw for f in finances),
        "software": sum(f.external_costs_sw for f in finances),
        "freelancers": sum(f.external_costs_service for f in finances)
    }

    # 3. Average Hourly Rate (Last 30 days)
    projects_query = MusicProject.query
    projects_query = apply_studio_filter(projects_query, MusicProject)
    all_projects = projects_query.all()
    rates = [calculate_hourly_rate(p) for p in all_projects if calculate_hourly_rate(p) > 0]
    avg_rate = round(sum(rates) / len(rates), 2) if rates else 0.0

    # 4. Monthly Summary
    today = date.today()
    start_of_month = datetime(today.year, today.month, 1)
    
    projects_monthly_query = MusicProject.query.filter(MusicProject.target_deadline >= start_of_month)
    projects_monthly_query = apply_studio_filter(projects_monthly_query, MusicProject)
    monthly_projects = projects_monthly_query.all()
    monthly_rev = sum(p.finance.budget for p in monthly_projects if p.finance)
    monthly_costs = sum((p.finance.external_costs_hw + p.finance.external_costs_sw + p.finance.external_costs_service) 
                        for p in monthly_projects if p.finance)
    monthly_net = sum(calculate_roi(p) for p in monthly_projects)

    return jsonify({
        "top_clients": clients_data,
        "spending_pie": spending_pie,
        "avg_hourly_rate_30d": avg_rate,
        "monthly_summary": {
            "revenue": monthly_rev,
            "costs": monthly_costs,
            "net_profit": monthly_net
        }
    })

@app.route('/api/projects', methods=['GET', 'POST'])
@require_module('studio')
def handle_projects():
    if not (current_user.role == 'ADMIN' or current_user.can_access_projects or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień do projektów'}), 403
    if request.method == 'POST':
        if not (current_user.role == 'ADMIN' or current_user.can_manage_projects):
            return jsonify({'error': 'Brak uprawnień do tworzenia projektów'}), 403
        data = request.json
        
        c_name = data.get('client_name')
        if not c_name:
             return jsonify({'error': 'Musisz podać nazwę klienta'}), 400
             
        # Find or create client (studio-aware)
        safe_c_name = c_name.strip()
        client = Client.query.filter_by(name=safe_c_name, studio_id=get_studio_id_for_create()).first()
        if not client:
            client = Client(name=safe_c_name, studio_id=get_studio_id_for_create())
            db.session.add(client)
            db.session.flush() # get ID
            
        new_project = MusicProject(
            client_id=client.id,
            name=data['name'],
            bpm=data.get('bpm'),
            key=data.get('key'),
            genre=data.get('genre'),
            target_deadline=datetime.strptime(data['deadline'], '%Y-%m-%d') if data.get('deadline') else None,
            status=data.get('status', 'Active'),
            invoice_id=data.get('invoice_id'),
            assigned_user_id=int(data['assigned_user_id']) if (data.get('assigned_user_id') and str(data['assigned_user_id']).isdigit()) else None,
            description=data.get('description'),
            studio_id=get_studio_id_for_create(),
            public_token=str(uuid.uuid4())
        )
        db.session.add(new_project)
        db.session.flush()
        
        # Initialize finance
        new_finance = ProjectFinance(
            project_id=new_project.id,
            budget=float(data.get('budget', 0.0)),
            external_costs_hw=float(data.get('costs_hw', 0.0)),
            external_costs_sw=float(data.get('costs_sw', 0.0)),
            external_costs_service=float(data.get('costs_service', 0.0)),
            time_logged=float(data.get('time_logged', 0.0))
        )
        db.session.add(new_finance)
        
        # Update Client LTV if budget is provided
        client = db.session.get(Client, new_project.client_id)
        if client:
            client.ltv += new_finance.budget

        db.session.commit()
        return jsonify({"success": True, "id": new_project.id})

    projects_query = MusicProject.query
    projects_query = apply_studio_filter(projects_query, MusicProject)
    projects = projects_query.all()
    return jsonify([{
        "id": p.id,
        "name": p.name,
        "client": p.client.name if p.client else 'Brak klienta',
        "status": p.status,
        "assigned_user_id": p.assigned_user_id,
        "assigned_user_name": p.assigned_user.username if p.assigned_user else None,
        "brief_data": (json.loads(p.brief_data) if isinstance(p.brief_data, str) else p.brief_data) if p.brief_data else None,
        "public_token": p.public_token,
        "tasks": [{
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "deadline": t.deadline,
            "assigned_user_name": t.assigned_user.username if t.assigned_user else None,
            "links": t.links
        } for t in p.tasks],
        "roi": calculate_roi(p),
        "hourly_rate": calculate_hourly_rate(p)
    } for p in projects])

@app.route('/api/projects/<int:id>/generate-token', methods=['POST'])
@login_required
@require_module('studio')
def generate_project_token(id):
    if not (current_user.role == 'ADMIN' or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień'}), 403
    project = db.session.get(MusicProject, id)
    if not project:
        return jsonify({'error': 'Projekt nie istnieje'}), 404
        
    project.public_token = str(uuid.uuid4())
    db.session.commit()
    
    base_url = request.host_url.rstrip('/')
    return jsonify({
        "success": True, 
        "token": project.public_token,
        "url": f"{base_url}/brief/{project.public_token}"
    })

@app.route('/brief/<token>')
def public_brief_form(token):
    project = MusicProject.query.filter_by(public_token=token).first_or_404()
    return render_template('brief.html', project=project)

@app.route('/api/public/brief/<token>', methods=['POST'])
def submit_public_brief(token):
    project = MusicProject.query.filter_by(public_token=token).first()
    if not project:
        return jsonify({'error': 'Nieprawidłowy token'}), 404
        
    data = request.json
    project.brief_data = data
    project.status = 'Otrzymano brief'
    
    # Update Client Info if provided
    c_info = data.get('client_info', {})
    if c_info:
        client = project.client
        if c_info.get('name'): client.name = c_info['name']
        if c_info.get('email'): client.email = c_info['email']
        if c_info.get('phone'): client.phone = c_info['phone']
        if c_info.get('company'): client.company_name = c_info['company']
        if c_info.get('nip'): client.nip = c_info['nip']
        if c_info.get('address'): client.address = c_info['address']
        
    # Handle Secret Project (NDA)
    if data.get('is_secret'):
        if '🔒 TAJNE / NDA' not in (project.internal_notes or ''):
            project.internal_notes = (project.internal_notes or '') + "\n🔒 TAJNE / NDA: Zakaz publikacji w social mediach."
            
    db.session.commit()
    
    # Discord notification
    webhook = None
    if project.assigned_user and project.assigned_user.discord_contractor_webhook:
        webhook = project.assigned_user.discord_contractor_webhook
    
    if not webhook:
        # Fallback to studio admin
        admin = User.query.filter_by(assigned_studio_id=project.studio_id, role='ADMIN').first()
        if admin:
            webhook = admin.discord_contractor_webhook or admin.discord_admin_webhook
            
    if not webhook:
        # Global fallback from Config
        webhook = get_config_val('ADMIN_WEBHOOK')
            
    if webhook:
        # print(f"DEBUG: sending brief notification to {webhook[:20]}...")
        send_brief_notification(webhook, {
            "name": project.name,
            "client_name": project.client.name if project.client else "Brak danych",
            "type": data.get('type', 'Nieokreślony'),
            "deadline": data.get('deadline'),
            "vibe": data.get('vibe'),
            "references": data.get('references'),
            "segment_notes": data.get('segment_notes'),
            "notes": data.get('notes'),
            "is_secret": data.get('is_secret', False)
        })
    
    return jsonify({"success": True, "message": "Brief został zapisany pomyślnie!"})

@app.route('/api/projects/<int:id>/full-update', methods=['PATCH'])
@login_required
@require_module('studio')
def full_update_project(id):
    if not (current_user.role == 'ADMIN' or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień'}), 403
    project = db.session.get(MusicProject, id)
    if not project:
        return jsonify({'error': 'Projekt nie istnieje'}), 404
        
    data = request.json
    
    # Update Project fields
    if 'internal_notes' in data:
        project.internal_notes = data['internal_notes']
    if 'status' in data:
        project.status = data['status']
    
    # Update Client fields if provided
    client = project.client
    if client:
        if 'client_name' in data: client.name = data['client_name']
        if 'client_email' in data: client.email = data['client_email']
        if 'client_phone' in data: client.phone = data['client_phone']
        if 'client_company' in data: client.company_name = data['client_company']
        if 'client_nip' in data: client.nip = data['client_nip']
        if 'client_address' in data: client.address = data['client_address']
        if 'client_discord' in data: client.discord_id = data['client_discord']

    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/projects/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@require_module('studio')
def handle_single_project(id):
    if not (current_user.role == 'ADMIN' or current_user.can_access_projects or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień do projektów'}), 403
    project = db.session.get(MusicProject, id)
    if not project:
        return jsonify({"error": "Projekt nie istnieje"}), 404
        
    sid = get_studio_id_for_query()
    if sid is not None and project.studio_id != sid:
         return jsonify({"error": "Brak dostępu do tego projektu"}), 403
         
    if request.method == 'GET':
        f = project.finance
        return jsonify({
            "id": project.id,
            "name": project.name,
            "client_id": project.client_id,
            "bpm": project.bpm,
            "key": project.key,
            "genre": project.genre,
            "deadline": project.target_deadline.strftime('%Y-%m-%d') if project.target_deadline else None,
            "status": project.status,
            "assigned_user_id": project.assigned_user_id,
            "description": project.description,
            "internal_notes": project.internal_notes,
            "brief_data": (json.loads(project.brief_data) if isinstance(project.brief_data, str) else project.brief_data) if project.brief_data else None,
            "client": {
                "id": project.client.id,
                "name": project.client.name,
                "phone": project.client.phone,
                "email": project.client.email,
                "company_name": project.client.company_name,
                "nip": project.client.nip,
                "address": project.client.address,
                "discord_id": project.client.discord_id
            } if project.client else None,
            "finance": {
                "budget": f.budget if f else 0,
                "costs_hw": f.external_costs_hw if f else 0,
                "costs_sw": f.external_costs_sw if f else 0,
                "costs_service": f.external_costs_service if f else 0,
                "time_logged": f.time_logged if f else 0
            }
        })
    elif request.method == 'DELETE':
        db.session.delete(project)
        db.session.commit()
        return jsonify({"success": True})
    elif request.method == 'PUT':
        data = request.json
        project.name = data.get('name', project.name)
        project.bpm = data.get('bpm', project.bpm)
        project.key = data.get('key', project.key)
        project.genre = data.get('genre', project.genre)
        if data.get('deadline'):
            project.target_deadline = datetime.strptime(data['deadline'], '%Y-%m-%d')
        project.status = data.get('status', project.status)
        if 'assigned_user_id' in data:
            project.assigned_user_id = data.get('assigned_user_id')
        if 'description' in data:
            project.description = data.get('description')
        
        if project.finance:
            # Update LTV difference
            old_budget = project.finance.budget
            new_budget = float(data.get('budget', old_budget))
            project.client.ltv += (new_budget - old_budget)
            
            project.finance.budget = new_budget
            project.finance.external_costs_hw = float(data.get('costs_hw', project.finance.external_costs_hw))
            project.finance.external_costs_sw = float(data.get('costs_sw', project.finance.external_costs_sw))
            project.finance.external_costs_service = float(data.get('costs_service', project.finance.external_costs_service))
            project.finance.time_logged = float(data.get('time_logged', project.finance.time_logged))
            
        db.session.commit()
        return jsonify({"success": True})

@app.route('/api/projects/<int:id>/tasks', methods=['GET', 'POST'])
@require_module('studio')
def handle_project_tasks(id):
    if not (current_user.role == 'ADMIN' or current_user.can_access_projects or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień do projektów'}), 403
    project = db.session.get(MusicProject, id)
    if not project:
        return jsonify({"error": "Projekt nie istnieje"}), 404
        
    if request.method == 'POST':
        # Now allow if ADMIN or has can_manage_tasks permission
        if not (current_user.role == 'ADMIN' or current_user.can_manage_tasks):
            return jsonify({'error': 'Brak uprawnień do tworzenia zadań'}), 403
        data = request.json
        dl = data.get('deadline')
        new_task = ProjectTask(
            project_id=id,
            title=data['title'],
            description=data.get('description', ''),
            links=data.get('links', '[]'),
            deadline=datetime.strptime(dl, '%Y-%m-%d') if dl else None,
            assigned_user_id=data.get('assigned_user_id'),
            status=data.get('status', 'TODO')
        )
        db.session.add(new_task)
        db.session.commit()
        return jsonify({"success": True, "id": new_task.id})

    tasks = ProjectTask.query.filter_by(project_id=id).all()
    return jsonify([{
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "links": t.links,
        "deadline": t.deadline.strftime('%Y-%m-%d') if t.deadline else None,
        "assigned_user_id": t.assigned_user_id,
        "assigned_user_name": t.assigned_user.username if t.assigned_user else None,
        "status": t.status
    } for t in tasks])

@app.route('/api/tasks/<int:id>', methods=['PUT', 'DELETE'])
@require_module('studio')
def handle_single_task(id):
    if not (current_user.role == 'ADMIN' or current_user.can_manage_tasks):
        return jsonify({'error': 'Brak uprawnień do edycji zadań'}), 403
    task = db.session.get(ProjectTask, id)
    if not task:
        return jsonify({"error": "Zadanie nie istnieje"}), 404
        
    if request.method == 'DELETE':
        db.session.delete(task)
        db.session.commit()
        return jsonify({"success": True})
        
    data = request.json
    task.title = data.get('title', task.title)
    if 'description' in data:
        task.description = data['description']
    if 'links' in data:
        task.links = data['links']
        
    dl = data.get('deadline')
    if dl:
        task.deadline = datetime.strptime(dl, '%Y-%m-%d')
    if 'assigned_user_id' in data:
        task.assigned_user_id = data['assigned_user_id']
        
    old_status = task.status
    new_status = data.get('status', task.status)
    status_changed = old_status != new_status
    task.status = new_status
    
    db.session.commit()
    
    # Discord notification if status changed
    if status_changed:
        webhook = None
        # Priority: Task assigned user -> Project assigned user -> Studio owner
        if task.assigned_user and task.assigned_user.discord_contractor_webhook:
            webhook = task.assigned_user.discord_contractor_webhook
        elif task.project.assigned_user and task.project.assigned_user.discord_contractor_webhook:
            webhook = task.project.assigned_user.discord_contractor_webhook
        else:
            owner = User.query.filter_by(assigned_studio_id=task.project.studio_id, role='ADMIN').first()
            if owner and owner.discord_contractor_webhook:
                webhook = owner.discord_contractor_webhook
                
        if webhook:
            send_task_update_notification(webhook, {
                "title": task.title,
                "project_name": task.project.name,
                "old_status": old_status,
                "new_status": new_status,
                "user_name": current_user.display_name or current_user.username
            })
            
    return jsonify({"success": True})

@app.route('/api/calendar', methods=['GET'])
def get_calendar():
    res = []
    projects_q = MusicProject.query
    tasks_q = ProjectTask.query
    
    if current_user.role != 'ADMIN':
        projects_q = projects_q.filter_by(assigned_user_id=current_user.id)
        tasks_q = tasks_q.filter_by(assigned_user_id=current_user.id)
        
    for p in projects_q.all():
        if p.target_deadline:
            res.append({
                "type": "project",
                "id": p.id,
                "title": f"Projekt: {p.name}",
                "date": p.target_deadline.strftime('%Y-%m-%d')
            })
            
    for t in tasks_q.all():
        if t.deadline:
            res.append({
                "type": "task",
                "id": t.id,
                "project_id": t.project_id,
                "title": f"Zadanie: {t.title}",
                "date": t.deadline.strftime('%Y-%m-%d'),
                "status": t.status,
                "username": t.assigned_user.username if t.assigned_user else 'Brak'
            })
            
    # Manual Events
    # Visible if: (mine) OR (public AND same studio)
    events_q = CalendarEvent.query
    if current_user.role != 'ADMIN':
        events_q = events_q.filter(
            (CalendarEvent.user_id == current_user.id) | 
            (CalendarEvent.is_public == True)
        )
    events_q = apply_studio_filter(events_q, CalendarEvent)
    
    for e in events_q.all():
        res.append({
            "type": "manual",
            "event_type": e.event_type,
            "id": e.id,
            "title": e.title,
            "date": e.date.strftime('%Y-%m-%d'),
            "is_public": e.is_public,
            "username": e.user.username if e.user else 'Brak',
            "is_mine": (e.user_id == current_user.id or current_user.role == 'ADMIN')
        })
            
    return jsonify(res)

@app.route('/api/calendar', methods=['POST'])
@login_required
def add_calendar_event():
    data = request.json
    try:
        new_event = CalendarEvent(
            title=data['title'],
            description=data.get('description', ''),
            date=datetime.strptime(data['date'], '%Y-%m-%d'),
            event_type=data.get('event_type', 'WORK'),
            is_public=bool(data.get('is_public', False)),
            user_id=current_user.id,
            studio_id=current_user.assigned_studio_id or 1
        )
        db.session.add(new_event)
        db.session.commit()
        return jsonify({"success": True, "id": new_event.id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/calendar/<int:id>', methods=['DELETE'])
@login_required
def delete_calendar_event(id):
    event = db.session.get(CalendarEvent, id)
    if not event: return jsonify({"error": "Wydarzenie nie istnieje"}), 404
    if event.user_id != current_user.id and current_user.role != 'ADMIN':
        return jsonify({"error": "To nie Twoje wydarzenie"}), 403
    db.session.delete(event)
    db.session.commit()
    return jsonify({"success": True})

# --- EXPENSE & COST API ---
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/costs/upload', methods=['POST'])
@require_module('finance')
@require_role('ADMIN', 'FREELANCER')
def upload_cost_document():
    if 'file' not in request.files:
        return jsonify({"error": "Brak pliku"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nie wybrano pliku"}), 400
    if file and allowed_file(file.filename):
        filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(app.config['COST_UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return jsonify({"success": True, "file_path": f"uploads/costs/{filename}"})
    return jsonify({"error": "Niedozwolony format pliku"}), 400

@app.route('/api/expenses', methods=['GET', 'POST'])
@require_module('finance')
@require_role('ADMIN', 'FREELANCER')
def handle_expenses():
    if request.method == 'POST':
        data = request.json
        new_expense = Expense(
            title=data['title'],
            amount=float(data['amount']),
            category=data['category'],
            date=datetime.strptime(data['date'], '%Y-%m-%d') if data.get('date') else datetime.utcnow(),
            file_path=data.get('file_path'),
            project_id=data.get('project_id') if data.get('project_id') else None,
            studio_id=get_studio_id_for_create()
        )
        db.session.add(new_expense)
        db.session.commit()
        
        # Discord Alert for High Expenses
        threshold = float(get_config_val('COST_THRESHOLD_LIMIT', '1000.0'))
        
        if new_expense.amount >= threshold:
            global_admin = get_config_val('ADMIN_WEBHOOK')
            
            webhooks = []
            if global_admin: webhooks.append(global_admin)
            if current_user.discord_admin_webhook: webhooks.append(current_user.discord_admin_webhook)
            
            expense_data = {
                "title": new_expense.title,
                "amount": new_expense.amount,
                "category": new_expense.category,
                "date": new_expense.date.strftime("%Y-%m-%d")
            }
            # Attach file if exists
            full_file_path = os.path.join(os.getcwd(), 'static', new_expense.file_path) if new_expense.file_path else None
            
            for wh in set(webhooks):
                if wh:
                    send_expense_alert_to_admin(wh, expense_data, full_file_path)
            
        return jsonify({"success": True, "id": new_expense.id})
    
    expenses_query = Expense.query.order_by(Expense.date.desc())
    expenses_query = apply_studio_filter(expenses_query, Expense)
    expenses = expenses_query.all()
    return jsonify([{
        "id": e.id,
        "title": e.title,
        "amount": e.amount,
        "category": e.category,
        "date": e.date.strftime('%Y-%m-%d'),
        "file_path": e.file_path,
        "project_id": e.project_id,
        "project_name": e.project.name if e.project else None
    } for e in expenses])

@app.route('/api/expenses/<int:id>', methods=['DELETE'])
@require_module('finance')
@require_role('ADMIN', 'FREELANCER')
def delete_expense(id):
    expense = db.session.get(Expense, id)
    if not expense:
        return jsonify({"error": "Wydatek nie istnieje"}), 404
        
    # Delete file if exists
    if expense.file_path:
        full_path = os.path.join(os.getcwd(), 'static', expense.file_path)
        if os.path.exists(full_path):
            try: os.remove(full_path)
            except: pass
            
    db.session.delete(expense)
    db.session.commit()
    return jsonify({"success": True})
@app.route('/api/invoices/collective', methods=['POST'])
@require_role('ADMIN', 'PRODUCER', 'FREELANCER')
def handle_collective_invoice():
    data = request.json
    invoice_ids = data.get('invoice_ids', [])
    if not invoice_ids:
        return jsonify({"error": "Brak wybranych zamówień"}), 400
        
    orders = Invoice.query.filter(Invoice.id.in_(invoice_ids)).all()
    if not orders:
        return jsonify({"error": "Nie znaleziono zamówień"}), 404
        
    client_ids = set([o.client_id for o in orders if o.client_id])
    if len(client_ids) > 1:
        return jsonify({"error": "Wszystkie zamówienia muszą dotyczyć tego samego klienta!"}), 400
        
    client_id = client_ids.pop() if client_ids else None
    
    # Validation
    for o in orders:
        if o.document_type != 'ZAMOWIENIE':
            return jsonify({"error": f"Dokument {o.number} nie jest zamówieniem."}), 400
            
    # Create new FAKTURA
    invoice_id_short = str(uuid.uuid4())[:8].upper()
    now = datetime.now()
    invoice_number = f"F/{now.year}/{now.month}/{invoice_id_short}"
    
    total = sum(o.total_amount for o in orders)
    descriptions = [o.description for o in orders if o.description]
    merged_description = "Faktura zbiorcza za zamówienia:\n" + "\n".join([o.number for o in orders]) + "\n" + "\n".join(descriptions)
    
    new_invoice = Invoice(
        number=invoice_number,
        client_id=client_id,
        date=now,
        total_amount=total,
        description=merged_description,
        document_type='FAKTURA',
        payment_method='PRZELEW',
        created_by_id=current_user.id,
        studio_id=get_studio_id_for_create()
    )
    db.session.add(new_invoice)
    db.session.flush()
    
    for o in orders:
        for item in o.items:
            db.session.add(InvoiceItem(
                invoice_id=new_invoice.id,
                product_name=item.product_name,
                unit_price=item.unit_price,
                quantity=item.quantity
            ))
        o.status = 'Zafakturowano'
        
    db.session.commit()
    
    global_admin = get_config_val('ADMIN_WEBHOOK')
    if global_admin:
        invoice_pdf_data, my_data = _prepare_pdf_data(new_invoice, current_user)
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            create_invoice_pdf(tmp_path, invoice_pdf_data, my_data)
            if current_user.pdf_encryption_enabled and current_user.pdf_password:
                encrypt_pdf(tmp_path, current_user.pdf_password)
            send_invoice_to_admin(global_admin, invoice_pdf_data, tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    return jsonify({"success": True, "pdf_url": f"/api/pdf/invoice/{new_invoice.id}"})


# ── DELIVERY / ORDERS API ────────────────────────────────────────────────────
@app.route('/api/couriers', methods=['GET'])
@login_required
def get_couriers():
    users = User.query.filter_by(is_active=True).all()
    # We can refine this to return only users with role COURIER or ADMIN if we want,
    # but returning all active users for small teams is often what they want.
    return jsonify([{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role} for u in users])


@app.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    sid = get_studio_id_for_query()
    # Orders are PARAGON or WZ with delivery intent
    q = Invoice.query.filter_by(studio_id=sid)
    
    # If courier, show assigned or unassigned
    if current_user.role == 'COURIER':
        q = q.filter(db.or_(Invoice.assigned_courier_id == current_user.id, Invoice.assigned_courier_id == None))
        
    orders = q.all()
    res = []
    for o in orders:
        res.append({
            "id": o.id,
            "number": o.number,
            "total": o.total_amount,
            "status": o.delivery_status,
            "comment": o.delivery_comment,
            "address": o.client.address if o.client else "Odbiór osobisty",
            "lat": o.lat,
            "lng": o.lng,
            "courier_id": o.assigned_courier_id,
            "courier_name": o.assigned_courier.username if o.assigned_courier else None,
            "client_name": o.client.name if o.client else "Anonim",
            "date": o.date.strftime('%Y-%m-%d %H:%M')
        })
    return jsonify(res)

@app.route('/api/orders/<int:id>/status', methods=['PATCH'])
@login_required
def update_order_status(id):
    order = Invoice.query.get_or_404(id)
    # Check studio access
    if order.studio_id != get_studio_id_for_query():
        return jsonify({"error": "Brak uprawnień"}), 403
        
    data = request.json
    new_status = data.get('status')
    if new_status in ['PENDING', 'READY', 'IN_DELIVERY', 'DELIVERED', 'CANCELLED']:
        order.delivery_status = new_status
        db.session.commit()
        return jsonify({"success": True, "new_status": new_status})
    return jsonify({"error": "Nieprawidłowy status"}), 400

@app.route('/api/orders/<int:id>/assign', methods=['PATCH'])
@login_required
def assign_order_courier(id):
    order = Invoice.query.get_or_404(id)
    if order.studio_id != get_studio_id_for_query():
        return jsonify({"error": "Brak uprawnień"}), 403
        
    data = request.json
    courier_id = data.get('courier_id')
    order.assigned_courier_id = courier_id
    db.session.commit()
    return jsonify({"success": True})

def ensure_admin_exists():

    """Initial bootstrap to create the first admin account if none exist."""
    with app.app_context():
        try:
            db.create_all()
            if User.query.first() is None:
                master_admin = User(
                    username='admin',
                    password_hash=generate_password_hash('NoxTools2024!'),
                    role='ADMIN',
                    must_change_password=False,
                    display_name='Nox Admin'
                )
                db.session.add(master_admin)
                db.session.commit()
                print(">>> [BOOTSTRAP] Created initial admin: admin / NoxTools2024!")
            
            # Ensure at least one studio exists
            if Studio.query.first() is None:
                db.session.add(Studio(name="NOX Music Studio"))
                db.session.commit()
            
            first_studio = Studio.query.first()
            
            # Backfill Users
            users_to_fix = User.query.filter(User.assigned_studio_id == None).all()
            for u in users_to_fix:
                u.assigned_studio_id = first_studio.id
            
            # Backfill Invoices
            inv_to_fix = Invoice.query.filter(Invoice.studio_id == None).all()
            for i in inv_to_fix:
                i.studio_id = first_studio.id
                
            # Backfill Expenses
            exp_to_fix = Expense.query.filter(Expense.studio_id == None).all()
            for e in exp_to_fix:
                e.studio_id = first_studio.id
                
            # Backfill Configs (except those that should remain global if any)
            # Actually, let's copy global configs to the first studio if missing
            global_configs = Config.query.filter(Config.studio_id == None).all()
            for gc in global_configs:
                exists = Config.query.filter_by(key=gc.key, studio_id=first_studio.id).first()
                if not exists:
                    db.session.add(Config(key=gc.key, value=gc.value, studio_id=first_studio.id))
            
            db.session.commit()
        except Exception as e:
            print(f">>> [BOOTSTRAP] Error: {str(e)}")

# Run bootstrap at startup
ensure_admin_exists()

# ── TIME TRACKING SYSTEM ──────────────────────────────────────────────────────────

@app.route('/api/time-logs', methods=['GET', 'POST'])
@login_required
def handle_time_logs():
    if request.method == 'GET':
        logs = TimeLog.query.filter_by(user_id=current_user.id).order_by(TimeLog.date.desc()).all()
        return jsonify([{
            'id': l.id,
            'date': l.date.strftime('%Y-%m-%d'),
            'start': l.start_time,
            'end': l.end_time,
            'duration': l.duration,
            'creator': l.creator.username if l.creator else 'System'
        } for l in logs])

    data = request.json
    start = data.get('start')
    end = data.get('end')
    date_str = data.get('date')
    
    if not all([start, end, date_str]):
        return jsonify({"error": "Brakujące dane"}), 400
        
    try:
        t1 = datetime.strptime(start, '%H:%M')
        t2 = datetime.strptime(end, '%H:%M')
        diff = t2 - t1
        if diff.total_seconds() < 0: # overnight
            diff = timedelta(hours=24) + diff
        duration = diff.total_seconds() / 3600.0
        
        new_log = TimeLog(
            user_id=current_user.id,
            studio_id=current_user.assigned_studio_id,
            date=datetime.strptime(date_str, '%Y-%m-%d').date(),
            start_time=start,
            end_time=end,
            duration=round(duration, 2),
            created_by_id=current_user.id
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/time-logs/<int:id>', methods=['DELETE'])
@login_required
def delete_time_log(id):
    log = db.session.get(TimeLog, id)
    if not log or (log.user_id != current_user.id and current_user.role != 'ADMIN'):
        return jsonify({"error": "Brak uprawnień"}), 403
    db.session.delete(log)
    db.session.commit()
    return jsonify({"success": True})

@app.route('/api/admin/time-logs', methods=['GET'])
@login_required
@require_module('studio')
def admin_get_time_logs():
    if current_user.role != 'ADMIN':
        return jsonify({"error": "Brak uprawnień admina"}), 403
        
    users = User.query.filter_by(assigned_studio_id=current_user.assigned_studio_id).all()
    today = datetime.now()
    month_start = today.replace(day=1, hour=0, minute=0, second=0).date()
    
    result = []
    for u in users:
        month_logs = TimeLog.query.filter(TimeLog.user_id == u.id, TimeLog.date >= month_start).all()
        total = sum(l.duration for l in month_logs)
        result.append({
            'user_id': u.id,
            'username': u.username,
            'display_name': u.full_name or u.username,
            'total_month': round(total, 2)
        })
    return jsonify(result)

@app.route('/api/admin/time-logs/<int:user_id>', methods=['GET', 'POST'])
@login_required
@require_module('studio')
def admin_manage_user_time(user_id):
    if current_user.role != 'ADMIN':
        return jsonify({"error": "Brak uprawnień"}), 403
        
    target_user = db.session.get(User, user_id)
    if not target_user or target_user.assigned_studio_id != current_user.assigned_studio_id:
        return jsonify({"error": "Użytkownik nie znaleziony"}), 404

    if request.method == 'GET':
        logs = TimeLog.query.filter_by(user_id=user_id).order_by(TimeLog.date.desc()).all()
        return jsonify([{
            'id': l.id,
            'date': l.date.strftime('%Y-%m-%d'),
            'start': l.start_time,
            'end': l.end_time,
            'duration': l.duration,
            'creator': l.creator.username if l.creator else 'System'
        } for l in logs])
        
    data = request.json
    try:
        t1 = datetime.strptime(data['start'], '%H:%M')
        t2 = datetime.strptime(data['end'], '%H:%M')
        duration = (t2 - t1).total_seconds() / 3600.0
        
        new_log = TimeLog(
            user_id=user_id,
            studio_id=current_user.assigned_studio_id,
            date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
            start_time=data['start'],
            end_time=data['end'],
            duration=round(duration, 2),
            created_by_id=current_user.id
        )
        db.session.add(new_log)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/admin/reports/instant/<int:user_id>', methods=['POST'])
@login_required
@require_module('studio')
def generate_instant_report(user_id):
    if current_user.role != 'ADMIN':
        return jsonify({"error": "Brak uprawnień"}), 403
        
    u = db.session.get(User, user_id)
    if not u or u.assigned_studio_id != current_user.assigned_studio_id:
        return jsonify({"error": "Użytkownik nie znaleziony"}), 404
        
    today = datetime.now()
    month_start = today.replace(day=1).date()
    logs = TimeLog.query.filter(TimeLog.user_id == u.id, TimeLog.date >= month_start).order_by(TimeLog.date.asc()).all()
    
    if not logs:
        return jsonify({"error": "Brak wpisów do raportu w tym miesiącu"}), 400
        
    # Generate PDF
    month_names = ["", "STYCZEŃ", "LUTY", "MARZEC", "KWIECIEŃ", "MAJ", "CZERWIEC", "LIPIEC", "SIERPIEŃ", "WRZESIEŃ", "PAŹDZIERNIK", "LISTOPAD", "GRUDZIEŃ"]
    safe_name = (u.full_name or u.username).replace(" ", "_")
    filename = f"RAPORT_{safe_name}_{today.strftime('%Y%m%d_%H%M')}.pdf"
    filepath = os.path.join(PDF_FOLDER, filename)
    
    report_data = {
        "number": f"INST/{today.strftime('%Y/%m')}/{u.id}",
        "month_name": month_names[today.month],
        "year": today.year,
        "user_full_name": u.full_name or u.username,
        "total_hours": sum(l.duration for l in logs),
        "logs": [{
            "date": l.date.strftime('%Y-%m-%d'),
            "start": l.start_time,
            "end": l.end_time,
            "duration": l.duration,
            "creator": l.creator.username if l.creator else 'System'
        } for l in logs]
    }
    
    create_time_report_pdf(filepath, report_data)
    
    # Discord Notify
    wh = current_user.discord_contractor_webhook or get_config_val('ADMIN_WEBHOOK')
    if wh:
        from utils.discord_notifier import _send_with_file
        embed = {
            "title": f"📑 RAPORT INSTANT: {report_data['user_full_name']}",
            "fields": [
                {"name": "Pracownik", "value": report_data['user_full_name'], "inline": True},
                {"name": "Suma Godzin", "value": f"**{report_data['total_hours']:.2f} h**", "inline": True}
            ],
            "color": 3447003,
            "footer": {"text": "NoxPos - Personel"}
        }
        _send_with_file(wh, embed, filepath)
    
    # Return correct URL based on environment
    url_path = f"/api/get-pdf/{filename}" if IS_VERCEL else f"/static/pdfs/{filename}"
    return jsonify({"success": True, "pdf_url": url_path})

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'True') == 'True')
