-- Ricalcolo status_2020 con la logica corretta, dopo la scoperta (manuale
-- NISORIA2000, modulo RINGPUL, "Campo Status = Dimensione covata") che per
-- i pulcini il campo Status della stringa EPE contiene in realta' la
-- dimensione della covata (convenzione NISORIA), non uno status EURING.
-- Vedi claude/euring-semantic-field-mapping.md nel progetto.

UPDATE epe_archivio.euring2020_converted c
SET status_2020 = CASE
        WHEN length(r.euring_string) < 38 THEN NULL
        WHEN r.age_concluded = '1' THEN '-'
        WHEN substring(r.euring_string from 38 for 1) IN ('U','N','R','K','M','T','L','W','P','S')
             THEN substring(r.euring_string from 38 for 1)
        ELSE 'U'
    END,
    conversion_notes = NULLIF(
        concat_ws('; ',
            NULLIF(c.conversion_notes, ''),
            CASE
                WHEN length(r.euring_string) < 38
                     THEN 'status non disponibile (euring_string troppo corta, lunghezza=' || length(r.euring_string) || ')'
                WHEN r.age_concluded = '1' AND substring(r.euring_string from 38 for 1) <> '-'
                     THEN 'status impostato a "-" (pullus): valore originale in posizione 38 ("' || substring(r.euring_string from 38 for 1) || '") era la dimensione di covata (convenzione NISORIA), non uno status EURING'
                WHEN substring(r.euring_string from 38 for 1) = '-'
                     THEN 'status originario "-" normalizzato a U (non registrato, non pullo)'
                WHEN substring(r.euring_string from 38 for 1) NOT IN ('U','N','R','K','M','T','L','W','P','S')
                     THEN 'status non riconosciuto (valore originale="' || substring(r.euring_string from 38 for 1) || '"), impostato a U'
            END
        ),
        ''
    )
FROM epe_archivio.euring2000_raw r
WHERE c.record01guid = r.record01guid;
