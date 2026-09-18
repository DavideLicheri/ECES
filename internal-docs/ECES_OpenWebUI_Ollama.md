# ECES AI Bot — Caratteristiche del Progetto e Stato dell'Installazione

> **Ambiente:** VM ISPRA `epepostgresdb` (<VM_IP>) — Ubuntu 22.04 LTS  
> **Stack:** Open WebUI + Ollama + ECES FastAPI + PostgreSQL  
> **Aggiornato:** maggio 2026

---

## 1. Cos'è ECES

**ECES (EURING Code Evaluation System)** è un sistema backend FastAPI per il riconoscimento automatico e la conversione semantica dei codici EURING utilizzati nell'inanellamento ornitologico scientifico europeo. Gestisce quattro versioni dello standard (1966, 1979, 2000, 2020) e le API richiedono autenticazione **JWT**.

Il bot AI si compone di tre strati:

```
[Utente — browser su http://<VM_IP>:3000]
              │
              ▼
    [Open WebUI — Docker :3000]
              │  Tool call Python
              ▼
    [Ollama — host :11434]
    [modello: qwen2.5:3b → 14b]
              │  HTTP + Bearer JWT
              ▼
    [ECES FastAPI — host :8000]
              │
              ▼
    [PostgreSQL :5432 — eces_analytics]
```

---

## 2. Infrastruttura attuale

| Componente          | Stato      | Dettagli                                              |
|---------------------|------------|-------------------------------------------------------|
| Ubuntu 22.04 LTS    | ✅ Attivo  | VM ISPRA, 7.8 GB RAM *(ampliamento a 16 GB richiesto)* |
| Docker 29.5.0       | ✅ Attivo  | Con Docker Compose plugin                            |
| Ollama              | ✅ Attivo  | CPU-only, porta 11434 su `0.0.0.0`                   |
| qwen2.5:3b          | ✅ Caricato | Modello temporaneo → verrà sostituito con **14b**     |
| Open WebUI          | ✅ Attivo  | Docker container, porta 3000                         |
| ECES Backend FastAPI| ✅ Attivo  | `/opt/eces/`, porta 8000, 4 workers, utente `eces`   |
| PostgreSQL ECES     | ✅ Attivo  | DB: `eces_analytics`, user: `eces_user`              |

### Percorsi chiave sulla VM

| File / Directory                                            | Contenuto                        |
|-------------------------------------------------------------|----------------------------------|
| `/opt/eces/`                                                | Installazione backend ECES       |
| `/opt/eces/backend/main.py`                                 | Entry point FastAPI (CORS, auth) |
| `/opt/eces/venv/`                                           | Virtualenv Python                |
| `/opt/eces/ispra_config.env`                                | Variabili di configurazione ECES |
| `/home/<VM_USER>/eces-ai/docker-compose.yml`           | Compose Open WebUI               |
| `/etc/systemd/system/ollama.service.d/override.conf`        | Override Ollama systemd          |

---

## 3. Configurazione Open WebUI

| Parametro              | Valore                                   |
|------------------------|------------------------------------------|
| URL accesso            | `http://<VM_IP>:3000`              |
| Connessione Ollama     | `http://172.17.0.1:11434` *(gateway Docker bridge)* |
| Autenticazione Ollama  | `Bearer ollama-local`                    |
| Modello custom         | **ECES Bot** (basato su qwen2.5:3b)      |
| Strumenti configurati  | `eces_recognize`, `eces_convert`         |
| System prompt          | Configurato per versioni EURING 1966/1979/2000/2020 |

> **Nota networking:** Open WebUI gira in Docker. Per raggiungere i servizi sull'host (Ollama :11434, ECES :8000) usa l'IP del gateway bridge Docker: `172.17.0.1` invece di `localhost`.

---

## 4. Autenticazione ECES API (JWT)

Le API ECES richiedono un token JWT ottenuto così:

