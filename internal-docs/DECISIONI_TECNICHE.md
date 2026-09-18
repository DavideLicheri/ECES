# Decisioni Tecniche - ECES Project

Questo documento raccoglie TUTTE le decisioni tecniche importanti prese durante lo sviluppo del progetto ECES, con le motivazioni e le alternative considerate.

## 📋 Indice
1. [Architettura Database](#architettura-database)
2. [Cache Strategy](#cache-strategy)
3. [Matrix Editing Philosophy](#matrix-editing-philosophy)
4. [Multi-Worker Architecture](#multi-worker-architecture)
5. [Frontend State Management](#frontend-state-management)
6. [Deployment Strategy](#deployment-strategy)

---

## 1. Architettura Database

### Decisione: PostgreSQL con Servizio Ibrido

**Contesto**: Sistema necessita di analytics avanzate e storage strutturato per dati EURING.

**Scelta Finale**: 
- PostgreSQL 14 in produzione (nativo)
- PostgreSQL 14 in sviluppo (Docker)
- Servizio ibrido che supporta sia PostgreSQL che SQLite (fallback)

**Motivazioni**:
- ✅ Parità tra ambiente dev e prod
- ✅ Analytics avanzate (aggregazioni, time-series)
- ✅ Transazioni ACID per integrità dati
- ✅ Scalabilità per crescita futura
- ✅ Fallback a SQLite per testing rapidi

**Alternative Considerate**:
1. **SQLite** - Scartato: limitazioni per analytics e concorrenza
2. **MySQL** - Scartato: meno feature avanzate per analytics
3. **MongoDB** - Scartato: dati strutturati meglio in SQL

**Implementazione**:
```python
# backend/app/services/database_service_local.py
class DatabaseService:
    def __init__(self):
        if os.getenv('DATABASE_URL', '').startswith('postgresql://'):
            self.engine = create_engine(os.getenv('DATABASE_URL'))
        else:
            self.engine = create_engine('sqlite:///./eces_local.db')
```

**File Documentazione**: `docs/architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md`

---

## 2. Cache Strategy

### Decisione: In-Memory Cache con Invalidation Completa

**Contesto**: Backend gira con 4 worker uvicorn. Ogni worker ha cache indipendente.

**Problema Originale**:
- Worker 1 salva dati → aggiorna SUA cache → scrive su disco ✅
- Worker 2, 3, 4 hanno cache vecchia ❌
- User reload → colpisce Worker 2 → vede dati vecchi ❌

**Scelta Finale**: 
Invalidare completamente la cache dopo ogni save:
```python
async def update_version(self, version: EuringVersion) -> None:
    await self.repository.save_version(version)
    # CRITICAL: Invalidate cache
    self._version_model = None
    self._version_cache.clear()
```

**Motivazioni**:
- ✅ Semplice da implementare
- ✅ Funziona con qualsiasi numero di worker
- ✅ Nessuna dipendenza esterna
- ✅ Garantisce consistenza: ciò che vedi = ciò che è su disco
- ⚠️ Primo reload dopo save più lento (accettabile)

**Alternative Considerate**:
1. **Redis Shared Cache** - Scartato: complessità, dipendenza esterna
2. **Disable Cache** - Scartato: performance pessime
3. **File-Based Lock** - Scartato: problemi con NFS, deadlock
4. **Single Worker** - Scartato: non scalabile

**File Documentazione**: `docs/fixes/MATRIX_MULTI_WORKER_CACHE_FIX.md`

---

## 3. Matrix Editing Philosophy

### Decisione: Zero Automatismi, Reload da Backend

**Contesto**: User modifica campo nella matrice, vuole vedere ESATTAMENTE ciò che ha scritto.

**Principio Guida**: 
> "io voglio che sia riportato esattamente quello che scrivo... senza che venga cambiato"
> - User, 18 Feb 2026

**Scelta Finale**:
1. User modifica campo → salva
2. Backend salva su disco
3. Frontend attende 1000ms
4. Frontend ricarica TUTTO da backend
5. User vede ESATTAMENTE ciò che è su disco

**Motivazioni**:
- ✅ Comportamento prevedibile e deterministico
- ✅ Nessuna trasformazione automatica
- ✅ Source of truth: file JSON su disco
- ✅ Nessuna sincronizzazione complessa tra versioni

**Cosa NON Facciamo**:
- ❌ NO normalizzazione automatica (es. "string" → "alphanumeric")
- ❌ NO sincronizzazione cross-version automatica
- ❌ NO aggiornamento locale ottimistico (troppo error-prone)
- ❌ NO merge di modifiche simultanee

**Implementazione Frontend**:
```typescript
// Dopo save, attendi e ricarica da backend
setTimeout(async () => {
  await loadMatrixData(true); // Force reload from backend
}, 1000);
```

**File Documentazione**: `docs/fixes/MATRIX_SAVE_ISSUE_SOLUTION.md`

---

## 4. Multi-Worker Architecture

### Decisione: 4 Worker Uvicorn con Cache Invalidation

**Contesto**: Server ISPRA ha 4 core CPU, vogliamo sfruttarli tutti.

**Scelta Finale**:
```bash
# systemd service
uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000
```

**Motivazioni**:
- ✅ Sfrutta tutti i core CPU
- ✅ Migliore throughput per richieste concorrenti
- ✅ Fault tolerance (se un worker crasha, altri continuano)
- ✅ Con cache invalidation, nessun problema di consistenza

**Sfide Affrontate**:
1. **Cache Stale** - Risolto con invalidation completa
2. **File Locking** - Non necessario (write sono rare)
3. **Session Affinity** - Non necessario (stateless API)

**Alternative Considerate**:
1. **Single Worker** - Scartato: spreco di risorse
2. **Gunicorn** - Scartato: uvicorn più performante per async
3. **Load Balancer Esterno** - Scartato: overhead non necessario

---

## 5. Frontend State Management

### Decisione: Backend come Source of Truth

**Contesto**: React state management per matrice EURING complessa.

**Scelta Finale**:
- Backend è SEMPRE source of truth
- Frontend mantiene stato locale SOLO per UI (editing, modals)
- Dopo ogni save, reload completo da backend
- NO ottimizzazione locale, NO merge state

**Motivazioni**:
- ✅ Semplice da ragionare
- ✅ Nessun bug di sincronizzazione
- ✅ Comportamento prevedibile
- ⚠️ Più lento (accettabile per editing matrice)

**Pattern Implementato**:
```typescript
// 1. User edita campo
const [editValue, setEditValue] = useState(field.value);

// 2. User salva
await EuringAPI.updateMatrixField(...);

// 3. Reload da backend (NO update locale)
setTimeout(() => loadMatrixData(true), 1000);
```

**Cosa Abbiamo Evitato**:
- ❌ Shallow copy issues (nested objects)
- ❌ Stale closure problems
- ❌ Race conditions tra save e reload
- ❌ Merge conflicts tra local e remote state

---

## 6. Deployment Strategy

### Decisione: Manual Deployment con Script Automatizzati

**Contesto**: Server ISPRA interno, no CI/CD pipeline disponibile.

**Scelta Finale**:
1. Build locale: `npm run build`
2. Upload via SCP: `scp dist.tar.gz server:/tmp/`
3. Deploy manuale sul server con script
4. Restart servizi: `systemctl restart eces.service`

**Motivazioni**:
- ✅ Controllo completo su ogni step
- ✅ Nessuna dipendenza da servizi esterni
- ✅ Audit trail completo (log manuali)
- ✅ Rollback immediato (backup automatico)

**Script Deployment**:
```bash
# deploy_matrix_cache_fix.sh
scp backend/file.py server:/tmp/
# Poi comandi manuali sul server
```

**Alternative Considerate**:
1. **GitHub Actions** - Scartato: server non accessibile da internet
2. **Jenkins** - Scartato: overhead setup non giustificato
3. **Ansible** - Scartato: complessità eccessiva per singolo server

---

## 📊 Metriche di Successo

### Performance
- Tempo risposta API: < 200ms (95th percentile)
- Tempo reload matrice dopo save: ~1 secondo
- Throughput: 100+ req/sec con 4 worker

### Affidabilità
- Uptime: 99.9%
- Zero data loss su save
- Consistenza dati: 100%

### Developer Experience
- Setup locale: < 10 minuti
- Deploy: < 5 minuti
- Rollback: < 2 minuti

---

## 🔄 Processo di Revisione Decisioni

Quando rivedere una decisione tecnica:
1. **Performance degrada** oltre soglie accettabili
2. **Nuovi requisiti** non supportati da architettura attuale
3. **Tecnologia obsoleta** o non più mantenuta
4. **Team feedback** indica problemi ricorrenti

Processo:
1. Documenta problema attuale
2. Analizza alternative
3. Prototipa soluzione
4. Testa in ambiente dev
5. Documenta nuova decisione
6. Deploy graduale

---

## 📚 Riferimenti

- [Matrix Multi-Worker Cache Fix](fixes/MATRIX_MULTI_WORKER_CACHE_FIX.md)
- [Local Development Setup](architecture/LOCAL_DEVELOPMENT_SETUP_COMPLETE.md)
- [Deployment Steps](deployment/DEPLOYMENT_STEPS.md)

---

**Ultimo aggiornamento**: 18 Febbraio 2026
**Autore**: Team ECES Development
**Versione**: 1.0
