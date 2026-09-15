-- Tabella euring2020_converted in epe_archivio: versione 2020 dei 6 campi
-- verificati (specie, scheme, numero anello, place code, data, condizione,
-- circostanze). NON e' una stringa EURING2020 completa a 64 campi: gli altri
-- campi non sono stati validati contro le tabelle codici ufficiali (vedi
-- scheda di progetto claude/euring-semantic-field-mapping.md), quindi non
-- vengono generati per ora. Sufficiente per il bootstrap dei conteggi Lizzy.

CREATE OR REPLACE FUNCTION epe_archivio.safe_make_date(y INTEGER, m INTEGER, d INTEGER)
RETURNS DATE AS $$
BEGIN
    RETURN make_date(y, m, d);
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION epe_archivio.safe_make_date IS 'Come make_date, ma restituisce NULL invece di sollevare errore su combinazioni giorno/mese/anno non valide (es. 30 febbraio) o mancanti.';

CREATE TABLE IF NOT EXISTS epe_archivio.euring2020_converted (
    record01guid                     TEXT PRIMARY KEY REFERENCES epe_archivio.euring2000_raw(record01guid),
    ring_scheme_2020                  TEXT,
    ring_identification_number_2020    TEXT,
    species_code_2020                   TEXT,
    place_code_2020                      TEXT,
    event_date_2020                       DATE,
    condition_2020                         INTEGER,
    circumstances_2020                      TEXT,
    conversion_notes                         TEXT,
    converted_at                              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE epe_archivio.euring2020_converted IS 'Versione EURING2020 di 6 campi verificati (specie, scheme, numero anello, place code, data, condizione, circostanze) per ogni record recuperato da Oracle EPE. Non e una stringa 2020 completa: gli altri 27 campi condivisi fra 2000 e 2020 non sono stati validati contro le tabelle codici ufficiali, lavoro da fare a parte se servira. Vedi claude/euring-semantic-field-mapping.md nel progetto.';

INSERT INTO epe_archivio.euring2020_converted (
    record01guid, ring_scheme_2020, ring_identification_number_2020,
    species_code_2020, place_code_2020, event_date_2020,
    condition_2020, circumstances_2020, conversion_notes
)
SELECT
    record01guid,
    scheme,
    identification_number,
    species_concluded,
    localita,
    epe_archivio.safe_make_date(year, month, day),
    CASE WHEN condition_id ~ '^[0-9]+$' THEN condition_id::INTEGER ELSE NULL END,
    circumstances_id,
    NULLIF(
        concat_ws('; ',
            CASE WHEN epe_archivio.safe_make_date(year, month, day) IS NULL
                 THEN 'data non valida o mancante (giorno=' || COALESCE(day::text, 'null') || ' mese=' || COALESCE(month::text, 'null') || ' anno=' || COALESCE(year::text, 'null') || ')'
            END,
            CASE WHEN condition_id IS NULL OR condition_id !~ '^[0-9]+$'
                 THEN 'condition non numerica (valore=' || COALESCE(condition_id, 'null') || ')'
            END
        ),
        ''
    )
FROM epe_archivio.euring2000_raw
ON CONFLICT (record01guid) DO NOTHING;
