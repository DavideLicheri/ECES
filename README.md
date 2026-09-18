# ECES — EURING Code Evolution System

**ISPRA - DG SINA** · [github.com/DavideLicheri/Semantic-EPE](https://github.com/DavideLicheri/Semantic-EPE)

[EURING](https://www.euring.org) è l'organizzazione scientifica che coordina l'inanellamento degli uccelli selvatici in Europa, raccogliendo dati standardizzati da oltre 40 paesi. Per lo scambio di questi dati EURING ha definito nel tempo un codice posizionale che ha subito quattro revisioni (1966, 1979, 2000, 2020), ciascuna con struttura, lunghezza e semantica dei campi proprie.

**ECES** nasce per gestire questa evoluzione: permette di confrontare le versioni del codice, mantenere una mappatura semantica cross-versione (EPE ASP), editare le definizioni dei campi in modo controllato e persistente, ed esporre le informazioni semantiche via API per strumenti AI.

---

## Architettura del sistema

```
React SPA (frontend)
        │
        │ fetch / axios
        ▼
FastAPI backend (porta 8000) ────► JSON files (SKOS-like)
        │                               euring_1966.json
        │                               euring_1979.json
        │                               euring_2000.json
        │                               euring_2020.json
        ▼
PostgreSQL (analytics)          Open WebUI / Ollama
                                        │
                                   Lizzy (qwen2.5:14b)
                                   AI assistant per
                                   interpretazione
                                   stringhe EURING
```

### Lizzy — assistente AI

**Lizzy** è un assistente AI in italiano, basato su `qwen2.5:14b` in Open WebUI/Ollama, che usa le API ECES per riconoscere, interpretare e convertire stringhe EURING senza tabelle hardcoded nel sistema. ECES è la sua unica fonte di verità per la semantica dei campi.

**Strumenti Open WebUI configurati per Lizzy:**

| Strumento | Funzione |
|-----------|----------|
| `eces_recognize` | Riconosce la versione di una stringa EURING |
| `eces_convert` | Converte tra versioni 1966/1979/2000/2020 |
| `eces_field_info` | Restituisce la semantica di un campo; con `code=XX` decodifica un singolo valore (lookup puntuale) |
| `eces_species_lookup` | Ricerca specie da CSV EURING locale (3628 specie, aggiornamento mensile) |
| `ispra_species_lookup` | Nome italiano ufficiale CNI-ISPRA via endpoint SPARQL |
| `eces_fenologia` | Conteggi storici EURING per specie+luogo+periodo dell'anno (fenologia: migrazione, svernamento, riproduzione), con dichiarazione degli schemi di inanellamento coinvolti |

---

## Funzionalità

- **Matrice EURING** — visualizzazione comparativa di tutti i campi nelle 4 versioni, con ordinamento EPE e identificazione dei campi aggiuntivi per versione
- **Editor Campi** — modifica interattiva delle proprietà dei campi (descrizione, tipo, posizione, lunghezza, dominio semantico, nome canonico cross-versione, valori ammessi con descrizioni, tipo semantico, sorgente, range)
- **Aggiunta e cancellazione campi** per singola versione
- **Riconoscimento automatico** della versione di una stringa EURING
- **Parsing stringa** — decomposizione campo per campo in italiano o inglese
- **Conversione semantica** tra versioni
- **Lookup puntuale** — decodifica di un singolo codice senza restituire l'intero dizionario (ottimizzato per place_code: 2052 voci)
- **Autenticazione JWT** con ruoli (user, matrix_editor, super_admin)
- **Persistenza SKOS** su file JSON con invalidazione cache
- **Analytics** su PostgreSQL (query log per super_admin)
- **Statistiche fenologiche Lizzy** — conteggi aggregati specie/luogo/pentade/schema, popolati da bootstrap storico [ISPRA RDF](https://dati.isprambiente.it/) (oltre 8,2 milioni di inanellamenti storici) e aggiornati dai dati organici correnti, con meccanismo anti-doppio-conteggio basato su impronte (schema+anello+data)

---

## Stack

| Livello | Tecnologie |
|---------|-----------|
| Backend | Python 3.10, FastAPI, Uvicorn |
| Frontend | React 18, TypeScript, Vite |
| Dati | JSON (SKOS-like), bcrypt auth |
| Analytics | PostgreSQL |
| AI | Ollama, Open WebUI, qwen2.5:14b |

---

## Avvio locale

### Backend

```bash
cd backend
pip install -r requirements.txt
PYTHONPATH=. python3 main.py
```

Disponibile su **http://localhost:8000** — Swagger UI: http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Disponibile su **http://localhost:3000**

---

## Struttura del progetto

```
├── backend/
│   ├── app/
│   │   ├── api/           # Endpoint FastAPI (euring_api.py, auth_api.py, analytics_api.py)
│   │   ├── auth/          # JWT + ruoli (get_current_active_user, require_matrix_edit_permission, require_super_admin)
│   │   ├── models/        # Modelli Pydantic (EuringVersion, FieldDefinition, ValidValuesType…)
│   │   ├── repositories/  # Persistenza JSON (SKOSRepository)
│   │   └── services/      # Business logic (SKOSManager, LookupTableService, RecognitionEngine…)
│   ├── data/
│   │   ├── auth/          # users.json
│   │   └── euring_versions/
│   │       └── versions/  # euring_{1966,1979,2000,2020}.json
│   ├── scripts/
│   │   └── import_euring_codes.py  # Import place codes / ringing schemes / circumstances da libreria euring
│   └── main.py
│
└── frontend/
    └── src/
        ├── components/
        │   ├── EuringMatrix.tsx           # Matrice comparativa (vista tabella + positionale)
        │   ├── PositionalMatrixEditor.tsx  # Editor campi con pannello laterale (struttura + semantica)
        │   ├── PositionalMatrix.tsx        # Visualizzazione posizionale interattiva
        │   └── ...
        └── services/
            └── api.ts                     # Client API tipizzato
```

---

## Versioni EURING supportate

| Versione | Formato | Campi | Note |
|----------|---------|-------|------|
| 1966 | Separato da spazi | 11 | Prima versione |
| 1979 | Posizionale fisso | ~30 | 78 caratteri |
| 2000 | Posizionale fisso | ~35 | 96 caratteri, standard EPE |
| 2020 | Pipe-delimited | 64 | Formato moderno, coordinate decimali |

---

## API principali

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `GET` | `/api/euring/versions` | Matrice campi × versioni (riferimento 2020) |
| `GET` | `/api/euring/versions/matrix` | Matrice campi × versioni (ordinamento EPE 2000) |
| `GET` | `/api/euring/field/{name}?version=2020` | Semantica completa di un campo |
| `GET` | `/api/euring/field/{name}/lookup?code=XX&version=2020` | Decodifica un singolo codice |
| `PUT` | `/api/euring/field/{name}?version=2020` | Aggiorna dati semantici di un campo |
| `POST` | `/api/euring/field/{name}/sync` | Sincronizza dati strutturali ↔ semantici |
| `PUT` | `/api/euring/versions/matrix/field` | Aggiorna proprietà strutturale di un campo |
| `POST` | `/api/euring/versions/matrix/field/add` | Aggiunge un campo a una versione |
| `DELETE` | `/api/euring/versions/matrix/field/remove` | Rimuove un campo da una versione |
| `POST` | `/api/euring/recognize` | Riconosce la versione di una stringa |
| `POST` | `/api/euring/parse` | Parsing campo per campo di una stringa |
| `POST` | `/api/euring/convert` | Conversione semantica tra versioni |
| `POST` | `/api/euring/reload` | Hot-reload dati JSON senza riavvio |
| `POST` | `/api/auth/login` | Login (restituisce JWT) |
| `GET` | `/api/auth/me` | Utente corrente |

---

## Modello semantico dei campi

`FieldDefinition` supporta la classificazione semantica dei valori ammessi tramite `valid_values_type`:

| Tipo | Descrizione | Esempio |
|------|-------------|---------|
| `enumeration` | Lista chiusa di codici con descrizione | sex, age, condition |
| `external_reference` | Lista esterna (place codes, ringing schemes) | place_code (2052 voci) |
| `free_numeric` | Valore numerico libero con range opzionale | wing_length, mass |
| `free_text` | Testo libero | notes |
| `free_alphanumeric` | Alfanumerico libero | ring_number |
| `computed` | Calcolato da altri campi | elapsed_time |

I dizionari `valid_values_descriptions` per place_code, current_place_code, ringing_scheme e circumstances vengono popolati tramite la libreria Python `euring` con lo script `backend/scripts/import_euring_codes.py`.

---

## Produzione (VM ISPRA)

```
Host:    <VM_IP>  (accesso via FortiClient VPN)
Utente:  <VM_USER>
Path:    /opt/eces/
Servizio: sudo systemctl restart eces
Health:  curl http://localhost:8000/api/euring/health
```

---

## Licenza

Uso interno ISPRA — sviluppato per l'analisi dei dati EURING.
