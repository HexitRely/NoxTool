# 🚀 Wdrażanie NoxTools na Vercel (Gotowe od strzała)

Aplikacja **NoxTools** jest w pełni zautomatyzowana. Nie musisz uruchamiać żadnych skryptów po stronie bazy – system sam przygotuje tabelę i Twoje pierwsze konto przy pierwszym wejściu na stronę.

## 1. Wymagania Wstępne
- Konto na [Vercel](https://vercel.com).
- Baza **PostgreSQL** (np. [Supabase](https://supabase.com) lub [Neon.tech](https://neon.tech)).
- Kod wrzucony na GitHub.

## 2. Instrukcja w 3 krokach
1. **Wybierz Repozytorium**: Na Vercelu kliknij **Add New -> Project** i zaimportuj kod.
2. **Dodaj Zmienne Środowiskowe**: W zakładce **Environment Variables** dodaj:
   - `DATABASE_URL`: Link do Twojej bazy PostgreSQL (np. z Supabase).
   - `SECRET_KEY`: Dowolny losowy ciąg znaków (np. `twoje-sekretne-haslo-123`).
3. **Kliknij Deploy**: Gotowe!

## 3. Twoje Dane Dostępowe
Zaraz po wdrożeniu, przejdź pod swój adres `.vercel.app`. System sam założy konto Master Admin:

- **Login**: `admin`
- **Hasło**: `NoxTools2024!`

---
**💡 Porada:** Po pierwszym zalogowaniu wejdź w *Ustawienia -> Mój Profil* i zmień hasło na własne.

*Powered by NOX*
