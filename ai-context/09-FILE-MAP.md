# Mappa File Progetto ECES

## Struttura Generale

```
eces/
├── frontend/          # React TypeScript application
├── backend/           # FastAPI Python application
├── docs/              # Documentazione
├── ai-context/        # Documentazione per AI agents
├── data/              # Dati autenticazione
└── README.md          # Documentazione principale
```

## Frontend (`frontend/`)

### Entry Points
- **`src/main.tsx`**: Entry point applicazione React
- **`src/App.tsx`**: Componente root, gestione routing e auth
- **`index.html`**: HTML template

### Components (`src/components/`)

#### Core Panels
- **`RecognitionPanel.tsx`** + `.css`: Riconoscimento versione EURING
- **`ConversionPanel.tsx`** + `.css`: Conversione tra versioni
- **`StringNavigator.tsx`** + `.css`: Navigazione batch stringhe
- **`EuringMatrix.tsx`** + `.css`: Matrice comparativa versioni
- **`DomainPanel.tsx`** + `.css`: Analisi domini semantici

#### Domain Analysis
- **`DomainEvolutionTimeline.tsx`** + `.css`: Timeline evoluzione domini
- **`DomainEvolutionCharts.tsx`** + `.css`: Grafici evoluzione
- **`DomainComparison.tsx`** + `.css`: Confronto versioni per dominio

#### Authentication
- **`Login.tsx`** + `.css`: Form login
- **`Register.tsx`** + `.css`: Form registrazione
- **`UserProfile.tsx`** + `.css`: Profilo utente
- **`UserManagement.tsx`** + `.css`: Gestione utenti (super_admin)

#### Analytics
- **`Analytics.tsx`** + `.css`: Dashboard analytics (super_admin)

#### UI Components
- **`ResultsPanel.tsx`**: Visualizzazione risultati generici
- **`SemanticDomains.css`**: Stili domini semantici
- **`ui/Select.tsx`**: Componente select custom

### Services (`src/services/`)
- **`api.ts`**: Client API EURING (EuringAPI class)
  - `recognizeVersion()`
  - `convertString()`
  - `parseEuringString()`
  - `parseEuringStringsBatch()`
  - `getVersionsMatrix()`
  - `getDomainEvolution()`
  - `updateMatrixField()`
  - `getLookupTable()`

- **`auth.ts`**: Servizio autenticazione (AuthService class)
  - `login()`
  - `register()`
  - `logout()`
  - `getCurrentUser()`
  - `isAuthenticated()`
  - `changePassword()`

### Types (`src/types/`)
- **`euring-types.ts`**: TypeScript types per EURING
  - `RecognitionResult`
  - `ConversionResult`
  - `ParseResult`
  - `MatrixData`
  - `DomainEvolution`
  - `User`

### Utils (`src/utils/`)
- **`semanticDomains.ts`**: Definizioni e utility domini semantici
  - `SemanticDomain` enum
  - `getDomainInfo()`
  - `getDomainColor()`
  - `getDomainIcon()`

### i18n (`src/i18n/`)
⚠️ **Non attivo** - Sistema presente ma non utilizzato
- **`index.ts`**: Servizio i18n
- **`translations/it.ts`**: Traduzioni italiane
- **`translations/en.ts`**: Traduzioni inglesi

### Hooks (`src/hooks/`)
- **`useTranslation.ts`**: Hook i18n (non usato)

### Assets (`src/assets/`)
- **`images/epeLogo.jpg`**: Logo EPE

### Configuration
- **`vite.config.ts`**: Configurazione Vite
- **`tsconfig.json`**: Configurazione TypeScript
- **`package.json`**: Dipendenze e scripts
- **`.env.development`**: Variabili ambiente dev
- **`.env.production`**: Variabili ambiente prod

## Backend (`backend/`)

### Entry Point
- **`main.py`**: Applicazione FastAPI principale
  - Configurazione CORS
  - Mount routers
  - Startup/shutdown events

