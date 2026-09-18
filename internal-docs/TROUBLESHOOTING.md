# Troubleshooting Guide - ECES

Guida completa per risolvere i problemi più comuni del sistema ECES.

## 📋 Indice Rapido

1. [Matrix Editing](#matrix-editing)
2. [Backend Issues](#backend-issues)
3. [Frontend Issues](#frontend-issues)
4. [Database Issues](#database-issues)
5. [Deployment Issues](#deployment-issues)

---

## Matrix Editing

### ❌ Problema: Modifiche non persistono dopo reload

**Sintomi**:
- Modifico un campo nella matrice
- Salvo
- Dopo reload, vedo il valore vecchio

**Causa**: Multi-worker cache stale

**Soluzione**: ✅ RISOLTO con cache invalidation
```python
# backend/app/services/skos_manager.py
async def update_version(self, version: EuringVersion) -> None:
    await self.repository.save_version(version)
    self._version_model = None  # Invalida cache
    self._version_cache.clear()
```

**Verifica Fix**:
```bash
# Nei log dovresti vedere:
🔄 [SKOS Manager] Invalidating cache to force reload from disk...
✅ [SKOS Manager] Cache invalidated! Next request will reload from disk.
```

**Se il problema persiste**:
1. Verifica che il file sia stato deployato:
   ```bash
   sudo ls -la /opt/eces/backend/app/services/skos_manager.py
   ```
2. Verifica che il servizio sia stato riavviato:
   ```bash
   sudo systemctl status eces.service
   ```
3. Controlla i log per errori:
   ```bash
   sudo journalctl -u eces.service -n 100
   ```

**Documentazione**: `docs/fixes/MATRIX_MULTI_WORKER_CACHE_FIX.md`

---

### ❌ Problema: Campo si modifica automaticamente

**Sintomi**:
- Modifico campo A
- Campo B, C, D cambiano automaticamente

**Causa**: Shallow copy in React state (RISOLTO)

**Soluzione**: ✅ Reload completo da backend dopo save
```typescript
// NO local state update
// YES reload from backend
setTimeout(() => loadMatrixData(true), 1000);
```

**Verifica**:
- Modifica UN campo
- Salva
- Attendi reload
- SOLO quel campo deve essere cambiato

**Documentazione**: `docs/fixes/MATRIX_SAVE_ISSUE_SOLUTION.md`

---

### ❌ Problema: Valore salvato diverso da quello scritto

**Sintomi**:
- Scrivo "string"
- Dopo reload vedo "alphanumeric"

**Causa**: Multi-worker cache (RISOLTO)

**Debug**:
1. Verifica file JSON su disco:
   ```bash
   sudo grep -A 5 '"name": "FIELD_NAME"' /opt/eces/backend/data/euring_versions/versions/euring_YEAR.json
   ```
2. Se il file è corretto ma UI mostra valore sbagliato → cache issue
3. Se il file è sbagliato → problema nel save

**Soluzione**: Cache invalidation (vedi sopra)

---

## Backend Issues

### ❌ Problema: Backend non risponde

**Sintomi**:
- Frontend mostra errori di rete
- API non risponde

**Debug**:
```bash
# 1. Verifica servizio attivo
sudo systemctl status eces.service

# 2. Se non attivo, avvia
sudo systemctl start eces.service

# 3. Verifica log per errori
sudo journalctl -u eces.service -n 50

# 4. Verifica porta in ascolto
sudo netstat -tlnp | grep 8000
```

**Cause Comuni**:
1. **Servizio crashato** → Restart: `sudo systemctl restart eces.service`
2. **Errore Python** → Controlla log, fixa codice, redeploy
3. **Porta occupata** → Killa processo: `sudo kill -9 PID`
4. **Permessi file** → Verifica owner: `sudo chown -R eces:eces /opt/eces/backend`

---

### ❌ Problema: Worker crashano ripetutamente

**Sintomi**:
```
Feb 18 17:00:00 epepostgresdb systemd[1]: eces.service: Main process exited
```

**Debug**:
```bash
# Vedi ultimi 100 log
sudo journalctl -u eces.service -n 100

# Cerca errori Python
sudo journalctl -u eces.service | grep -i "error\|exception\|traceback"
```

**Cause Comuni**:
1. **Import error** → Verifica dipendenze: `pip list`
2. **File not found** → Verifica path: `ls -la /opt/eces/backend/data/`
3. **Permission denied** → Fixa permessi: `sudo chown -R eces:eces /opt/eces/`
4. **Memory leak** → Restart: `sudo systemctl restart eces.service`

---

### ❌ Problema: Slow API responses

**Sintomi**:
- API risponde ma molto lentamente (> 2 secondi)

**Debug**:
```bash
# 1. Verifica CPU usage
top

# 2. Verifica memory
free -h

# 3. Verifica disk I/O
iostat -x 1

# 4. Verifica log per query lente
sudo journalctl -u eces.service | grep "processing_time_ms"
```

**Soluzioni**:
1. **CPU alta** → Aumenta worker o ottimizza codice
2. **Memory alta** → Restart servizio, investiga memory leak
3. **Disk I/O alta** → Ottimizza query, aggiungi indici DB
4. **Cache miss** → Verifica cache invalidation non troppo frequente

---

## Frontend Issues

### ❌ Problema: Pagina bianca dopo deployment

**Sintomi**:
- Browser mostra pagina bianca
- Console mostra errori 404

**Debug**:
```bash
# 1. Verifica file esistono
ls -la /opt/eces/frontend/dist/

# 2. Verifica nginx config
sudo nginx -t

# 3. Verifica nginx serve file
curl http://localhost/eces/

# 4. Verifica permessi
sudo ls -la /opt/eces/frontend/dist/index.html
```

**Soluzioni**:
1. **File mancanti** → Redeploy frontend
2. **Nginx config errata** → Fixa config, reload nginx
3. **Permessi sbagliati** → `sudo chmod -R 755 /opt/eces/frontend/dist/`
4. **Cache browser** → Hard refresh (Ctrl+Shift+R)

---

### ❌ Problema: JavaScript errors in console

**Sintomi**:
```
Uncaught TypeError: Cannot read property 'X' of undefined
```

**Debug**:
1. Apri DevTools (F12)
2. Vai a Console tab
3. Leggi stack trace completo
4. Identifica file e linea

**Soluzioni Comuni**:
1. **API response null** → Verifica backend risponde correttamente
2. **State undefined** → Aggiungi null check: `field?.property`
3. **Async race condition** → Usa `useEffect` dependencies correttamente
4. **Build issue** → Rebuild: `npm run build`

---

## Database Issues

### ❌ Problema: Database connection failed

**Sintomi**:
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Debug**:
```bash
# 1. Verifica PostgreSQL attivo
sudo systemctl status postgresql

# 2. Verifica connessione
psql -U eces_user -d eces_db -h localhost

# 3. Verifica DATABASE_URL
sudo cat /opt/eces/backend/.env | grep DATABASE_URL
```

**Soluzioni**:
1. **PostgreSQL non attivo** → `sudo systemctl start postgresql`
2. **Credenziali sbagliate** → Verifica .env file
3. **Database non esiste** → Crea: `sudo -u postgres createdb eces_db`
4. **Permessi** → Grant: `GRANT ALL ON DATABASE eces_db TO eces_user;`

---

### ❌ Problema: Query lente

**Sintomi**:
- Analytics page carica lentamente
- Log mostrano query > 1 secondo

**Debug**:
```sql
-- Vedi query lente
SELECT query, calls, total_time, mean_time 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;
```

**Soluzioni**:
1. **Mancano indici** → Aggiungi indici su colonne filtrate
2. **Troppi dati** → Aggiungi paginazione
3. **Query non ottimizzata** → Usa EXPLAIN ANALYZE
4. **Connection pool** → Aumenta pool size

---

## Deployment Issues

### ❌ Problema: Deploy fallisce con permission denied

**Sintomi**:
```bash
scp: /tmp/file.py: Permission denied
```

**Soluzione**:
```bash
# 1. Verifica permessi /tmp
ls -la /tmp/

# 2. Se necessario, usa sudo
ssh user@server "sudo cp /tmp/file.py /opt/eces/backend/..."
```

---

### ❌ Problema: Servizio non riavvia dopo deploy

**Sintomi**:
```bash
sudo systemctl restart eces.service
# Nessun output, ma servizio non attivo
```

**Debug**:
```bash
# 1. Verifica status
sudo systemctl status eces.service

# 2. Vedi log dettagliati
sudo journalctl -u eces.service -n 50

# 3. Testa manualmente
cd /opt/eces/backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**Soluzioni**:
1. **Syntax error** → Fixa codice, redeploy
2. **Import error** → Installa dipendenze: `pip install -r requirements.txt`
3. **Port in use** → Killa processo: `sudo lsof -ti:8000 | xargs sudo kill -9`

---

## 🆘 Emergency Procedures

### Rollback Completo

Se tutto va male, rollback all'ultima versione funzionante:

```bash
# 1. Connetti al server
ssh <VM_USER>@<VM_IP>

# 2. Diventa root
sudo su -

# 3. Rollback backend
cd /opt/eces/backend
cp -r backup_YYYYMMDD/* .

# 4. Rollback frontend
cd /opt/eces/frontend
rm -rf dist
cp -r dist.backup dist

# 5. Restart servizi
systemctl restart eces.service
systemctl reload nginx

# 6. Verifica
systemctl status eces.service
curl http://localhost/eces/
```

---

### Restart Completo Sistema

```bash
# 1. Stop tutto
sudo systemctl stop eces.service
sudo systemctl stop nginx
sudo systemctl stop postgresql

# 2. Verifica nessun processo attivo
ps aux | grep -E "uvicorn|nginx|postgres"

# 3. Start tutto
sudo systemctl start postgresql
sudo systemctl start eces.service
sudo systemctl start nginx

# 4. Verifica
sudo systemctl status postgresql
sudo systemctl status eces.service
sudo systemctl status nginx
```

---

## 📞 Escalation

Se nessuna soluzione funziona:

1. **Raccogli informazioni**:
   ```bash
   # Log backend
   sudo journalctl -u eces.service -n 200 > backend_logs.txt
   
   # Log nginx
   sudo tail -n 200 /var/log/nginx/error.log > nginx_logs.txt
   
   # System info
   df -h > disk_usage.txt
   free -h > memory_usage.txt
   top -b -n 1 > cpu_usage.txt
   ```

2. **Crea backup**:
   ```bash
   sudo tar -czf eces_backup_$(date +%Y%m%d_%H%M%S).tar.gz /opt/eces/
   ```

3. **Contatta team di sviluppo** con:
   - Descrizione problema
   - Log raccolti
   - Passi per riprodurre
   - Cosa hai già provato

---

**Ultimo aggiornamento**: 18 Febbraio 2026
**Versione**: 1.0
