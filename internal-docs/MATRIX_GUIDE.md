# 📊 Guida Matrice EURING

Guida completa all'uso dell'editor della Matrice EURING per la gestione semantica dei campi.

## 🎯 Panoramica

La **Matrice EURING** è un editor interattivo che permette di:
- **Visualizzare** tutte le versioni EURING in formato comparativo
- **Modificare** campi, descrizioni e domini semantici
- **Gestire** lookup tables con valori predefiniti
- **Salvare** modifiche in modo persistente

## 🚀 Accesso alla Matrice

1. **Avvia l'applicazione** (frontend + backend)
2. **Naviga** alla sezione "Matrice EURING"
3. **Attiva modalità editing** con il pulsante "✏️ Modalità Editing"

## 📋 Interfaccia Utente

### **Controlli Principali**
- **🔒/✏️ Modalità Editing**: Attiva/disattiva editing
- **🔄 Ricarica Dati**: Aggiorna dati dal backend
- **☑️ Versioni**: Seleziona versioni da visualizzare
- **👁️ Campi Vuoti**: Mostra/nascondi campi non presenti

### **Struttura Matrice**
```
| Ord. | Campo | Descrizione | 1966 | 1979 | 2000 | 2020 |
|------|-------|-------------|------|------|------|------|
|  1   | scheme| Scheme ID   |  ✓   |  ✓   |  ✓   |  ✓   |
```

## ✏️ Editing dei Campi

### **Proprietà Modificabili**
- **📝 Descrizione**: Descrizione del campo
- **🏷️ Dominio Semantico**: Categoria semantica
- **🔧 Tipo Dato**: string, integer, float, date, code
- **📏 Lunghezza**: Lunghezza massima campo
- **📍 Posizione**: Posizione nel formato
- **📋 Valori Validi**: Lista valori predefiniti

### **Come Modificare**
1. **Clicca** sulla proprietà da modificare (evidenziata in blu)
2. **Modal di editing** si apre automaticamente
3. **Modifica** il valore nel campo appropriato
4. **Salva** con "✅ Salva Modifiche" o Ctrl+Enter
5. **Annulla** con "❌ Annulla" o Esc

## 📋 Lookup Tables (Valori Predefiniti)

### **Cosa Sono**
Le lookup tables definiscono i valori validi per un campo nel formato:
```
CODICE:DESCRIZIONE
```

### **Esempi Pratici**
```
A0:Metal ring only
B0:Metal ring + colour ring(s)
C0:Metal ring + colour mark(s)
D0:Metal ring + flag(s)
```

### **Come Gestirle**
1. **Clicca** su "Valori" di un campo
2. **Modal editing** si apre con textarea
3. **Scrivi** valori nel formato `CODICE:DESCRIZIONE`
4. **Una riga per valore**
5. **Salva** per applicare le modifiche

### **Formati Supportati**
```
# Formato completo (consigliato)
A0:Metal ring only
B0:Metal ring + colour ring(s)

# Formato solo codici (descrizioni automatiche)
A0,B0,C0
```

## 🏷️ Domini Semantici

### **7 Domini Disponibili**
1. **🏷️ Identification & Marking**: Ring, marks, identification
2. **🐦 Species Classification**: Species codes and taxonomy
3. **👥 Demographics**: Age, sex, status information
4. **⏰ Temporal Information**: Dates, times, seasons
5. **🌍 Spatial Information**: Coordinates, locations
6. **📏 Biometric Measurements**: Measurements, weights
7. **🔬 Methodology & Conditions**: Methods, conditions

### **Assegnazione Automatica**
Il sistema assegna automaticamente domini basandosi su:
- **Nome del campo**
- **Contenuto semantico**
- **Pattern riconosciuti**

### **Modifica Manuale**
1. **Clicca** su "Dominio" di un campo
2. **Seleziona** dal dropdown
3. **Salva** la modifica

## ➕ Aggiunta/Rimozione Campi

