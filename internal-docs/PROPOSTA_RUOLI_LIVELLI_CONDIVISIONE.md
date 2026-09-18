# Proposta: piramide di ruoli e livelli di dettaglio per l'archivio EURING 2020

> **Stato: PARZIALMENTE IMPLEMENTATA.** Le query di visibilità a livelli, la condivisione mirata (con storico immutabile) e la promozione automatica viewer→user sono implementate e deployate in produzione. Alcuni punti restano esplicitamente aperti (vedi ultima sezione) — questo documento va letto come base di discussione in evoluzione, non come specifica statica. Aggiornato l'ultima volta il 09/09/2026.

## Obiettivo

Definire quanto vede ciascun ruolo utente dei dati EURING 2020 archiviati in ECES, bilanciando due esigenze: permettere un uso comunitario/di ricerca dei dati (anche aggregato/anonimizzato per chi non ha un rapporto diretto con un dato), e proteggere l'identità dell'anello e le informazioni sensibili (posizione esatta, tempistiche) fino a quando il proprietario del dato non sceglie esplicitamente di condividerle.

## I 7 domini semantici (già esistenti nel sistema)

ECES organizza già i 64 campi di una stringa EURING 2020 in 7 domini semantici (`app/models/euring_models.py::SemanticDomain`, mappatura campo→dominio in `euring_2020.json`). La proposta si basa su questi domini invece che su liste di campi scelte ad hoc:

| Dominio | Campi | Contenuto |
|---|---|---|
| `identification_marking` | 4 | ringing scheme, identification number, verifica anello, info anello metallico |
| `species` | 2 | specie dichiarata/conclusa |
| `demographics` | 11 | sesso, età, status, dimensione covata... |
| `temporal` | 5 | data, accuratezza data, ora, condizione, tempo trascorso |
| `spatial` | 8 | place code, coordinate geografiche (**latitudine, longitudine**), distanza, direzione, nome del luogo |
| `biometrics` | 18 | lunghezza ala, peso, muta, becco, tarso... |
| `methodology` | 16 | metodo di cattura, circostanze, marche, note... |

Principio: se un livello include un dominio, lo include per intero (mai singoli campi scelti dentro un dominio).

## I 3 livelli di dettaglio

- **Livello 1**: SOLO `species` + `methodology`. Nessun identificativo, nemmeno mascherato — righe non correlabili tra loro. Nessun `temporal`/`spatial`.
- **Livello 2**: Livello 1 + `demographics` + `identification_marking` **mostrato sempre come alias mascherato** (identificativo stabile, mai lo scheme/numero anello reale). Ancora nessun `temporal`/`spatial`.
- **Livello 3**: tutti i 7 domini, incluso `identification_marking` in chiaro (scheme + numero anello reale) — dato completo.

Principio di fondo: i domini "cosa" (species, methodology, demographics) si aprono progressivamente tra Livello 1 e 2; i domini "dove/quando" (temporal, spatial) e biometrics restano bloccati fino al Livello 3 — mai rivelati a un livello intermedio, per proteggere localizzazione e tempistiche di specie rare (rischio bracconaggio/disturbo).

## Ruoli e tetto di visibilità di default

Quanto vede un ruolo di un dato con cui non ha nessun rapporto diretto (non è proprietario, nessuna condivisione attiva):

| Ruolo | Livello di default | Note |
|---|---|---|
| `viewer` | Livello 1 | Ruolo di default alla registrazione. Pensato come ruolo "di passaggio" per chi esplora il sistema prima di contribuire. |
| `user` | Livello 2 | Può sottomettere/archiviare proprie stringhe. |
| `rings_admin` | Livello 3 **solo** per alias del proprio scheme o nel proprio territorio di pertinenza; Livello 2 altrove (come `user`) | Coordinatore di un centro di inanellamento — vede senza maschera i dati del proprio scheme perché ne è già responsabile nel mondo reale (assegna i numeri, previene i duplicati). |
| `super_admin` | Livello 3 su tutto | Nessuna restrizione. |

Sull'alias di un rings_admin: se **almeno un evento** della storia di vita di un alias soddisfa (a) scheme dell'anello uguale al proprio, oppure (b) luogo dell'evento nel proprio territorio, l'intera storia di vita di quell'alias diventa visibile senza maschera — stessa granularità per-alias già usata per la condivisione tra proprietari (non per singolo evento).

