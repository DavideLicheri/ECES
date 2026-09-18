# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ECES (EURING Code Evolution System) is a web application for managing, visualizing, and converting EURING bird ringing codes across four historical versions (1966, 1979, 2000, 2020). It is an internal ISPRA tool, all UI text is hardcoded in Italian (an i18n system was removed due to race condition bugs). The system uses JWT authentication with three roles: `user`, `matrix_editor`, `super_admin`.

**Lizzy** is an AI assistant (qwen2.5:14b on Ollama/Open WebUI) that uses ECES as its sole source of truth for EURING field semantics. ECES exposes dedicated API endpoints consumed by Lizzy's Open WebUI tools (`eces_recognize`, `eces_convert`, `eces_field_info`, `eces_species_lookup`, `ispra_species_lookup`).

## Commands

### Backend

```bash
cd backend
pip install -r requirements.txt
PYTHONPATH=. python3 main.py          # Starts on http://localhost:8000; /docs for Swagger UI
```

Run all tests (from repo root):
```bash
cd backend && python -m pytest
```

Run a single test file:
```bash
cd backend && python -m pytest tests/test_version_loading.py -v
```

Run tests with a specific marker (unit, integration, property, slow):
```bash
cd backend && python -m pytest -m unit
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # Dev server on http://localhost:3000
npm run build    # tsc + vite build → dist/
npm run lint     # ESLint (config creata 02/09/2026, prima non esisteva; soglia --max-warnings 132 = baseline debito esistente di 'any', non 0)
npm run preview  # Preview production build
```

### Docker (PostgreSQL only for local analytics)

```bash
docker-compose up postgres   # Just the database
docker-compose up            # Full stack including backend container
```

## Architecture

### Data Flow

```
React SPA (port 3000) ──fetch/axios──► FastAPI (port 8000)
                                            │
                          ┌─────────────────┼─────────────────┐
                          ▼                 ▼                  ▼
                     JSON files       PostgreSQL           users.json
                  (EURING versions   (analytics &          (auth only)
                   + mappings)        query logs)
```

The Vite config sets `base: '/eces/'`, so in production the frontend is served under the `/eces/` path prefix via Nginx.

### Backend Layer Structure

`main.py` → three API routers → services → repositories → data files

- **`app/api/`** — Three routers: `euring_api.py` (EURING operations), `auth_api.py` (JWT auth), `analytics_api.py` (super_admin only)
- **`app/services/`** — All business logic. Key services:
  - `skos_manager.py` — Loads and caches EURING version definitions from JSON; the central service for version data
  - `recognition_engine.py` — Identifies EURING version of a string using length + discriminant pattern analysis (>95% accuracy, no ML)
  - `conversion_service.py` + `semantic_converter.py` — Convert strings between versions via semantic field mapping
  - `lookup_table_service.py` — Provides valid-value tables for coded fields (sex, age, etc.)
  - `domain_evolution_analyzer.py` / `domain_compatibility_assessor.py` / `semantic_field_grouper.py` — Domain panel analysis
  - `usage_logger.py` / `database_service.py` — Log queries to PostgreSQL for analytics
- **`app/repositories/skos_repository.py`** — Reads/writes EURING JSON files; supports cache invalidation on field edits
- **`app/auth/`** — JWT with bcrypt. `auth_service.py` handles hashing; `dependencies.py` exposes FastAPI `Depends` guards (`get_current_active_user`, `require_matrix_edit_permission`, `require_super_admin`, `get_current_user_optional`)
- **`app/models/euring_models.py`** — All Pydantic models: `EuringVersion`, `FieldDefinition`, `ConversionMapping`, `FieldMapping`, `SemanticDomain` enum, `ValidValuesType` enum, etc.

### Data Files (`backend/data/`)

- `euring_versions/versions/euring_{1966,1979,2000,2020}.json` — Full field definitions per version (positions, lengths, types, lookup values, semantic domain assignments, `valid_values_type`, `valid_values_descriptions`, `valid_values_source`)
- `euring_versions/conversion_mappings.json` — Field-to-field mapping rules across version pairs
- `euring_versions/domain_evolutions/` — Per-domain evolution data for the DomainPanel
- `auth/users.json` — User records with bcrypt-hashed passwords; the `super_admin` default is `admin`/`admin`

`euring_2020.json` contains populated `valid_values_descriptions` for: `place_code` (2052 voci), `current_place_code` (2052), `ringing_scheme` (161), `circumstances` (92). These are sourced from the Python `euring` library and imported via `backend/scripts/import_euring_codes.py`.

### Frontend Structure

Single-page app with tab navigation. Auth state lives in `App.tsx` (no Redux). JWT stored in `localStorage` under key `eces_token`.

- **`services/auth.ts`** — `AuthService` singleton handles login, logout, token storage, expiry check
- **`services/api.ts`** — Typed API client for all EURING endpoints
- **`types/euring-types.ts`** — TypeScript types matching backend Pydantic models
- Major components: `RecognitionPanel`, `ConversionPanel`, `StringNavigator` (batch, paginated 50/page), `EuringMatrix` (tabular cross-version view), `PositionalMatrixEditor` (field editing with side panel), `DomainPanel` (domain evolution/charts/compatibility)
- Each component has a co-located `.css` file; styling uses plain CSS modules, no CSS-in-JS

## Key Conventions

### Authentication & Permissions

