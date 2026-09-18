# 📚 ECES - Documentazione Completa

Benvenuto nella documentazione tecnica completa del progetto ECES (EURING Code Exchange System).

## 🎯 Quick Start

### Per Sviluppatori Nuovi
1. Leggi [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md) per capire le scelte architetturali
2. Segui [architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md](architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md) per setup locale
3. Consulta [TROUBLESHOOTING.md](TROUBLESHOOTING.md) quando incontri problemi

### Per Deployment
1. Leggi [deployment/DEPLOYMENT_STEPS.md](deployment/DEPLOYMENT_STEPS.md)
2. Segui i passi uno alla volta
3. Verifica con i test indicati

### Per Risolvere Problemi
1. Cerca in [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Se non trovi soluzione, leggi i fix specifici in `fixes/`
3. Documenta nuove soluzioni trovate

---

## 📂 Struttura Documentazione

```
docs/
├── README.md                          # Questo file
├── INDEX.md                           # Indice completo di tutta la documentazione
├── DECISIONI_TECNICHE.md             # Tutte le decisioni architetturali con motivazioni
├── TROUBLESHOOTING.md                # Guida risoluzione problemi comuni
│
├── architecture/                      # Documentazione architettura sistema
│   └── LOCAL_DEVELOPMENT_SETUP_COMPLETE.md
│
├── deployment/                        # Guide deployment
│   └── DEPLOYMENT_STEPS.md
│
└── fixes/                            # Documentazione fix specifici
    ├── MATRIX_MULTI_WORKER_CACHE_FIX.md
    ├── MATRIX_SAVE_ISSUE_SOLUTION.md
    └── MATRIX_DATA_TYPE_ISSUE_ANALYSIS.md
```

---

## 📖 Documenti Principali

### 🏗️ Architettura

#### [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md)
Documento master con TUTTE le decisioni tecniche importanti:
- Database: PostgreSQL vs SQLite
- Cache: In-memory con invalidation
- Multi-worker: 4 worker uvicorn
- Frontend: Backend come source of truth
- Deployment: Manual con script

**Quando leggerlo**: Prima di fare modifiche architetturali importanti

---

#### [architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md](architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md)
Setup completo ambiente di sviluppo locale:
- Docker Compose con PostgreSQL 14
- Servizio database ibrido (PostgreSQL/SQLite)
- Script di setup automatizzati
- Testing locale

**Quando leggerlo**: Primo giorno di lavoro sul progetto

---

### 🔧 Fix e Soluzioni

#### [fixes/MATRIX_MULTI_WORKER_CACHE_FIX.md](fixes/MATRIX_MULTI_WORKER_CACHE_FIX.md) ⭐
**SOLUZIONE DEFINITIVA** al problema multi-worker cache:
- Problema: modifiche non persistono dopo reload
- Causa: 4 worker con cache indipendenti
- Soluzione: cache invalidation completa dopo save
- Status: ✅ RISOLTO e DEPLOYATO

**Quando leggerlo**: Se modifiche alla matrice non persistono

---

#### [fixes/MATRIX_SAVE_ISSUE_SOLUTION.md](fixes/MATRIX_SAVE_ISSUE_SOLUTION.md)
Analisi completa problema salvataggio matrice:
- Evoluzione del problema
- Tentativi di soluzione
- Soluzione finale: reload da backend
- Philosophy: zero automatismi

**Quando leggerlo**: Per capire la filosofia di editing della matrice

---

#### [fixes/MATRIX_DATA_TYPE_ISSUE_ANALYSIS.md](fixes/MATRIX_DATA_TYPE_ISSUE_ANALYSIS.md)
Analisi problema data_type che cambia:
- Investigazione file system
- Analisi codice backend/frontend
- Identificazione root cause
- Soluzioni proposte

**Quando leggerlo**: Per capire come è stato debuggato il problema cache

---

### 🚀 Deployment

#### [deployment/DEPLOYMENT_STEPS.md](deployment/DEPLOYMENT_STEPS.md)
Guida passo-passo per deployment su server ISPRA:
- Comandi esatti da eseguire
- Verifica ad ogni step
- Interpretazione log
- Rollback procedure

**Quando leggerlo**: Prima di ogni deployment

---

### 🆘 Troubleshooting

#### [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
Guida completa risoluzione problemi:
- Matrix editing issues
- Backend issues
- Frontend issues
- Database issues
- Deployment issues
- Emergency procedures

**Quando leggerlo**: Quando qualcosa non funziona

---

## 🔍 Come Trovare Informazioni

### Per Problema Specifico
1. Cerca in [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Se non trovi, cerca in `fixes/` per problema simile
3. Se ancora non trovi, leggi [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md) per capire architettura

### Per Feature Nuova
1. Leggi [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md) per capire pattern esistenti
2. Segui pattern simili
3. Documenta nuove decisioni

### Per Onboarding
1. [architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md](architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md) - Setup ambiente
2. [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md) - Capire architettura
3. `fixes/` - Capire problemi affrontati e soluzioni
4. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Riferimento per problemi comuni

---

## 📝 Come Contribuire alla Documentazione

### Quando Risolvi un Problema
1. Crea file `.md` in `fixes/` con nome descrittivo
2. Usa template:
   ```markdown
   # [TITOLO PROBLEMA]
   
   ## Problema
   [Descrizione]
   
   ## Analisi
   [Investigazione]
   
   ## Soluzione
   [Cosa hai fatto]
   
   ## Testing
   [Come verificare]
   
   ## File Modificati
   - `path/to/file` - [descrizione]
   ```
3. Aggiungi link in [INDEX.md](INDEX.md)
4. Aggiungi entry in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) se applicabile

### Quando Prendi Decisione Tecnica
1. Aggiungi sezione in [DECISIONI_TECNICHE.md](DECISIONI_TECNICHE.md)
2. Includi:
   - Contesto
   - Decisione finale
   - Motivazioni
   - Alternative considerate
   - Implementazione
3. Link a documentazione dettagliata se necessario

### Quando Aggiungi Feature
1. Documenta in file separato se complessa
2. Aggiorna [INDEX.md](INDEX.md)
3. Aggiorna [TROUBLESHOOTING.md](TROUBLESHOOTING.md) con possibili problemi
4. Aggiorna [deployment/DEPLOYMENT_STEPS.md](deployment/DEPLOYMENT_STEPS.md) se necessario

---

## 🎓 Best Practices Documentazione

### Scrittura
- ✅ Usa linguaggio chiaro e diretto
- ✅ Includi esempi di codice
- ✅ Spiega il "perché", non solo il "cosa"
- ✅ Documenta alternative considerate
- ❌ Non assumere conoscenze pregresse
- ❌ Non usare gergo senza spiegarlo

### Organizzazione
- ✅ Un problema = un file
- ✅ File correlati nella stessa cartella
- ✅ Nomi file descrittivi
- ✅ Link incrociati tra documenti
- ❌ Non duplicare informazioni
- ❌ Non creare file troppo lunghi (max 500 righe)

### Manutenzione
- ✅ Aggiorna quando codice cambia
- ✅ Marca soluzioni obsolete
- ✅ Data ultimo aggiornamento in footer
- ✅ Versiona documentazione importante
- ❌ Non lasciare documentazione obsoleta
- ❌ Non rimuovere storia (marca come obsoleto)

---

## 📊 Metriche Documentazione

### Coverage
- ✅ Tutti i fix maggiori documentati
- ✅ Tutte le decisioni architetturali documentate
- ✅ Setup locale documentato
- ✅ Deployment documentato
- ✅ Troubleshooting documentato

### Qualità
- Chiarezza: ⭐⭐⭐⭐⭐
- Completezza: ⭐⭐⭐⭐⭐
- Aggiornamento: ⭐⭐⭐⭐⭐
- Esempi: ⭐⭐⭐⭐⭐

---

## 🔗 Link Utili

### Documentazione Esterna
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [React Docs](https://react.dev/)
- [PostgreSQL Docs](https://www.postgresql.org/docs/)
- [Docker Docs](https://docs.docker.com/)

### Repository
- [GitHub Repository](https://github.com/your-org/eces) (se pubblico)

### Server
- Server ISPRA: `<VM_IP>`
- Frontend: `http://<VM_IP>/eces/`
- Backend API: `http://<VM_IP>:8000/api/`

---

## 📞 Contatti

Per domande sulla documentazione:
- Team di sviluppo ECES
- Email: [your-email]
- Slack: #eces-dev (se disponibile)

---

## 📅 Changelog Documentazione

### 2026-02-18 - v1.0
- ✅ Creata struttura documentazione completa
- ✅ Documentato fix multi-worker cache
- ✅ Documentato setup locale
- ✅ Creata guida troubleshooting
- ✅ Documentate tutte le decisioni tecniche

---

**Ultimo aggiornamento**: 18 Febbraio 2026  
**Versione**: 1.0  
**Autore**: Team ECES Development