### **Aggiungere un Campo**
1. **Trova** il campo nella matrice (riga con "Non presente")
2. **Clicca** "➕ Aggiungi" nella cella della versione
3. **Conferma** posizione suggerita o modificala
4. **Campo creato** con valori di default

### **Rimuovere un Campo**
1. **Modalità editing** attiva
2. **Clicca** "🗑️" nella cella del campo
3. **Conferma** rimozione
4. **Campo rimosso** dalla versione

## 💾 Salvataggio e Persistenza

### **Salvataggio Automatico**
- **Ogni modifica** viene salvata immediatamente
- **Repository SKOS** mantiene persistenza
- **Cache locale** per performance

### **Indicatori di Stato**
- **✅ Salvato**: Modifica applicata con successo
- **❌ Errore**: Problema nel salvataggio
- **🔄 Caricamento**: Operazione in corso

## 📱 Responsive Design

### **Desktop**
- **Matrice completa** con tutte le colonne
- **Editing inline** con modal zoomati
- **Scroll orizzontale** per molte versioni

### **Mobile/Tablet**
- **Scroll orizzontale** automatico
- **Modal ottimizzati** per touch
- **Pulsanti touch-friendly**

## 🔧 Funzionalità Avanzate

### **Filtri e Visualizzazione**
- **Seleziona versioni**: Mostra solo versioni specifiche
- **Campi vuoti**: Nascondi campi non presenti
- **Ordinamento EPE**: Ordine compatibile con EPE ASP

### **Validazione Dati**
- **Posizioni**: Numeri interi ≥ 0
- **Lunghezze**: Numeri interi > 0
- **Formati**: Validazione automatica

### **Performance**
- **Cache intelligente**: Evita ricaricamenti inutili
- **Aggiornamenti incrementali**: Solo dati modificati
- **Scroll preservation**: Mantiene posizione durante aggiornamenti

## ⚠️ Best Practices

### **Editing Sicuro**
1. **Backup dati** prima di modifiche massive
2. **Test modifiche** su campi singoli
3. **Verifica coerenza** tra versioni
4. **Mantieni compatibilità** EPE per sistemi esistenti

### **Gestione Lookup Tables**
1. **Descrizioni chiare** e concise (max 20 caratteri per visualizzazione)
2. **Codici consistenti** tra versioni
3. **Formato standard**: `CODICE:DESCRIZIONE`
4. **Validazione manuale** dei valori

### **Domini Semantici**
1. **Assegnazione coerente** tra versioni simili
2. **Revisione periodica** delle classificazioni
3. **Documentazione** delle scelte semantiche

## 🐛 Troubleshooting

### **Problemi Comuni**

**Modal non si apre:**
- Verifica modalità editing attiva
- Ricarica pagina se necessario

**Modifiche non salvate:**
- Controlla connessione backend
- Verifica formato dati inseriti
- Guarda messaggi di errore

**Valori non visualizzati:**
- Cache browser: Ctrl+F5 per refresh
- Verifica formato lookup table
- Controlla log console (F12)

### **Debug**
- **Console browser** (F12) per errori JavaScript
- **Network tab** per chiamate API fallite
- **Backend logs** per errori server

## 📊 Metriche e Statistiche

La matrice mostra:
- **Campi totali**: Numero campi di riferimento
- **Campi visualizzati**: Campi attualmente mostrati
- **Versioni selezionate**: Numero versioni attive
- **Tempo elaborazione**: Performance backend

## 🎯 Casi d'Uso Tipici

### **Ricercatore**
- Confronta campi tra versioni
- Aggiunge descrizioni mancanti
- Standardizza domini semantici

### **Data Manager**
- Gestisce lookup tables
- Mantiene coerenza dati
- Valida modifiche

### **Sviluppatore**
- Estende definizioni campi
- Aggiunge nuove versioni
- Testa compatibilità

---

**La Matrice EURING è il cuore del sistema per la gestione semantica dei dati ornitologici! 🎉**