-- Aggiunge status_2020 a epe_archivio.euring2020_converted, estratto dalla
-- posizione 38 di euring_string (verificato contro le specifiche ufficiali
-- EURING 2000 pag.58 e 2020 pag.16, tabella codici identica in entrambe le
-- versioni). Il valore '-' e' normalizzato a 'U' (Unknown/unrecorded): nei
-- dati EPE reali il trattino non segnala mai un pullo (nessuna delle righe
-- con status='-' ha age_concluded=1, il codice EURING del pullo), correla
-- invece quasi solo con eta' non registrata - deviazione dal manuale
-- ufficiale, confermata empiricamente su questo archivio. Vedi
-- claude/euring-semantic-field-mapping.md nel progetto.

ALTER TABLE epe_archivio.euring2020_converted
    ADD COLUMN IF NOT EXISTS status_2020 TEXT;

UPDATE epe_archivio.euring2020_converted c
SET status_2020 = CASE
        WHEN length(r.euring_string) < 38 THEN NULL
        WHEN substring(r.euring_string from 38 for 1) = '-' THEN 'U'
        WHEN substring(r.euring_string from 38 for 1) IN ('U','N','R','K','M','T','L','W','P','S')
             THEN substring(r.euring_string from 38 for 1)
        ELSE NULL
    END,
    conversion_notes = NULLIF(
        concat_ws('; ',
            NULLIF(c.conversion_notes, ''),
            CASE WHEN length(r.euring_string) < 38
                 THEN 'status non disponibile (euring_string troppo corta, lunghezza=' || length(r.euring_string) || ')'
                 WHEN substring(r.euring_string from 38 for 1) = '-'
                 THEN 'status originario "-" normalizzato a U (non registrato, non pullo)'
                 WHEN substring(r.euring_string from 38 for 1) NOT IN ('U','N','R','K','M','T','L','W','P','S')
                 THEN 'status non riconosciuto (valore=' || substring(r.euring_string from 38 for 1) || ')'
            END
        ),
        ''
    )
FROM epe_archivio.euring2000_raw r
WHERE c.record01guid = r.record01guid;
