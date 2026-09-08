"""
Archive Service for ECES
=========================
Orchestrazione dell'archivio deduplicato + a faccette per le stringhe
EURING gestite da ECES (recognize/convert/parse).

Flusso per ogni stringa:
  1. Se non e' gia' in formato euring_2020, prova la conversione semantica
     a euring_2020 (riusando EuringConversionService, la stessa logica gia'
     usata da /api/euring/convert).
  2. Se la conversione fallisce, l'archiviazione si ferma qui (la stringa
     resta comunque nel log normale user_queries, come oggi).
  3. Parsa la stringa 2020 con Euring2020PositionParser (basato su
     euring_2020.json, non su un parser separato -- vedi quel modulo per
     il perche').
  4. Solo se il parsing e' "pulito" (esattamente 64/64 campi -- verificato
     su 12 stringhe reali il 23/07/2026, non tutte le stringhe reali lo
     sono: alcuni centri esportano un sottoinsieme di campi diverso, per
     motivi non ancora noti) la stringa entra nell'archivio a faccette.
     Niente parsing "best effort"/euristico per i casi non puliti --
     deciso esplicitamente il 23/07/2026 per non rischiare di produrre
     faccette con campi mappati male.

L'archiviazione non deve MAI far fallire la richiesta principale
(recognize/convert/parse): ogni eccezione viene loggata e inghiottita.
"""
import logging
from typing import Any, Dict, List, Optional

from .conversion_service import EuringConversionService
from .skos_manager import SKOSManagerImpl
from .parsers.euring_2020_position_parser import Euring2020PositionParser
from .database_service import database_service
from .phenology_utils import parse_euring_date_to_pentad
from .email_service import email_service
from ..auth.auth_service import AuthService

logger = logging.getLogger(__name__)


