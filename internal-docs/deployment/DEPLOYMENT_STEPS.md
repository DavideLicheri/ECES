# Guida Deployment Passo-Passo

## File già caricati in /tmp/ sul server ✅

I seguenti file sono già stati caricati:
- `/tmp/frontend_matrix_save_debug.tar.gz`
- `/tmp/skos_manager.py`
- `/tmp/skos_repository.py`
- `/tmp/euring_api.py`

## Comandi da eseguire sul server

### 1. Connettiti al server
```bash
ssh <VM_USER>@<VM_IP>
```
Password: vedi gestore password (rimossa da qui il 14/08/2026 dopo un audit di sicurezza — era esposta in chiaro su un repository pubblico)

---

### 2. Diventa root
```bash
sudo su -
```
Password: vedi gestore password

---

### 3. Backup del frontend attuale
```bash
cd /opt/eces/frontend
```

```bash
rm -rf dist.backup
```

```bash
mv dist dist.backup
```

---

### 4. Crea nuova directory dist
```bash
mkdir -p dist
```

```bash
cd dist
```

---

### 5. Estrai il nuovo frontend
```bash
tar -xzf /tmp/frontend_matrix_save_debug.tar.gz
```

Verifica che i file siano stati estratti:
```bash
ls -la
```

Dovresti vedere: `index.html`, `assets/`, `images/`, ecc.

---

### 6. Deploy backend - skos_manager.py
```bash
cp /tmp/skos_manager.py /opt/eces/backend/app/services/
```

Verifica:
```bash
ls -la /opt/eces/backend/app/services/skos_manager.py
```

---

### 7. Deploy backend - skos_repository.py
```bash
cp /tmp/skos_repository.py /opt/eces/backend/app/repositories/
```

Verifica:
```bash
ls -la /opt/eces/backend/app/repositories/skos_repository.py
```

---

### 8. Deploy backend - euring_api.py
```bash
cp /tmp/euring_api.py /opt/eces/backend/app/api/
```

Verifica:
```bash
ls -la /opt/eces/backend/app/api/euring_api.py
```

---

### 9. Restart del servizio backend
```bash
systemctl restart eces.service
```

Attendi 2-3 secondi, poi verifica lo status:
```bash
systemctl status eces.service
```

Dovresti vedere: `Active: active (running)`

Se vedi errori, premi `q` per uscire e guarda i log:
```bash
journalctl -u eces.service -n 50
```

---

### 10. Test configurazione nginx
```bash
nginx -t
```

Dovresti vedere:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

### 11. Reload nginx
```bash
systemctl reload nginx
```

---

### 12. Esci da root
```bash
exit
```

---

### 13. Monitora i log in tempo reale
```bash
sudo journalctl -u eces.service -f
```

Lascia questo terminale aperto per vedere i log in tempo reale.

---

## Test del Sistema

1. Apri il browser: `http://<VM_IP>/eces/`
2. Fai login come super_admin
3. Vai alla Matrice EURING
4. Trova un campo con `data_type: "alphanumeric"` (es. `scheme_code`)
5. Clicca per modificarlo
6. Cambia il valore in `"string"`
7. Salva

## Cosa Vedere nei Log

Mentre salvi, nel terminale con i log dovresti vedere:

```
🔄 [API] Setting data_type from 'alphanumeric' to 'string'
✅ [API] Field scheme_code.data_type is now: 'string'
💾 [API] Calling skos_manager.update_version for euring_2000
🔄 [SKOS Manager] Updating version: euring_2000
✅ [SKOS Manager] Updated cache for euring_2000
✅ [SKOS Manager] Updated version in model list at index 2
💾 [SKOS Manager] Saving to repository...
💾 [Repository] Saving euring_2000 to /opt/eces/backend/data/euring_versions/versions/euring_2000.json
📝 [Repository] Sample field before save: scheme_code - data_type: string
✅ [Repository] File written successfully to /opt/eces/backend/data/euring_versions/versions/euring_2000.json
✅ [Repository] Verification: scheme_code - data_type: string
✅ [SKOS Manager] Save complete for euring_2000!
✅ [API] Save complete!
✅ [API] Verification: scheme_code.data_type = 'string'
```

## Interpretazione dei Risultati

### ✅ Se vedi tutti i log con "string"
Il salvataggio funziona correttamente! Se il valore torna comunque a "alphanumeric" dopo il reload, il problema è ambientale (Docker, file system, permessi).

### ❌ Se vedi "alphanumeric" nei log
Il problema è nel codice - il valore non viene impostato correttamente prima del salvataggio.

### ⚠️ Se non vedi nessun log
Il backend non sta ricevendo la richiesta, o c'è un problema di routing.

---

## Comandi Utili

### Vedere gli ultimi 100 log
```bash
sudo journalctl -u eces.service -n 100
```

### Vedere i log da un'ora fa
```bash
sudo journalctl -u eces.service --since "1 hour ago"
```

### Restart completo se necessario
```bash
sudo systemctl restart eces.service
sudo systemctl reload nginx
```

### Verificare che il file JSON sia stato modificato
```bash
sudo grep -A 5 '"name": "scheme_code"' /opt/eces/backend/data/euring_versions/versions/euring_2000.json
```

Dovresti vedere `"data_type": "string"` se il salvataggio ha funzionato.
