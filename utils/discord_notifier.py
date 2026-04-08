import requests
import json
import os

def send_invoice_to_admin(webhook_url, invoice_data, pdf_path):
    if not webhook_url or webhook_url == "":
        print("Webhook URL not configured.")
        return False
        
    doc_type = invoice_data.get('document_type', 'FAKTURA')
    payment_method = invoice_data.get('payment_method', 'PRZELEW')
    
    # Color & Emoji Mapping
    # FAKTURA: Green, PARAGON: Purple, WYCENA: Yellow, WZ: Blue
    config = {
        'FAKTURA': {'color': 3066993, 'emoji': '📑', 'title': 'Nowa Faktura'},
        'PARAGON': {'color': 10181046, 'emoji': '🧾', 'title': 'Nowy Paragon'},
        'WYCENA': {'color': 15844367, 'emoji': '💰', 'title': 'Nowa Wycena/Oferta'},
        'WZ': {'color': 3447003, 'emoji': '📦', 'title': 'Nowe Wydanie Zewnętrzne (WZ)'}
    }
    
    cfg = config.get(doc_type, config['FAKTURA'])
    
    try:
        fields = [
            {"name": "Klient", "value": invoice_data['client_name'], "inline": True},
            {"name": "Metoda Płatności", "value": f"**{payment_method}**", "inline": True}
        ]
        
        if doc_type != 'WZ':
            fields.insert(0, {"name": "Kwota", "value": f"**{invoice_data['total']:.2f} PLN**", "inline": True})
            status = "Oczekiwanie na przelew" if payment_method == 'PRZELEW' else "Opłacono"
            fields.append({"name": "Status", "value": status, "inline": False})
            
        # NEW: Password notice
        if invoice_data.get('is_encrypted'):
            fields.append({
                "name": "🔐 Hasło do pliku", 
                "value": f"||{invoice_data['pdf_password']}||", 
                "inline": False
            })
            
        embed = {
            "title": f"{cfg['emoji']} {cfg['title']}: {invoice_data['number']}",
            "fields": fields,
            "color": cfg['color'],
            "footer": {"text": "NoxPos - Finanse"}
        }
        return _send_with_file(webhook_url, embed, pdf_path)
    except Exception as e:
        print(f"Error sending invoice: {str(e)}")
        return False

def send_confirmation_to_contractors(webhook_url, project_data, pdf_path):
    if not webhook_url or webhook_url == "":
        print("Contractor Webhook URL not configured.")
        return False
        
    try:
        embed = {
            "title": f"🎹 Potwierdzenie Projektu: {project_data['title']}",
            "fields": [
                {"name": "Wykonawca", "value": project_data['author'], "inline": True},
                {"name": "Termin", "value": project_data['deadline'], "inline": True}
            ],
            "color": 10181046, # Purple
            "footer": {"text": "NoxPos - Produkcja"}
        }
        return _send_with_file(webhook_url, embed, pdf_path)
    except Exception as e:
        print(f"Error sending confirmation: {str(e)}")
        return False

def send_invoice_update_to_admin(webhook_url, invoice_data, pdf_path):
    if not webhook_url or webhook_url == "":
        return False
    try:
        embed = {
            "title": f"🔄 Zaktualizowano Fakturę: {invoice_data['number']}",
            "fields": [
                {"name": "Nowa Kwota", "value": f"**{invoice_data['total']:.2f} PLN**", "inline": True},
                {"name": "Klient", "value": invoice_data['client_name'], "inline": True},
                {"name": "Status", "value": "Zaktualizowano - Oczekiwanie na przelew", "inline": False}
            ],
            "color": 3447003,
            "footer": {"text": "NoxPos - Aktualizacja"}
        }
        return _send_with_file(webhook_url, embed, pdf_path)
    except Exception as e:
        print(f"Error sending invoice update: {str(e)}")
        return False

def send_invoice_deletion_to_admin(webhook_url, invoice_number, total):
    if not webhook_url or webhook_url == "":
        return False
    try:
        embed = {
            "title": f"🗑️ Usunięto Fakturę: {invoice_number}",
            "description": f"Faktura na kwotę **{total:.2f} PLN** została usunięta z systemu.",
            "color": 15158332, # Red
            "footer": {"text": "NoxPos - Usunięcie"}
        }
        payload = {"payload_json": json.dumps({"embeds": [embed]})}
        response = requests.post(webhook_url, data=payload, timeout=10)
        if response.status_code not in [200, 204]:
            print(f"Discord Deletion Error: {response.status_code} - {response.text}")
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending deletion alert: {str(e)}")
        return False

def send_payment_update_to_admin(webhook_url, invoice_number, total, status):
    if not webhook_url or webhook_url == "":
        return False
    try:
        color = 3066993 if status == "Paid" else 15105570 # Green for Paid, Orange for Pending
        emoji = "✅" if status == "Paid" else "⏳"
        embed = {
            "title": f"{emoji} Zmiana statusu płatności: {invoice_number}",
            "fields": [
                {"name": "Nowy Status", "value": f"**{status}**", "inline": True},
                {"name": "Kwota", "value": f"{total:.2f} PLN", "inline": True}
            ],
            "color": color,
            "footer": {"text": "NoxPos - Płatności"}
        }
        payload = {"payload_json": json.dumps({"embeds": [embed]})}
        response = requests.post(webhook_url, data=payload, timeout=10)
        if response.status_code not in [200, 204]:
            print(f"Discord Payment Update Error: {response.status_code} - {response.text}")
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending payment update: {str(e)}")
        return False

def _send_with_file(webhook_url, embed, file_path):
    try:
        if not os.path.exists(file_path):
            print(f"File not found for Discord upload: {file_path}")
            return False
            
        with open(file_path, 'rb') as f:
            files = {
                "file": (os.path.basename(file_path), f, "application/pdf")
            }
            payload = {
                "payload_json": json.dumps({"embeds": [embed]})
            }
            # Clean webhook URL just in case
            webhook_url = webhook_url.strip()
            response = requests.post(webhook_url, data=payload, files=files, timeout=15)
            if response.status_code not in [200, 204]:
                print(f"Discord Webhook Error ({os.path.basename(file_path)}): {response.status_code} - {response.text}")
            else:
                print(f"Discord Notification Sent Successfully: {os.path.basename(file_path)}")
            return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error in _send_with_file: {str(e)}")
        return False

def send_expense_alert_to_admin(webhook_url, expense_data, file_path=None):
    if not webhook_url or webhook_url == "":
        return False
    try:
        embed = {
            "title": "🚨 WYSOKI KOSZT ZAREJESTROWANY",
            "color": 15158332, # Red
            "fields": [
                {"name": "Tytuł", "value": expense_data['title'], "inline": True},
                {"name": "Kwota", "value": f"**{expense_data['amount']:.2f} PLN**", "inline": True},
                {"name": "Kategoria", "value": expense_data['category'], "inline": True},
                {"name": "Data", "value": expense_data['date'], "inline": True}
            ],
            "footer": {"text": "NoxPos - Monitor Finansowy"}
        }
        
        if file_path and os.path.exists(file_path):
            return _send_with_file(webhook_url, embed, file_path)
        else:
            payload = {"payload_json": json.dumps({"embeds": [embed]})}
            response = requests.post(webhook_url, data=payload)
            return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending expense alert: {str(e)}")
        return False
