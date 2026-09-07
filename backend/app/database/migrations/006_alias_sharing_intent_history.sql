-- ECES Analytics Database Schema — Migration 006
-- Storico immutabile (append-only) delle scelte di condivisione mirata,
-- per rispondere a un rischio concreto sollevato da Davide il 07/09/2026
-- (vedi HANDOFF.md): oggi `alias_sharing_intent` (migrazione 005) e' un
-- semplice UPSERT -- ogni nuova scelta sovrascrive stato e messaggio
-- precedenti senza lasciare traccia. Tre rischi concreti, tutti confermati
-- rilevanti da Davide:
--   1. Nessuna prova in caso di disputa tra due proprietari (uno nega di
--      aver scritto/promesso qualcosa, l'altro non puo' dimostrarlo).
--   2. Un messaggio puo' essere cambiato dopo che la controparte l'ha gia'
--      letto, senza alcun indicatore che sia stato modificato.
--   3. Un messaggio scortese o manipolatorio puo' essere scritto e poi
--      sovrascritto immediatamente, prima che diventi un problema visibile.
--
-- Questa migrazione NON cambia la logica di `alias_sharing_intent` (resta
-- la fonte di verita' per lo stato ATTUALE, usata per il controllo di
-- reciprocita' in search_canonical_2020/facet_counts_2020/
-- get_alias_life_history) -- aggiunge solo una tabella di log accanto,
-- scritta (mai aggiornata ne' cancellata) ad ogni chiamata di
-- set_alias_sharing_intent, oltre all'UPSERT esistente.
--
-- QUESTA MIGRAZIONE E' SOLO ADDITIVA.

BEGIN;

CREATE TABLE IF NOT EXISTS alias_sharing_intent_log (
    id BIGSERIAL PRIMARY KEY,
    alias_id BIGINT NOT NULL REFERENCES ring_alias(alias_id),
    from_username TEXT NOT NULL,
    to_username TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_alias_sharing_intent_log_state CHECK (state IN ('offered', 'declined')),
    CONSTRAINT chk_alias_sharing_intent_log_not_self CHECK (from_username != to_username)
);

CREATE INDEX IF NOT EXISTS idx_alias_sharing_intent_log_lookup
    ON alias_sharing_intent_log(alias_id, from_username, to_username, decided_at);

COMMENT ON TABLE alias_sharing_intent_log IS
    'Storico immutabile (append-only per CONVENZIONE applicativa -- nessun codice del backend esegue mai UPDATE o DELETE su questa tabella) di ogni scelta di condivisione mirata mai fatta. Una riga per ogni chiamata a set_alias_sharing_intent, oltre all''UPSERT su alias_sharing_intent che resta lo stato attuale. Creata 07/09/2026 su richiesta di Davide dopo aver notato che il solo UPSERT non lascia traccia in caso di disputa tra proprietari o di messaggio modificato/cancellato senza preavviso. Consultata da get_my_sharing_status per popolare la cronologia visibile a entrambi i proprietari coinvolti (mai a estranei).';

COMMIT;
