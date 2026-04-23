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

# Try to find a Polish-supporting font
def get_font_path():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    paths = [
        os.path.join(root_dir, "static", "fonts", "Roboto-Regular.ttf"),
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
    try:
        pdfmetrics.registerFont(TTFont('PolishFont', FONT_PATH))
        FONT_NAME = 'PolishFont'
    except Exception as e:
        print(f"Error registering font {FONT_PATH}: {e}")
        FONT_NAME = 'Helvetica'
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
        'WZ': 'WZ - WYDANIE ZEWNĘTRZNE',
        'ZAMOWIENIE': 'ZAMÓWIENIE (KBE FLORIST)'
    }
    friendly_type = type_map.get(doc_type, doc_type)
    
    # Main Title
    c.setFont(FONT_NAME, 16)
    c.drawRightString(190*mm, height - 20*mm, f"DOKUMENT NR {invoice_data['number']}")
    
    # Document Type & Metadata
    c.setFont(FONT_NAME, 10)
    c.drawRightString(190*mm, height - 26*mm, f"Typ dokumentu: {friendly_type}")
    c.drawRightString(190*mm, height - 31*mm, f"Data wystawienia: {invoice_data['date']}")
    
    # Seller
    is_worker = invoice_data.get('is_worker_invoice', False)
    seller_data = invoice_data.get('worker_details', {}) if is_worker else my_data
    
    seller_city = seller_data.get('city', my_data['city'])
    c.drawRightString(190*mm, height - 36*mm, f"Miejsce wystawienia: {seller_city}")
    
    c.setFont(FONT_NAME, 12)
    c.drawString(20*mm, height - 50*mm, "SPRZEDAWCA:")
    c.setFont(FONT_NAME, 10)
    c.drawString(20*mm, height - 55*mm, seller_data['name'])
    
    # Handle NIP or PESEL for Seller
    seller_id_type = seller_data.get('id_type', 'NIP')
    seller_id_val = seller_data.get('pesel' if seller_id_type == 'PESEL' else 'nip', '')
    if seller_id_val and seller_id_val.strip():
        c.drawString(20*mm, height - 60*mm, f"{seller_id_type}: {seller_id_val}")
    c.drawString(20*mm, height - 65*mm, seller_data['address'])
    
    # Buyer
    buyer_name = invoice_data['client_name']
    buyer_nip = invoice_data.get('client_nip', '')
    buyer_addr = invoice_data['client_address']
    
    c.setFont(FONT_NAME, 12)
    c.drawString(110*mm, height - 50*mm, "NABYWCA:")
    c.setFont(FONT_NAME, 10)
    c.drawString(110*mm, height - 55*mm, buyer_name)
    if buyer_nip:
        c.drawString(110*mm, height - 60*mm, f"NIP: {buyer_nip}")
    c.drawString(110*mm, height - 65*mm, buyer_addr)
    
    # Recipient Info (Metadata)
    metadata = invoice_data.get('metadata', {})
    name_rec = metadata.get('recipient_name', '').strip()
    addr_rec = metadata.get('recipient_address', '').strip()
    
    # Only show if at least name or address is provided and not just "---"
    has_recipient = (name_rec and name_rec != '---') or (addr_rec and addr_rec != '---')
    
    if has_recipient:
        c.setFont(FONT_NAME, 10)
        c.drawString(110*mm, height - 72*mm, "ODBIORCA:")
        c.setFont(FONT_NAME, 9)
        phone_rec = metadata.get('recipient_phone', '')
        time_del = metadata.get('time', 'ASAP')
        note = metadata.get('note', '')

        c.drawString(110*mm, height - 77*mm, f"{name_rec} {phone_rec}")
        c.drawString(110*mm, height - 82*mm, f"Adres: {addr_rec}")
        c.drawString(110*mm, height - 87*mm, f"Czas: {time_del}")
        
        if note:
            c.setFont(FONT_NAME, 8)
            c.drawString(20*mm, height - 87*mm, f"BILECIK/NOTATKA: {note}")
        
        # Shift table lower to avoid overlap
        y_table_start = height - 105*mm
    else:
        y_table_start = height - 85*mm

    # Table header
    table_header_y = y_table_start + 5*mm
    c.line(20*mm, table_header_y + 3*mm, 190*mm, table_header_y + 3*mm)
    c.setFont(FONT_NAME, 10)
    c.drawString(20*mm, table_header_y, "Lp.")
    c.drawString(30*mm, table_header_y, "Nazwa usługi")
    
    if doc_type != 'WZ':
        c.drawString(95*mm, table_header_y, "Ilość")
        c.drawString(110*mm, table_header_y, "Cena jedn.")
        c.drawString(140*mm, table_header_y, "Stawka")
        c.drawString(155*mm, table_header_y, "Kwota VAT")
        c.drawString(178*mm, table_header_y, "Suma")
    else:
        c.drawString(165*mm, table_header_y, "Ilość")
        
    c.line(20*mm, table_header_y - 2*mm, 190*mm, table_header_y - 2*mm)
    
    y = table_header_y - 7*mm
    for i, item in enumerate(invoice_data['items']):
        c.drawString(20*mm, y, str(i+1))
        c.drawString(30*mm, y, item['name'])
        
        if doc_type != 'WZ':
            c.drawString(95*mm, y, str(item['quantity']))
            c.drawString(110*mm, y, f"{item['price']:.2f}")
            
            rate_disp = f"{item['vat_rate']}%" if item['vat_rate'] not in ['zw', 'np'] else item['vat_rate']
            c.drawString(140*mm, y, rate_disp)
            
            vat_val = item.get('vat_value', 0.0)
            c.drawString(155*mm, y, f"{vat_val:.2f}")
            
            c.drawString(178*mm, y, f"{(item['price'] * item['quantity']):.2f}")
        else:
            c.drawString(165*mm, y, str(item['quantity']))
        y -= 7*mm
        
    c.line(20*mm, y + 2*mm, 190*mm, y + 2*mm)
    
    if doc_type != 'WZ':
        c.setFont(FONT_NAME, 12)
        c.drawString(130*mm, y - 5*mm, f"SUMA: {invoice_data['total']:.2f} PLN")
    
    # Payment info
    account_no = seller_data.get('bank_account', my_data['account']) if is_worker else my_data['account']
    if doc_type not in ['WZ', 'WYCENA']:
        pm = invoice_data.get('payment_method', 'PRZELEW')
        c.setFont(FONT_NAME, 10)
        c.drawString(20*mm, y - 15*mm, f"Forma płatności: {pm.capitalize()}")
        if pm == 'PRZELEW':
            c.drawString(20*mm, y - 20*mm, f"Numer konta: {account_no}")
    
    qr_path = None
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
    y_clause = 10*mm
    if invoice_data.get('legal_basis'):
        c.setFont(FONT_NAME, 8)
        c.drawString(20*mm, 15*mm, f"Podstawa prawna zwolnienia z VAT: {invoice_data['legal_basis']}")
        y_clause = 10*mm

    if invoice_data.get('include_rights_clause', True) and doc_type != 'WZ':
        c.setFont(FONT_NAME, 8)
        clause = f"Przeniesienie autorskich praw majątkowych następuje z chwilą pełnej zapłaty wynagrodzenia."
        c.drawString(20*mm, y_clause, clause)
    elif doc_type == 'WZ':
        c.setFont(FONT_NAME, 8)
        clause = "Dokument WZ potwierdza wydanie towaru/usługi. Nie stanowi podstawy płatności."
        c.drawString(20*mm, y_clause, clause)
    
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