### API Endpoints (`app/api/`)
- **`euring_api.py`**: Endpoint EURING (principale)
  - `/api/euring/recognize` - POST
  - `/api/euring/convert` - POST
  - `/api/euring/parse` - POST
  - `/api/euring/parse/batch` - POST
  - `/api/euring/versions/matrix` - GET
  - `/api/euring/domain/evolution/{domain}` - GET
  - `/api/euring/matrix/field/update` - POST
  - `/api/euring/lookup/{version}/{field}` - GET

- **`auth_api.py`**: Endpoint autenticazione
  - `/api/auth/register` - POST
  - `/api/auth/login` - POST
  - `/api/auth/me` - GET
  - `/api/auth/change-password` - POST
  - `/api/auth/users` - GET (super_admin)
  - `/api/auth/users/{id}` - PUT (super_admin)

- **`analytics_api.py`**: Endpoint analytics (super_admin)
  - `/api/analytics/queries` - GET
  - `/api/analytics/stats` - GET

### Authentication (`app/auth/`)
- **`auth_service.py`**: Servizio autenticazione
  - `create_access_token()`
  - `verify_password()`
  - `hash_password()`
  - `get_user_by_username()`
  - `create_user()`
  - `update_user()`

- **`dependencies.py`**: Dependency injection per auth
  - `get_current_user()`
  - `get_current_active_user()`
  - `require_matrix_edit_permission()`
  - `require_super_admin()`

- **`models.py`**: Modelli Pydantic per auth
  - `User`
  - `UserCreate`
  - `UserUpdate`
  - `Token`
  - `LoginRequest`

### Data Models (`app/models/`)
- **`euring_models.py`**: Modelli Pydantic EURING (GRANDE FILE)
  - `FieldDefinition`
  - `EuringVersion`
  - `ConversionMapping`
  - `FieldMapping`
  - `DomainEvolution`
  - `SemanticDomain` enum
  - `RecognitionResult`
  - `ConversionResult`
  - `ParseResult`
  - E molti altri...

### Services (`app/services/`)

#### Core Services
- **`recognition_engine.py`**: Riconoscimento versione EURING
  - `RecognitionEngineImpl` class
  - `recognize_version()` - Algoritmo discriminant analysis

- **`conversion_service.py`**: Conversione tra versioni
  - `EuringConversionService` class
  - `convert()` - Conversione diretta
  - `convert_semantic()` - Conversione semantica

- **`semantic_converter.py`**: Conversione semantica avanzata
  - `SemanticConverter` class
  - Mapping basato su domini semantici

- **`skos_manager.py`**: Gestione definizioni EURING
  - `SKOSManagerImpl` class
  - `load_version_model()` - Carica da JSON
  - `get_all_versions()`
  - `get_version_by_id()`

- **`version_loader.py`**: Caricamento versioni da file
  - `VersionLoader` class
  - Parsing JSON definitions

#### Domain Services
- **`semantic_domain_mapper.py`**: Mapping campi a domini
  - `assign_domains_to_fields()`
  - Logica assegnazione automatica

- **`domain_evolution_analyzer.py`**: Analisi evoluzione domini
  - `DomainEvolutionAnalyzer` class
  - `analyze_domain_evolution()`

- **`domain_compatibility_assessor.py`**: Valutazione compatibilità
  - `DomainCompatibilityAssessor` class
  - `assess_compatibility()`

- **`domain_conversion_service.py`**: Conversione per dominio
  - `DomainConversionService` class
  - Conversioni domain-specific

- **`semantic_field_grouper.py`**: Raggruppamento campi semantici
  - `SemanticFieldGrouper` class
  - Grouping logic

#### Utility Services
- **`field_translator.py`**: Traduzione campi (non usato)
  - `FieldTranslator` class
  - `translate_field_name()`
  - `translate_field_value()`