- New users register with `is_active: false`; a `super_admin` must approve them
- Endpoint guards via FastAPI `Depends`: import from `app.auth.dependencies` and use `get_current_active_user`, `require_matrix_edit_permission`, or `require_super_admin`
- Frontend checks token expiry via `authService.isTokenExpired()` on every page load; expired tokens trigger auto-logout

### EURING Data Editing

- Field edits go through `SKOSRepository.save_version()` which writes back to the JSON files in `data/euring_versions/versions/`
- After a save, `SKOSManagerImpl._version_model` and `_version_cache` must be invalidated (set to `None`/clear) so the next request reloads from disk

### Backend Environment Variables

All use the `ECES_` prefix:

| Variable | Default | Purpose |
|---|---|---|
| `ECES_SECRET_KEY` | (nessun default sicuro — va sempre impostato con un valore casuale forte, es. `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`; rimosso da qui il 14/08/2026 dopo audit di sicurezza, il valore precedente era pubblicato in chiaro) | JWT signing key |
| `ECES_ENVIRONMENT` | `development` | Enables uvicorn reload when `development` |
| `ECES_CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins |
| `ECES_HOST` / `ECES_PORT` | `0.0.0.0` / `8000` | Bind address |
| `DATABASE_URL` | — | PostgreSQL for analytics; analytics is skipped gracefully if unavailable |

### Field Semantic Model

`FieldDefinition` supports semantic classification of valid values via `valid_values_type` (`ValidValuesType` enum):

| Value | Meaning |
|---|---|
| `enumeration` | Closed list with descriptions (sex, age, condition…) |
| `external_reference` | Large external list (place_code 2052 entries, ringing_scheme 161) |
| `free_numeric` | Free numeric value with optional range |
| `free_text` | Free text |
| `free_alphanumeric` | Free alphanumeric (ring_number…) |
| `computed` | Derived from other fields (elapsed_time…) |

Additional optional fields on `FieldDefinition`: `valid_values_descriptions` (dict code→label), `valid_values_source` (string), `valid_values_lookup_tool` (string), `valid_values_range` (dict).

### Lookup Endpoint

`GET /api/euring/field/{field_name}/lookup?code=XX&version=2020` decodes a single code without returning the full dictionary. Implemented in `euring_api.py` after `get_field_info`. This is the endpoint used by Lizzy's `eces_field_info(field_name, code=XX)` to avoid sending 2052 entries to the model for place_code lookups.

### Import Script

`backend/scripts/import_euring_codes.py` — standalone script that uses the `euring` Python library to populate `valid_values`, `valid_values_descriptions` for place_code, current_place_code, ringing_scheme, circumstances via `PUT /api/euring/field/{name}`. Run with the venv Python:
```bash
/opt/eces/venv/bin/python backend/scripts/import_euring_codes.py
```

### Production Deployment

No git on the production VM (`/opt/eces/`). Deploy by copying files via `scp`:
```bash
scp backend/app/api/euring_api.py <VM_USER>@<VM_IP>:/opt/eces/backend/app/api/euring_api.py
sudo systemctl restart eces
```
The VM is at `<VM_IP>`, access via FortiClient VPN, user `<VM_USER>`, password auth.

## Testing

Tests use `pytest` + `pytest-asyncio` + `hypothesis`. The test suite is sparse — `tests/test_version_loading.py` covers `VersionLoaderService` and `SKOSManagerImpl` integration. Tests must be run from the `backend/` directory (or with `PYTHONPATH` set to include `backend/`) because imports are relative to that root.

## Lizzy — AI Assistant

Lizzy è l'assistente AI specializzata in inanellamento ornitologico EURING. Gira su qwen2.5:14b via Ollama + Open WebUI su infrastruttura dedicata esterna alla VM ISPRA — soluzione temporanea in attesa dell'arrivo di GPU dedicate su ISPRA.

### Infrastruttura
- Ollama: porta 11434, CPU-only, override in `/etc/systemd/system/ollama.service.d/override.conf`
- Open WebUI: Docker container, porta 3000, compose in `~/eces-ai/docker-compose.yml`
- Modelli disponibili: `qwen2.5:14b` (default), `qwen2.5:32b` (batch), `qwen2.5:3b` (test)

### Strumenti Open WebUI configurati
| Strumento | Funzione | Endpoint ECES |
|---|---|---|
| `eces_recognize` | Riconosce versione stringa EURING | POST /api/euring/recognize |
| `eces_convert` | Converte tra versioni | POST /api/euring/convert |
| `eces_field_info` | Semantica campo + lookup puntuale | GET /api/euring/field/{name} + /lookup |
| `eces_species_lookup` | Nome specie da codice EURING | CSV /app/backend/data/euring_species_codes.csv |
| `ispra_species_lookup` | Nome italiano ufficiale CNI-ISPRA | SPARQL https://dati.isprambiente.it/sparql |

### Fonte dati specie
- CSV EURING: `/app/backend/data/euring_species_codes.csv` (3628 specie, aggiornamento mensile via `/etc/cron.monthly/update_euring_species`)
- SPARQL ISPRA: grafo `https://w3id.org/italia/env/ld/euring/taxon/` — 2274 specie con `vernacularName` italiano

### Principio architetturale
ECES è l'unica fonte di verità per Lizzy. Lizzy non usa mai la propria memoria per decodificare codici EURING — interroga sempre ECES via `eces_field_info`. Per codici singoli usa il lookup puntuale (`eces_field_info(field_name, code=XX)`) che chiama `GET /api/euring/field/{name}/lookup?code=XX` per evitare di caricare dizionari completi (es. place_code ha 2052 voci).