def create_time_report_pdf(filepath, report_data):
    """
    report_data should contain:
    - number: document number
    - month_name: e.g. 'STYCZEŃ'
    - year: e.g. 2026
    - user_full_name: employee name
    - logs: list of {date, start, end, duration, creator}
    - total_hours: float
    """
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    
    # Header
    c.setFont(FONT_NAME, 14)
    c.drawString(20*mm, height - 20*mm, f"ZBIORCZA KARTA PRACY - {report_data['month_name']} {report_data['year']}")
    c.setFont(FONT_NAME, 10)
    c.drawRightString(190*mm, height - 20*mm, f"Nr dokumentu: {report_data['number']}")
    
    c.setFont(FONT_NAME, 11)
    c.drawString(20*mm, height - 30*mm, f"Pracownik / Freelancer: {report_data['user_full_name']}")
    c.drawString(20*mm, height - 35*mm, f"Data wystawienia: {datetime.now().strftime('%Y-%m-%d')}")
    
    # Table Header
    y = height - 45*mm
    c.line(20*mm, y + 3*mm, 190*mm, y + 3*mm)
    c.setFont(FONT_NAME, 9)
    c.drawString(22*mm, y, "LP")
    c.drawString(35*mm, y, "DATA")
    c.drawString(65*mm, y, "GODZINA OD")
    c.drawString(95*mm, y, "GODZINA DO")
    c.drawString(125*mm, y, "SUMA (h)")
    c.drawString(155*mm, y, "KTO UZUPEŁNIAŁ")
    c.line(20*mm, y - 2*mm, 190*mm, y - 2*mm)
    
    y -= 7*mm
    for i, log in enumerate(report_data['logs']):
        if y < 30*mm: # Simple pagination
            c.showPage()
            c.setFont(FONT_NAME, 9)
            y = height - 20*mm
            c.line(20*mm, y + 3*mm, 190*mm, y + 3*mm)
            
        c.drawString(22*mm, y, str(i+1))
        c.drawString(35*mm, y, str(log['date']))
        c.drawString(65*mm, y, str(log['start']))
        c.drawString(95*mm, y, str(log['end']))
        c.drawString(125*mm, y, f"{log['duration']:.2f}")
        c.drawString(155*mm, y, str(log['creator']))
        y -= 6*mm

    c.line(20*mm, y + 4*mm, 190*mm, y + 4*mm)
    
    # Summary
    y -= 10*mm
    c.setFont(FONT_NAME, 12)
    c.drawString(130*mm, y, f"ŁĄCZNIE: {report_data['total_hours']:.2f} h")
    
    # Footer
    c.setFont(FONT_NAME, 9)
    c.drawString(20*mm, 20*mm, f"Dokument wystawiony dla: {report_data['user_full_name']}")
    
    # Branding
    c.setFont(FONT_NAME, 8)
    c.drawCentredString(width/2, 5*mm, "System NoxPos - Raport Czasu Pracy")
    
    c.save()
