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
        # Sanitize data
        client_name = invoice_data.get('client_name', 'Nieznany')
        total_val = invoice_data.get('total', 0.0)
        formatted_total = f"{float(total_val):.2f}"
        inv_number = invoice_data.get('number', '---')
        
        fields = [
            {"name": "Klient", "value": str(client_name), "inline": True},
            {"name": "Metoda Płatności", "value": f"**{payment_method}**", "inline": True}
        ]
        
        if doc_type != 'WZ':
            fields.insert(0, {"name": "Kwota", "value": f"**{formatted_total} PLN**", "inline": True})
            status = "Oczekiwanie na przelew" if payment_method == 'PRZELEW' else "Opłacono"
            fields.append({"name": "Status", "value": status, "inline": False})
            
        # NEW: Password notice
        if invoice_data.get('is_encrypted'):
            fields.append({
                "name": "🔐 Hasło do pliku", 
                "value": f"||{invoice_data.get('pdf_password', 'brak')}||", 
                "inline": False
            })
            
        embed = {
            "title": f"{cfg['emoji']} {cfg['title']}: {inv_number}",
            "fields": fields,
            "color": int(cfg.get('color', 3066993)),
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
            
        file_size = os.path.getsize(file_path)
        print(f"DEBUG Discord: Uploading file {os.path.basename(file_path)} ({file_size} bytes)")
        
        if file_size == 0:
            print(f"DEBUG Discord: WARNING! File is empty.")

        with open(file_path, 'rb') as f:
            # Send file as 'file' form field
            files = { "file": (os.path.basename(file_path), f, "application/pdf") }
            
            # Send embed data as 'payload_json'
            payload = { "payload_json": json.dumps({"embeds": [embed]}) }
            
            url = webhook_url.strip()
            response = requests.post(url, data=payload, files=files, timeout=20)
            
            if response.status_code not in [200, 204]:
                print(f"Discord Webhook Error ({os.path.basename(file_path)}): Status {response.status_code}")
                print(f"Response Body: {response.text}")
            else:
                print(f"Discord Notification Sent Successfully: {os.path.basename(file_path)}")
            return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error in _send_with_file: {str(e)}")
        import traceback
        traceback.print_exc()
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
def send_brief_notification(webhook_url, project_data):
    if not webhook_url or webhook_url == "":
        return False
    try:
        is_secret = project_data.get('is_secret', False)
        color = 15844367 if is_secret else 3447003 # Gold for Secret, Blue for normal
        
        fields = [
            {"name": "Klient", "value": project_data['client_name'], "inline": True},
            {"name": "Typ", "value": f"**{project_data['type']}**", "inline": True},
            {"name": "Deadline", "value": project_data.get('deadline') or 'Brak', "inline": True},
        ]
        
        if project_data.get('vibe'):
            fields.append({"name": "🎨 Wizja / Klimat", "value": project_data['vibe'], "inline": False})
        
        if project_data.get('references'):
            fields.append({"name": "🎵 Referencje", "value": project_data['references'], "inline": False})
        
        if project_data.get('segment_notes'):
            fields.append({"name": "⏱️ Uwagi do fragmentów", "value": project_data['segment_notes'], "inline": False})
        
        if project_data.get('notes'):
            fields.append({"name": "📝 Dodatkowe uwagi", "value": project_data['notes'], "inline": False})
        
        fields.append({"name": "🔒 Projekt Tajny (NDA)", "value": "TAK - Zakaz publikacji" if is_secret else "NIE", "inline": False})
        
        embed = {
            "title": f"📁 NOWY BRIEF PROJEKTU: {project_data['name']}",
            "fields": fields,
            "color": color,
            "footer": {"text": "NoxPos - Produkcja"}
        }
        payload = {"payload_json": json.dumps({"embeds": [embed]})}
        response = requests.post(webhook_url, data=payload, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending brief notification: {str(e)}")
        return False

def send_task_update_notification(webhook_url, task_data):
    if not webhook_url or webhook_url == "":
        return False
    try:
        # Green for DONE, Orange for others
        color = 3066993 if task_data['new_status'] == 'DONE' else 15105570
        
        embed = {
            "title": f"📝 Zmiana statusu zadania: {task_data['title']}",
            "description": f"Zadanie w projekcie **{task_data['project_name']}** zmieniło status.",
            "fields": [
                {"name": "Poprzedni", "value": task_data['old_status'], "inline": True},
                {"name": "Nowy", "value": f"➡️ **{task_data['new_status']}**", "inline": True},
                {"name": "Zmienił", "value": task_data['user_name'], "inline": False}
            ],
            "color": color,
            "footer": {"text": "NoxPos - Zadania"}
        }
        payload = {"payload_json": json.dumps({"embeds": [embed]})}
        response = requests.post(webhook_url, data=payload, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Error sending task update notification: {str(e)}")
        return False
