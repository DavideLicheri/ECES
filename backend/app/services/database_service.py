"""
Database service for ECES Analytics
PostgreSQL integration with connection pooling
"""
import asyncio
import asyncpg
import json
import hashlib
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, date, timedelta
from pathlib import Path
import os

from ..auth.models import User, UserRole
from ..models.euring_models import SemanticDomain
from .skos_manager import SKOSManagerImpl

logger = logging.getLogger(__name__)

# Priorita' #6 della scaletta (02-04/09/2026), piramide ruoli/livelli --
# vedi docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md. I 3 livelli di dettaglio
# sui 7 domini semantici EURING 2020:
#   Livello 1: SOLO species + methodology. Nessun identificativo.
#   Livello 2: Livello 1 + demographics + identification_marking MASCHERATO
#              (mai scheme/numero anello reale -- alias_id al suo posto).
#   Livello 3: tutti i 7 domini, identification_marking in chiaro.
# Principio: se un livello include un dominio, lo include per intero (mai
# singoli campi scelti dentro un dominio).
_LEVEL_1_DOMAINS = {SemanticDomain.SPECIES.value, SemanticDomain.METHODOLOGY.value}
_LEVEL_2_EXTRA_DOMAINS = {SemanticDomain.DEMOGRAPHICS.value, SemanticDomain.IDENTIFICATION_MARKING.value}

# Nomi campo EAV (euring_2020_field_values.field_name) usati per
# l'elevazione a Livello 3 di un rings_admin (vedi _resolve_visibility_level
# e le query sotto) -- stessi nomi gia' in uso in ARCHIVE_FACET_FIELDS
# (euring_api.py) e nei parsed_fields di get_alias_life_history.
_RINGING_SCHEME_FIELD = "ringing scheme"
_PLACE_CODE_FIELD = "place code"

