import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import qrcode
from datetime import datetime
from pypdf import PdfReader, PdfWriter

def encrypt_pdf_bytes(pdf_bytes, password):
    """Encrypts PDF bytes with the given password using AES-256 and returns encrypted bytes."""
    if not password:
        return pdf_bytes
        
    import io
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
        
    writer.encrypt(password, algorithm="AES-256")
    
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()

def encrypt_pdf(file_path, password):
    """Encrypts a PDF file with the given password using AES-256."""
    if not password:
        return
        
    reader = PdfReader(file_path)
    writer = PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
        
    writer.encrypt(password, algorithm="AES-256")
    
    with open(file_path, "wb") as f:
        writer.write(f)

# Try to find a Polish-supporting font on Windows
def get_font_path():
    paths = [
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" # Linux fallback
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

FONT_PATH = get_font_path()
if FONT_PATH:
    pdfmetrics.registerFont(TTFont('PolishFont', FONT_PATH))
    FONT_NAME = 'PolishFont'
else:
    FONT_NAME = 'Helvetica'

def generate_qr_string(account, amount, recipient, title):
    # ZBP Standard: ||NR_KONTA|KWOTA_W_GROSZACH|NAZWA_ODBIORCY|TYTUL|||
    # Amount is total * 100 as integer string
    amount_gr = str(int(round(float(amount) * 100)))
    clean_account = account.replace(" ", "").replace("-", "")
    return f"||{clean_account}|{amount_gr}|{recipient}|{title}|||"

def create_invoice_pdf(filepath, invoice_data, my_data):
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    
    doc_type = invoice_data.get('document_type', 'FAKTURA')
    
    # Map friendly type name
    type_map = {
        'FAKTURA': 'RACHUNEK / FAKTURA',
        'PARAGON': 'PARAGON',
        'WYCENA': 'OFERTA / WYCENA',
        'WZ': 'WZ - WYDANIE ZEWNĘTRZNE'
    }
    friendly_type = type_map.get(doc_type, doc_type)
    
    # Main Title
    c.setFont(FONT_NAME, 16)
    c.drawRightString(190*mm, height - 20*mm, f"DOKUMENT NR {invoice_data['number']}")
    
    # Document Type & Metadata
    c.setFont(FONT_NAME, 10)
    c.drawRightString(190*mm, height - 26*mm, f"Typ dokumentu: {friendly_type}")
    c.drawRightString(190*mm, height - 31*mm, f"Data wystawienia: {invoice_data['date']}")
    c.drawRightString(190*mm, height - 36*mm, f"Miejsce wystawienia: {my_data['city']}")
    
    # Seller
    is_worker = invoice_data.get('is_worker_invoice', False)
    seller_data = invoice_data.get('worker_details', {}) if is_worker else my_data
    
    c.setFont(FONT_NAME, 12)
    c.drawString(20*mm, height - 50*mm, "SPRZEDAWCA:")
    c.setFont(FONT_NAME, 10)
    c.drawString(20*mm, height - 55*mm, seller_data['name'])
    
    # Handle NIP or PESEL for Seller
    seller_id_type = seller_data.get('id_type', 'NIP')
    seller_id_val = seller_data.get('pesel' if seller_id_type == 'PESEL' else 'nip', '')
    c.drawString(20*mm, height - 60*mm, f"{seller_id_type}: {seller_id_val}")
    c.drawString(20*mm, height - 65*mm, seller_data['address'])
    
    # Buyer
    buyer_name = my_data['name'] if is_worker else invoice_data['client_name']
    buyer_nip = my_data['nip'] if is_worker else invoice_data.get('client_nip', '')
    buyer_addr = my_data['address'] if is_worker else invoice_data['client_address']
    
    c.setFont(FONT_NAME, 12)
    c.drawString(110*mm, height - 50*mm, "NABYWCA:")
    c.setFont(FONT_NAME, 10)
    c.drawString(110*mm, height - 55*mm, buyer_name)
    if buyer_nip:
        c.drawString(110*mm, height - 60*mm, f"NIP: {buyer_nip}")
    c.drawString(110*mm, height - 65*mm, buyer_addr)
    
    # Contract Info
    if invoice_data.get('contract_number'):
        c.setFont(FONT_NAME, 10)
        c.drawString(20*mm, height - 72*mm, f"Wystawiono na podstawie umowy nr {invoice_data['contract_number']}")
    
    # Description
    if invoice_data.get('description'):
        c.setFont(FONT_NAME, 9)
        c.drawString(20*mm, height - 77*mm, f"Opis: {invoice_data['description']}")
    
    # Table header
    c.line(20*mm, height - 80*mm, 190*mm, height - 80*mm)
    c.drawString(20*mm, height - 85*mm, "Lp.")
    c.drawString(30*mm, height - 85*mm, "Nazwa usługi")
    
    if doc_type != 'WZ':
        c.drawString(110*mm, height - 85*mm, "Cena jedn.")
        c.drawString(140*mm, height - 85*mm, "Ilość")
        c.drawString(165*mm, height - 85*mm, "Wartość")
    else:
        c.drawString(165*mm, height - 85*mm, "Ilość")
        
    c.line(20*mm, height - 88*mm, 190*mm, height - 88*mm)
    
    y = height - 95*mm
    for i, item in enumerate(invoice_data['items']):
        c.drawString(20*mm, y, str(i+1))
        c.drawString(30*mm, y, item['name'])
        
        if doc_type != 'WZ':
            c.drawString(110*mm, y, f"{item['price']:.2f} PLN")
            c.drawString(140*mm, y, str(item['quantity']))
            c.drawString(165*mm, y, f"{(item['price'] * item['quantity']):.2f} PLN")
        else:
            c.drawString(165*mm, y, str(item['quantity']))
        y -= 7*mm
        
    c.line(20*mm, y + 2*mm, 190*mm, y + 2*mm)
    
    if doc_type != 'WZ':
        c.setFont(FONT_NAME, 12)
        c.drawString(130*mm, y - 5*mm, f"SUMA: {invoice_data['total']:.2f} PLN")
    
    # Payment info
    if doc_type not in ['WZ', 'WYCENA']:
        pm = invoice_data.get('payment_method', 'PRZELEW')
        c.setFont(FONT_NAME, 10)
        c.drawString(20*mm, y - 15*mm, f"Forma płatności: {pm.capitalize()}")
        if pm == 'PRZELEW':
            c.drawString(20*mm, y - 20*mm, f"Numer konta: {my_data['account']}")
    
    qr_path = None
    account_no = seller_data.get('bank_account', my_data['account']) if is_worker else my_data['account']
    seller_name_for_qr = seller_data['name'] if is_worker else my_data['name']
    
    if invoice_data.get('include_qr_code', True) and doc_type in ['FAKTURA', 'PARAGON'] and invoice_data.get('payment_method') == 'PRZELEW' and account_no:
        qr_str = generate_qr_string(account_no, invoice_data['total'], seller_name_for_qr, invoice_data['number'])
        qr = qrcode.make(qr_str)
        
        # FIX: Handle BytesIO or string path
        if isinstance(filepath, str):
            qr_path = filepath.replace(".pdf", "_qr.png")
        else:
            import tempfile
            import uuid
            qr_path = os.path.join(tempfile.gettempdir(), f"qr_{uuid.uuid4().hex}.png")
            
        qr.save(qr_path)
        
        qr_y = 15*mm
        c.drawImage(qr_path, 160*mm, qr_y, width=30*mm, height=30*mm)
        c.setFont(FONT_NAME, 7)
        c.drawRightString(158*mm, qr_y + 18*mm, "Zeskanuj w aplikacji bankowej,")
        c.drawRightString(158*mm, qr_y + 14*mm, "aby dokonać szybkiego przelewu")
    
    # Legal Clause
    if invoice_data.get('include_rights_clause', True) and doc_type != 'WZ':
        c.setFont(FONT_NAME, 8)
        clause = f"Przeniesienie autorskich praw majątkowych następuje z chwilą pełnej zapłaty wynagrodzenia."
        c.drawString(20*mm, 10*mm, clause)
    elif doc_type == 'WZ':
        c.setFont(FONT_NAME, 8)
        clause = "Dokument WZ potwierdza wydanie towaru/usługi. Nie stanowi podstawy płatności."
        c.drawString(20*mm, 10*mm, clause)
    
    # Centered branding footer
    c.setFont(FONT_NAME, 8)
    c.drawCentredString(width/2, 5*mm, "powered by NOX")
    
    c.save()
    if qr_path and os.path.exists(qr_path):
        os.remove(qr_path)

def create_confirmation_pdf(filepath, project_data, my_data):
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    
    c.setFont(FONT_NAME, 16)
    c.drawString(20*mm, height - 20*mm, "POTWIERDZENIE PROJEKTU")
    
    c.setFont(FONT_NAME, 10)
    c.drawString(20*mm, height - 30*mm, f"Projekt: {project_data['title']}")
    c.drawString(20*mm, height - 35*mm, f"Data: {datetime.now().strftime('%Y-%m-%d')}")
    c.drawString(20*mm, height - 40*mm, f"Autor: {project_data['author']}")
    
    c.setFont(FONT_NAME, 12)
    c.drawString(20*mm, height - 55*mm, "SPECYFIKACJA TECHNICZNA:")
    c.setFont(FONT_NAME, 10)
    specs = [
        "Format: WAV",
        "Próbkowanie: 44.1/48 kHz",
        "Rozdzielczość bitowa: 16/24 bit",
        "Dodatkowo: Stemy (jeśli dotyczy)",
        f"Termin oddania: {project_data['deadline']}"
    ]
    y = height - 62*mm
    for s in specs:
        c.drawString(25*mm, y, f"- {s}")
        y -= 6*mm
        
    c.setFont(FONT_NAME, 12)
    c.drawString(20*mm, y - 5*mm, "ZAKRES PRAC:")
    c.setFont(FONT_NAME, 10)
    c.drawString(25*mm, y - 12*mm, project_data['scope'])
    
    # Legal Clause
    c.setFont(FONT_NAME, 8)
    clause = f"Przeniesienie autorskich praw majątkowych następuje z chwilą pełnej zapłaty wynagrodzenia, o którym mowa w fakturze powiązanej."
    c.drawString(20*mm, 40*mm, clause)
    
    # Centered branding footer
    c.setFont(FONT_NAME, 8)
    c.drawCentredString(width/2, 5*mm, "powered by NOX")
    
    c.save()
