#!/usr/bin/env python3
"""
Bootstrap una tantum dei contatori Lizzy (lizzy_species_place_pentad_stats,
migrazioni 004+007) e della tabella di impronte anti-doppio-conteggio
(lizzy_bootstrap_fingerprints, migrazione 008) a partire dall'archivio
storico EPE recuperato (epe_archivio.euring2020_converted, database dev
"eces-postgres-dev", vedi indagine Bootstrap Lizzy 12-15/09/2026).

Architettura (decisa con Davide):
  - Sorgente: epe_archivio.euring2020_converted sul Postgres dev (Docker
    eces-postgres-dev, porta 5433 sul Mac) -- SOLO le righe complete
    (scheme + ring_number + species + place_identifier_resolved + data,
    tutti non-null; verificato 15/09/2026: 8.223.607/8.260.682 righe).
  - place_identifier_resolved e' gia' popolata (colonna aggiunta il
    15/09/2026): codice EURING numerico dove presente, altrimenti nome
    comune (Italia) o countrynameedb (estero). NON usare place_code_2020
    direttamente: e' NULL nel 63% dei casi (record con coordinate invece
    del codice gazetteer, convenzione EURING, non un bug).
  - Destinazione: Postgres di produzione (VM ISPRA 10.158.251.79), NON
    esposto esternamente -- raggiungibile SOLO tramite un tunnel SSH locale
    aperto a mano da Davide PRIMA di lanciare questo script, es.:
        ssh -L 6543:localhost:5432 amministratore@10.158.251.79
    poi passare --prod-dsn puntando a localhost:6543.
  - Pentade calcolata in Python riusando ESATTAMENTE
    app.services.phenology_utils.date_to_pentad() -- mai reimplementata qui.
  - Impronte (ringing_scheme, ring_number, event_date): inserite a batch con
    ON CONFLICT DO NOTHING (idempotente), man mano che si scorre l'archivio.
  - Contatori (species_code, place_code, pentad, ringing_scheme): aggregati
    in un dizionario Python su TUTTO l'archivio prima di scrivere, poi
    scritti in un'unica passata con ON CONFLICT DO UPDATE SET
    occurrence_count = EXCLUDED.occurrence_count e
    source = 'ispra_rdf_bootstrap' -- overwrite, non incremento, cosi' lo
    script e' sicuro da rilanciare piu' volte (idempotente). Limite noto:
    se lo script si interrompe A META', i contatori (a differenza delle
    impronte) NON sono ancora stati scritti -- vanno scritti solo alla
    fine di una scansione completa. Un rilancio integrale rifa' tutto da
    capo in sicurezza (idempotente), semplicemente ripete il lavoro.

Uso (dal Mac, dentro backend/, con il venv attivo e il tunnel SSH gia'
aperto in un altro terminale):

    python scripts/bootstrap_lizzy_stats.py --dry-run
    python scripts/bootstrap_lizzy_stats.py

La password di produzione va sempre passata da te (mai scritta qui ne'
chiesta da Claude). Puoi passarla con --prod-dsn oppure, per non lasciarla
nella history della shell, esportarla prima:

    export LIZZY_PROD_DSN="postgresql://eces_user:PASSWORD@localhost:6543/eces_analytics"
    python scripts/bootstrap_lizzy_stats.py --dry-run
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg

from app.services.phenology_utils import date_to_pentad

DEFAULT_DEV_DSN = "postgresql://eces_user:eces_dev_password@localhost:5433/eces_analytics"

SOURCE_QUERY = """
    SELECT
        ring_scheme_2020,
        ring_identification_number_2020,
        species_code_2020,
        place_identifier_resolved,
        event_date_2020
    FROM epe_archivio.euring2020_converted
    WHERE ring_scheme_2020 IS NOT NULL
      AND ring_identification_number_2020 IS NOT NULL
      AND species_code_2020 IS NOT NULL
      AND place_identifier_resolved IS NOT NULL
      AND event_date_2020 IS NOT NULL
"""

FINGERPRINT_INSERT = """
    INSERT INTO lizzy_bootstrap_fingerprints (ringing_scheme, ring_number, event_date)
    VALUES ($1, $2, $3)
    ON CONFLICT DO NOTHING
"""

STATS_UPSERT = """
    INSERT INTO lizzy_species_place_pentad_stats
        (species_code, place_code, pentad, ringing_scheme, occurrence_count, source)
    VALUES ($1, $2, $3, $4, $5, 'ispra_rdf_bootstrap')
    ON CONFLICT (species_code, place_code, pentad, ringing_scheme, source)
    DO UPDATE SET occurrence_count = EXCLUDED.occurrence_count
