"""
Authentication models for ECES
"""
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, EmailStr
from datetime import datetime

class UserRole(str, Enum):
    """User roles in ECES system"""
    SUPER_ADMIN = "super_admin"      # Full access including matrix editing
    # RINGS_ADMIN sostituisce il precedente ADMIN generico (14/08/2026,
    # design piramide ruoli/livelli, docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md).
    # Coordinatore di un centro di inanellamento: stessa capacita' di ADMIN
    # (elenco utenti) + Livello 3 senza maschera sui dati del proprio
    # ringing_scheme e/o territorio (vedi campi sotto). Eventuali utenti
    # esistenti con valore "admin" salvato in users.json vanno migrati a
    # "rings_admin" -- se il caricamento fallisce con un errore di validazione
    # sul campo role, e' quello il sintomo.
    RINGS_ADMIN = "rings_admin"
    USER = "user"                    # Standard user access
    VIEWER = "viewer"                # Read-only access

class User(BaseModel):
    """User model"""
    id: str
    username: str
    email: EmailStr
    full_name: str
    role: UserRole
    department: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None
    # Consenso esplicito all'uso aggregato/anonimo dei propri dati per la
    # conoscenza semantica di Lizzy (HANDOFF.md, punti 16-17, 25/07/2026).
    # Opt-in: default False. Gli utenti esistenti al momento dell'introduzione
    # di questo campo non hanno la chiave in users.json -- il default Pydantic
    # qui sotto li rende non-consenzienti automaticamente, senza bisogno di
    # nessuna migrazione dati sul file JSON.
    consents_to_aggregate_analysis: bool = False
    # Campi per rings_admin (14/08/2026, design piramide ruoli/livelli).
    # Irrilevanti per gli altri ruoli, sempre opzionali/vuoti per loro --
    # stesso pattern non-migratorio del campo sopra: chi non ce li ha in
    # users.json li ottiene di default da Pydantic al caricamento.
    # ringing_scheme: il codice schema (tabella EURING ringing_scheme, 161
    # voci) di cui questo rings_admin e' responsabile -- assegnato a mano dal
    # super_admin, nessuna deduzione automatica.
    ringing_scheme: Optional[str] = None
    # territory_place_codes: place_code (tabella EURING, 2052 voci) su cui
    # questo rings_admin ha visibilita' di Livello 3 anche per anelli non del
    # proprio scheme. Deciso il 14/08/2026: per ora si assegna a livello di
    # intera nazione (un solo place_code "tutto il paese"), non sub-regionale
    # -- si puo' restringere in seguito, il campo stesso supporta gia' piu'
    # voci per quel caso futuro. Il criterio "territorio" NON e' ancora
    # confermato come convenzione reale dai centri EURING (Davide deve
    # verificare) -- il campo dati esiste ma va usato con cautela finche' non
    # confermato (docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md, punto aperto 1).
    territory_place_codes: List[str] = []
    # Promozione automatica viewer->user (punto aperto 2 del documento di
    # design, deciso con Davide 08/09/2026): quando un viewer archivia una
    # stringa genuinamente nuova (is_new=True, vedi archive_service.py) sotto
    # il proprio account, viene promosso a user. Il token JWT gia' in mano
    # al browser resta pero' "viewer" finche' non si rifa' login -- questo
    # flag lo segnala UNA TANTUM alla prossima lettura del profilo (login o
    # /api/auth/me), che lo consuma subito dopo (auth_api.py). Default False,
    # nessuna migrazione dati: chi non ce l'ha in users.json lo ottiene da
    # Pydantic al caricamento, stesso pattern non-migratorio degli altri
    # campi opzionali sopra.
    pending_promotion_notice: bool = False

class UserLogin(BaseModel):
    """Login request model"""
    username: str
    password: str

class UserCreate(BaseModel):
    """User creation model"""
    username: str
    email: EmailStr
    full_name: str
    password: str
    role: UserRole = UserRole.USER
    department: Optional[str] = None
    consents_to_aggregate_analysis: bool = False

class Token(BaseModel):
    """JWT Token model"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: User

class TokenData(BaseModel):
    """Token payload data"""
    username: Optional[str] = None
    role: Optional[UserRole] = None

class UserRegistration(BaseModel):
    """User registration model (public)"""
    username: str
    email: EmailStr
    full_name: str
    password: str
    department: Optional[str] = None
    # Checkbox esplicita nel form di registrazione (punto 17): default False,
    # l'utente deve attivarla volontariamente. Revocabile/attivabile in
    # qualunque momento dopo la registrazione via PUT /auth/consent.
    consents_to_aggregate_analysis: bool = False

class UserRoleUpdate(BaseModel):
    """User role update model"""
    username: str
    new_role: UserRole

class RingsAdminAssignmentUpdate(BaseModel):
    """
    Assegnazione scheme/territorio per un rings_admin (priorita' #6 della
    scaletta, 02/09/2026 -- vedi docs/PROPOSTA_RUOLI_LIVELLI_CONDIVISIONE.md).
    Solo il super_admin puo' assegnare questi campi; l'endpoint verifica che
    l'utente target abbia gia' ruolo rings_admin.
    territory_place_code e' singolare (non una lista) per decisione esplicita
    di Davide il 14/08/2026: "ogni centro guarda per ora l'intera nazione",
    un solo place_code a testa -- il modello User.territory_place_codes resta
    List[str] per un eventuale futuro sub-regionale, ma oggi si assegna un
    solo valore (o nessuno, per rimuovere l'assegnazione).
    """
    username: str
    ringing_scheme: Optional[str] = None
    territory_place_code: Optional[str] = None

class UserListResponse(BaseModel):
    """User list response model"""
    users: list[User]
    total_count: int

class RegistrationResponse(BaseModel):
    """Registration response model"""
    success: bool
    message: str
    user: Optional[User] = None

class PasswordChange(BaseModel):
    """Password change model"""
    current_password: str
    new_password: str

class PasswordChangeResponse(BaseModel):
    """Password change response model"""
    success: bool
    message: str

class ConsentUpdate(BaseModel):
    """
    Aggiornamento del consenso all'uso aggregato/anonimo dei dati (punto 17).
    Revocabile in qualunque momento dall'utente stesso, da UserProfile.tsx.
    L'effetto riguarda solo le sottomissioni future, non retroattivo sui
    contatori gia' aggregati (non si puo' "disaggregare" un conteggio fatto).
    """
    consents_to_aggregate_analysis: bool

class ConsentUpdateResponse(BaseModel):
    """Risposta all'aggiornamento del consenso"""
    success: bool
    message: str
    consents_to_aggregate_analysis: bool