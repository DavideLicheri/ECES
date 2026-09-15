"""
Utilita' per il calendario fenologico usato dai contatori aggregati di Lizzy
(HANDOFF.md, punto 14a, decisione 30/07/2026: granularita' a pentadi invece
che a mesi, su richiesta di Davide -- 73 pentadi/anno, standard ornitologico
BTO/EURING per l'analisi della fenologia delle specie).

Convenzione sul 29 febbraio (anni bisestili): NON si fa slittare la
numerazione delle pentadi successive di un giorno. Si usa sempre una tabella
di riferimento non bisestile (febbraio = 28 giorni); il 29 febbraio viene
"fuso" nella stessa pentade del 28 febbraio. Questo mantiene la pentade N
allineata (quasi) alle stesse date di calendario ogni anno, comparabile
anno su anno -- ma le pentadi NON sono allineate ai confini dei mesi (28 non
e' divisibile per 5), caratteristica normale del sistema a pentadi, non un
bug.
"""
from datetime import date
from typing import Optional

# Giorni per mese, calendario di riferimento NON bisestile (fisso, sempre 28
# per febbraio) -- usato per calcolare il giorno-dell'anno in modo coerente
# indipendentemente dall'anno reale della stringa EURING.
_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def date_to_pentad(day: int, month: int) -> int:
    """
    Converte giorno+mese (1-12) nella pentade corrispondente (1-73).

    Il 29 febbraio (day=29, month=2) viene trattato come il 28 febbraio
    (fuso nella stessa pentade) -- vedi nota di modulo sulla convenzione.
    """
    if not (1 <= month <= 12):
        raise ValueError(f"Mese non valido: {month}")

    if month == 2 and day == 29:
        day = 28  # fusione 29/2 -> stessa pentade del 28/2

    if not (1 <= day <= _DAYS_IN_MONTH[month - 1]):
        raise ValueError(f"Giorno non valido per il mese {month}: {day}")

    day_of_year = sum(_DAYS_IN_MONTH[: month - 1]) + day
    pentad = ((day_of_year - 1) // 5) + 1
    return pentad


def parse_euring_date_to_pentad(date_str: Optional[str]) -> Optional[int]:
    """
    Estrae la pentade da un campo 'date' EURING in formato DDMMYYYY (8 cifre,
    confermato sui dati reali verificati oggi in produzione, es. '21082024',
    '15022026'). Ritorna None (non solleva eccezioni) se il campo e' assente,
    vuoto, non ha 8 cifre, o contiene un giorno/mese non valido -- coerente
    con la regola gia' in uso altrove nel progetto di non bloccare
    l'archiviazione principale per dati imperfetti.
    """
    if not date_str:
        return None

    date_str = date_str.strip()
    if len(date_str) != 8 or not date_str.isdigit():
        return None

    day = int(date_str[0:2])
    month = int(date_str[2:4])

    try:
        return date_to_pentad(day, month)
    except ValueError:
        return None


def parse_euring_date_to_date(date_str: Optional[str]) -> Optional[date]:
    """
    Estrae la data completa (giorno/mese/anno) da un campo 'date' EURING in
    formato DDMMYYYY (8 cifre) -- usata per la chiave dell'impronta
    anti-doppio-conteggio (lizzy_bootstrap_fingerprints, migrazione 008),
    NON per la pentade: qui l'anno conta e il 29 febbraio resta 29 febbraio
    (nessuna fusione col 28, a differenza di parse_euring_date_to_pentad,
    che e' solo per il bucketing fenologico). Ritorna None (non solleva
    eccezioni) se il campo e' assente, vuoto, non ha 8 cifre, o la data non
    e' valida -- stessa convenzione di non-blocco usata altrove.
    """
    if not date_str:
        return None

    date_str = date_str.strip()
    if len(date_str) != 8 or not date_str.isdigit():
        return None

    day = int(date_str[0:2])
    month = int(date_str[2:4])
    year = int(date_str[4:8])

    try:
        return date(year, month, day)
    except ValueError:
        return None


if __name__ == "__main__":
    # Esempi di verifica manuale -- eseguire con `python3 phenology_utils.py`
    examples = [
        (1, 1),    # 1 gennaio -> attesa pentade 1
        (5, 1),    # 5 gennaio -> fine pentade 1
        (6, 1),    # 6 gennaio -> inizio pentade 2
        (28, 2),   # 28 febbraio (non bisestile) -> ?
        (29, 2),   # 29 febbraio (bisestile, fuso col 28/2) -> deve dare stesso risultato di sopra
        (1, 3),    # 1 marzo -> ?
        (21, 8),   # 21 agosto (dalla stringa reale ESC vista oggi: 21082024)
        (15, 2),   # 15 febbraio (dalla stringa reale ESC vista oggi: 15022026)
        (31, 12),  # 31 dicembre -> attesa pentade 73 (ultima)
    ]
    for day, month in examples:
        print(f"{day:02d}/{month:02d} -> pentade {date_to_pentad(day, month)}")
