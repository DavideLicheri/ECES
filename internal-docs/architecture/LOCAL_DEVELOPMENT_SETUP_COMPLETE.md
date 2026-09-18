# ECES Local Development Setup - Complete

## Setup Completato ✅

Ho creato un ambiente di sviluppo locale completo per ECES con due opzioni:

### 1. Docker PostgreSQL (Raccomandato) 🐳

**Vantaggi:**
- Identico all'ambiente di produzione
- PostgreSQL completo con tutte le funzionalità analytics
- Isolamento completo
- Facile reset e cleanup

**Files Creati:**
- `docker-compose.yml` - Configurazione Docker con PostgreSQL 14
- `backend/Dockerfile.dev` - Container backend per sviluppo
- `backend/requirements.txt` - Dipendenze Python complete
- `setup_docker_development.sh` - Setup automatico Docker
- `test_docker_development.sh` - Test ambiente Docker
- `start_postgres_only.sh` - Avvia solo PostgreSQL
- `start_docker_dev.sh` - Avvia ambiente completo Docker
- `start_backend_with_docker_db.sh` - Backend locale + PostgreSQL Docker
- `stop_docker_dev.sh` - Ferma servizi Docker
- `reset_docker_dev.sh` - Reset completo ambiente

**Comandi:**
```bash
# Setup iniziale
./setup_docker_development.sh

# Test setup
./test_docker_development.sh

# Workflow sviluppo
./start_postgres_only.sh              # Terminal 1
./start_backend_with_docker_db.sh     # Terminal 2  
cd frontend && npm run dev             # Terminal 3
```

### 2. SQLite Local (Alternativa) 💾

**Vantaggi:**
- Nessuna dipendenza Docker
- Setup veloce
- Ideale per sviluppo semplice

**Files Creati:**
- `backend/app/database/schema.py` - Schema SQLite
- `backend/app/services/database_service_local.py` - Servizio database SQLite
- `backend/app/services/usage_logger_local.py` - Logger semplificato
- `setup_local_development.sh` - Setup SQLite
- `test_local_development.sh` - Test ambiente SQLite

## Configurazione Ibrida Intelligente 🧠

Il sistema è configurato per scegliere automaticamente il database giusto:

```python
# In analytics_api.py
import os
if os.getenv("DATABASE_URL", "").startswith("postgresql://"):
    from ..services.database_service import database_service      # PostgreSQL
    from ..services.usage_logger import usage_logger
else:
    from ..services.database_service_local import database_service  # SQLite
    from ..services.usage_logger_local import usage_logger
```

## Accesso Applicazioni 🌐

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000  
- **API Docs**: http://localhost:8000/docs
- **Database (Docker)**: postgresql://eces_user:eces_dev_password@localhost:5432/eces_analytics
- **Database (SQLite)**: `backend/eces_local.db`

## Credenziali Sviluppo 🔑

- Vedi gestore password (rimosso da qui il 18/09/2026 dopo revisione di sicurezza — era esposto in chiaro su repository pubblico)
- **Ruolo**: Super Admin

## Workflow Raccomandato 🎯

### Per Sviluppo Normale:
1. `./start_postgres_only.sh` - Avvia PostgreSQL Docker
2. `./start_backend_with_docker_db.sh` - Backend locale + DB Docker
3. `cd frontend && npm run dev` - Frontend locale

### Per Sviluppo Semplice (senza Docker):
1. `./setup_local_development.sh` - Setup SQLite
2. `./start_dev_environment.sh` - Tutto locale

### Per Deploy Produzione:
1. Sviluppa e testa localmente
2. `./deploy_to_production.sh` - Deploy su ISPRA

## Compatibilità Database 🔄

**Differenze Gestite:**
- Sintassi SQL (PostgreSQL vs SQLite)
- Tipi di dati (UUID, JSON, TIMESTAMP)
- Funzioni aggregate e matematiche
- Parametri query ($1 vs ?)

**Funzionalità Identiche:**
- API endpoints
- Autenticazione
- Analytics dashboard
- Logging utenti
- Gestione sessioni

## Prossimi Passi 📋

### Se hai Docker:
```bash
./setup_docker_development.sh
./test_docker_development.sh
./start_postgres_only.sh
```

### Se non hai Docker:
```bash
./setup_local_development.sh
./test_local_development.sh
./start_dev_environment.sh
```

### Installare Docker (raccomandato):
1. Scarica Docker Desktop: https://www.docker.com/products/docker-desktop
2. Installa e avvia Docker Desktop
3. Esegui `./setup_docker_development.sh`

## Files di Configurazione 📁

### Docker Environment:
- `backend/.env.docker` - Configurazione backend Docker
- `frontend/.env.docker` - Configurazione frontend Docker

### Local Environment:
- `backend/.env.local` - Configurazione backend SQLite
- `frontend/.env.local` - Configurazione frontend locale

## Troubleshooting 🔧

### Docker non disponibile:
- Usa setup SQLite: `./setup_local_development.sh`

### Porta 5432 occupata:
- Cambia porta in `docker-compose.yml`
- Oppure ferma altri servizi PostgreSQL

### Errori import backend:
- Controlla variabile `DATABASE_URL`
- Verifica dipendenze: `pip install -r backend/requirements.txt`

### Frontend non si connette:
- Verifica backend su http://localhost:8000
- Controlla CORS settings in backend

## Vantaggi Setup Completo ✨

1. **Flessibilità**: Docker o SQLite a scelta
2. **Compatibilità**: Identico a produzione (Docker)
3. **Semplicità**: Nessun setup complesso (SQLite)
4. **Isolamento**: Database separato per sviluppo
5. **Reset Facile**: Script di reset automatici
6. **Testing**: Script di test automatici
7. **Deploy**: Script deploy produzione integrato

## Stato Attuale 📊

✅ **Completato:**
- Setup Docker completo
- Setup SQLite alternativo  
- Configurazione ibrida intelligente
- Script di gestione automatici
- Documentazione completa
- Test automatici

⏳ **Da Fare:**
- Installare Docker (opzionale)
- Testare ambiente scelto
- Iniziare sviluppo

🎉 **L'ambiente di sviluppo locale è pronto!**