## Meccanismi di elevazione oltre il tetto di ruolo (per uno specifico alias)

- **Essere il proprietario del dato** → sempre Livello 3 sui propri dati.
- **Rendere pubblico** (meccanismo già in produzione, `alias_owner_visibility`) → eleva l'alias da Livello 2 a Livello 3 per chiunque, senza bisogno di reciprocità.
- **Condivisione mirata reciproca** (meccanismo già in produzione, `alias_sharing_intent`, con messaggio opzionale) → eleva a Livello 3 solo tra i due proprietari che scelgono reciprocamente di condividere — resta un meccanismo indipendente dal sistema a livelli/ruoli.

## Vincolo implementativo

La stringa canonica grezza (`canonical_string`) contiene sempre lo scheme e il numero di anello reali nelle prime posizioni — non è un dato separabile dal resto della stringa. Il mascheramento non può quindi funzionare redigendo/oscurando la stringa grezza (rischio concreto di bug che fa trapelare le posizioni giuste): deve funzionare non restituendo mai `canonical_string` a chi è sotto il Livello 3, costruendo invece un oggetto di risposta nuovo a partire dai soli campi dei domini permessi. È il pattern già usato oggi dal placeholder della storia di vita — va replicato sistematicamente in tutti i punti che serviranno i Livelli 1/2.

## Punti ancora aperti (non decisi)

1. ~~**Territorio di pertinenza dei rings_admin**: se e come i centri di inanellamento reali si spartiscono le responsabilità per place_code regionali non è ancora verificato con l'EURING/i centri stessi.~~ **CHIUSO (09/09/2026), deliberatamente conservativo**: la giurisdizione territoriale reale esiste ed è precisa (i centri la fanno rispettare tra loro), ma non è mai stata dichiarata ufficialmente da nessuna fonte consultabile — non è quindi un dato che ECES possa dedurre o importare in autonomia. In alcuni casi (es. i centri regionali spagnoli) i confini si intrecciano con tensioni politiche reali che esulano completamente dall'inanellamento: ECES che pubblicasse o inferisse da sé una mappa territoriale rischierebbe di prendere posizione su una materia estranea al suo scopo. Decisione: l'assegnazione resta quella già implementata il 14/08/2026 (un solo `place_code` a livello nazionale per rings_admin, "tutto il paese", impostato a mano dal super_admin) — non per limite tecnico ma per scelta deliberata. Un eventuale affinamento sub-nazionale potrà avvenire SOLO su richiesta esplicita del centro interessato, mai per iniziativa di ECES né dedotto da fonti esterne. Nessuna modifica di codice necessaria (il meccanismo tecnico non cambia, cambia solo la policy su chi lo popola e perché).
2. ~~**Promozione viewer → user**: non è ancora deciso se avvenga automaticamente alla prima sottomissione riuscita di una stringa, o richieda un passaggio più esplicito/deliberato.~~ **CHIUSO (08/09/2026)**: promozione automatica alla prima sottomissione genuinamente nuova (`is_new=True`), esclusa esplicitamente `lizzy` (che archivia in background ad ogni sua chiamata, non è un vero contributo umano). Notifica via email + banner in-app al prossimo accesso, con invito a uscire e rientrare per applicare il nuovo ruolo. Implementato in `archive_service.py`, `auth_service.py`, `email_service.py`, `auth_api.py`, `App.tsx`/`auth.ts`. Verificato staticamente e end-to-end con un utente reale in produzione, nessuna regressione. Deployato (commit `a3268a1`, 08/09/2026).
3. **Testo dell'avviso di conferma per lo switch di profilo "tutto aperto/tutto chiuso"**: solo abbozzato, non approvato.
4. **Condivisione mirata con scelta parziale/completo**: rimandata a un giro successivo di design.
5. ~~**Utenti esistenti con `role: "admin"`** in `data/auth/users.json` da verificare/migrare a `rings_admin`.~~ **CHIUSO (08/09/2026)**: verificato in produzione, nessun utente con `role: "admin"` residuo (3 utenti reali: `admin→super_admin`, `braccio_di_ferro→viewer`, `lizzy→viewer`). Nessuna migrazione necessaria.