class ArchiveService:
    def __init__(self):
        # Istanze proprie di conversion_service/skos_manager/auth_service, non
        # condivise con quelle create in euring_api.py -- stesso pattern di
        # instanziazione gia' in uso nel resto del codice (non c'e' oggi una
        # vera dependency injection). Costo noto e accettato: la cache interna
        # di SKOSManagerImpl viene popolata una seconda volta (dati read-only,
        # nessun problema di correttezza, solo un parse JSON in piu' all'avvio).
        self._conversion_service = EuringConversionService()
        self._skos_manager = SKOSManagerImpl()
        self._parser: Optional[Euring2020PositionParser] = None
        # Usato SOLO per verificare consents_to_aggregate_analysis del
        # proprietario prima di incrementare i contatori aggregati di Lizzy
        # (punto 14a/16-17, migrazione 004) -- mai per altro in questo servizio.
        self._auth_service = AuthService()

    async def _get_parser(self) -> Euring2020PositionParser:
        if self._parser is None:
            version_model = await self._skos_manager.load_version_model()
            euring_2020 = next(v for v in version_model.versions if v.id == "euring_2020")
            self._parser = Euring2020PositionParser(euring_2020)
        return self._parser

    async def archive_string(
        self, euring_string: str, source_version: str,
        owner_username: Optional[str] = None
    ) -> Optional[int]:
        """
        Tenta di archiviare una stringa nell'archivio canonico 2020 a faccette.

        Args:
            euring_string: la stringa cosi' come ricevuta, in source_version
            source_version: uno tra 'euring_1966', 'euring_1979',
                'euring_2000', 'euring_2020'
            owner_username: chi ha sottomesso questa stringa (current_user.username
                dal punto di chiamata in euring_api.py). Usato SOLO al primo
                inserimento di un canonical_id (ownership/visibilita', punti 6-11
                della discussione 25/07/2026, HANDOFF.md) -- le occorrenze
                successive della stessa stringa non cambiano il proprietario
                originale. None se non disponibile (non dovrebbe succedere nei
                3 punti di chiamata attuali, tutti dietro autenticazione, ma la
                funzione non deve fallire se capita).

        Returns:
            canonical_id se archiviata con successo, altrimenti None.
            None NON e' un errore: significa solo che questa stringa non e'
            entrata nell'archivio a faccette (conversione non pulita, o
            parsing non a 64 campi esatti) -- resta comunque nel log
            normale (user_queries), nessun dato viene perso.
        """
        try:
            euring_string = (euring_string or "").strip()
            if not euring_string:
                return None

            if source_version == "euring_2020":
                canonical_string = euring_string
            else:
                result = self._conversion_service.convert_semantic(
                    euring_string, source_version, "euring_2020"
                )
                if not result.get("success") or not result.get("converted_string"):
                    logger.info(
                        f"Archiviazione saltata: conversione {source_version}->euring_2020 "
                        f"non riuscita ({result.get('error', 'motivo sconosciuto')})"
                    )
                    return None
                canonical_string = result["converted_string"].strip()

            parser = await self._get_parser()
            parsed = parser.parse(canonical_string)

            if not parsed["is_clean"]:
                logger.info(
                    f"Archiviazione saltata: parsing non pulito "
                    f"({parsed['field_count']}/{parsed['expected_field_count']} campi) "
                    f"-- {parsed['errors']}"
                )
                return None

            field_positions = {f.name: f.position for f in parser.fields_by_position}

            upsert_result = await database_service.upsert_euring_2020_canonical(
                canonical_string=canonical_string,
                parsed_fields=parsed["fields"],
                field_count=parsed["field_count"],
                field_positions=field_positions,
                owner_username=owner_username,
            )

            if upsert_result is None:
                return None

            canonical_id, is_new, other_owners, alias_id = upsert_result

            await database_service.link_unique_string_to_canonical(
                euring_string, canonical_id
            )

            # Contatori aggregati e anonimi per Lizzy (punto 14a, migrazione 004):
            # SOLO alla prima comparsa di questa stringa esatta (is_new -- non
            # ad ogni resottomissione dello stesso evento) e SOLO se il
            # proprietario ha esplicitamente dato consenso all'uso aggregato
            # (punto 16-17). Il conteggio non contiene mai canonical_id, utente,
            # o stringa -- solo specie+luogo+pentade+schema.
            if is_new and owner_username:
                await self._maybe_increment_lizzy_stats(parsed["fields"], owner_username)

            # Promozione automatica viewer->user (punto aperto 2 del documento
            # di design, deciso con Davide 08/09/2026): SOLO alla prima
            # comparsa genuina di questa stringa esatta (is_new, non ad ogni
            # resottomissione) e MAI per l'account 'lizzy' (che archivia in
            # background ad ogni sua chiamata /recognize o /convert -- vedi
            # euring_api.py e il commento su archive_service.archive_string
            # nella docstring del modulo -- promuoverla sarebbe un effetto
            # collaterale indesiderato della sua attivita' di consultazione,
            # non una vera contribuzione umana).
            if is_new and owner_username and owner_username != "lizzy":
                await self._maybe_promote_viewer(owner_username)

            # Notifica generica agli altri proprietari dello stesso alias
            # (redesign condivisione, migrazione 005, 07/08/2026) -- sostituisce
            # la vecchia condivisione automatica. Mai il contenuto del dato,
            # solo l'avviso che qualcun altro ha toccato lo stesso anello.
            if is_new and owner_username and other_owners and alias_id:
                await self._maybe_notify_alias_touch(
                    toucher_username=owner_username,
                    other_owners=other_owners,
                    alias_id=alias_id,
                )

            return canonical_id

        except Exception as e:
            logger.error(f"Errore durante l'archiviazione della stringa: {e}")
            return None

    async def _maybe_increment_lizzy_stats(
        self, parsed_fields: Dict[str, Any], owner_username: str
    ) -> None:
        """
        Incrementa lizzy_species_place_pentad_stats SOLO se: (a) il
        proprietario ha consents_to_aggregate_analysis=true in
        data/auth/users.json (verifica qui in Python, non via join SQL -- il
        consenso non vive in Postgres), e (b) tutti i campi necessari sono
        presenti e validi (specie, luogo, schema, data parsabile in pentade).
        Nessuna eccezione propagata: un errore qui non deve mai far fallire
        l'archiviazione principale (stesso principio di archive_string).
        """
        try:
            owner = self._auth_service.get_user(owner_username)
            if not owner or not owner.consents_to_aggregate_analysis:
                return

            species_code = (
                parsed_fields.get("species concluded")
                or parsed_fields.get("species mentioned")
            )
            # "current place code" e' un campo di correzione raro (usato solo
            # quando il "place code" originale diventa obsoleto, vedi
            # euring_2020.json field_definitions) -- quasi sempre vuoto.
            # "place code" e' il luogo effettivo dell'evento/osservazione,
            # il campo giusto per la fenologia. Bug trovato e corretto
            # 03/08/2026 verificando con dati reali che il contatore non si
            # sarebbe mai popolato altrimenti.
            place_code = parsed_fields.get("current place code") or parsed_fields.get("place code")
            ringing_scheme = parsed_fields.get("ringing scheme")
            pentad = parse_euring_date_to_pentad(parsed_fields.get("date"))

            if not (species_code and place_code and ringing_scheme and pentad):
                logger.info(
                    "Contatore Lizzy saltato: campi specie/luogo/schema/data "
                    "mancanti o data non parsabile."
                )
                return

            await database_service.increment_lizzy_stats(
                species_code=species_code.strip(),
                place_code=place_code.strip(),
                pentad=pentad,
                ringing_scheme=ringing_scheme.strip(),
            )
        except Exception as e:
            logger.error(f"Errore durante l'incremento dei contatori Lizzy: {e}")

    async def _maybe_promote_viewer(self, owner_username: str) -> None:
        """
        Promuove un viewer a user alla sua prima sottomissione genuinamente
        nuova (punto aperto 2 del documento di design, deciso con Davide
        08/09/2026). No-op silenzioso se l'utente non e' attualmente viewer
        (auth_service.promote_viewer_to_user ritorna None in quel caso, senza
        sollevare eccezioni -- vedi auth_service.py). Il chiamante
        (archive_string) garantisce gia' l'esclusione di 'lizzy' e la
        condizione is_new; qui ci si limita alla promozione + email.
        Nessuna eccezione propagata: stesso principio di
        _maybe_increment_lizzy_stats/_maybe_notify_alias_touch -- un errore
        qui non deve mai far fallire l'archiviazione principale.
        """
        try:
            promoted_user = self._auth_service.promote_viewer_to_user(owner_username)
            if promoted_user is None:
                return
            email_service.send_promotion_notification({
                "username": promoted_user.username,
                "email": promoted_user.email,
                "full_name": promoted_user.full_name,
            })
        except Exception as e:
            logger.error(
                f"Errore durante la promozione automatica viewer->user di {owner_username}: {e}"
            )

    async def _maybe_notify_alias_touch(
        self, toucher_username: str, other_owners: List[str], alias_id: int
    ) -> None:
        """
        Notifica generica (redesign condivisione, migrazione 005, 07/08/2026)
        a ciascun altro proprietario gia' presente sullo stesso alias: mai il
        contenuto del dato, solo l'avviso che qualcun altro l'ha toccato --
        sostituisce la vecchia condivisione automatica. La scelta di
        condividere resta sempre e solo del proprietario notificato (tramite
        alias_sharing_intent/alias_owner_visibility, non da questa funzione).
        Nessuna eccezione propagata: un errore qui non deve mai far fallire
        l'archiviazione principale (stesso principio di
        _maybe_increment_lizzy_stats).
        """
        for owner_username in other_owners:
            try:
                owner = self._auth_service.get_user(owner_username)
                if not owner:
                    continue
                email_service.send_alias_touched_notification(
                    owner_email=owner.email,
                    owner_full_name=owner.full_name,
                    toucher_username=toucher_username,
                    alias_id=alias_id,
                )
            except Exception as e:
                logger.error(
                    f"Errore durante la notifica di alias toccato a {owner_username}: {e}"
                )


# Istanza globale del servizio
archive_service = ArchiveService()
