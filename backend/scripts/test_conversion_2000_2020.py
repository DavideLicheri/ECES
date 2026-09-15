"""
Test end-to-end (non ancora un test automatico nel repo) della curatela
canonical_name/semantic_meaning: verifica che DomainConversionService
generi mapping/regole di trasformazione sensate fra 2000 e 2020, e prova a
parsare davvero un paio di stringhe reali recuperate da EPE.

Da lanciare da dentro backend/ (venv attiva):
    python3 scripts/test_conversion_2000_2020.py
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from app.models.euring_models import EuringVersion
from app.services.domain_conversion_service import DomainConversionService
from app.services.parsers.euring_2000_epe_compatible_parser import Euring2000EpeCompatibleParser

# alcune stringhe reali dal nostro archivio (epe_archivio.euring2000_raw)
STRINGHE_REALI = [
    "IABA0LN...1651001ZZ0624006240N0ZUUU33U-----0708199400700LI00+454660+0343100000004-------------",
    "IABA0K...26936401ZZ1099010990N0ZUUU00P-----0610199001100IA01+454943+0100339000004-------------",
    "IABA0B...04053901ZZ1277012770N0ZUUU00N-----1512198200800IA25+433504+0102741000004-------------",
]


def load_version(path):
    with open(path, encoding="utf-8") as fh:
        return EuringVersion(**json.load(fh))


async def main():
    v2000 = load_version("data/euring_versions/versions/euring_2000.json")
    v2020 = load_version("data/euring_versions/versions/euring_2020.json")

    svc = DomainConversionService()
    svc.load_versions([v2000, v2020])

    print("=== TUTTI i mapping generati da DomainConversionService (2000 -> 2020) ===")
    mappings = await svc.create_all_domain_conversion_mappings(v2000.id, v2020.id)
    for m in mappings:
        print(f"\n--- dominio: {m.domain} (compatibilita': {m.compatibility}, lossy: {m.lossy_conversion}) ---")
        if not m.field_mappings:
            print("  (nessun field_mapping)")
        for fm in m.field_mappings:
            print(f"  '{fm.source_field}' -> '{fm.target_field}' | tipo={fm.transformation_type} | funzione={fm.transformation_function} | accuratezza={fm.conversion_accuracy}")
        for note in (m.conversion_notes or []):
            print(f"  nota: {note}")

    print("\n\n=== Parsing di 3 stringhe reali con il parser EPE-compatibile ===")
    parser = Euring2000EpeCompatibleParser()
    campi_chiave_it = ["Osservatorio", "Specie conclusa", "Condizioni", "Circostanze", "Giorno", "Mese", "Anno"]
    for s in STRINGHE_REALI:
        s_pulita = s.rstrip()
        try:
            parsed = parser.to_dict(s_pulita)
            valori = {k: parsed.get(k) for k in campi_chiave_it}
            print(f"\nstringa (primi 40 char): {s_pulita[:40]}...")
            print(f"  lunghezza: {len(s_pulita)}")
            print(f"  validazioni EPE: {parsed.get('_epe_validations')}")
            print(f"  valori chiave: {valori}")
        except Exception as e:
            print(f"\nERRORE nel parsing di {s_pulita[:40]}...: {e}")


if __name__ == "__main__":
    asyncio.run(main())
