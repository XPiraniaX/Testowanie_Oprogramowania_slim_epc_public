# Sprawozdanie z testowania — Simple EPC Simulator

## 1. Wstęp

Przedmiotem testów jest **Simple EPC Simulator** — minimalny symulator rdzenia
sieci LTE (*Evolved Packet Core*). Aplikacja to usługa HTTP zbudowana na
**FastAPI + SQLite**, która odwzorowuje podstawowe operacje rdzenia sieci:

- dołączanie/odłączanie urządzeń **UE** (*User Equipment*, ID `1–100`),
- zarządzanie **bearerami** (kanałami nośnymi, ID `1–9`),
- uruchamianie/zatrzymywanie **symulowanego ruchu** (TCP/UDP, w `Mbps`/`kbps`/`bps`),
- odczyt statystyk przepustowości,
- agregację statystyk oraz reset stanu.

Ruch nie jest realny — w tle działa korutyna `asyncio`, która co sekundę
zwiększa liczniki bajtów (`bytes_tx`, `bytes_rx`). Cały stan trwały przechowywany
jest w jednej tabeli SQLite (`ue_state`) jako dokument JSON.

Celem prac było **rzetelne pokrycie testami wszystkich warstw aplikacji** —
od walidacji modeli, przez logikę repozytorium i handlerów, aż po kontrakt HTTP —
ze szczególnym naciskiem na **przypadki brzegowe i graniczne** (a nie tylko
„happy path").

## 2. Cel i zakres testów

Zakres testów zaprojektowano zgodnie z podejściem **piramidy testów** opisanym
w `TESTING_SCOPE_GUIDE.md` — od najszybszych i najbardziej izolowanych testów
jednostkowych po wolniejsze testy integracyjne:

| # | Warstwa                              | Plik | Co weryfikuje |
|---|--------------------------------------|------|---------------|
| 1 | Modele (Pydantic)                    | `tests/test_models.py` | walidacja pól, konwersja jednostek, normalizacja, serializacja |
| 2 | Repozytorium (SQLite)                | `tests/test_epc_repository.py` | trwałość stanu, niezmienniki domenowe, obsługa błędów |
| 3 | Logika handlerów (mocki)             | `tests/test_endpoint_unit.py` | gałęzie sukcesu/błędu, mapowanie `ValueError → HTTP 400`, agregacja |
| 4 | Kontrakt API (`TestClient`)          | `tests/test_api_contract.py` | metody/ścieżki HTTP, kody `200/400/422`, kształt JSON, routing |
| 5 | Generator ruchu (asyncio)(DODATKOWE) | `tests/test_traffic_manager.py` | strażniki `start`, `stop/stop_all`, singleton, realna pętla w tle |
| 6 | Kompozycja aplikacji (DODATKOWE)     | `tests/test_app_lifecycle.py` | metadane FastAPI, hook `shutdown` |

Łącznie: **173 testy**, wszystkie przechodzą.

| Plik | Liczba przypadków |
|------|------------------:|
| `test_models.py` | 49 |
| `test_api_contract.py` | 45 |
| `test_endpoint_unit.py` | 44 |
| `test_epc_repository.py` | 22 |
| `test_traffic_manager.py` | 11 |
| `test_app_lifecycle.py` | 2 |
| **Razem** | **173** |

## 3.Sposób uruchomienia

Uruchomienie:

```powershell
py -m pytest -v
```

## 4. Szczegółowy opis warstw testowych

### 4.1 Modele (`test_models.py`)

Weryfikacja kontraktów danych Pydantic:

- **Zakresy ID** — wartości graniczne `ue_id ∈ {1, 100}`, `bearer_id ∈ {1, 9}`
  są akceptowane; wartości spoza zakresu (`0`, `101`, `-1`, `10`) są odrzucane.
- **Konwersja przepustowości** do kanonicznego `target_bps` (`Mbps→·10⁶`,
  `kbps→·10³`, `bps→·1`) oraz reguła „dokładnie jedna jednostka".
- **Walidacja protokołu** — dozwolone tylko `tcp`/`udp` (wzorzec, wielkość liter ma znaczenie).
- **Przypadki brzegowe (dodane):**
  - koercja typów: `"5"` → `5`, ale `1.5`, `"5.5"`, `None`, `"abc"` → błąd walidacji,
  - throughput zerowy/ujemny/ułamkowy (patrz rozdział 5),
  - domyślne wartości `BearerConfig` i `ThroughputStats`,
  - **round-trip JSON** `UEState` — klucze słownika `int` przeżywają serializację
    do JSON (gdzie stają się stringami) i wracają jako `int`. To kluczowy kontrakt,
    na którym opiera się warstwa repozytorium.

### 4.2 Repozytorium (`test_epc_repository.py`)

Weryfikacja trwałości i niezmienników domenowych na realnym SQLite:

- pełny cykl `attach → get → list → detach`,
- automatyczne tworzenie domyślnego bearera `9` i **zakaz jego usuwania**,
- odrzucanie duplikatów (UE, bearer) oraz operacji na nieistniejących encjach,
- trwałość `update_bearer` / `update_stats` (zapis i ponowny odczyt z dysku),
- reset stanu.
- **Przypadki brzegowe (dodane):** operacje na pustej bazie, `save_ue`
  (overwrite/insert), uszkodzony JSON w bazie, współdzielenie jednego pliku
  przez dwa repozytoria, dodanie wszystkich bearerów `1–8`, fallback ścieżki
  do zmiennej `EPC_DB_PATH`, kolejność sprawdzeń przy usuwaniu bearera `9`.

### 4.3 Logika handlerów (`test_endpoint_unit.py`)

Testy jednostkowe funkcji-handlerów wywoływanych bezpośrednio, z w pełni
zamockowanym repozytorium (`MagicMock`) i atrapą menedżera ruchu. Pokrywają:

- gałęzie sukcesu i błędu każdego endpointu,
- spójne **mapowanie `ValueError → HTTPException(400)`**,
- decyzje agregacyjne w `/ues/stats` (wszystkie UE / pojedyncze / z detalami),
- obliczanie przepustowości z liczników i czasu (w tym ochrona przed dzieleniem
  przez zero przy `duration == 0`).
- **Gałęzie dodane:** użycie bieżącego czasu vs `last_update_ts` gdy ruch
  aktywny, brak nadpisywania istniejących statystyk przy ponownym starcie,
  brak wywołania `stop` gdy ruch nie działa, agregacja detali dla wielu UE.

### 4.4 Kontrakt API (`test_api_contract.py`)

Testy end-to-end przez `TestClient` — sprawdzają realne wpięcie tras, kody
statusów i kształt odpowiedzi JSON:

- ścieżki „szczęśliwe" i pełne przejścia stanu
  (`attach → add → start → read → stop → detach`),
- rozróżnienie `422` (walidacja żądania) vs `400` (reguły domenowe),
- specyfika trasy `/ues/stats` vs `/ues/{ue_id}`,
- reset przywracający czysty stan.
- **Przypadki brzegowe (dodane):** `405` (niedozwolona metoda), `404`
  (nieznana trasa), `422` dla nie-liczbowych parametrów ścieżki, błędny JSON
  w body, dostępność `/openapi.json`, `/docs`, `/redoc`, podwójny start ruchu,
  agregacja wielu UE, idempotentny reset oraz zachowania throughputu zero/ujemny.

### 4.5 Generator ruchu (`test_traffic_manager.py`)

Warstwa **wcześniej w ogóle nietestowana**. Pokrycie obejmuje:

- strażniki `start()` — wyjątek przy już działającym ruchu oraz przy braku
  konfiguracji bearera (brak protokołu / zerowa lub brakująca przepustowość),
- `stop()` / `stop_all()` — anulowanie `Future` i czyszczenie mapy zadań,
- `is_running()` oraz singleton `get_traffic_manager()`,
- **test integracyjny `@pytest.mark.slow`** uruchamiający realną pętlę `asyncio`
  w wątku tła i sprawdzający, że liczniki bajtów faktycznie rosną, a `bytes_tx`
  i `bytes_rx` przyrastają symetrycznie (UL = DL).

W szybkich testach jednostkowych planowanie korutyny jest podmieniane
(monkeypatch na `run_coroutine_threadsafe`), aby nie uruchamiać realnej pętli.

### 4.6 Kompozycja aplikacji (`test_app_lifecycle.py`)

- poprawne metadane aplikacji FastAPI i wpięcie routera (obecność tras),
- hook `shutdown` wywołujący `stop_all()` na menedżerze ruchu.

## 5. Ciekawe znaleziska (zachowania graniczne i potencjalne usterki)

Testy brzegowe ujawniły kilka **nieoczywistych zachowań** aplikacji. Nie są to
testy, które „naprawiają" kod — celowo **dokumentują obecny stan**, by ułatwić
ewentualną decyzję o poprawce.

1. **Błędny `bearer_id` w repozytorium rzuca `ValidationError`, a nie `ValueError`.**
   `EPCRepository.add_bearer(ue, 10)` buduje wewnętrznie `BearerConfig`, więc
   wartość spoza zakresu `1–9` powoduje **Pydantic `ValidationError`** — a ten
   typ **nie jest** mapowany przez warstwę API na `400`. To realna luka:
   przy bezpośrednim wywołaniu repozytorium z niepoprawnym ID zachowanie różni
   się od reszty błędów domenowych. (test:
   `test_add_bearer_out_of_range_raises_validation_error_not_value_error`)

2. **Parametry ścieżki nie są walidowane zakresowo.**
   W body żądania `ue_id` poza `1–100` daje `422`, ale w ścieżce
   (`GET /ues/99999`) ten sam warunek **nie** jest sprawdzany — żądanie dociera
   do repozytorium i wraca jako `400 "UE not found"`. Niespójność walidacji
   body vs path. (testy `test_out_of_range_ue_path_param_*`)

3. **Brak dolnej granicy przepustowości — wartości zerowe i ujemne.**
   Model `StartTrafficRequest` akceptuje `bps=0` (zwraca `target_bps == 0`)
   oraz wartości **ujemne** (`bps=-100` → `-100`). Co więcej:
   - na poziomie API **zero** jest odrzucane dopiero przez generator ruchu jako
     `400 "Bearer not configured for traffic"` (bo `0` jest „fałszywe"),
   - **ujemna** wartość przechodzi (jest „prawdziwa") i ruch startuje z `target_bps < 0`.

   To pokazuje brak walidacji sensowności wartości na poziomie modelu.

4. **Konwersja jednostek obcina, nie zaokrągla.**
   `kbps=1.2345 → 1234`, `Mbps=0.0000004 → 0`. Bardzo małe wartości „znikają"
   do zera. Zachowanie wynika z `int(...)` (truncacja w stronę zera).

5. **Reguła „dokładnie jedna jednostka" liczy `0` jako podaną wartość.**
   `bps=0` razem z `kbps=5` to dla walidatora „dwie wartości" → błąd. Logiczne,
   ale nieoczywiste (`0` to nie „brak").

6. **Stan ruchu jest tylko w pamięci.**
   Mapa działających zadań (`tasks`) nie jest utrwalana. Po restarcie bearer
   może mieć `active=True` w SQLite, choć żadna korutyna już nie działa.
   Testy menedżera ruchu odzwierciedlają tę separację (stan trwały w bazie,
   stan runtime w pamięci).

7. **Singleton menedżera ruchu zatrzymuje pierwsze repozytorium.**
   `get_traffic_manager()` tworzy instancję raz; kolejne wywołania z innym
   repozytorium i tak zwracają pierwszą instancję (z pierwotnym repo). Może to
   zaskoczyć przy współistnieniu wielu repozytoriów. (test
   `test_get_traffic_manager_is_a_singleton`)

## 6. Poprawa symulatora (`epc_poprawione/`)

Oprócz samych testów przygotowaliśmy **propozycje poprawek** błędów i
niespójności wykrytych podczas testowania. Umieściliśmy je w osobnym katalogu
`epc_poprawione/`, który zawiera kopie modułów `models.py`, `db.py`,
`traffic.py` i `api.py` z naniesionymi zmianami.

katalog `epc_poprawione/` ma charakter wyłącznie
**informacyjny** — nie jest częścią uruchamianej aplikacji ani zestawu
testów (świadomie nie objęliśmy go testami). Służy pokazaniu prowadzącemu,
 *gdzie* leży problem i *jak* proponujemy go naprawić. Każde miejsce zmiany
 oznaczyliśmy komentarzem `# POPRAWIONE`.

Mapowanie poprawek na znaleziska z sekcji 5:

| Plik | Znalezisko | Proponowana poprawka |
|------|-----------|----------------------|
| `db.py` | #1 (`ValidationError` zamiast `ValueError`) | jawna walidacja zakresu `bearer_id` (1–9) w `add_bearer` → `ValueError` mapowany na `400` |
| `api.py` | #2 (parametry ścieżki bez walidacji) | `Path(ge=…, le=…)` na `ue_id`/`bearer_id` → niepoprawne ID daje `422` zamiast `400 "UE not found"` |
| `models.py` | #3, #4, #5 (brak dolnej granicy przepustowości) | `gt=0` na `Mbps/kbps/bps`, odrzucanie `NaN/inf` oraz wartości „znikających” do zera; `strict=True` na polach ID |
| `traffic.py` | #6 (stan runtime vs trwały) | pętla generatora przerywa się po `detach`/usunięciu bearera, sprzątanie zakończonych zadań, twardszy strażnik konfiguracji bearera |
| `api.py` | kolejność zapisu stanu w `start_traffic` | `tm.start()` wykonywane przed utrwaleniem `active=True`; przy błędzie bearer nie zostaje `active`; `detach_ue` zatrzymuje powiązane zadania |

Ponieważ część poprawek **zmienia zachowanie** udokumentowane przez istniejące
testy (np. `strict=True` odrzuca string `"5"` jako `ue_id`, a `gt=0` odrzuca
`bps=0` i wartości ujemne), ewentualne wdrożenie tych zmian do `epc/`
wymagałoby aktualizacji odpowiednich przypadków w `tests/test_models.py`.

## 7. Podsumowanie

Aplikacja została pokryta **173 testami** w sześciu komplementarnych warstwach —
od walidacji modeli po realny test integracyjny pętli ruchu. Pokrycie wykracza
poza scenariusze podstawowe: świadomie przetestowano wartości graniczne,
niepoprawne dane wejściowe, sytuacje wyścigu i nieoczywiste konwersje.

Najważniejsze wnioski:

- rdzeń logiki (cykl życia UE/bearerów, agregacja statystyk, mapowanie błędów)
  działa zgodnie z oczekiwaniami i jest dobrze udokumentowany testami;
- ujawniono kilka **niespójności walidacji** (path vs body, `ValidationError`
  vs `ValueError`) oraz **brak walidacji sensowności przepustowości**
  (zero/ujemne/mikro-wartości) — to dobrzy kandydaci do poprawek w kodzie
  produkcyjnym;
- wcześniej nietestowany moduł `traffic.py` został pokryty zarówno szybkimi
  testami jednostkowymi, jak i testem integracyjnym realnej pętli `asyncio`.

Wszystkie testy przechodzą, są deterministyczne i izolowane, co daje solidną
podstawę do dalszego rozwoju aplikacji oraz refaktoryzacji bez ryzyka regresji.