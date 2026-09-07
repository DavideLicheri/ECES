"""
Script di verifica manuale per il mascheramento a livelli (priorita' #6
della scaletta, 02-04/09/2026 -- vedi docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md
e HANDOFF.md). Scritto da Claude perche' il sandbox di sviluppo NON aveva
PostgreSQL/Docker disponibili (niente permessi root) -- questo script va
quindi lanciato TU, Davide, con un Postgres reale, prima di considerare
il lavoro sulle 4 query di visibilita' davvero verificato end-to-end.

Uso:
    cd backend
    docker-compose up -d postgres   # dalla root del repo, in un altro terminale
    # oppure qualunque Postgres locale/di test raggiungibile con le stesse
    # variabili ECES_ usate da database_service.py (DB_HOST, DB_PORT, DB_NAME,
    # DB_USER, DB_PASSWORD -- default coerenti con docker-compose.yml)
    python3 scripts/verify_visibility_masking.py

Lo script:
1. Applica schema.sql + le migrazioni 002-006 (idempotenti, IF NOT EXISTS --
   sicuro anche se gia' applicate).
2. Inserisce dati di test isolati (canonical_string con prefisso
   'TESTMASK_', per poterli riconoscere e ripulire senza toccare dati reali).
3. Chiama le 4 funzioni riscritte (search_canonical_2020, facet_counts_2020,
   get_visible_events_for_alias, get_alias_life_history) simulando 6 utenti
   diversi (anonimo, viewer, user, rings_admin con scheme che combacia,
   rings_admin senza match, super_admin) e stampa/verifica i risultati.
4. Verifica lo storico immutabile della condivisione mirata (migrazione 006,
   07/09/2026): 3 chiamate a set_alias_sharing_intent con stati/messaggi
   diversi devono lasciare tutte e 3 le tracce nello storico, mentre lo
   stato "attuale" riflette solo l'ultima -- e lo storico deve essere
   identico visto da entrambi i proprietari coinvolti.
5. Ripulisce SEMPRE i dati di test alla fine (anche in caso di errore),
   indipendentemente da come va la verifica.

Se una asserzione fallisce, lo script si ferma con un AssertionError chiaro
su COSA non ha funzionato -- non e' un test silenzioso.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

from app.services.database_service import DatabaseService  # noqa: E402
from app.auth.models import User, UserRole  # noqa: E402
from datetime import datetime  # noqa: E402


def _db_url() -> str:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    database = os.getenv("DB_NAME", "eces_analytics")
    user = os.getenv("DB_USER", "eces_user")
    password = os.getenv("DB_PASSWORD", "eces_password")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


async def _apply_schema_and_migrations(pool: asyncpg.Pool):
    backend_dir = Path(__file__).resolve().parent.parent
    files = [backend_dir / "app" / "database" / "schema.sql"] + sorted(
        (backend_dir / "app" / "database" / "migrations").glob("*.sql")
    )
    async with pool.acquire() as conn:
        for f in files:
            print(f"  applico {f.name}...")
            sql = f.read_text()
            await conn.execute(sql)
    print("Schema + migrazioni applicati (idempotente).")


def _mk_user(username: str, role: UserRole, ringing_scheme=None, territory_place_codes=None) -> User:
    return User(
        # .local e' un TLD riservato, respinto da email-validator (stesso
        # problema incontrato il 04/09/2026 verificando l'endpoint di
        # assegnazione scheme/territorio) -- example.com e' il dominio
        # riservato per la documentazione/test (RFC 2606).
        id=username, username=username, email=f"{username}@example.com",
        full_name=username, role=role, is_active=True, created_at=datetime.now(),
        ringing_scheme=ringing_scheme, territory_place_codes=territory_place_codes or [],
    )


async def _seed(pool: asyncpg.Pool):
    """
    Crea 2 alias fisici (anelli), ciascuno con 2 eventi:
      - alias A: scheme 'TESTSCHEME_A', un evento e' PROPRIO di 'owner1' e
        privato, l'altro e' privato di 'owner2' -- nessun rapporto con gli
        utenti di test sotto, quindi il livello dipende SOLO dal ruolo,
        tranne per il rings_admin con scheme='TESTSCHEME_A' (deve elevarsi
        a Livello 3 su ENTRAMBI gli eventi dell'alias, non solo quello che
        matcha).
      - alias B: un evento reso PUBBLICO da 'owner3' -- deve essere Livello
        3 per chiunque, incluso l'anonimo.
    Ritorna gli id utili per le query.
    """
    async with pool.acquire() as conn:
        alias_a = await conn.fetchval(
            "INSERT INTO ring_alias (ringing_scheme, identification_number) VALUES ($1, $2) RETURNING alias_id",
            "TESTSCHEME_A", "TEST0001",
        )
        alias_b = await conn.fetchval(
            "INSERT INTO ring_alias (ringing_scheme, identification_number) VALUES ($1, $2) RETURNING alias_id",
            "TESTSCHEME_B", "TEST0002",
        )

        async def insert_canonical(suffix: str, owner: str, alias_id: int, place_code: str = "IA--"):
            cid = await conn.fetchval(
                """
                INSERT INTO euring_2020_canonical
                    (canonical_string, string_hash, parsed_fields, field_count, owner_username, alias_id)
                VALUES ($1, $2, $3::jsonb, $4, $5, $6)
                RETURNING id
                """,
                f"TESTMASK_{suffix}",
                f"hash_{suffix}",
                '{"date": "01062026", "place code": "%s"}' % place_code,
                64,
                owner,
                alias_id,
            )
            for fname, fvalue, pos in [
                ("ringing scheme", "TESTSCHEME_A" if alias_id == alias_a else "TESTSCHEME_B", 1),
                ("species concluded", "TESTSPECIES", 2),
                ("sex concluded", "TESTSEX", 3),
                ("place code", place_code, 4),
                ("date", "01062026", 5),
            ]:
                await conn.execute(
                    "INSERT INTO euring_2020_field_values (canonical_id, field_position, field_name, field_value) VALUES ($1,$2,$3,$4)",
                    cid, pos, fname, fvalue,
                )
            return cid

        cid_a1 = await insert_canonical("A1", "owner1", alias_a)
        cid_a2 = await insert_canonical("A2", "owner2", alias_a)
        cid_b1 = await insert_canonical("B1", "owner3", alias_b, place_code="IT--")

        # alias B, evento owner3: reso pubblico.
        await conn.execute(
            "INSERT INTO alias_owner_visibility (alias_id, username, is_public) VALUES ($1, $2, true)",
            alias_b, "owner3",
        )

        return {
            "alias_a": alias_a, "alias_b": alias_b,
            "cid_a1": cid_a1, "cid_a2": cid_a2, "cid_b1": cid_b1,
        }


async def _cleanup(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, alias_id FROM euring_2020_canonical WHERE canonical_string LIKE 'TESTMASK_%'")
        cids = [r["id"] for r in rows]
        alias_ids = list({r["alias_id"] for r in rows if r["alias_id"] is not None})
        if alias_ids:
            await conn.execute("DELETE FROM alias_owner_visibility WHERE alias_id = ANY($1)", alias_ids)
            await conn.execute("DELETE FROM alias_sharing_intent WHERE alias_id = ANY($1)", alias_ids)
            # Storico immutabile (migrazione 006, 07/09/2026) -- va ripulito
            # anche lui prima di poter cancellare ring_alias (stesso vincolo
            # di chiave esterna delle altre tabelle sopra).
            await conn.execute("DELETE FROM alias_sharing_intent_log WHERE alias_id = ANY($1)", alias_ids)
        if cids:
            await conn.execute("DELETE FROM euring_2020_canonical WHERE id = ANY($1)", cids)  # CASCADE su field_values
        if alias_ids:
            await conn.execute("DELETE FROM ring_alias WHERE alias_id = ANY($1)", alias_ids)
        print(f"Pulizia fatta: {len(cids)} righe canonical, {len(alias_ids)} alias di test rimossi.")


async def main():
    pool = await asyncpg.create_pool(_db_url(), min_size=1, max_size=3)
    print("Connesso a Postgres. Applico schema/migrazioni...")
    await _apply_schema_and_migrations(pool)

    # Da qui in poi ci sono dati di test nel DB -- tutto il resto deve stare
    # dentro il try/finally, altrimenti un errore prima del blocco (come
    # successo il 04/09/2026 con un bug nella validazione email) lascia le
    # righe TESTMASK_ orfane nel database senza pulizia automatica.
    try:
        ids = await _seed(pool)
        print(f"Dati di test creati: {ids}")

        db = DatabaseService()
        db.pool = pool

        users = {
            "anonimo": None,
            "viewer": _mk_user("test_viewer", UserRole.VIEWER),
            "user": _mk_user("test_user", UserRole.USER),
            "rings_admin_match": _mk_user("test_ra_match", UserRole.RINGS_ADMIN, ringing_scheme="TESTSCHEME_A"),
            "rings_admin_no_match": _mk_user("test_ra_nomatch", UserRole.RINGS_ADMIN, ringing_scheme="TESTSCHEME_ALTRO"),
            "super_admin": _mk_user("test_super", UserRole.SUPER_ADMIN),
        }

        print("\n=== search_canonical_2020 ===")
        levels_seen = {}
        for label, u in users.items():
            result = await db.search_canonical_2020({}, page=1, page_size=50, requesting_user=u)
            our_rows = [r for r in result["results"] if r["id"] in (ids["cid_a1"], ids["cid_a2"], ids["cid_b1"])]
            levels = {r["id"]: r["level"] for r in our_rows}
            levels_seen[label] = levels
            print(f"  {label}: {len(our_rows)} righe di test trovate, livelli = {levels}")
            for r in our_rows:
                if r["level"] < 3:
                    assert r["canonical_string"] is None, f"BUG: canonical_string non deve essere presente sotto Livello 3 ({label})"
                    assert "ringing scheme" not in (r["masked_fields"] or {}), f"BUG: 'ringing scheme' reale trapelato a {label}!"

        # Verifiche chiave sui livelli attesi
        assert levels_seen["anonimo"].get(ids["cid_b1"]) == 3, "l'evento pubblico deve essere Livello 3 anche per l'anonimo"
        assert ids["cid_a1"] not in levels_seen["anonimo"] and ids["cid_a2"] not in levels_seen["anonimo"], \
            "l'anonimo non deve vedere affatto gli eventi privati (nemmeno mascherati)"
        assert levels_seen["viewer"][ids["cid_a1"]] == 1, "viewer senza rapporto col dato deve essere Livello 1"
        assert levels_seen["user"][ids["cid_a1"]] == 2, "user senza rapporto col dato deve essere Livello 2"
        assert levels_seen["rings_admin_match"][ids["cid_a1"]] == 3, "rings_admin con scheme che combacia deve essere Livello 3 su TUTTO l'alias"
        assert levels_seen["rings_admin_match"][ids["cid_a2"]] == 3, "elevazione rings_admin deve coprire l'INTERO alias, non solo l'evento che matcha"
        assert levels_seen["rings_admin_no_match"][ids["cid_a1"]] == 2, "rings_admin senza match deve restare Livello 2 di default"
        assert levels_seen["super_admin"][ids["cid_a1"]] == 3, "super_admin deve essere sempre Livello 3"
        print("  OK: tutte le verifiche sui livelli attese sono passate.")

        print("\n=== facet_counts_2020 ('ringing scheme' non deve mai contare righe sotto Livello 3) ===")
        for label, u in users.items():
            facets = await db.facet_counts_2020(["ringing scheme", "species concluded"], {}, requesting_user=u)
            scheme_values = [f["value"] for f in facets.get("ringing scheme", [])]
            species_values = [f["value"] for f in facets.get("species concluded", [])]
            print(f"  {label}: ringing_scheme facet values={scheme_values[:5]}, species facet values={species_values[:5]}")
        # Il viewer (Livello 1 di default, nessuna elevazione) non deve MAI
        # vedere 'TESTSCHEME_A' (alias A, privato: cid_a1/cid_a2 senza alcuna
        # visibilita' pubblica/condivisa) nella faccetta scheme.
        # 'TESTSCHEME_B' invece e' LEGITTIMO che compaia: appartiene a cid_b1,
        # reso pubblico via alias_owner_visibility nel seed -- un record
        # pubblico e' Livello 3 per chiunque per definizione, quindi il suo
        # scheme reale in faccetta non e' una fuga di dati (corretto durante
        # la verifica il 04/09/2026: l'assert originale non distingueva i due
        # casi).
        facets_viewer = await db.facet_counts_2020(["ringing scheme"], {}, requesting_user=users["viewer"])
        viewer_scheme_values = [f["value"] for f in facets_viewer.get("ringing scheme", [])]
        assert "TESTSCHEME_A" not in viewer_scheme_values, \
            "BUG PRIVACY: un viewer non deve mai vedere lo scheme reale di un alias privato nella faccetta 'ringing scheme'"
        assert "TESTSCHEME_B" in viewer_scheme_values, \
            "un viewer DEVE vedere lo scheme reale di un alias reso pubblico (e' Livello 3 per chiunque)"
        print("  OK: solo lo scheme dell'alias pubblico compare in faccetta per un viewer, non quello privato.")

        print("\n=== get_alias_life_history (alias A, deve avere masked_fields ma mai lo scheme reale sotto L3) ===")
        for label, u in [("viewer", users["viewer"]), ("rings_admin_match", users["rings_admin_match"])]:
            history = await db.get_alias_life_history(ids["alias_a"], u)
            print(f"  {label}: {len(history)} eventi, kinds={[e['kind'] for e in history]}")
            for e in history:
                if e["kind"] == "masked":
                    assert "ringing scheme" not in e["masked_fields"], f"BUG: scheme reale in life_history mascherata per {label}"
        print("  OK.")

        print("\n=== storico condivisione mirata (migrazione 006, 07/09/2026) ===")
        # owner1 e owner2 possiedono entrambi un evento su alias_a (vedi
        # _seed) -- condizione richiesta da set_alias_sharing_intent per
        # accettare la scelta (entrambi devono essere proprietari reali).
        ok1 = await db.set_alias_sharing_intent(
            alias_id=ids["alias_a"], from_username="owner1", to_username="owner2",
            state="offered", message="Prima proposta di condivisione",
        )
        assert ok1, "set_alias_sharing_intent (1a chiamata) doveva riuscire"
        ok2 = await db.set_alias_sharing_intent(
            alias_id=ids["alias_a"], from_username="owner1", to_username="owner2",
            state="declined", message="Ripensandoci, rifiuto",
        )
        assert ok2, "set_alias_sharing_intent (2a chiamata) doveva riuscire"
        ok3 = await db.set_alias_sharing_intent(
            alias_id=ids["alias_a"], from_username="owner1", to_username="owner2",
            state="offered", message="Ho cambiato ancora idea, condivido",
        )
        assert ok3, "set_alias_sharing_intent (3a chiamata) doveva riuscire"

        status_owner1 = await db.get_my_sharing_status(ids["alias_a"], "owner1")
        assert status_owner1 is not None, "owner1 possiede dati su alias_a, get_my_sharing_status non deve fallire"
        other = next((o for o in status_owner1["others"] if o["username"] == "owner2"), None)
        assert other is not None, "owner2 deve comparire come 'other' per owner1"

        # Stato ATTUALE (alias_sharing_intent, UPSERT) deve riflettere SOLO
        # l'ultima chiamata -- comportamento invariato, non stiamo toccando
        # questa logica.
        assert other["my_state"] == "offered", "lo stato attuale deve essere l'ultimo impostato (offered)"
        assert other["my_message"] == "Ho cambiato ancora idea, condivido", \
            "il messaggio attuale deve essere l'ultimo impostato"

        # Storico (alias_sharing_intent_log, append-only) deve avere TUTTE
        # e 3 le chiamate, in ordine cronologico -- questo e' il punto
        # centrale della richiesta di Davide: nessuna delle 3 versioni deve
        # andare perduta.
        history = other["history"]
        assert len(history) == 3, f"lo storico deve avere le 3 chiamate fatte, trovate {len(history)}"
        assert [h["state"] for h in history] == ["offered", "declined", "offered"], \
            "lo storico deve riflettere l'ordine cronologico esatto degli stati impostati"
        assert [h["message"] for h in history] == [
            "Prima proposta di condivisione", "Ripensandoci, rifiuto", "Ho cambiato ancora idea, condivido",
        ], "lo storico deve conservare TUTTI i messaggi precedenti, non solo l'ultimo"
        assert all(h["from_username"] == "owner1" for h in history), \
            "tutte le voci di questo storico sono state scritte da owner1 verso owner2"

        # Simmetria: owner2 deve vedere lo STESSO storico (stessa relazione,
        # letta dall'altro lato) -- la cronologia non e' privata di chi la
        # consulta, e' condivisa tra i due proprietari coinvolti.
        status_owner2 = await db.get_my_sharing_status(ids["alias_a"], "owner2")
        other_from_2 = next((o for o in status_owner2["others"] if o["username"] == "owner1"), None)
        assert other_from_2 is not None
        assert len(other_from_2["history"]) == 3, "owner2 deve vedere lo stesso storico di owner1 (stessa relazione)"
        assert other_from_2["their_state"] == "offered", "owner2 deve vedere lo stato attuale di owner1 come 'their_state'"
        print("  OK: storico immutabile completo (3/3 voci), stato attuale coerente, simmetrico tra i due proprietari.")

        print("\nTUTTE LE VERIFICHE PASSATE.")

    finally:
        await _cleanup(pool)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
