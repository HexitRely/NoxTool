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

# Import local modules
from models import db, Product, Client, Invoice, InvoiceItem, Config, ProjectConfirmation, MusicProject, ProjectFinance, Expense, ModuleConfig, Studio, User, ProjectTask, CalendarEvent
from utils.pdf_gen import create_invoice_pdf, create_confirmation_pdf, encrypt_pdf, encrypt_pdf_bytes
from utils.discord_notifier import (
    send_invoice_to_admin, 
    send_confirmation_to_contractors,
    send_invoice_update_to_admin,
    send_invoice_deletion_to_admin,
    send_payment_update_to_admin,
    send_expense_alert_to_admin
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
    return User.query.get(int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Unauthorized', 'login_required': True}), 401
    return redirect('/login')

# Auth guard for all non-public routes
PUBLIC_PATHS = {'/login', '/api/auth/login', '/static'}

@app.before_request
def require_login_globally():
    if request.path == '/login' or request.path.startswith('/static'):
        return None
    if request.path == '/api/auth/login':
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
    # Client extensions
    add_column_if_not_exists('client', 'phone', 'VARCHAR(30)')
    add_column_if_not_exists('client', 'discord_id', 'VARCHAR(100)')
    add_column_if_not_exists('client', 'website', 'VARCHAR(200)')
    # Invoice flags
    add_column_if_not_exists('invoice', 'include_rights_clause', 'BOOLEAN DEFAULT TRUE')
    add_column_if_not_exists('invoice', 'include_qr_code', 'BOOLEAN DEFAULT TRUE')
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
    add_column_if_not_exists('calendar_event', 'is_public', 'BOOLEAN DEFAULT 0')
    
    add_column_if_not_exists('music_project', 'description', 'TEXT')
    add_column_if_not_exists('music_project', 'assigned_user_id', 'INTEGER')

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
    """Returns studio_id to filter queries by. None for ADMIN means 'all studios'."""
    if current_user.role == 'ADMIN':
        sid = request.args.get('studio_id')
        return int(sid) if sid else None
    return current_user.assigned_studio_id

def get_studio_id_for_create():
    """Returns the studio_id to stamp on newly created records."""
    if current_user.role == 'ADMIN':
        data = request.json or {}
        sid = data.get('studio_id') or request.args.get('studio_id')
        if sid:
            return int(sid)
        # Admin defaults to first studio if not specified
        first = Studio.query.first()
        return first.id if first else 1
    return current_user.assigned_studio_id

def apply_studio_filter(query, model):
    """Append studio_id WHERE clause if user is not ADMIN or ADMIN specified a studio."""
    sid = get_studio_id_for_query()
    if sid is not None:
        query = query.filter(model.studio_id == sid)
    return query

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
    return jsonify(current_user.to_dict())

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
        studio = Studio(name=data['name'], address=data.get('address', ''), bank_account=data.get('bank_account', ''))
        db.session.add(studio)
        db.session.commit()
        return jsonify({'success': True, 'id': studio.id})
    studios = Studio.query.all()
    return jsonify([{'id': s.id, 'name': s.name, 'address': s.address, 'bank_account': s.bank_account} for s in studios])

@app.route('/api/studios/<int:id>', methods=['PUT', 'DELETE'])
@require_role('ADMIN')
def handle_single_studio(id):
    studio = Studio.query.get(id)
    if not studio:
        return jsonify({'error': 'Studio nie istnieje'}), 404
    if request.method == 'DELETE':
        db.session.delete(studio)
        db.session.commit()
        return jsonify({'success': True})
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
            can_manage_tasks=True if data.get('role') == 'ADMIN' else data.get('can_manage_tasks', False)
        )
        user.set_password(data.get('password', 'changeme123'))
        db.session.add(user)
        db.session.commit()
        return jsonify({'success': True, 'id': user.id})
    return jsonify([u.to_dict() for u in User.query.all()])

@app.route('/api/users/<int:id>', methods=['PUT', 'DELETE'])
@require_role('ADMIN')
def handle_single_user(id):
    user = User.query.get(id)
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
        
    if data.get('password'):
        user.set_password(data['password'])
    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/modules', methods=['GET'])
def get_modules():
    modules = ModuleConfig.query.order_by(ModuleConfig.sort_order).all()
    return jsonify([{
        'key': m.key,
        'display_name': m.display_name,
        'icon': m.icon,
        'is_enabled': m.is_enabled,
        'is_core': m.is_core,
        'sort_order': m.sort_order
    } for m in modules])

@app.route('/api/modules/toggle', methods=['POST'])
def toggle_module():
    data = request.json
    key = data.get('key')
    mod = ModuleConfig.query.filter_by(key=key).first()
    if not mod:
        return jsonify({'error': 'Moduł nie istnieje'}), 404
    if mod.is_core:
        return jsonify({'error': 'Nie można wyłączyć modułu podstawowego (core)'}), 400
    mod.is_enabled = not mod.is_enabled
    db.session.commit()
    return jsonify({'success': True, 'key': mod.key, 'is_enabled': mod.is_enabled})

# --- API ENDPOINTS ---

@app.route('/api/dashboard', methods=['GET'])
@require_role('ADMIN', 'PRODUCER')
def get_dashboard():
    limit_type = Config.query.filter_by(key='LIMIT_TYPE').first().value
    limit_val = float(Config.query.filter_by(key='LIMIT_VALUE').first().value)
    
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
    product = Product.query.get(id)
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
    client = Client.query.get(id)
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
    creator = user_context or User.query.get(invoice.created_by_id)
    
    # Get my data from Config
    # If user has personal NIP/Address, use it instead of global
    use_personal = False
    if creator.role != 'ADMIN' and creator.nip and creator.address:
        use_personal = True

    if use_personal:
        my_data = {
            "name": creator.full_name or creator.username, 
            "nip": creator.nip,
            "account": Config.query.filter_by(key='MY_ACCOUNT').first().value,
            "city": "", 
            "address": creator.address
        }
        if "," in creator.address:
            parts = creator.address.split(",", 1)
            my_data["city"] = parts[0].strip()
            my_data["address"] = parts[1].strip()
    else:
        my_data = {
            "name": Config.query.filter_by(key='MY_NAME').first().value,
            "nip": Config.query.filter_by(key='MY_NIP').first().value,
            "account": Config.query.filter_by(key='MY_ACCOUNT').first().value,
            "city": Config.query.filter_by(key='MY_CITY').first().value,
            "address": Config.query.filter_by(key='MY_ADDRESS').first().value
        }
    
    items_for_pdf = [{
        "name": it.product_name,
        "price": it.unit_price,
        "quantity": it.quantity
    } for it in invoice.items]

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
        "worker_details": {
            "name": creator.full_name or creator.username,
            "nip": creator.nip,
            "pesel": creator.pesel,
            "id_type": creator.id_type,
            "address": creator.address or "",
            "bank_account": creator.bank_account or Config.query.filter_by(key='MY_ACCOUNT').first().value 
        }
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
    elif client_id:
        client = Client.query.get(client_id)
        
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
    admin_conf = Config.query.filter_by(key='ADMIN_WEBHOOK').first()
    ekipa_conf = Config.query.filter_by(key='EKIPA_WEBHOOK').first()
    
    global_admin = admin_conf.value if admin_conf else None
    global_ekipa = ekipa_conf.value if ekipa_conf else None
    
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
            
        for wh in set(webhooks):
            if wh:
                if send_invoice_to_admin(wh, invoice_pdf_data, tmp_path):
                    discord_sent = True
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
    invoice = Invoice.query.get(id)
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
        webhook_url = Config.query.filter_by(key='ADMIN_WEBHOOK').first().value
        send_invoice_deletion_to_admin(webhook_url, num, total)
        return jsonify({"success": True})

    if request.method == 'PUT':
        data = request.json
        client_id = data.get('client_id')
        new_client_data = data.get('new_client_data')
        
        client = None
        if new_client_data:
            if new_client_data.get('nip'):
                client = Client.query.filter_by(nip=new_client_data['nip']).first()
            if not client and new_client_data.get('name'):
                client = Client(
                    name=new_client_data['name'],
                    address=new_client_data.get('address'),
                    nip=new_client_data.get('nip')
                )
                db.session.add(client)
                db.session.commit()
        elif client_id:
            client = Client.query.get(client_id)

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
        
        db.session.commit()
        
        # Notify Discord
        admin_conf = Config.query.filter_by(key='ADMIN_WEBHOOK').first()
        ekipa_conf = Config.query.filter_by(key='EKIPA_WEBHOOK').first()
        
        global_admin = admin_conf.value if admin_conf else None
        global_ekipa = ekipa_conf.value if ekipa_conf else None
        
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
    invoice = Invoice.query.get(id)
    if not invoice: return jsonify({"error": "Faktura nie istnieje"}), 404
    invoice.status = 'Paid' if invoice.status != 'Paid' else 'Pending'
    db.session.commit()
    
    # Notify Discord
    admin_conf = Config.query.filter_by(key='ADMIN_WEBHOOK').first()
    global_admin = admin_conf.value if admin_conf else None
    
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
    invoice = Invoice.query.get(id)
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
    quote = Invoice.query.get(id)
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
    global_admin = Config.query.filter_by(key='ADMIN_WEBHOOK').first().value
    
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
    invoice = Invoice.query.get(data['invoice_id'])
    if not invoice:
        return jsonify({"error": "Faktura nie istnieje"}), 404
        
    # Get Author from config
    author = Config.query.filter_by(key='AUTHOR_NAME').first()
    author_val = author.value if author else "Dawid Blacharski"
    
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
        "name": Config.query.filter_by(key='MY_NAME').first().value
    }
    project_pdf_data = {
        "title": new_conf.title,
        "author": new_conf.author,
        "deadline": new_conf.deadline,
        "scope": new_conf.scope
    }
    # Integration: Send to Discord
    global_ekipa = Config.query.filter_by(key='CONTRACTOR_WEBHOOK').first()
    
    webhooks = []
    if global_ekipa and global_ekipa.value: webhooks.append(global_ekipa.value)
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
    invoice = Invoice.query.get(id)
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
    
    # Apply encryption if enabled
    # We check the creator's settings for consistency
    creator = User.query.get(invoice.user_id) if hasattr(invoice, 'user_id') else current_user
    if creator and creator.pdf_encryption_enabled and creator.pdf_password:
        pdf_bytes = encrypt_pdf_bytes(pdf_bytes, creator.pdf_password)
        
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
    conf = ProjectConfirmation.query.get(id)
    if not conf: return jsonify({"error": "Potwierdzenie nie istnieje"}), 404
    
    # Prepare metadata
    my_data = {
        "name": Config.query.filter_by(key='MY_NAME').first().value
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
        user = User.query.get(current_user.id)
        
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
    if current_user.role == 'PRODUCER' and request.method == 'POST':
         return jsonify({"error": "Admin only"}), 403
         
    if request.method == 'POST':
        data = request.json
        for key, value in data.items():
            conf = Config.query.filter_by(key=key).first()
            if conf:
                conf.value = value
            else:
                db.session.add(Config(key=key, value=value))
        db.session.commit()
        return jsonify({"success": True})
    
    confs = Config.query.all()
    return jsonify({c.key: c.value for c in confs})

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
    # 1. Top 3 Clients by LTV
    top_clients = Client.query.order_by(Client.ltv.desc()).limit(3).all()
    clients_data = [{
        "name": c.name,
        "ltv": c.ltv,
        "project_count": len(c.projects)
    } for c in top_clients]

    # 2. Spending Pie Chart (Total across all projects)
    finances = ProjectFinance.query.all()
    spending_pie = {
        "hardware": sum(f.external_costs_hw for f in finances),
        "software": sum(f.external_costs_sw for f in finances),
        "freelancers": sum(f.external_costs_service for f in finances)
    }

    # 3. Average Hourly Rate (Last 30 days)
    # For simplicity, we take projects completed in last 30 days or all active if none completed
    all_projects = MusicProject.query.all()
    rates = [calculate_hourly_rate(p) for p in all_projects if calculate_hourly_rate(p) > 0]
    avg_rate = round(sum(rates) / len(rates), 2) if rates else 0.0

    # 4. Monthly Summary
    today = date.today()
    start_of_month = datetime(today.year, today.month, 1)
    
    # Simple aggregation for the current month
    monthly_projects = MusicProject.query.filter(MusicProject.target_deadline >= start_of_month).all()
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
        new_project = MusicProject(
            client_id=data['client_id'],
            name=data['name'],
            bpm=data.get('bpm'),
            key=data.get('key'),
            genre=data.get('genre'),
            target_deadline=datetime.strptime(data['deadline'], '%Y-%m-%d') if data.get('deadline') else None,
            status=data.get('status', 'Active'),
            invoice_id=data.get('invoice_id'),
            assigned_user_id=data.get('assigned_user_id'),
            description=data.get('description'),
            studio_id=get_studio_id_for_create()
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
        client = Client.query.get(new_project.client_id)
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
        "client": p.client.name,
        "status": p.status,
        "assigned_user_id": p.assigned_user_id,
        "assigned_user_name": p.assigned_user.username if p.assigned_user else None,
        "roi": calculate_roi(p),
        "hourly_rate": calculate_hourly_rate(p)
    } for p in projects])

@app.route('/api/projects/<int:id>', methods=['GET', 'PUT', 'DELETE'])
@require_module('studio')
def handle_single_project(id):
    if not (current_user.role == 'ADMIN' or current_user.can_access_projects or current_user.can_manage_projects):
        return jsonify({'error': 'Brak uprawnień do projektów'}), 403
    project = MusicProject.query.get(id)
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
    project = MusicProject.query.get(id)
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
    task = ProjectTask.query.get(id)
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
    task.status = data.get('status', task.status)
    db.session.commit()
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
            "is_mine": e.user_id == current_user.id
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
    event = CalendarEvent.query.get(id)
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
        threshold_cfg = Config.query.filter_by(key='COST_THRESHOLD_LIMIT').first()
        threshold = float(threshold_cfg.value) if threshold_cfg else 1000.0
        
        if new_expense.amount >= threshold:
            global_admin = Config.query.filter_by(key='ADMIN_WEBHOOK').first().value
            
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
    expense = Expense.query.get(id)
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
        except Exception as e:
            print(f">>> [BOOTSTRAP] Error: {str(e)}")

# Run bootstrap at startup
ensure_admin_exists()

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'True') == 'True')
