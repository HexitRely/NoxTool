from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# ── NEW: Studio (physical location) ──────────────────────────────────────────
class Studio(db.Model):
    __tablename__ = 'studio'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(500))
    bank_account = db.Column(db.String(50))

# ── NEW: User with RBAC ───────────────────────────────────────────────────────
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(100))
    password_hash = db.Column(db.String(256))
    email = db.Column(db.String(100))
    nip = db.Column(db.String(20))
    pesel = db.Column(db.String(20))
    id_type = db.Column(db.String(10), default='NIP') # NIP or PESEL
    role = db.Column(db.String(20), default='PRODUCER')  # ADMIN, PRODUCER, FREELANCER
    assigned_studio_id = db.Column(db.Integer, db.ForeignKey('studio.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    can_manage_catalog = db.Column(db.Boolean, default=False)
    can_access_history = db.Column(db.Boolean, default=False)
    can_create_documents = db.Column(db.Boolean, default=False) # New permission
    
    # granular view access flags
    can_access_dashboard = db.Column(db.Boolean, default=False)
    can_access_pos = db.Column(db.Boolean, default=False)
    can_access_crm = db.Column(db.Boolean, default=False)
    can_access_finance = db.Column(db.Boolean, default=False)
    can_access_settings = db.Column(db.Boolean, default=False)
    can_access_projects = db.Column(db.Boolean, default=False)
    can_manage_projects = db.Column(db.Boolean, default=False)  # create/edit/delete projects
    can_manage_tasks = db.Column(db.Boolean, default=False)     # create/edit/delete tasks
    
    # NEW: Personalized Settings
    pdf_password = db.Column(db.String(100))
    pdf_encryption_enabled = db.Column(db.Boolean, default=False)
    discord_admin_webhook = db.Column(db.String(500))
    discord_contractor_webhook = db.Column(db.String(500))
    address = db.Column(db.String(500))
    bank_account = db.Column(db.String(100))
    must_change_password = db.Column(db.Boolean, default=True)

    studio = db.relationship('Studio', backref=db.backref('users', lazy=True))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'full_name': self.full_name,
            'email': self.email,
            'nip': self.nip,
            'pesel': self.pesel,
            'id_type': self.id_type,
            'role': self.role,
            'assigned_studio_id': self.assigned_studio_id,
            'studio_name': self.studio.name if self.studio else None,
            'is_active': self.is_active,
            'can_manage_catalog': self.can_manage_catalog,
            'can_access_history': self.can_access_history,
            'can_create_documents': self.can_create_documents,
            'can_access_dashboard': self.can_access_dashboard,
            'can_access_pos': self.can_access_pos,
            'can_access_crm': self.can_access_crm,
            'can_access_finance': self.can_access_finance,
            'can_access_settings': self.can_access_settings,
            'can_access_projects': self.can_access_projects,
            'can_manage_projects': self.can_manage_projects,
            'can_manage_tasks': self.can_manage_tasks,
            'pdf_password': self.pdf_password,
            'pdf_encryption_enabled': self.pdf_encryption_enabled,
            'discord_admin_webhook': self.discord_admin_webhook,
            'discord_contractor_webhook': self.discord_contractor_webhook,
            'address': self.address,
            'bank_account': self.bank_account,
            'must_change_password': self.must_change_password
        }

# ── Existing models (with studio_id added) ────────────────────────────────────
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    default_price = db.Column(db.Float, default=0.0)
    category = db.Column(db.String(50), default='Produkcja')
    sort_order = db.Column(db.Integer, default=0)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    nip = db.Column(db.String(20))
    id_type = db.Column(db.String(10), default='NIP')
    email = db.Column(db.String(100))
    phone = db.Column(db.String(30))
    discord_id = db.Column(db.String(100))
    website = db.Column(db.String(200))
    # Advanced CRM fields
    ltv = db.Column(db.Float, default=0.0)
    social_media_links = db.Column(db.Text)
    preferred_gear = db.Column(db.Text)
    # Studio isolation
    studio_id = db.Column(db.Integer, db.ForeignKey('studio.id'), nullable=True)
    studio = db.relationship('Studio', backref=db.backref('clients', lazy=True))

class MusicProject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    bpm = db.Column(db.Integer)
    key = db.Column(db.String(50))
    genre = db.Column(db.String(100))
    target_deadline = db.Column(db.DateTime)
    status = db.Column(db.String(50), default='Active')
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    # Studio isolation
    studio_id = db.Column(db.Integer, db.ForeignKey('studio.id'), nullable=True)
    # Project extensions
    description = db.Column(db.Text)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assigned_user = db.relationship('User', backref=db.backref('assigned_projects', lazy=True))

    client = db.relationship('Client', backref=db.backref('projects', lazy=True, cascade='all, delete-orphan'))
    invoice = db.relationship('Invoice', backref=db.backref('projects', lazy=True))
    studio = db.relationship('Studio', backref=db.backref('projects', lazy=True))

class ProjectFinance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('music_project.id'), unique=True)
    budget = db.Column(db.Float, default=0.0)
    external_costs_hw = db.Column(db.Float, default=0.0)
    external_costs_sw = db.Column(db.Float, default=0.0)
    external_costs_service = db.Column(db.Float, default=0.0)
    time_logged = db.Column(db.Float, default=0.0)

    project = db.relationship('MusicProject', backref=db.backref('finance', uselist=False, cascade='all, delete-orphan'))

