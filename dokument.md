# Raport Stanu Projektu: NDG Shield | Music Production POS

## 1. Cel i charakterystyka aplikacji
Aplikacja to wyspecjalizowany system typu **POS (Point of Sale) oraz CRM**, stworzony z myślą o producentach muzycznych i twórcach. Głównym celem systemu jest automatyzacja wystawiania dokumentów (faktury, paragony, wyceny, WZ) oraz **ścisłe monitorowanie limitów przychodów** (np. dla działalności nierejestrowanej - NDG).

---

## 2. Architektura Techniczna
System oparty jest na nowoczesnym, lekkim stosie technologicznym:

*   **Backend:** Python 3 + Flask.
*   **Baza danych:** SQLite (zarządzana przez Flask-SQLAlchemy).
*   **Frontend:** Vanilla HTML5, CSS3 (zmienne CSS, Flexbox, Grid) oraz czysty JavaScript (SPA - Single Page Application).
*   **Generowanie dokumentów:** ReportLab (silnik PDF) + Pillow + qrcode (generowanie kodów QR przelewów).
*   **Integracje:** 
    *   **GUS / MF White List:** Automatyczne pobieranie danych kontrahentów po numerze NIP.
    *   **Discord Webhooks:** System powiadomień na kanały administracyjne, techniczne i dla wykonawców.

---

## 3. Kluczowe Funkcjonalności

### 📊 Dashboard (Panel Główny)
*   **Monitor Limitów (NDG Shield):** Wizualny pasek postępu pokazujący sumę przychodów w bieżącym okresie (miesiąc/kwartał) w stosunku do ustawionego limitu.
*   **System Alertów:** Automatyczne ostrzeżenia (kolor żółty/czerwony), gdy przychody zbliżają się do limitu ustawowego.
*   **Szybki Podgląd:** Tabela ostatnich 5 dokumentów z możliwością szybkiego pobrania PDF lub zmiany statusu płatności.

### 🛒 Moduł POS (Punkt Sprzedaży)
*   **Ujednolicony Interfejs:** Dwukolumnowy układ pozwalający na błyskawiczne wystawianie dokumentów.
*   **Obsługa Dokumentów:** Faktura bez VAT, Paragon (dla osób fizycznych), Wycena oraz WZ (Wydanie Zewnętrzne).
*   **Kafelkowy Wybór Usług:** Produkty podzielone na kategorie (np. Produkcja, Mix/Mastering), co pozwala na dodawanie pozycji jednym kliknięciem.
*   **Inteligentny Klient:** Możliwość wyboru klienta z bazy lub wpisania nowego NIP – system automatycznie uzupełni dane z rejestrów państwowych.
*   **Opcje Zaawansowane:** Przełącznik klauzuli o przeniesieniu praw autorskich oraz generowania kodu QR do płatności.

### 👥 CRM (Baza Klientów)
*   **Historia Wydatków:** Podgląd, ile dany klient łącznie wydał w naszej firmie.
*   **Archiwum Klienta:** Pełna lista dokumentów przypisanych do konkretnej osoby/firmy.
*   **Zarządzanie:** Edycja danych, dodawanie numerów telefonów, ID Discord oraz stron WWW.

### 🎹 Katalog Usług
*   Definiowanie domyślnych cen, kategorii oraz kolejności wyświetlania na kafelkach w POS.

### ⚙️ Ustawienia i Integracje
*   **Dane Sprzedawca:** Konfiguracja własnego NIP, numeru konta i adresu (używane w PDF).
*   **Konfiguracja Limitów:** Możliwość przełączania między limitem miesięcznym a kwartalnym.
*   **Webhooki Discord:**
    *   `ADMIN_WEBHOOK`: Powiadomienia o finansach (faktury, paragony).
    *   `EKIPA_WEBHOOK`: Powiadomienia o zleceniach technicznych (dokumenty WZ).
    *   `CONTRACTOR_WEBHOOK`: Automatyczne wysyłanie potwierdzeń projektów do podwykonawców.

---

## 4. Wygląd i UX (User Experience)
Aplikacja posiada nowoczesny, ciemny interfejs typu **Dark Mode** z akcentami kolorystycznymi:
- 🔵 **Niebieski (Primary):** Akcje główne, nawigacja.
- 🟢 **Zielony (Success):** Przycisk wystawiania, status "Opłacone".
- 🟡 **Żółty (Warning):** Ostrzeżenia o limitach, status "Oczekujące".
- 🔴 **Czerwony (Danger):** Krytyczne przekroczenie limitów, usuwanie.

**Struktura interfejsu:**
1.  **Sidebar (Lewo):** Logo, menu nawigacyjne oraz szybki podgląd limitu.
2.  **Top-bar (Góra):** Tytuł widoku i status połączenia.
3.  **Content (Środek):** Dynamicznie przełączane sekcje bez przeładowania strony (SPA).

---

## 5. Logika biznesowa dokumentów
System automatycznie nadaje numery dokumentom według schematu:
`TYP/ROK/MIESIĄC/KRÓTKI_ID_UUID` (np. `F/2026/4/A1B2C3D4`).

**Specjalne funkcje PDF:**
*   **QR Online:** Dokumenty zawierają kod QR, który po zeskanowaniu w aplikacji bankowej automatycznie wypełnia dane do przelewu.
*   **Prawa Autorskie:** Automatyczne dołączanie profesjonalnej klauzuli prawnej dotyczącej przeniesienia autorskich praw majątkowych do utworu.
*   **Konwersja:** Możliwość przekształcenia jednym kliknięciem "Wyceny" w "Fakturę" po akceptacji klienta.

---

### Status Techniczny:
*   **Gotowość:** Aplikacja w pełni funkcjonalna, gotowa do pracy lokalnej.
*   **Baza danych:** Plik `data/database.db`.
*   **Dokumenty:** Przechowywane fizycznie w `static/pdfs/`.
*   **Uruchamianie:** Skrypt `run.bat` (automatyzuje start serwera).