```http
POST http://172.17.0.1:8000/api/auth/login
Content-Type: application/json

{"username": "admin", "password": "admin"}
```

```json
{"access_token": "<JWT>", "expires_in": 28800}
```

Il token dura **8 ore**. Tutte le chiamate successive richiedono:

```http
Authorization: Bearer <JWT>
```

### Schema caching JWT (da implementare)

```python
class Tools:
    _token = None
    _token_expiry = 0

    def _get_token(self) -> str:
        import time, requests
        if not self._token or time.time() > self._token_expiry - 300:
            r = requests.post(
                "http://172.17.0.1:8000/api/auth/login",
                json={"username": "admin", "password": "admin"},
                timeout=10
            )
            data = r.json()
            self._token = data["access_token"]
            self._token_expiry = time.time() + data["expires_in"]
        return self._token
```

> Il token viene rinnovato automaticamente 5 minuti prima della scadenza. Attualmente ogni chiamata esegue un nuovo login (funzionale ma inefficiente).

---

## 5. Endpoint ECES disponibili per gli strumenti

**Base URL (dall'interno Docker):** `http://172.17.0.1:8000`  
**Base URL (dall'host):** `http://localhost:8000` o `http://<VM_IP>:8000`

| Metodo | Endpoint                        | Strumento Open WebUI    |
|--------|---------------------------------|-------------------------|
| `POST` | `/api/auth/login`               | *(auth interna)*        |
| `POST` | `/api/euring/recognize`         | `eces_recognize` ✅     |
| `POST` | `/api/euring/convert`           | `eces_convert` ✅       |
| `POST` | `/api/euring/batch/recognize`   | `eces_batch_recognize` ⚠️ *da aggiungere* |
| `POST` | `/api/euring/batch/convert`     | *(futuro)*              |
| `GET`  | `/api/euring/versions`          | *(info)*                |
| `GET`  | `/api/euring/health`            | *(monitoring)*          |

---

## 6. Problemi aperti

### 6.1 Tool calling instabile — priorità ALTA

Il modello `qwen2.5:3b` attiva gli strumenti ECES solo se esplicitamente richiesto con frasi come *"usa lo strumento eces_recognize"*. Con domande naturali risponde a memoria.

- **Causa:** modello 3B troppo piccolo per tool calling autonomo affidabile
- **Soluzione primaria:** upgrade a `qwen2.5:14b` quando arrivano i 16 GB RAM
  ```bash
  ollama pull qwen2.5:14b
  # poi aggiornare il modello base in "ECES Bot" su Open WebUI
  ```
- **Soluzione temporanea:** rafforzare il system prompt con regole RULE assolute

### 6.2 Token JWT non cachato — priorità ALTA

Gli strumenti eseguono un login ad ogni chiamata. Implementare il caching (schema in §4).

### 6.3 Strumento batch mancante — priorità ALTA

Manca `eces_batch_recognize` per elaborare fino a 1000 stringhe in una sola chiamata:

```python
# Endpoint da chiamare:
POST http://172.17.0.1:8000/api/euring/batch/recognize
Body: {"strings": ["stringa1", "stringa2", ...]}
```

### 6.4 System prompt da arricchire — priorità MEDIA

Il system prompt attuale copre le basi EURING ma manca di:

- Tabella codici specie EURING (almeno specie comuni italiane/europee)
- Tabella codici età: `1`=pullus, `2`=juvenile, `3`=adult, ecc.
- Tabella codici sesso: `1`=M, `2`=F, `3`=?, `4`=intersex, `9`=unknown
- Tabella modalità di cattura (mist net, trap, ecc.)
- 4 esempi di stringhe reali (una per versione)
- Regola esplicita: **SEMPRE chiamare `eces_recognize` prima di analizzare**

### 6.5 CORS non configurato per Open WebUI — priorità MEDIA

Verificare `/opt/eces/backend/main.py` e aggiungere le origini mancanti:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://<VM_IP>:3000",  # Open WebUI IP pubblico VM
        "http://172.17.0.1:3000",     # Docker bridge gateway
        "http://localhost:3000",       # locale
        "http://localhost:5173",       # Vite dev (se usato)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

> Modifiche a `/opt/eces/` richiedono `sudo` (ECES gira come utente `eces`, non root).

### 6.6 Avvio automatico al reboot — priorità BASSA

Creare un servizio systemd o script cron che al riavvio della VM:
1. Attende che ECES (:8000) e Ollama (:11434) siano raggiungibili
2. Avvia il container Open WebUI via `docker compose up -d`

---

## 7. Architettura di rete completa

| Servizio            | Porta  | Binding    | Accessibile da Docker come  |
|---------------------|--------|------------|-----------------------------|
| ECES Backend FastAPI| 8000   | 0.0.0.0    | `http://172.17.0.1:8000`    |
| PostgreSQL          | 5432   | localhost  | *(non esposto a Docker)*    |
| Ollama              | 11434  | 0.0.0.0    | `http://172.17.0.1:11434`   |
| Open WebUI          | 3000   | 0.0.0.0    | `http://<VM_IP>:3000` |

**Docker Compose:** `/home/<VM_USER>/eces-ai/docker-compose.yml`  
**Ollama systemd override:** `/etc/systemd/system/ollama.service.d/override.conf`

---

## 8. Versioni EURING gestite da ECES

| Versione | Formato           | Lunghezza | Separatore | Caratteristica principale     |
|----------|-------------------|-----------|------------|-------------------------------|
| **1966** | Spazi             | ~55 char  | Spazio     | Coordinate in gradi/minuti    |
| **1979** | Fisso concatenato | 78 char   | Nessuno    | Prima codifica compatta        |
| **2000** | Fisso codificato  | 96 char   | Nessuno    | Campi multi-byte codificati   |
| **2020** | Pipe-delimited    | ~91 char  | `\|`       | Coordinate decimali WGS84     |

Conversioni possibili: **12 combinazioni** (4 versioni × 3 target). Le conversioni sono **semantiche**: preservano il significato dei campi, non ricodificano meccanicamente.

---

## 9. Roadmap upgrade

| Priorità | Task                                         | Trigger                    |
|----------|----------------------------------------------|----------------------------|
| 🔴 Alta  | Implementare caching JWT negli strumenti     | Subito                     |
| 🔴 Alta  | Aggiungere strumento `eces_batch_recognize`  | Subito                     |
| 🔴 Alta  | Upgrade modello → `qwen2.5:14b`              | Quando disponibili 16 GB RAM |
| 🟡 Media | Arricchire system prompt EURING              | Subito                     |
| 🟡 Media | Fix CORS in `/opt/eces/backend/main.py`      | Subito                     |
| 🟢 Bassa | Script avvio automatico al reboot            | Prima del go-live           |
| 🟢 Bassa | Cambiare credenziali ECES API (admin/admin)  | Prima del go-live           |

---

## 10. Note operative

- **Accesso VM:** solo via **FortiClient VPN ISPRA** o rete interna
- **Utente sudo:** `<VM_USER>`
- **Servizio ECES:** gira come utente `eces` → modifiche a `/opt/eces/` richiedono `sudo`
- **Repository GitHub:** `https://github.com/DavideLicheri/Semantic-EPE` *(privato)*
- **Credenziali ECES API:** `admin` / `admin` — ⚠️ **da cambiare prima del go-live**
- **PostgreSQL:** user `eces_user`, password: vedi gestore password (ruotata il 14/08/2026 dopo audit di sicurezza — era esposta in chiaro su repository pubblico), DB `eces_analytics`
- **Lingua del bot:** italiano per default (configurato in system prompt)

---

*Documento generato il 2026-05-17 — basato su: progetto ECES (`/Users/davidelicheri/AI/`) + documento di installazione `ECES_ClaudeCode_Task4Ollama.pdf`.*
