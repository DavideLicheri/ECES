-- ECES Analytics Database Schema — Migration 007
-- Aggiunge la colonna 'source' a lizzy_species_place_pentad_stats per
-- distinguere i conteggi organici (inseriti dagli utenti tramite Lizzy)
-- dai conteggi caricati in blocco dal bootstrap storico dell'archivio EPE
-- (backend/scripts/bootstrap_lizzy_stats.py, epe_archivio.euring2020_converted).
--
-- Contesto/decisioni (14 settembre 2026):
--   - Prima di questa migrazione la tabella (migrazione 004) non distingueva
--     la provenienza dei conteggi. Il bootstrap storico avrebbe dovuto
--     sommarsi ai conteggi organici nella stessa riga (stesso PK a 4
--     colonne), rendendo impossibile in seguito distinguere/rimuovere/
--     ricalcolare separatamente i due contributi.
--   - Soluzione: 'source' entra nella PRIMARY KEY, cosi' organico e
--     bootstrap restano righe separate per la stessa combinazione
--     specie+luogo+pentade+schema. La query di consultazione somma
--     occurrence_count su tutte le righe per il totale (nessuna modifica
--     alla logica di lettura esistente, solo a quella di scrittura).
--   - Valori ammessi vincolati esplicitamente (chk_lizzy_pentad_source):
--     'eces_organic' (default, per non rompere gli INSERT esistenti del
--     codice applicativo) e 'ispra_rdf_bootstrap'.
--   - Applicata manualmente in produzione il 14/09/2026 prima di questo
--     commit; questo file la rende replicabile su altri ambienti (dev,
--     ricostruzione da zero).

BEGIN;

ALTER TABLE lizzy_species_place_pentad_stats
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'eces_organic';

ALTER TABLE lizzy_species_place_pentad_stats
    DROP CONSTRAINT IF EXISTS lizzy_species_place_pentad_stats_pkey;

ALTER TABLE lizzy_species_place_pentad_stats
    ADD CONSTRAINT lizzy_species_place_pentad_stats_pkey
    PRIMARY KEY (species_code, place_code, pentad, ringing_scheme, source);

ALTER TABLE lizzy_species_place_pentad_stats
    DROP CONSTRAINT IF EXISTS chk_lizzy_pentad_source;

ALTER TABLE lizzy_species_place_pentad_stats
    ADD CONSTRAINT chk_lizzy_pentad_source
    CHECK (source = ANY (ARRAY['eces_organic'::text, 'ispra_rdf_bootstrap'::text]));

COMMENT ON COLUMN lizzy_species_place_pentad_stats.source IS
    'Provenienza del conteggio: eces_organic (inserimenti utente) o ispra_rdf_bootstrap (bootstrap storico da epe_archivio). Righe separate per la stessa combinazione, sommate in lettura per il totale. Migration 007, 14 settembre 2026.';

COMMIT;
