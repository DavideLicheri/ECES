-- ECES Analytics Database Schema — Migration 008
-- Tabella di impronte (fingerprint) per evitare il doppio conteggio tra il
-- bootstrap storico dell'archivio EPE e gli incrementi organici futuri di
-- lizzy_species_place_pentad_stats (migrazione 007).
--
-- Contesto/decisioni (14 settembre 2026):
--   - Il bootstrap (backend/scripts/bootstrap_lizzy_stats.py) carica in
--     lizzy_species_place_pentad_stats (source='ispra_rdf_bootstrap') i
--     conteggi aggregati da epe_archivio.euring2020_converted, una tantum.
--     Se in futuro lo stesso evento di inanellamento/ricattura venisse
--     inserito anche a mano da un utente Lizzy (source='eces_organic'),
--     verrebbe contato due volte nella somma di lettura.
--   - Soluzione: per ogni riga sorgente elaborata dal bootstrap, viene
--     registrata qui una "impronta" univoca (scheme + numero anello + data
--     evento) -- non un conteggio aggregato, ma l'identificativo del
--     singolo evento gia' coperto dal bootstrap.
--   - Prima di ogni incremento organico, il codice applicativo
--     (database_service.is_in_lizzy_bootstrap, chiamato da
--     archive_service._maybe_increment_lizzy_stats) verifica se
--     l'evento e' gia' presente qui: se si', salta l'incremento organico
--     (decisione esplicita di Davide: in caso di errore nel controllo
--     stesso, si fallisce chiuso, cioe' si salta comunque l'incremento
--     piuttosto che rischiare un doppio conteggio).
--   - Popolata dal bootstrap con INSERT ... ON CONFLICT DO NOTHING:
--     8.223.607 righe sorgente elaborate, 8.212.432 impronte uniche
--     inserite (il resto erano duplicati sullo stesso evento nell'archivio
--     storico). I dati organici preesistenti non sono stati toccati.
--   - Applicata manualmente in produzione il 14/09/2026, insieme alla GRANT
--     verso eces_user (dimenticata nella creazione iniziale via utente
--     postgres -- causa di un InsufficientPrivilegeError durante il primo
--     tentativo di esecuzione del bootstrap). Questo file la rende
--     replicabile su altri ambienti (dev, ricostruzione da zero).

BEGIN;

CREATE TABLE IF NOT EXISTS lizzy_bootstrap_fingerprints (
    ringing_scheme TEXT NOT NULL,
    ring_number TEXT NOT NULL,
    event_date DATE NOT NULL,

    PRIMARY KEY (ringing_scheme, ring_number, event_date)
);

GRANT SELECT, INSERT ON lizzy_bootstrap_fingerprints TO eces_user;

COMMENT ON TABLE lizzy_bootstrap_fingerprints IS
    'Impronte (ringing_scheme, ring_number, event_date) di ogni evento gia'' conteggiato dal bootstrap storico (migrazione 007/008, 14/09/2026) in lizzy_species_place_pentad_stats. Consultata da database_service.is_in_lizzy_bootstrap prima di ogni incremento organico per evitare il doppio conteggio; fail-closed (in caso di errore, incremento saltato).';

COMMIT;