class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(50), nullable=False, unique=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    total_amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='Pending')
    pdf_path = db.Column(db.String(200))
    description = db.Column(db.String(500))
    contract_number = db.Column(db.String(100))
    document_type = db.Column(db.String(20), default='FAKTURA')
    payment_method = db.Column(db.String(20), default='PRZELEW')
    include_rights_clause = db.Column(db.Boolean, default=True)
    include_qr_code = db.Column(db.Boolean, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_worker_invoice = db.Column(db.Boolean, default=False)
    # Studio isolation
    studio_id = db.Column(db.Integer, db.ForeignKey('studio.id'), nullable=True)

    client = db.relationship('Client', backref=db.backref('invoices', lazy=True, cascade='all, delete-orphan'))
    creator = db.relationship('User', backref=db.backref('created_invoices', lazy=True))
    studio = db.relationship('Studio', backref=db.backref('invoices', lazy=True))

class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    product_name = db.Column(db.String(100))
    unit_price = db.Column(db.Float)
    quantity = db.Column(db.Integer)

    invoice = db.relationship('Invoice', backref=db.backref('items', lazy=True, cascade='all, delete-orphan'))

class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True)
    value = db.Column(db.String(500))

class ProjectConfirmation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    title = db.Column(db.String(200))
    author = db.Column(db.String(100))
    deadline = db.Column(db.String(100))
    scope = db.Column(db.Text)
    pdf_path = db.Column(db.String(200))

    invoice = db.relationship('Invoice', backref=db.backref('confirmation', uselist=False, cascade='all, delete-orphan'))

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    file_path = db.Column(db.String(300))
    project_id = db.Column(db.Integer, db.ForeignKey('music_project.id'), nullable=True)
    # Studio isolation
    studio_id = db.Column(db.Integer, db.ForeignKey('studio.id'), nullable=True)

    project = db.relationship('MusicProject', backref=db.backref('expenses', lazy=True))
    studio = db.relationship('Studio', backref=db.backref('expenses', lazy=True))

class ModuleConfig(db.Model):
    __tablename__ = 'module_config'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(10), default='📦')
    is_enabled = db.Column(db.Boolean, default=True)
    is_core = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)

# ── NEW: Project Tasks with Markdown ──────────────────────────────────────────
class ProjectTask(db.Model):
    __tablename__ = 'project_task'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('music_project.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    links = db.Column(db.Text) # JSON string
    deadline = db.Column(db.DateTime, nullable=True)
    assigned_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    status = db.Column(db.String(50), default='TODO')
    
    project = db.relationship('MusicProject', backref=db.backref('tasks', lazy=True, cascade='all, delete-orphan'))
    assigned_user = db.relationship('User', backref=db.backref('assigned_tasks', lazy=True))

# ── NEW: Manual Calendar Events ───────────────────────────────────────────────
class CalendarEvent(db.Model):
    __tablename__ = 'calendar_event'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    event_type = db.Column(db.String(50), default='WORK') # WORK, VACATION, BUSY, OTHER
    is_public = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    studio_id = db.Column(db.Integer, db.ForeignKey('studio.id'), nullable=False)
    
    user = db.relationship('User', backref=db.backref('calendar_events', lazy=True))
    studio = db.relationship('Studio', backref=db.backref('calendar_events', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'date': self.date.strftime('%Y-%m-%d'),
            'type': self.event_type,
            'is_public': self.is_public,
            'user_id': self.user_id,
            'username': self.user.username if self.user else 'Unknown'
        }