class DatabaseService:
    """Service per gestione database PostgreSQL analytics"""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self.db_url = self._get_database_url()
        self.is_enabled = os.getenv("ENABLE_DATABASE_LOGGING", "false").lower() == "true"
        # Cache dominio->field_names per euring_2020, usata dal mascheramento
        # a livelli (priorita' #6). Istanza separata da quella di
        # euring_api.py/auth_api.py, stesso pattern gia' in uso altrove: sola
        # lettura, nessuno stato condiviso da sincronizzare.
        self._skos_manager = SKOSManagerImpl()
        self._domain_field_map_cache: Optional[Dict[str, List[str]]] = None

    def _get_database_url(self) -> str:
        """Costruisce URL database da variabili ambiente"""
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        database = os.getenv("DB_NAME", "eces_analytics")
        user = os.getenv("DB_USER", "eces_user")
        password = os.getenv("DB_PASSWORD", "eces_password")
        ssl_mode = os.getenv("PGSSLMODE", "prefer")
        
        # Costruisci URL con parametri SSL
        url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        if ssl_mode == "disable":
            url += "?sslmode=disable"
        
        return url
    
    async def initialize(self):
        """Inizializza connection pool PostgreSQL"""
        if not self.is_enabled:
            logger.info("Database logging disabled")
            return
            
        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
                server_settings={
                    'application_name': 'eces_analytics',
                    'timezone': 'UTC'
                }
            )
            logger.info("Database connection pool initialized")
            
            # Test connessione
            async with self.pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"Connected to PostgreSQL: {version}")
                
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            self.pool = None
    
    async def close(self):
        """Chiude connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")
    
    async def log_user_query(self, user: User, query_data: Dict[str, Any]) -> bool:
        """
        Registra query utente nel database
        
        Args:
            user: Utente che ha fatto la query
            query_data: Dati della query (tipo, stringa, risultato, etc.)
            
        Returns:
            bool: True se salvato con successo
        """
        if not self.pool or not self.is_enabled:
            return False
            
        try:
            async with self.pool.acquire() as conn:
                # Inserisci nella tabella user_queries
                await conn.execute("""
                    INSERT INTO user_queries (
                        user_id, username, user_role, query_type, input_string,
                        ip_address, user_agent, session_id, result_status,
                        result_data, processing_time_ms, euring_version_detected,
                        confidence_score
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """, 
                    user.id,
                    user.username,
                    user.role.value,
                    query_data['query_type'],
                    query_data['input_string'],
                    query_data.get('ip_address'),
                    query_data.get('user_agent'),
                    query_data.get('session_id'),
                    query_data['result_status'],
                    json.dumps(query_data['result_data']) if query_data.get('result_data') else None,
                    query_data.get('processing_time_ms', 0),
                    query_data.get('euring_version_detected'),
                    query_data.get('confidence_score')
                )
                
                # Aggiorna o inserisci nella tabella unique_strings
                await self._update_unique_strings(conn, query_data)
                
                logger.debug(f"Logged query for user {user.username}: {query_data['query_type']}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to log user query: {e}")
            return False
    
    async def get_usage_statistics(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """
        Genera statistiche d'uso per periodo specificato
        
        Args:
            start_date: Data inizio periodo
            end_date: Data fine periodo
            
        Returns:
            Dict con statistiche complete
        """
        if not self.pool:
            return {}
            
        try:
            async with self.pool.acquire() as conn:
                # Statistiche generali
                stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_queries,
                        COUNT(DISTINCT user_id) as unique_users,
                        COUNT(DISTINCT input_string) as unique_strings,
                        ROUND(AVG(processing_time_ms), 2) as avg_processing_time,
                        ROUND(
                            COUNT(*) FILTER (WHERE result_status = 'success') * 100.0 / COUNT(*), 
                            2
                        ) as success_rate,
                        MIN(timestamp) as first_query,
                        MAX(timestamp) as last_query
                    FROM user_queries 
                    WHERE date_only BETWEEN $1 AND $2
                """, start_date, end_date)
                
                # Top stringhe più testate
                top_strings = await conn.fetch("""
                    SELECT 
                        us.original_string,
                        us.total_queries,
                        us.successful_queries,
                        ROUND(us.successful_queries * 100.0 / us.total_queries, 2) as success_rate,
                        us.most_common_version,
                        us.string_length
                    FROM unique_strings us
                    WHERE us.string_hash IN (
                        SELECT DISTINCT encode(sha256(input_string::bytea), 'hex')
                        FROM user_queries 
                        WHERE date_only BETWEEN $1 AND $2
                    )
                    ORDER BY us.total_queries DESC 
                    LIMIT 10
                """, start_date, end_date)
                
                # Distribuzione versioni EURING
                version_dist = await conn.fetch("""
                    SELECT 
                        COALESCE(euring_version_detected, 'Unknown') as version,
                        COUNT(*) as count,
                        ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
                    FROM user_queries 
                    WHERE date_only BETWEEN $1 AND $2
                    GROUP BY euring_version_detected
                    ORDER BY count DESC
                """, start_date, end_date)
                
                # Utenti più attivi
                top_users = await conn.fetch("""
                    SELECT 
                        username,
                        COUNT(*) as query_count,
                        COUNT(DISTINCT input_string) as unique_strings_tested,
                        ROUND(AVG(processing_time_ms), 2) as avg_processing_time,
                        MAX(timestamp) as last_activity
                    FROM user_queries 
                    WHERE date_only BETWEEN $1 AND $2
                    GROUP BY user_id, username
                    ORDER BY query_count DESC
                    LIMIT 10
                """, start_date, end_date)
                
                # Trend giornaliero
                daily_trend = await conn.fetch("""
                    SELECT 
                        date_only,
                        COUNT(*) as queries,
                        COUNT(DISTINCT user_id) as active_users,
                        ROUND(AVG(processing_time_ms), 2) as avg_time
                    FROM user_queries 
                    WHERE date_only BETWEEN $1 AND $2
                    GROUP BY date_only
                    ORDER BY date_only
                """, start_date, end_date)
                
                return {
                    "period": {
                        "start": start_date.isoformat(),
                        "end": end_date.isoformat(),
                        "days": (end_date - start_date).days + 1
                    },
                    "summary": dict(stats) if stats else {},
                    "top_strings": [dict(row) for row in top_strings],
                    "version_distribution": [dict(row) for row in version_dist],
                    "top_users": [dict(row) for row in top_users],
                    "daily_trend": [dict(row) for row in daily_trend]
                }
                
        except Exception as e:
            logger.error(f"Failed to get usage statistics: {e}")
            return {}
    
    async def export_research_dataset(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Esporta dataset anonimizzato per ricerca scientifica
        
        Args:
            filters: Filtri per export (date, versioni, etc.)
            
        Returns:
            Lista di record anonimizzati
        """
        if not self.pool:
            return []
            
        try:
            start_date = filters.get('start_date', date.today() - timedelta(days=30))
            end_date = filters.get('end_date', date.today())
            min_confidence = filters.get('min_confidence', 0.0)
            
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT 
                        input_string,
                        euring_version_detected,
                        confidence_score,
                        result_status,
                        processing_time_ms,
                        date_only,
                        EXTRACT(HOUR FROM timestamp) as hour_of_day,
                        input_length,
                        (result_data->>'field_count')::integer as field_count
                    FROM user_queries
                    WHERE date_only BETWEEN $1 AND $2
                        AND result_status = 'success'
                        AND (confidence_score IS NULL OR confidence_score >= $3)
                    ORDER BY timestamp
                """, start_date, end_date, min_confidence)
                
                # Anonimizza e restituisce
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Failed to export research dataset: {e}")
            return []
    
    async def get_string_analytics(self, string_hash: str) -> Dict[str, Any]:
        """
        Ottieni analytics dettagliate per una stringa specifica
        
        Args:
            string_hash: Hash SHA256 della stringa
            
        Returns:
            Dict con analytics della stringa
        """
        if not self.pool:
            return {}
            
        try:
            async with self.pool.acquire() as conn:
                # Info stringa
                string_info = await conn.fetchrow("""
                    SELECT * FROM unique_strings WHERE string_hash = $1
                """, string_hash)
                
                if not string_info:
                    return {}
                
                # Cronologia test
                test_history = await conn.fetch("""
                    SELECT 
                        timestamp,
                        username,
                        result_status,
                        euring_version_detected,
                        confidence_score,
                        processing_time_ms
                    FROM user_queries 
                    WHERE encode(sha256(input_string::bytea), 'hex') = $1
                    ORDER BY timestamp DESC
                    LIMIT 50
                """, string_hash)
                
                return {
                    "string_info": dict(string_info),
                    "test_history": [dict(row) for row in test_history]
                }
                
        except Exception as e:
            logger.error(f"Failed to get string analytics: {e}")
            return {}
    
    async def update_daily_statistics(self, target_date: Optional[date] = None):
        """
        Aggiorna statistiche giornaliere pre-calcolate
        
        Args:
            target_date: Data per cui calcolare statistiche (default: oggi)
        """
        if not self.pool:
            return
            
        if target_date is None:
            target_date = date.today()
            
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("SELECT update_daily_statistics($1)", target_date)
                logger.info(f"Updated daily statistics for {target_date}")
                
        except Exception as e:
            logger.error(f"Failed to update daily statistics: {e}")
    
    async def cleanup_old_data(self, retention_days: int = 365) -> int:
        """
        Pulisce dati vecchi secondo retention policy
        
        Args:
            retention_days: Giorni di retention (default: 365)
            
        Returns:
            Numero di record eliminati
        """
        if not self.pool:
            return 0
            
        try:
            async with self.pool.acquire() as conn:
                deleted_count = await conn.fetchval(
                    "SELECT cleanup_old_data($1)", retention_days
                )
                logger.info(f"Cleaned up {deleted_count} old records")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            return 0

    async def upsert_euring_2020_canonical(
        self,
        canonical_string: str,
        parsed_fields: Dict[str, Any],
        field_count: int,
        field_positions: Dict[str, int],
        owner_username: Optional[str] = None,
    ) -> Optional[Tuple[int, bool, List[str], Optional[int]]]:
        """
        Persiste una stringa EURING 2020 gia' parsata "pulita" (64/64 campi)
        nell'archivio canonico a faccette.

        Le righe EAV (euring_2020_field_values) vengono inserite SOLO alla
        prima comparsa di questa stringa esatta (string_hash nuovo): se la
        stringa e' gia' nota, si aggiornano solo last_seen/occurrence_count
        su euring_2020_canonical, i valori di campo non cambiano (la stessa
        stringa produce sempre lo stesso parsing).

        Al primo inserimento vengono anche risolti (HANDOFF.md, punti 6-11,
        migrazione 003):
          - alias_id: upsert su ring_alias per (ringing scheme, identification
            number) estratti da parsed_fields -- calcolato indipendentemente
            dalla visibilita' (punto 10).
          - owner_username (visibility resta sempre 'private' qui, colonna
            ormai vestigiale -- vedi sotto).

        **Redesign 07/08/2026 (HANDOFF.md, migrazione 005)**: rimossa la
        condivisione automatica che flippava visibility='shared' e scriveva
        euring_2020_shared_with nell'istante in cui un secondo proprietario
        toccava lo stesso alias -- rendeva "richiedi contatto" irraggiungibile
        in ogni scenario reale (trovato 03/08/2026) e non lasciava mai al
        primo proprietario la scelta se condividere. Ora, se esistono altri
        proprietari sullo stesso alias, NON si tocca alcuna visibilita' qui:
        si restituisce solo l'elenco per permettere al chiamante (archive_
        service.py) di inviare una notifica generica ("qualcuno ha toccato
        uno dei tuoi anelli", mai il contenuto del dato) -- la scelta di
        condividere resta sempre e solo del proprietario, tramite le nuove
        tabelle alias_sharing_intent (condivisione mirata reciproca) e
        alias_owner_visibility (pubblico, unilaterale), entrambe per
        (alias, proprietario) e gestite altrove, non da questa funzione.

        Le occorrenze successive della stessa identica stringa NON toccano
        owner_username/visibility/alias_id (gia' fissati al primo inserimento).

        Args:
            canonical_string: stringa EURING 2020 completa (pipe-delimited)
            parsed_fields: {field_name: value} da Euring2020PositionParser
            field_count: numero di segmenti trovati (atteso: 64)
            field_positions: {field_name: position} per popolare l'EAV
            owner_username: chi ha sottomesso questa stringa (None se non
                disponibile -- il record risultera' senza proprietario finche'
                non viene backfillato)

        Returns:
            Tupla (id, is_new, other_owners, alias_id) -- is_new=True solo se
            questa e' la prima volta che questa esatta stringa viene
            archiviata (rilevante per non incrementare due volte i contatori
            aggregati di Lizzy, vedi archive_service.py). other_owners:
            elenco (senza duplicati) degli username di altri proprietari gia'
            presenti su questo stesso alias al momento dell'inserimento --
            vuoto se non e' un nuovo record, se non c'e' alias, o se e' il
            primo proprietario. alias_id: None se la stringa non ha
            ringing_scheme/identification_number validi. None (l'intera
            tupla) se il logging su database e' disabilitato o in caso di
            errore (mai un'eccezione: l'archiviazione non deve mai far
            fallire la richiesta principale).
        """
        if not self.pool or not self.is_enabled:
            return None

        string_hash = hashlib.sha256(canonical_string.encode()).hexdigest()

        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    existing_id = await conn.fetchval(
                        "SELECT id FROM euring_2020_canonical WHERE string_hash = $1",
                        string_hash,
                    )

                    if existing_id is not None:
                        await conn.execute(
                            """
                            UPDATE euring_2020_canonical
                            SET last_seen = NOW(), occurrence_count = occurrence_count + 1
                            WHERE id = $1
                            """,
                            existing_id,
                        )
                        # alias_id non serve al chiamante qui: la notifica di
                        # "alias toccato" scatta solo per is_new=True (vedi
                        # archive_service.py), quindi non vale la pena di una
                        # query aggiuntiva per popolarlo su questo ramo.
                        return existing_id, False, [], None

                    # --- Nuovo record: risolvi alias + ownership ---
                    alias_id: Optional[int] = None
                    other_owners: List[str] = []

                    ringing_scheme = parsed_fields.get("ringing scheme")
                    identification_number = parsed_fields.get("identification number")

                    if ringing_scheme and identification_number:
                        alias_id = await conn.fetchval(
                            """
                            INSERT INTO ring_alias (ringing_scheme, identification_number)
                            VALUES ($1, $2)
                            ON CONFLICT (ringing_scheme, identification_number)
                            DO UPDATE SET ringing_scheme = EXCLUDED.ringing_scheme
                            RETURNING alias_id
                            """,
                            ringing_scheme.strip(),
                            identification_number.strip(),
                        )

                        if owner_username:
                            other_owner_rows = await conn.fetch(
                                """
                                SELECT DISTINCT owner_username
                                FROM euring_2020_canonical
                                WHERE alias_id = $1
                                  AND owner_username IS NOT NULL
                                  AND owner_username != $2
                                """,
                                alias_id,
                                owner_username,
                            )
                            other_owners = [row["owner_username"] for row in other_owner_rows]

                    canonical_id = await conn.fetchval(
                        """
                        INSERT INTO euring_2020_canonical
                            (canonical_string, string_hash, parsed_fields, field_count,
                             owner_username, visibility, alias_id)
                        VALUES ($1, $2, $3, $4, $5, 'private', $6)
                        RETURNING id
                        """,
                        canonical_string,
                        string_hash,
                        json.dumps(parsed_fields, ensure_ascii=False),
                        field_count,
                        owner_username,
                        alias_id,
                    )

                    field_rows = [
                        (canonical_id, field_positions[name], name, value)
                        for name, value in parsed_fields.items()
                        if name in field_positions
                    ]
                    if field_rows:
                        await conn.executemany(
                            """
                            INSERT INTO euring_2020_field_values
                                (canonical_id, field_position, field_name, field_value)
                            VALUES ($1, $2, $3, $4)
                            """,
                            field_rows,
                        )

                    return canonical_id, True, other_owners, alias_id

        except Exception as e:
            logger.error(f"Failed to upsert euring_2020_canonical: {e}")
            return None

    async def link_unique_string_to_canonical(self, input_string: str, canonical_id: int) -> None:
        """
        Collega una riga di unique_strings (dedup grezza, qualsiasi versione)
        al record canonico 2020 corrispondente.
        """
        if not self.pool or not self.is_enabled or canonical_id is None:
            return

        string_hash = hashlib.sha256(input_string.encode()).hexdigest()

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE unique_strings SET canonical_id = $1 WHERE string_hash = $2",
                    canonical_id,
                    string_hash,
                )
        except Exception as e:
            logger.error(f"Failed to link unique_strings to canonical: {e}")

    async def _get_domain_field_map(self) -> Dict[str, List[str]]:
        """
        Cache dominio->field_names (nomi EAV, es. 'ringing scheme') per
        euring_2020 -- usata dal mascheramento a livelli (priorita' #6,
        02-04/09/2026). Caricata una volta sola per processo, come il
        pattern gia' in uso per la validazione codici in auth_api.py.
        """
        if self._domain_field_map_cache is not None:
            return self._domain_field_map_cache

        await self._skos_manager.load_version_model()
        versions = await self._skos_manager.get_all_versions()
        candidates = [v for v in versions if v.year == 2020]
        target = max(candidates, key=lambda v: len(v.field_definitions)) if candidates else None

        mapping: Dict[str, List[str]] = {}
        if target:
            for f in target.field_definitions:
                if f.semantic_domain:
                    mapping.setdefault(f.semantic_domain.value, []).append(f.name)

        self._domain_field_map_cache = mapping
        return mapping

    def _rings_admin_elevation_sql(self, alias_id_expr: str, scheme_param: str, territory_param: str) -> str:
        """
        Frammento SQL booleano per l'elevazione a Livello 3 di un rings_admin
        (docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md): vero se ALMENO UN
        evento della storia di vita dell'alias (alias_id_expr, es. "c.alias_id")
        ha ringing_scheme o place_code coincidenti con quelli assegnati al
        rings_admin richiedente (PUT /api/auth/users/rings-admin-assignment).
        scheme_param/territory_param sono placeholder gia' pronti (es. "$3",
        "$4") -- possono essere NULL (rings_admin senza assegnazione, o
        richiedente di altro ruolo passato come NULL dal chiamante): in quel
        caso il relativo OR e' semplicemente sempre falso, nessuna elevazione.
        """
        return f"""(
            (
                {scheme_param}::text IS NOT NULL AND EXISTS (
                    SELECT 1 FROM euring_2020_field_values rsf
                    JOIN euring_2020_canonical rsc ON rsc.id = rsf.canonical_id
                    WHERE rsc.alias_id = {alias_id_expr}
                      AND rsf.field_name = '{_RINGING_SCHEME_FIELD}' AND rsf.field_value = {scheme_param}
                )
            ) OR (
                {territory_param}::text IS NOT NULL AND EXISTS (
                    SELECT 1 FROM euring_2020_field_values rpf
                    JOIN euring_2020_canonical rpc ON rpc.id = rpf.canonical_id
                    WHERE rpc.alias_id = {alias_id_expr}
                      AND rpf.field_name = '{_PLACE_CODE_FIELD}' AND rpf.field_value = {territory_param}
                )
            )
        )"""

    def _resolve_visibility_level(
        self, is_own: bool, is_public: bool, is_shared: bool,
        rings_admin_elevated: bool, role: Optional["UserRole"],
    ) -> int:
        """
        Livello 1/2/3 finale per una riga (priorita' #6). Le 4 condizioni di
        elevazione (proprietario, reso pubblico, condiviso mirato reciproco,
        rings_admin con un evento dell'alias nel proprio scheme/territorio)
        portano SEMPRE a Livello 3, indipendentemente dal ruolo. Altrimenti
        il livello di default dipende dal ruolo (tabella del documento di
        design): viewer=1, user=2, rings_admin=2 (elevazione gia' gestita
        sopra), super_admin=3 su tutto.

        Nota: questa funzione presuppone requesting_user non None -- per
        l'anonimo il WHERE delle query sotto resta binario/solo-pubblico
        (decisione di Davide 04/09/2026, invariata rispetto a prima), quindi
        ogni riga che arriva fin qui per un anonimo e' gia' is_public=True.
        """
        if is_own or is_public or is_shared or rings_admin_elevated:
            return 3
        if role == UserRole.SUPER_ADMIN:
            return 3
        if role in (UserRole.RINGS_ADMIN, UserRole.USER):
            return 2
        return 1  # viewer, o ruolo non riconosciuto -- il piu' restrittivo

    async def _build_masked_fields_batch(
        self, conn, levels_by_canonical_id: Dict[int, int], alias_by_canonical_id: Dict[int, int],
    ) -> Dict[int, Dict[str, Any]]:
        """
        Costruisce, per ogni canonical_id sotto Livello 3, un dizionario
        field_name->field_value con SOLO i campi dei domini permessi dal
        livello calcolato -- MAI a partire da canonical_string (vincolo del
        documento di design: il mascheramento non redige la stringa grezza,
        costruisce un oggetto nuovo dai soli campi ammessi, letto dalla
        tabella EAV euring_2020_field_values che gia' esiste per questo).

        Le righe a Livello 3 non compaiono nel risultato -- per quelle il
        chiamante continua a restituire canonical_string per intero, come
        prima di questa modifica.

        A Livello 2, identification_marking non viene MAI incluso con il
        valore reale (scheme/numero anello) -- sostituito da un
        `masked_alias_id` stabile (l'alias_id interno, gia' esistente e
        indipendente dallo scheme/numero reale).
        """
        ids_to_mask = [cid for cid, lvl in levels_by_canonical_id.items() if lvl < 3]
        if not ids_to_mask:
            return {}

        domain_map = await self._get_domain_field_map()
        level1_fields = set(domain_map.get(SemanticDomain.SPECIES.value, [])) | \
            set(domain_map.get(SemanticDomain.METHODOLOGY.value, []))
        level2_fields = set(domain_map.get(SemanticDomain.DEMOGRAPHICS.value, []))
        all_needed = level1_fields | level2_fields

        result: Dict[int, Dict[str, Any]] = {cid: {} for cid in ids_to_mask}

        if all_needed:
            rows = await conn.fetch(
                """
                SELECT canonical_id, field_name, field_value
                FROM euring_2020_field_values
                WHERE canonical_id = ANY($1) AND field_name = ANY($2)
                """,
                ids_to_mask,
                list(all_needed),
            )
            for r in rows:
                cid = r["canonical_id"]
                level = levels_by_canonical_id[cid]
                fname = r["field_name"]
                if fname in level1_fields or (level >= 2 and fname in level2_fields):
                    result[cid][fname] = r["field_value"]

        for cid in ids_to_mask:
            if levels_by_canonical_id[cid] >= 2:
                result[cid]["masked_alias_id"] = alias_by_canonical_id.get(cid)

        return result

    async def search_canonical_2020(
        self, filters: Dict[str, str], page: int, page_size: int,
        requesting_user: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Ricerca a faccette sull'archivio canonico EURING 2020.

        filters: {field_name: field_value}, un solo valore per campo (AND tra
        campi diversi). Il pattern (field_name, field_value) IN (...) GROUP BY
        canonical_id HAVING COUNT(DISTINCT field_name) = N e' il modo standard
        per esprimere "un canonical_id deve avere una riga EAV corrispondente
        per OGNI filtro" senza self-join multipli.

        requesting_user: se fornito (utente loggato), la query NON esclude
        piu' nessuna riga per visibilita' -- **decisione di Davide,
        04/09/2026**: qualunque utente loggato vede almeno il Livello 1
        (mascherato) di TUTTO l'archivio, coerente con la tabella ruoli del
        documento di design (viewer=Livello 1 di default). Il risultato per
        riga porta invece un campo `level` (1/2/3) e, sotto Livello 3,
        `masked_fields` al posto di `canonical_string` (mai la stringa grezza
        sotto Livello 3, vincolo esplicito del documento di design).
        Se None (utente anonimo), il comportamento resta quello di prima
        (**invariato per decisione di Davide**): SOLO i record di alias resi
        pubblici, per intero. **Bug di privacy corretto 30/07/2026**: prima
        di quella correzione il metodo ignorava del tutto owner_username/
        visibility e restituiva sempre l'intero archivio a chiunque
        (HANDOFF.md, punti 6-11). **Redesign 07/08/2026 (migrazione 005)**:
        la colonna `visibility` non e' letta -- calcolata da
        alias_owner_visibility/alias_sharing_intent. **Redesign 02-04/09/2026
        (priorita' #6)**: aggiunto il calcolo del livello di dettaglio e il
        mascheramento per dominio, vedi _resolve_visibility_level/
        _build_masked_fields_batch sopra e docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md.
        """
        if not self.pool:
            return {"total": 0, "results": []}

        offset = max(0, (page - 1) * page_size)
        requesting_username = requesting_user.username if requesting_user else None

        try:
            async with self.pool.acquire() as conn:
                pairs = list(filters.items()) if filters else []
                field_params: List[Any] = []
                for name, value in pairs:
                    field_params.extend([name, value])

                if requesting_username:
                    vis_idx = len(field_params) + 1
                    scheme_idx = vis_idx + 1
                    territory_idx = vis_idx + 2

                    is_own_expr = f"(c.owner_username = ${vis_idx})"
                    is_public_expr = """EXISTS (
                        SELECT 1 FROM alias_owner_visibility av
                        WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                          AND av.is_public = true
                    )"""
                    is_shared_expr = f"""(
                        c.owner_username IS NOT NULL AND EXISTS (
                            SELECT 1 FROM alias_sharing_intent si1
                            WHERE si1.alias_id = c.alias_id AND si1.from_username = c.owner_username
                              AND si1.to_username = ${vis_idx} AND si1.state = 'offered'
                        ) AND EXISTS (
                            SELECT 1 FROM alias_sharing_intent si2
                            WHERE si2.alias_id = c.alias_id AND si2.from_username = ${vis_idx}
                              AND si2.to_username = c.owner_username AND si2.state = 'offered'
                        )
                    )"""
                    rings_admin_elevated_expr = self._rings_admin_elevation_sql(
                        "c.alias_id", f"${scheme_idx}", f"${territory_idx}"
                    )
                    # Etichetta da mostrare in tabella (pubblico/condiviso/privato),
                    # calcolata dalle stesse due tabelle -- non piu' c.visibility
                    # (ormai vestigiale, redesign 07/08/2026, migrazione 005).
                    # Nota: NON riflette il livello di dettaglio (vedi `level`
                    # sotto) -- resta un'etichetta indipendente sulla relazione
                    # proprietario/richiedente, come prima di questa modifica.
                    visibility_select = f"""CASE
                        WHEN {is_public_expr} THEN 'public'
                        WHEN c.owner_username IS NOT NULL AND c.owner_username != ${vis_idx} AND {is_shared_expr} THEN 'shared'
                        ELSE 'private'
                    END"""
                    visibility_params = [
                        requesting_username,
                        requesting_user.ringing_scheme,
                        requesting_user.territory_place_codes[0] if requesting_user.territory_place_codes else None,
                    ]
                    select_extra = f"""
                           {is_own_expr} AS is_own,
                           {is_public_expr} AS is_public,
                           {is_shared_expr} AS is_shared,
                           {rings_admin_elevated_expr} AS rings_admin_elevated
                    """
                    # Nessuna esclusione per visibilita': qualunque utente
                    # loggato vede almeno il Livello 1 mascherato di ogni
                    # riga (decisione di Davide 04/09/2026) -- il WHERE filtra
                    # solo per i filtri di ricerca, non per visibilita'.
                    visibility_where = None
                else:
                    visibility_where = """EXISTS (
                        SELECT 1 FROM alias_owner_visibility av
                        WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                          AND av.is_public = true
                    )"""
                    visibility_params = []
                    visibility_select = "'public'"
                    # WHERE (visibility_where sopra) restringe gia' l'anonimo
                    # ai soli record pubblici -- is_public=true e' quindi
                    # sempre corretto qui, is_own/is_shared/elevated non si
                    # applicano a un richiedente senza identita'.
                    select_extra = "false AS is_own, true AS is_public, false AS is_shared, false AS rings_admin_elevated"

                if pairs:
                    placeholders = ", ".join(
                        f"(${i * 2 + 1}, ${i * 2 + 2})" for i in range(len(pairs))
                    )
                    id_subquery = f"""
                        SELECT canonical_id FROM euring_2020_field_values
                        WHERE (field_name, field_value) IN ({placeholders})
                        GROUP BY canonical_id
                        HAVING COUNT(DISTINCT field_name) = {len(pairs)}
                    """
                    where_clause = f"c.id IN ({id_subquery})"
                else:
                    where_clause = "TRUE"
                if visibility_where:
                    where_clause = f"{where_clause} AND {visibility_where}"

                all_params = field_params + visibility_params

                # Il WHERE del conteggio usa solo field_params (id_subquery
                # sui filtri) -- mai i placeholder di visibilita'/scheme/
                # territorio, che compaiono solo nella SELECT della query
                # sotto, non nel WHERE. Passare *all_params qui darebbe un
                # mismatch di parametri in asyncpg (piu' argomenti passati
                # di quanti placeholder referenziati nel testo della query).
                total = await conn.fetchval(
                    f"SELECT COUNT(*) FROM euring_2020_canonical c WHERE {where_clause}",
                    *field_params,
                )
                rows = await conn.fetch(
                    f"""
                    SELECT c.id, c.canonical_string, c.field_count,
                           c.first_seen, c.last_seen, c.occurrence_count,
                           {visibility_select} AS visibility, c.alias_id,
                           {select_extra}
                    FROM euring_2020_canonical c
                    WHERE {where_clause}
                    ORDER BY c.first_seen DESC
                    LIMIT ${len(all_params) + 1} OFFSET ${len(all_params) + 2}
                    """,
                    *all_params,
                    page_size,
                    offset,
                )

                role = requesting_user.role if requesting_user else None
                levels_by_id: Dict[int, int] = {}
                alias_by_id: Dict[int, int] = {}
                for r in rows:
                    level = self._resolve_visibility_level(
                        r["is_own"], r["is_public"], r["is_shared"], r["rings_admin_elevated"], role
                    )
                    levels_by_id[r["id"]] = level
                    alias_by_id[r["id"]] = r["alias_id"]

                masked_by_id = await self._build_masked_fields_batch(conn, levels_by_id, alias_by_id)

                results = []
                for r in rows:
                    row = dict(r)
                    level = levels_by_id[row["id"]]
                    row["level"] = level
                    # Campi di lavoro non da esporre nella risposta API.
                    for internal_key in ("is_own", "is_public", "is_shared", "rings_admin_elevated"):
                        row.pop(internal_key, None)
                    if level < 3:
                        row["canonical_string"] = None
                        row["masked_fields"] = masked_by_id.get(row["id"], {})
                    else:
                        row["masked_fields"] = None
                    results.append(row)

                return {
                    "total": total or 0,
                    "results": results,
                }
        except Exception as e:
            logger.error(f"Failed to search euring_2020_canonical: {e}")
            return {"total": 0, "results": []}

    async def facet_counts_2020(
        self, field_names: List[str], filters: Dict[str, str],
        requesting_user: Optional[User] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Conteggi per faccetta su un elenco curato di campi (vedi
        ARCHIVE_FACET_FIELDS in euring_api.py). Prima versione: calcolati
        sull'intero archivio VISIBILE a requesting_user (non ricalcolati in
        base ai filtri gia' attivi -- semplificazione nota, una vera
        implementazione "drill down" escluderebbe il filtro sul campo stesso
        quando conta le sue faccette).

        requesting_user: None = solo record di alias resi pubblici,
        **invariato per decisione di Davide 04/09/2026** (bug di privacy
        corretto 30/07/2026, i conteggi non includono mai record privati/
        condivisi altrui per un anonimo). **Redesign 02-04/09/2026 (priorita'
        #6)**: per un utente loggato, ogni campo viene contato SOLO dalle
        righe il cui livello di dettaglio (Livello 1/2/3, stessa logica di
        search_canonical_2020) copre il dominio semantico di quel campo --
        es. 'ringing scheme' (dominio identification_marking) non viene mai
        contato da righe sotto Livello 3, altrimenti la distribuzione
        aggregata rivelerebbe scheme reali anche quando la riga singola e'
        mascherata. Il livello di default del ruolo (senza elevazione) e'
        costante per l'intera richiesta -- se copre gia' il dominio del
        campo, nessuna restrizione e' necessaria; altrimenti contano solo le
        righe elevate a Livello 3 (proprie/pubbliche/condivise/rings_admin
        con match di scheme/territorio).
        """
        if not self.pool:
            return {}

        requesting_username = requesting_user.username if requesting_user else None

        if requesting_user and requesting_user.role == UserRole.SUPER_ADMIN:
            default_level = 3
        elif requesting_user and requesting_user.role in (UserRole.RINGS_ADMIN, UserRole.USER):
            default_level = 2
        elif requesting_user:
            default_level = 1  # viewer
        else:
            default_level = 0  # anonimo, gestito a parte sotto

        domain_map = await self._get_domain_field_map()
        field_to_domain: Dict[str, str] = {}
        for domain, fields in domain_map.items():
            for f in fields:
                field_to_domain[f] = domain

        def required_level_for(field_name: str) -> int:
            domain = field_to_domain.get(field_name)
            if domain in (SemanticDomain.SPECIES.value, SemanticDomain.METHODOLOGY.value):
                return 1
            if domain == SemanticDomain.DEMOGRAPHICS.value:
                return 2
            # identification_marking, temporal, spatial, biometrics, o
            # dominio sconosciuto: mai in un conteggio aggregato sotto
            # Livello 3 -- il piu' restrittivo, coerente col vincolo "mai
            # valori reali di un dominio mascherato, nemmeno aggregati".
            return 3

        if requesting_username:
            # $1 e' sempre field_name (vedi sotto) -- $2/$3/$4 fissi qui
            # perche' a differenza di search_canonical_2020 non c'e' un
            # numero variabile di filtri prima di questi placeholder.
            is_own_expr = "(c.owner_username = $2)"
            is_public_expr = """EXISTS (
                SELECT 1 FROM alias_owner_visibility av
                WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                  AND av.is_public = true
            )"""
            is_shared_expr = """(
                c.owner_username IS NOT NULL AND EXISTS (
                    SELECT 1 FROM alias_sharing_intent si1
                    WHERE si1.alias_id = c.alias_id AND si1.from_username = c.owner_username
                      AND si1.to_username = $2 AND si1.state = 'offered'
                ) AND EXISTS (
                    SELECT 1 FROM alias_sharing_intent si2
                    WHERE si2.alias_id = c.alias_id AND si2.from_username = $2
                      AND si2.to_username = c.owner_username AND si2.state = 'offered'
                )
            )"""
            rings_admin_elevated_expr = self._rings_admin_elevation_sql("c.alias_id", "$3", "$4")
            elevation_clause = f"({is_own_expr} OR {is_public_expr} OR {is_shared_expr} OR {rings_admin_elevated_expr})"
            elevation_params = [
                requesting_username,
                requesting_user.ringing_scheme,
                requesting_user.territory_place_codes[0] if requesting_user.territory_place_codes else None,
            ]
        else:
            elevation_clause = """EXISTS (
                SELECT 1 FROM alias_owner_visibility av
                WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                  AND av.is_public = true
            )"""
            elevation_params = []

        try:
            async with self.pool.acquire() as conn:
                result: Dict[str, List[Dict[str, Any]]] = {}
                for field_name in field_names:
                    needed = required_level_for(field_name)
                    if requesting_user and default_level >= needed:
                        visibility_sql = ""
                        params: List[Any] = [field_name]
                    else:
                        visibility_sql = f"AND {elevation_clause}"
                        params = [field_name] + elevation_params
                    rows = await conn.fetch(
                        f"""
                        SELECT fv.field_value, COUNT(*) as cnt
                        FROM euring_2020_field_values fv
                        JOIN euring_2020_canonical c ON c.id = fv.canonical_id
                        WHERE fv.field_name = $1
                          AND fv.field_value IS NOT NULL AND fv.field_value != ''
                          {visibility_sql}
                        GROUP BY fv.field_value
                        ORDER BY cnt DESC
                        LIMIT 20
                        """,
                        *params,
                    )
                    result[field_name] = [
                        {"value": r["field_value"], "count": r["cnt"]} for r in rows
                    ]
                return result
        except Exception as e:
            logger.error(f"Failed to compute facet counts: {e}")
            return {}

    async def increment_lizzy_stats(
        self, species_code: str, place_code: str, pentad: int, ringing_scheme: str
    ) -> None:
        """
        Incrementa (o crea) il contatore aggregato e anonimo per una
        combinazione specie+luogo+pentade+schema (HANDOFF.md, punto 14a,
        migrazione 004). Nessun riferimento a canonical_id/utente/stringa in
        questa tabella -- solo il codice applicativo chiamante (vedi
        archive_service._maybe_increment_lizzy_stats) e' responsabile di
        verificare il consenso PRIMA di chiamare questo metodo.
        """
        if not self.pool or not self.is_enabled:
            return

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO lizzy_species_place_pentad_stats
                        (species_code, place_code, pentad, ringing_scheme, occurrence_count)
                    VALUES ($1, $2, $3, $4, 1)
                    ON CONFLICT (species_code, place_code, pentad, ringing_scheme)
                    DO UPDATE SET occurrence_count = lizzy_species_place_pentad_stats.occurrence_count + 1
                    """,
                    species_code,
                    place_code,
                    pentad,
                    ringing_scheme,
                )
        except Exception as e:
            logger.error(f"Failed to increment lizzy stats: {e}")

    async def get_lizzy_species_place_pentad_stats(
        self, species_code: str, place_code: str, pentad: int
    ) -> Dict[str, Any]:
        """
        Consultazione per Lizzy (punto 14a): conteggio totale per una
        combinazione specie+luogo+pentade, sommato su tutti gli schemi, PIU'
        il numero di schemi distinti dietro quel conteggio -- la
        "dichiarazione di provenienza" decisa il 30/07/2026 al posto di una
        soglia fissa di "sufficienza" (nessun giudizio di plausibilita' qui:
        solo i numeri grezzi, l'interpretazione resta a chi consuma questo
        dato).
        """
        if not self.pool:
            return {"total_occurrences": 0, "distinct_schemes": 0, "schemes": []}

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT ringing_scheme, occurrence_count
                    FROM lizzy_species_place_pentad_stats
                    WHERE species_code = $1 AND place_code = $2 AND pentad = $3
                    ORDER BY occurrence_count DESC
                    """,
                    species_code,
                    place_code,
                    pentad,
                )
                total = sum(r["occurrence_count"] for r in rows)
                return {
                    "total_occurrences": total,
                    "distinct_schemes": len(rows),
                    "schemes": [
                        {"ringing_scheme": r["ringing_scheme"], "count": r["occurrence_count"]}
                        for r in rows
                    ],
                }
        except Exception as e:
            logger.error(f"Failed to get lizzy stats: {e}")
            return {"total_occurrences": 0, "distinct_schemes": 0, "schemes": []}

    async def get_visible_events_for_alias(
        self, alias_id: int, requesting_user: Optional[User]
    ) -> List[Dict[str, Any]]:
        """
        Eventi per un dato alias_id (anello) visibili PER INTERO (Livello 3)
        a requesting_user: pubblici, propri, condivisi con lui, oppure -- se
        e' un rings_admin -- se ALMENO UN evento della storia di vita
        dell'alias combacia col suo scheme/territorio assegnato (stessa
        regola di elevazione di search_canonical_2020). requesting_user=None
        (anonimo) -> solo pubblici, invariato.

        Resta binario (fully-visible si'/no): la gradazione Livello 1/2 per
        gli eventi NON pienamente visibili e' compito di
        get_alias_life_history, non di questa funzione -- pensata solo per
        il conteggio "N eventi non condivisi con te" (HANDOFF.md, punti
        9-10), in coppia con count_all_events_for_alias.

        Non restituisce mai owner_username grezzo (potrebbe essere di un
        altro utente per i record pubblici/condivisi) -- solo un flag
        `is_own` calcolato, coerente con l'invariante del punto 6.

        **Redesign 07/08/2026 (migrazione 005)**: stessa logica a due tabelle
        (alias_owner_visibility/alias_sharing_intent) di search_canonical_2020
        e get_alias_life_history, non piu' la colonna `visibility`.
        **Redesign 02-04/09/2026 (priorita' #6)**: aggiunta l'elevazione
        rings_admin e il bypass super_admin (vede sempre tutto per intero).
        """
        if not self.pool:
            return []

        requesting_username = requesting_user.username if requesting_user else None

        visibility_case = """CASE
                                 WHEN EXISTS (
                                     SELECT 1 FROM alias_owner_visibility av
                                     WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                                       AND av.is_public = true
                                 ) THEN 'public'
                                 WHEN c.owner_username IS NOT NULL AND c.owner_username != $2 AND EXISTS (
                                     SELECT 1 FROM alias_sharing_intent si1
                                     WHERE si1.alias_id = c.alias_id AND si1.from_username = c.owner_username
                                       AND si1.to_username = $2 AND si1.state = 'offered'
                                 ) AND EXISTS (
                                     SELECT 1 FROM alias_sharing_intent si2
                                     WHERE si2.alias_id = c.alias_id AND si2.from_username = $2
                                       AND si2.to_username = c.owner_username AND si2.state = 'offered'
                                 ) THEN 'shared'
                                 ELSE 'private'
                               END AS visibility"""

        try:
            async with self.pool.acquire() as conn:
                if requesting_username and requesting_user.role == UserRole.SUPER_ADMIN:
                    # Il super_admin vede sempre tutto per intero -- nessuna
                    # restrizione nel WHERE, ma le etichette is_own/visibility
                    # restano calcolate per coerenza con l'endpoint.
                    rows = await conn.fetch(
                        f"""
                        SELECT c.id, c.canonical_string, c.field_count,
                               (c.owner_username = $2) AS is_own,
                               {visibility_case},
                               c.first_seen, c.last_seen, c.occurrence_count
                        FROM euring_2020_canonical c
                        WHERE c.alias_id = $1
                        ORDER BY c.first_seen
                        """,
                        alias_id,
                        requesting_username,
                    )
                elif requesting_username:
                    rings_admin_elevated_expr = self._rings_admin_elevation_sql("c.alias_id", "$3", "$4")
                    rows = await conn.fetch(
                        f"""
                        SELECT c.id, c.canonical_string, c.field_count,
                               (c.owner_username = $2) AS is_own,
                               {visibility_case},
                               c.first_seen, c.last_seen, c.occurrence_count
                        FROM euring_2020_canonical c
                        WHERE c.alias_id = $1
                          AND (
                            c.owner_username = $2
                            OR EXISTS (
                                SELECT 1 FROM alias_owner_visibility av
                                WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                                  AND av.is_public = true
                            )
                            OR (
                                c.owner_username IS NOT NULL AND EXISTS (
                                    SELECT 1 FROM alias_sharing_intent si1
                                    WHERE si1.alias_id = c.alias_id AND si1.from_username = c.owner_username
                                      AND si1.to_username = $2 AND si1.state = 'offered'
                                ) AND EXISTS (
                                    SELECT 1 FROM alias_sharing_intent si2
                                    WHERE si2.alias_id = c.alias_id AND si2.from_username = $2
                                      AND si2.to_username = c.owner_username AND si2.state = 'offered'
                                )
                            )
                            OR {rings_admin_elevated_expr}
                          )
                        ORDER BY c.first_seen
                        """,
                        alias_id,
                        requesting_username,
                        requesting_user.ringing_scheme,
                        requesting_user.territory_place_codes[0] if requesting_user.territory_place_codes else None,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT c.id, c.canonical_string, c.field_count,
                               false AS is_own,
                               'public' AS visibility,
                               c.first_seen, c.last_seen, c.occurrence_count
                        FROM euring_2020_canonical c
                        WHERE c.alias_id = $1 AND EXISTS (
                            SELECT 1 FROM alias_owner_visibility av
                            WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                              AND av.is_public = true
                        )
                        ORDER BY c.first_seen
                        """,
                        alias_id,
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Failed to get visible events for alias {alias_id}: {e}")
            return []

    async def count_all_events_for_alias(self, alias_id: int) -> int:
        """
        Conteggio TOTALE di eventi per un dato alias_id, senza filtro di
        visibilita' e senza restituire alcun contenuto -- il numero grezzo
        da cui sottrarre len(get_visible_events_for_alias(...)) per ottenere
        il conteggio del placeholder "N eventi non condivisi con te".
        """
        if not self.pool:
            return 0

        try:
            async with self.pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM euring_2020_canonical WHERE alias_id = $1",
                    alias_id,
                )
                return total or 0
        except Exception as e:
            logger.error(f"Failed to count events for alias {alias_id}: {e}")
            return 0

    async def get_alias_life_history(
        self, alias_id: int, requesting_user: Optional[User]
    ) -> List[Dict[str, Any]]:
        """
        Storia di vita di un anello (alias_id) per la UI dell'archivio, in
        ordine cronologico per data evento. Eventi a Livello 3 (`kind:
        'full'`, canonical_string per intero); eventi sotto Livello 3
        (`kind: 'masked'`) portano `level` + `masked_fields` (stessi campi
        per dominio di search_canonical_2020) **piu'** il segnaposto
        anno/nazione/specie deciso con Davide il 03/08/2026 -- carve-out
        esplicito e volutamente conservato sopra il mascheramento per
        dominio: anno (4 cifre di 'date') e nazione (primi 2 caratteri di
        'place code', che per definizione EURING identificano sempre il
        paese) sono normalmente campi dei domini temporal/spatial, bloccati
        fino a Livello 3 -- ma qui restano un'eccezione mirata e coarse
        (mai la data/luogo completi), pensata per intercettare errori di
        trascrizione (specie diversa tra eventi dello stesso alias fisico e'
        un segnale di anello letto/trascritto male da qualche parte). Mai
        numero di anello, mai proprietario.

        **Redesign 07/08/2026 (migrazione 005)**: `visibility` calcolata a
        runtime da alias_owner_visibility/alias_sharing_intent, non piu' la
        colonna omonima. **Redesign 02-04/09/2026 (priorita' #6)**: il
        precedente segnaposto fisso a 3 campi diventa mascheramento a
        Livello 1/2 completo (stessa logica di search_canonical_2020),
        mantenendo year/country/species_code in aggiunta per compatibilita'
        con la UI esistente e per non perdere il carve-out anti-frode.
        """
        if not self.pool:
            return []

        requesting_username = requesting_user.username if requesting_user else None

        try:
            async with self.pool.acquire() as conn:
                if requesting_username:
                    rings_admin_elevated_expr = self._rings_admin_elevation_sql("c.alias_id", "$3", "$4")
                    rows = await conn.fetch(
                        f"""
                        SELECT c.id, c.canonical_string, c.field_count,
                               (c.owner_username = $2) AS is_own,
                               CASE
                                 WHEN EXISTS (
                                     SELECT 1 FROM alias_owner_visibility av
                                     WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                                       AND av.is_public = true
                                 ) THEN 'public'
                                 WHEN c.owner_username IS NOT NULL AND c.owner_username != $2 AND EXISTS (
                                     SELECT 1 FROM alias_sharing_intent si1
                                     WHERE si1.alias_id = c.alias_id AND si1.from_username = c.owner_username
                                       AND si1.to_username = $2 AND si1.state = 'offered'
                                 ) AND EXISTS (
                                     SELECT 1 FROM alias_sharing_intent si2
                                     WHERE si2.alias_id = c.alias_id AND si2.from_username = $2
                                       AND si2.to_username = c.owner_username AND si2.state = 'offered'
                                 ) THEN 'shared'
                                 ELSE 'private'
                               END AS visibility,
                               c.first_seen, c.last_seen, c.occurrence_count,
                               EXISTS (
                                   SELECT 1 FROM alias_owner_visibility av
                                   WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                                     AND av.is_public = true
                               ) AS is_public,
                               (
                                 c.owner_username IS NOT NULL AND EXISTS (
                                     SELECT 1 FROM alias_sharing_intent si1
                                     WHERE si1.alias_id = c.alias_id AND si1.from_username = c.owner_username
                                       AND si1.to_username = $2 AND si1.state = 'offered'
                                 ) AND EXISTS (
                                     SELECT 1 FROM alias_sharing_intent si2
                                     WHERE si2.alias_id = c.alias_id AND si2.from_username = $2
                                       AND si2.to_username = c.owner_username AND si2.state = 'offered'
                                 )
                               ) AS is_shared,
                               {rings_admin_elevated_expr} AS rings_admin_elevated,
                               c.parsed_fields->>'date' AS event_date,
                               c.parsed_fields->>'place code' AS place_code,
                               COALESCE(
                                   c.parsed_fields->>'species concluded',
                                   c.parsed_fields->>'species mentioned'
                               ) AS species_code
                        FROM euring_2020_canonical c
                        WHERE c.alias_id = $1
                        """,
                        alias_id,
                        requesting_username,
                        requesting_user.ringing_scheme,
                        requesting_user.territory_place_codes[0] if requesting_user.territory_place_codes else None,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT c.id, c.canonical_string, c.field_count,
                               false AS is_own,
                               CASE
                                 WHEN EXISTS (
                                     SELECT 1 FROM alias_owner_visibility av
                                     WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                                       AND av.is_public = true
                                 ) THEN 'public'
                                 ELSE 'private'
                               END AS visibility,
                               c.first_seen, c.last_seen, c.occurrence_count,
                               EXISTS (
                                   SELECT 1 FROM alias_owner_visibility av
                                   WHERE av.alias_id = c.alias_id AND av.username = c.owner_username
                                     AND av.is_public = true
                               ) AS is_public,
                               false AS is_shared,
                               false AS rings_admin_elevated,
                               c.parsed_fields->>'date' AS event_date,
                               c.parsed_fields->>'place code' AS place_code,
                               COALESCE(
                                   c.parsed_fields->>'species concluded',
                                   c.parsed_fields->>'species mentioned'
                               ) AS species_code
                        FROM euring_2020_canonical c
                        WHERE c.alias_id = $1
                        """,
                        alias_id,
                    )

                role = requesting_user.role if requesting_user else None
                levels_by_id: Dict[int, int] = {}
                for r in rows:
                    is_own = r["is_own"] if requesting_username else False
                    levels_by_id[r["id"]] = self._resolve_visibility_level(
                        is_own, r["is_public"], r["is_shared"], r["rings_admin_elevated"], role
                    )
                # Livello 3 forzato per l'anonimo sulle righe restituite (il
                # WHERE le ha gia' filtrate a solo pubbliche sopra) -- stessa
                # cautela difensiva di search_canonical_2020.
                if not requesting_username:
                    levels_by_id = {cid: 3 for cid in levels_by_id}

                alias_by_id = {r["id"]: alias_id for r in rows}
                masked_by_id = await self._build_masked_fields_batch(conn, levels_by_id, alias_by_id)

                events = []
                for r in rows:
                    event_date = (r["event_date"] or "").strip()
                    sort_key = None
                    event_date_display = None
                    if len(event_date) == 8 and event_date.isdigit():
                        # DDMMYYYY -> YYYYMMDD, per ordinare cronologicamente
                        sort_key = event_date[4:8] + event_date[2:4] + event_date[0:2]
                        # DDMMYYYY -> DD/MM/YYYY per la UI. Questa e' la data
                        # EFFETTIVA dell'evento EURING (campo 'date'), non va
                        # confusa con first_seen/last_seen che sono timestamp
                        # di quando la stringa e' stata archiviata in ECES --
                        # possono differire anche di anni (bug trovato da
                        # Davide 04/08/2026: due eventi di anni diversi
                        # mostravano la stessa "prima vista" perche' importati
                        # nello stesso giorno di test).
                        event_date_display = f"{event_date[0:2]}/{event_date[2:4]}/{event_date[4:8]}"

                    level = levels_by_id[r["id"]]
                    if level >= 3:
                        events.append({
                            "kind": "full",
                            "id": r["id"],
                            "canonical_string": r["canonical_string"],
                            "field_count": r["field_count"],
                            "visibility": r["visibility"],
                            "is_own": r["is_own"] if requesting_username else False,
                            "event_date": event_date_display,
                            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                            "occurrence_count": r["occurrence_count"],
                            "sort_key": sort_key,
                        })
                    else:
                        place_code = (r["place_code"] or "").strip()
                        events.append({
                            "kind": "masked",
                            "level": level,
                            "masked_fields": masked_by_id.get(r["id"], {}),
                            # Carve-out anti-frode 03/08/2026, vedi docstring.
                            "year": event_date[4:8] if sort_key else None,
                            "country": place_code[:2] if len(place_code) >= 2 else None,
                            "species_code": r["species_code"],
                            "sort_key": sort_key,
                        })

                events.sort(key=lambda e: (e["sort_key"] is None, e["sort_key"] or ""))
                for e in events:
                    e.pop("sort_key", None)
                return events
        except Exception as e:
            logger.error(f"Failed to get life history for alias {alias_id}: {e}")
            return []

    async def _owns_alias(self, conn, alias_id: int, username: str) -> bool:
        """
        Vero se username possiede almeno un record su questo alias_id --
        usato come controllo di accesso su tutti i nuovi endpoint di
        condivisione (redesign 07/08/2026): solo chi ha gia' un proprio dato
        su un anello puo' vedere gli altri proprietari o impostare scelte di
        condivisione/pubblicazione per quell'anello. Impedisce a un utente
        estraneo di scoprire chi possiede dati su un alias a caso.
        """
        row = await conn.fetchval(
            "SELECT 1 FROM euring_2020_canonical WHERE alias_id = $1 AND owner_username = $2 LIMIT 1",
            alias_id, username,
        )
        return row is not None

    async def get_my_sharing_status(
        self, alias_id: int, username: str
    ) -> Optional[Dict[str, Any]]:
        """
        Stato delle scelte di condivisione di username per questo alias
        (redesign condivisione, migrazione 005, 07/08/2026): il proprio flag
        "pubblico" (per alias+proprietario) e, per ciascun altro proprietario
        dello stesso alias, lo stato reciproco (la mia scelta verso di lui, la
        sua verso di me -- entrambe visibili: username e' gia' un proprietario
        di questo stesso alias, non un estraneo, quindi conoscere l'altro
        proprietario e il suo stato non viola il punto 6 di HANDOFF.md, che
        protegge SOLO gli estranei senza dati propri sull'alias). None se
        username non possiede nulla su questo alias (accesso negato) o in
        caso di errore.
        """
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                if not await self._owns_alias(conn, alias_id, username):
                    return None

                is_public = await conn.fetchval(
                    "SELECT is_public FROM alias_owner_visibility WHERE alias_id = $1 AND username = $2",
                    alias_id, username,
                )

                other_owners = await conn.fetch(
                    """
                    SELECT DISTINCT owner_username
                    FROM euring_2020_canonical
                    WHERE alias_id = $1 AND owner_username IS NOT NULL AND owner_username != $2
                    """,
                    alias_id, username,
                )

                others = []
                for row in other_owners:
                    other_username = row["owner_username"]
                    my_intent = await conn.fetchrow(
                        "SELECT state, message FROM alias_sharing_intent WHERE alias_id = $1 AND from_username = $2 AND to_username = $3",
                        alias_id, username, other_username,
                    )
                    their_intent = await conn.fetchrow(
                        "SELECT state, message FROM alias_sharing_intent WHERE alias_id = $1 AND from_username = $2 AND to_username = $3",
                        alias_id, other_username, username,
                    )
                    # Storico immutabile delle scelte in ENTRAMBE le
                    # direzioni tra questi due proprietari (migrazione 006,
                    # 07/09/2026) -- risponde al rischio "nessuna prova in
                    # caso di disputa / messaggio modificato senza
                    # preavviso" sollevato da Davide. Ordine cronologico
                    # crescente cosi' la UI puo' mostrarlo come una lista
                    # "dal piu' vecchio al piu' recente".
                    history_rows = await conn.fetch(
                        """
                        SELECT from_username, state, message, decided_at
                        FROM alias_sharing_intent_log
                        WHERE alias_id = $1
                          AND ((from_username = $2 AND to_username = $3)
                            OR (from_username = $3 AND to_username = $2))
                        ORDER BY decided_at ASC, id ASC
                        """,
                        alias_id, username, other_username,
                    )
                    others.append({
                        "username": other_username,
                        "my_state": my_intent["state"] if my_intent else None,
                        "my_message": my_intent["message"] if my_intent else None,
                        "their_state": their_intent["state"] if their_intent else None,
                        # Messaggio che l'ALTRO ha scritto verso di me -- bug
                        # trovato in test 09/08/2026: prima si leggeva solo
                        # their_state, il messaggio (motivo stesso del campo,
                        # vedi migrazione 005) non arrivava mai al destinatario.
                        "their_message": their_intent["message"] if their_intent else None,
                        "mutually_shared": bool(
                            my_intent and my_intent["state"] == "offered"
                            and their_intent and their_intent["state"] == "offered"
                        ),
                        "history": [
                            {
                                "from_username": h["from_username"],
                                "state": h["state"],
                                "message": h["message"],
                                "decided_at": h["decided_at"].isoformat(),
                            }
                            for h in history_rows
                        ],
                    })

                return {"is_public": bool(is_public), "others": others}
        except Exception as e:
            logger.error(f"Failed to get sharing status for alias {alias_id}/{username}: {e}")
            return None

    async def set_alias_public(self, alias_id: int, username: str, is_public: bool) -> bool:
        """
        Imposta la scelta di username di rendere pubblico (o meno) il PROPRIO
        dato su questo alias -- unilaterale, non richiede reciprocita', non
        coinvolge gli altri proprietari dello stesso alias (redesign
        condivisione, migrazione 005, 07/08/2026). Verifica che username
        possieda gia' un record su questo alias prima di applicare.
        """
        if not self.pool:
            return False

        try:
            async with self.pool.acquire() as conn:
                if not await self._owns_alias(conn, alias_id, username):
                    return False

                await conn.execute(
                    """
                    INSERT INTO alias_owner_visibility (alias_id, username, is_public, decided_at)
                    VALUES ($1, $2, $3, NOW())
                    ON CONFLICT (alias_id, username)
                    DO UPDATE SET is_public = EXCLUDED.is_public, decided_at = NOW()
                    """,
                    alias_id, username, is_public,
                )
                return True
        except Exception as e:
            logger.error(f"Failed to set public visibility for alias {alias_id}/{username}: {e}")
            return False

    async def set_alias_sharing_intent(
        self, alias_id: int, from_username: str, to_username: str,
        state: str, message: Optional[str] = None
    ) -> bool:
        """
        Imposta la scelta di from_username di condividere (state='offered')
        o rifiutare (state='declined') il PROPRIO dato su questo alias con
        to_username -- efficace solo se anche to_username fa la stessa scelta
        verso from_username (reciprocita', verificata a lettura in
        get_alias_life_history/search_canonical_2020/facet_counts_2020, non
        qui). Aggiornabile in qualunque momento (UPSERT) -- si puo' sempre
        cambiare idea, nessun lock. Verifica che ENTRAMBI gli utenti
        possiedano gia' un record su questo alias prima di applicare (non si
        puo' scegliere di condividere con/rifiutare qualcuno che non e'
        realmente un proprietario di questo anello).
        """
        if not self.pool:
            return False
        if state not in ("offered", "declined"):
            return False

        try:
            async with self.pool.acquire() as conn:
                if not await self._owns_alias(conn, alias_id, from_username):
                    return False
                if not await self._owns_alias(conn, alias_id, to_username):
                    return False

                # Transazione: l'UPSERT sullo stato attuale e la riga di
                # storico (migrazione 006, 07/09/2026 -- vedi commento in
                # testa al file SQL) devono valere insieme o non valere
                # affatto, altrimenti uno stato "attuale" potrebbe non avere
                # mai una traccia corrispondente nello storico.
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO alias_sharing_intent
                            (alias_id, from_username, to_username, state, message, decided_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        ON CONFLICT (alias_id, from_username, to_username)
                        DO UPDATE SET state = EXCLUDED.state, message = EXCLUDED.message, decided_at = NOW()
                        """,
                        alias_id, from_username, to_username, state, message,
                    )
                    # Riga di storico immutabile -- MAI un UPDATE/DELETE su
                    # questa tabella da nessuna parte del codice, vedi
                    # commento su alias_sharing_intent_log in migrazione 006.
                    await conn.execute(
                        """
                        INSERT INTO alias_sharing_intent_log
                            (alias_id, from_username, to_username, state, message, decided_at)
                        VALUES ($1, $2, $3, $4, $5, NOW())
                        """,
                        alias_id, from_username, to_username, state, message,
                    )
                return True
        except Exception as e:
            logger.error(
                f"Failed to set sharing intent for alias {alias_id} {from_username}->{to_username}: {e}"
            )
            return False

    async def _update_unique_strings(self, conn, query_data: Dict[str, Any]):
        """
        Aggiorna la tabella unique_strings per tracciare stringhe duplicate
        
        Args:
            conn: Connessione database attiva
            query_data: Dati della query
        """
        input_string = query_data['input_string']
        string_hash = hashlib.sha256(input_string.encode()).hexdigest()
        is_successful = query_data['result_status'] == 'success'
        euring_version = query_data.get('euring_version_detected')
        
        # Usa UPSERT (INSERT ... ON CONFLICT) per gestire duplicati
        await conn.execute("""
            INSERT INTO unique_strings (
                string_hash, original_string, string_length, 
                total_queries, successful_queries, most_common_version,
                first_seen, last_seen
            ) VALUES (
                $1, $2, $3, 1, $4, $5, NOW(), NOW()
            )
            ON CONFLICT (string_hash) DO UPDATE SET
                total_queries = unique_strings.total_queries + 1,
                successful_queries = unique_strings.successful_queries + $4,
                last_seen = NOW(),
                most_common_version = CASE 
                    WHEN $5 IS NOT NULL THEN $5 
                    ELSE unique_strings.most_common_version 
                END
        """, 
            string_hash,
            input_string,
            len(input_string),
            1 if is_successful else 0,
            euring_version
        )

# Istanza globale del servizio
database_service = DatabaseService()