- **`lookup_table_service.py`**: Gestione lookup tables
  - `LookupTableService` class
  - `get_lookup_table()`
  - `update_lookup_table()`

- **`usage_logger.py`**: Logging utilizzo (PostgreSQL)
  - `UsageLogger` class
  - `log_query()`

- **`usage_logger_local.py`**: Logging locale (file)
  - Alternativa a PostgreSQL

- **`database_service.py`**: Servizio database (PostgreSQL)
  - `DatabaseService` class
  - Query analytics

- **`database_service_local.py`**: Database locale (SQLite)
  - Alternativa a PostgreSQL

- **`email_service.py`**: Servizio email (non implementato)
  - Placeholder per future notifiche

#### Parsers (`app/services/parsers/`)
- **`euring_1966_parser.py`**: Parser EURING 1966
- **`euring_1979_parser.py`**: Parser EURING 1979
- **`euring_2000_parser.py`**: Parser EURING 2000
- **`euring_2000_epe_compatible_parser.py`**: Parser EPE-compatible
- **`euring_2020_parser.py`**: Parser EURING 2020
- **`euring_2020_official_parser.py`**: Parser EURING 2020 official

### Repositories (`app/repositories/`)
- **`skos_repository.py`**: Repository per dati SKOS
  - Data access layer per EURING definitions

### Middleware (`app/middleware/`)
- **`logging_middleware.py`**: Middleware logging richieste
- **`simple_logging_middleware.py`**: Versione semplificata

### Database (`app/database/`)
- **`schema.sql`**: Schema PostgreSQL
  - Tabelle: users, query_log
- **`schema.py`**: Schema SQLAlchemy (alternativo)

### Data (`data/`)

#### Authentication
- **`data/auth/users.json`**: Database utenti (JSON)
  ```json
  {
    "users": [
      {
        "id": "uuid",
        "username": "admin",
        "email": "admin@ispra.it",
        "hashed_password": "...",
        "role": "super_admin",
        "is_active": true
      }
    ]
  }
  ```

#### EURING Versions (`data/euring_versions/`)

**Versions** (`versions/`):
- **`euring_1966.json`**: Definizione EURING 1966
- **`euring_1979.json`**: Definizione EURING 1979
- **`euring_2000.json`**: Definizione EURING 2000
- **`euring_2020.json`**: Definizione EURING 2020
- **`euring_2020_official.json`**: Definizione EURING 2020 official

**Mappings**:
- **`conversion_mappings.json`**: Mappature conversione tra versioni
- **`relationships.json`**: Relazioni tra versioni

**Domain Evolutions** (`domain_evolutions/`):
- **`identification_marking.json`**: Evoluzione dominio
- **`species.json`**: Evoluzione dominio
- **`demographics.json`**: Evoluzione dominio
- **`temporal.json`**: Evoluzione dominio
- **`spatial.json`**: Evoluzione dominio
- **`biometrics.json`**: Evoluzione dominio
- **`methodology.json`**: Evoluzione dominio

**Official SKOS** (`official_skos/`):
- **`euring_2020_official.ttl`**: Definizione SKOS ufficiale

**Documentation** (`data/documentation/`):
- **`analysis/`**: Analisi dettagliate
  - `semantic_domain_summary.md`
  - `domain_evolution_matrices.md`
  - `semantic_field_mapping.md`
  - `euring_1966_detailed_analysis.md`
  - E altri...

### Tests (`tests/`)
- **`conftest.py`**: Configurazione pytest
- **`test_version_loading.py`**: Test caricamento versioni
- Altri test (da implementare)

### Configuration
- **`requirements.txt`**: Dipendenze Python
- **`.env.local`**: Variabili ambiente locale
- **`Dockerfile.dev`**: Dockerfile per development
- **`pytest.ini`**: Configurazione pytest

## Documentation (`docs/`)