"""


def _mask_dsn(dsn: str) -> str:
    """Nasconde la password nel DSN nei messaggi di log (mai stampare la password)."""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme_and_creds, rest = dsn.split("@", 1)
    scheme, creds = scheme_and_creds.split("://", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{rest}"


async def run(dev_dsn: str, prod_dsn: str, batch_size: int, dry_run: bool) -> None:
    print(f"Sorgente (dev):       {_mask_dsn(dev_dsn)}")
    print(f"Destinazione (prod):  {_mask_dsn(prod_dsn)}")
    print(f"Batch size:           {batch_size}")
    print(f"Dry-run:              {dry_run}")
    print()

    dev_conn = await asyncpg.connect(dev_dsn)
    prod_conn = await asyncpg.connect(prod_dsn)

    stats_counter = defaultdict(int)
    fingerprint_batch = []
    rows_processed = 0
    rows_skipped_bad_date = 0
    fingerprints_sent = 0

    try:
        async with dev_conn.transaction():
            async for row in dev_conn.cursor(SOURCE_QUERY, prefetch=batch_size):
                ringing_scheme = row["ring_scheme_2020"].strip()
                ring_number = row["ring_identification_number_2020"].strip()
                species_code = row["species_code_2020"].strip()
                place_code = row["place_identifier_resolved"].strip()
                event_date = row["event_date_2020"]

                try:
                    pentad = date_to_pentad(event_date.day, event_date.month)
                except ValueError:
                    rows_skipped_bad_date += 1
                    continue

                stats_counter[(species_code, place_code, pentad, ringing_scheme)] += 1
                fingerprint_batch.append((ringing_scheme, ring_number, event_date))
                rows_processed += 1

                if len(fingerprint_batch) >= batch_size:
                    if not dry_run:
                        await prod_conn.executemany(FINGERPRINT_INSERT, fingerprint_batch)
                    fingerprints_sent += len(fingerprint_batch)
                    fingerprint_batch.clear()
                    print(
                        f"  ... {rows_processed} righe elaborate, "
                        f"{fingerprints_sent} impronte inviate, "
                        f"{len(stats_counter)} combinazioni specie/luogo/pentade/schema finora"
                    )

            if fingerprint_batch:
                if not dry_run:
                    await prod_conn.executemany(FINGERPRINT_INSERT, fingerprint_batch)
                fingerprints_sent += len(fingerprint_batch)
                fingerprint_batch.clear()

        print()
        print(
            f"Scansione completata: {rows_processed} righe elaborate, "
            f"{rows_skipped_bad_date} scartate per data non valida."
        )
        print(f"Impronte inviate (ON CONFLICT DO NOTHING): {fingerprints_sent}")
        print(f"Combinazioni specie/luogo/pentade/schema da scrivere: {len(stats_counter)}")

        if dry_run:
            print(
                "\nDry-run: nessuna scrittura effettuata su lizzy_bootstrap_fingerprints "
                "o lizzy_species_place_pentad_stats."
            )
            return

        print("\nScrittura contatori su lizzy_species_place_pentad_stats...")
        stats_rows = [
            (species_code, place_code, pentad, ringing_scheme, count)
            for (species_code, place_code, pentad, ringing_scheme), count in stats_counter.items()
        ]
        async with prod_conn.transaction():
            await prod_conn.executemany(STATS_UPSERT, stats_rows)
        print(f"Fatto: {len(stats_rows)} combinazioni scritte con source='ispra_rdf_bootstrap'.")

    finally:
        await dev_conn.close()
        await prod_conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dev-dsn", default=DEFAULT_DEV_DSN,
        help=f"DSN del database dev sorgente (default: {DEFAULT_DEV_DSN})",
    )
    parser.add_argument(
        "--prod-dsn", default=os.environ.get("LIZZY_PROD_DSN"),
        help="DSN di produzione (via tunnel SSH locale). In alternativa, esporta LIZZY_PROD_DSN.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=20000,
        help="Righe per batch di lettura/scrittura impronte (default: 20000)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scansiona e calcola tutto, ma non scrive nulla su produzione.",
    )
    args = parser.parse_args()

    if not args.prod_dsn:
        parser.error("--prod-dsn mancante (o esporta LIZZY_PROD_DSN prima di lanciare lo script).")

    asyncio.run(run(args.dev_dsn, args.prod_dsn, args.batch_size, args.dry_run))