- **`README.md`**: Documentazione principale
- **`DEPLOYMENT.md`**: Guida deployment
- **`MATRIX_GUIDE.md`**: Guida editing matrice
- **`TROUBLESHOOTING.md`**: Risoluzione problemi
- **`DECISIONI_TECNICHE.md`**: Decisioni tecniche
- **`GITHUB_SETUP.md`**: Setup repository GitHub

### Architecture (`internal-docs/architecture/`)
- Diagrammi architettura (se presenti)

### Deployment (`internal-docs/deployment/`)
- Guide deployment specifiche

## AI Context (`ai-context/`)

Documentazione per agenti AI:
- **`README.md`**: Indice documentazione
- **`01-PROJECT-OVERVIEW.md`**: Panoramica progetto
- **`02-ARCHITECTURE.md`**: Architettura sistema
- **`03-DATA-MODEL.md`**: Modello dati EURING
- **`04-API-ENDPOINTS.md`**: Documentazione API
- **`05-FRONTEND-COMPONENTS.md`**: Componenti React
- **`06-AUTH-SYSTEM.md`**: Sistema autenticazione
- **`07-DEPLOYMENT.md`**: Procedure deployment
- **`08-DESIGN-DECISIONS.md`**: Decisioni tecniche
- **`09-FILE-MAP.md`**: Questo file
- **`10-KNOWN-ISSUES.md`**: Problemi noti

## Root Files

- **`README.md`**: Documentazione principale progetto
- **`LICENSE`**: Licenza software
- **`.gitignore`**: File ignorati da Git
- **`docker-compose.yml`**: Configurazione Docker (se usato)
- **`CLEANUP_SUMMARY.md`**: Riepilogo pulizia progetto

## File da Ignorare

### Frontend
- `node_modules/` - Dipendenze npm
- `dist/` - Build output
- `.env.local` - Variabili ambiente locali
- `*.tar.gz` - Build archives

### Backend
- `venv/` - Virtual environment Python
- `__pycache__/` - Python cache
- `*.pyc` - Python compiled
- `.env` - Variabili ambiente

### General
- `.DS_Store` - macOS metadata
- `*.log` - Log files
- `.vscode/` - VS Code settings (opzionale)

## File Critici (Non Modificare Senza Backup)

### Backend
- `data/auth/users.json` - Database utenti
- `data/euring_versions/versions/*.json` - Definizioni EURING
- `data/euring_versions/conversion_mappings.json` - Mappature conversione

### Frontend
- `src/services/api.ts` - Client API
- `src/services/auth.ts` - Servizio auth

### Configuration
- `backend/.env.local` - Configurazione backend
- `frontend/.env.production` - Configurazione frontend prod

## File Generati (Non Committare)

- `frontend/dist/` - Build frontend
- `frontend/node_modules/` - Dipendenze npm
- `backend/venv/` - Virtual environment
- `backend/__pycache__/` - Python cache
- `*.tar.gz` - Archives
- `*.log` - Log files

## Navigazione Rapida

### Voglio modificare...

**...l'interfaccia di riconoscimento**:
→ `frontend/src/components/RecognitionPanel.tsx`

**...la logica di conversione**:
→ `backend/app/services/conversion_service.py`

**...le definizioni EURING**:
→ `backend/data/euring_versions/versions/`

**...i permessi utente**:
→ `backend/app/auth/dependencies.py`

**...lo stile della matrice**:
→ `frontend/src/components/EuringMatrix.css`

**...l'algoritmo di riconoscimento**:
→ `backend/app/services/recognition_engine.py`

**...il deployment**:
→ `internal-docs/DEPLOYMENT.md` + script custom

**...i domini semantici**:
→ `frontend/src/utils/semanticDomains.ts` (frontend)
→ `backend/app/services/semantic_domain_mapper.py` (backend)

**...le API**:
→ `backend/app/api/euring_api.py` (endpoint)
→ `frontend/src/services/api.ts` (client)

**...l'autenticazione**:
→ `backend/app/auth/auth_service.py` (backend)
→ `frontend/src/services/auth.ts` (frontend)
