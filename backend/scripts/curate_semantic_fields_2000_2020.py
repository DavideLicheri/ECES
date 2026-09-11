"""
Curatela canonical_name / semantic_meaning per i campi EURING2000 (34 campi)
ed EURING2020 (64 campi).

Popola i due campi previsti dal modello FieldDefinition
(backend/app/models/euring_models.py) e gia' usati da
domain_conversion_service.py._find_corresponding_field() per trovare la
corrispondenza fra campi di versioni diverse (matching per uguaglianza
esatta di stringa su semantic_meaning).

Fonte: descrizioni ufficiali gia' presenti nei due file versione, incrociate
con le specifiche EURING 2000/2020 (backend/data/documentation/version_specs/).

Deciso il 10-11/09/2026 con Davide Licheri: i campi corrispondenti fra 2000 e
2020 ricevono lo STESSO canonical_name e la STESSA stringa di semantic_meaning
(richiesto dalla logica di matching esistente). Il campo 2000 "biometrics"
(posizione 151) e' un blob di testo libero non strutturato, mai stato diviso
nei singoli campi biometrici del 2020: riceve un canonical_name/semantic_meaning
suo proprio, deliberatamente NON coincidente con nessuno dei 20 campi biometrici
del 2020, per non dichiarare una corrispondenza che non esiste davvero.
"""
import json

BASE = "backend/data/euring_versions/versions"

# posizione (2000) -> (canonical_name, semantic_meaning)
MAP_2000 = {
    1:  ("ring_scheme", "Code identifying the ringing scheme (issuing centre) responsible for the ring."),
    4:  ("primary_identification_method", "Primary method used to identify the bird (e.g. metal ring, colour ring, other mark)."),
    6:  ("ring_identification_number", "The ring number identifying this individual bird, up to ten alphanumeric characters."),
    16: ("metal_ring_verification", "Whether the metal ring was verified by the scheme."),
    17: ("metal_ring_information", "Additional information about the metal ring."),
    18: ("other_marks_information", "Information about marks other than the conventional metal ring."),
    20: ("species_reported", "Species as reported by the person who handled the bird."),
    25: ("species_concluded", "Species as concluded/confirmed by the ringing scheme."),
    30: ("manipulated", "Whether/how the bird was manipulated (e.g. moved, held in captivity) before release."),
    31: ("moved_before_encounter", "Whether the bird was moved before the ringing/recovery encounter."),
    32: ("catching_method", "Method used to catch the bird."),
    33: ("catching_lures", "Lures used to catch the bird."),
    34: ("sex_reported", "Sex as reported by the person who handled the bird."),
    35: ("sex_concluded", "Sex as concluded by the ringing scheme."),
    36: ("age_reported", "Age as reported by the person who handled the bird."),
    37: ("age_concluded", "Age as concluded by the ringing scheme."),
    38: ("status", "Status of the full-grown bird (e.g. free-flying, in captivity)."),
    39: ("brood_size", "Number of nestlings in the brood, for nestling records only."),
    41: ("pullus_age", "Age in days of a pullus (nestling)."),
    43: ("pullus_age_accuracy", "Accuracy of the recorded pullus age, in days either side."),
    44: ("event_date", "Date of the ringing/encounter event."),
    52: ("date_accuracy", "Accuracy of the recorded date."),
    53: ("event_time", "Time of day of the event, 24-hour local time."),
    57: ("place_code", "EURING place code identifying the geographical area of the event."),
    61: ("geographical_coordinates_encoded", "Encoded latitude/longitude of the event location (degrees/minutes/seconds format)."),
    76: ("coordinates_accuracy", "Accuracy of the recorded geographical coordinates."),
    77: ("condition", "Physical condition of the bird when found."),
    78: ("circumstances", "Circumstances under which the bird was encountered."),
    80: ("circumstances_presumed", "Whether the recorded circumstances are certain or presumed."),
    81: ("euring_code_identifier", "Identifies which EURING code version was used to encode this record."),
    82: ("distance", "Distance in kilometres between this record and the first (ringing) record."),
    87: ("direction", "Direction in degrees from the first (ringing) record to this record."),
    90: ("elapsed_time", "Elapsed time in days between this record and the first (ringing) record."),
    151:("biometrics_legacy_blob", "Unstructured reserved block historically holding biometric measurements (wing length, primary length, weight, tarsus, fat score, skull ossification, moult, tail length, tail difference, bill length, bill depth, head and bill, toe, claws); not split into individual EURING2020 biometric fields, so it has no single corresponding 2020 field."),
}

# posizione (2020) -> (canonical_name, semantic_meaning)
MAP_2020 = {
    1:  ("ring_scheme", "Code identifying the ringing scheme (issuing centre) responsible for the ring."),
    2:  ("primary_identification_method", "Primary method used to identify the bird (e.g. metal ring, colour ring, other mark)."),
    3:  ("ring_identification_number", "The ring number identifying this individual bird, up to ten alphanumeric characters."),
    4:  ("metal_ring_verification", "Whether the metal ring was verified by the scheme."),
    5:  ("metal_ring_information", "Additional information about the metal ring."),
    6:  ("other_marks_information", "Information about marks other than the conventional metal ring."),
    7:  ("species_reported", "Species as reported by the person who handled the bird."),
    8:  ("species_concluded", "Species as concluded/confirmed by the ringing scheme."),
    9:  ("manipulated", "Whether/how the bird was manipulated (e.g. moved, held in captivity) before release."),
    10: ("moved_before_encounter", "Whether the bird was moved before the ringing/recovery encounter."),
    11: ("catching_method", "Method used to catch the bird."),
    12: ("catching_lures", "Lures used to catch the bird."),
    13: ("sex_reported", "Sex as reported by the person who handled the bird."),
    14: ("sex_concluded", "Sex as concluded by the ringing scheme."),
    15: ("age_reported", "Age as reported by the person who handled the bird."),
    16: ("age_concluded", "Age as concluded by the ringing scheme."),
    17: ("status", "Status of the full-grown bird (e.g. free-flying, in captivity)."),
    18: ("brood_size", "Number of nestlings in the brood, for nestling records only."),
    19: ("pullus_age", "Age in days of a pullus (nestling)."),
    20: ("pullus_age_accuracy", "Accuracy of the recorded pullus age, in days either side."),
    21: ("event_date", "Date of the ringing/encounter event."),
    22: ("date_accuracy", "Accuracy of the recorded date."),
    23: ("event_time", "Time of day of the event, 24-hour local time."),
    24: ("place_code", "EURING place code identifying the geographical area of the event."),
    25: ("geographical_coordinates_encoded", "Encoded latitude/longitude of the event location (degrees/minutes/seconds format)."),
    26: ("coordinates_accuracy", "Accuracy of the recorded geographical coordinates."),
    27: ("condition", "Physical condition of the bird when found."),
    28: ("circumstances", "Circumstances under which the bird was encountered."),
    29: ("circumstances_presumed", "Whether the recorded circumstances are certain or presumed."),
    30: ("euring_code_identifier", "Identifies which EURING code version was used to encode this record."),
    31: ("distance", "Distance in kilometres between this record and the first (ringing) record."),
    32: ("direction", "Direction in degrees from the first (ringing) record to this record."),
    33: ("elapsed_time", "Elapsed time in days between this record and the first (ringing) record."),
    # Campi biometrici/nuovi del 2020 senza un corrispondente 2000 pulito
    # (nel 2000 erano tutti dentro il blob unico "biometrics", posizione 151)
    34: ("wing_length", "Wing length measurement in millimetres."),
    35: ("third_primary_length", "Length of the third primary feather in millimetres."),
    36: ("wing_point_state", "Condition/state of the longest primary feather (wing point)."),
    37: ("body_mass", "Body mass of the bird in grams."),
    38: ("moult", "Moult state, single-letter code."),
    39: ("plumage_code", "Additional plumage information used to refine the age code."),
    40: ("hind_claw_length", "Length of the hind claw in millimetres."),
    41: ("bill_length", "Bill length measurement in millimetres."),
    42: ("bill_length_method", "Method used to measure bill length."),
    43: ("total_head_length", "Total head length measurement in millimetres."),
    44: ("tarsus_length", "Tarsus length measurement in millimetres."),
    45: ("tarsus_length_method", "Method used to measure tarsus length."),
    46: ("tail_length", "Tail length measurement in millimetres."),
    47: ("tail_difference", "Difference in millimetres between the longest and shortest tail feathers."),
    48: ("fat_score", "Fat score of the bird, using one of the defined assessment methods."),
    49: ("fat_score_method", "Method used to assess the fat score (B, E or P)."),
    50: ("pectoral_muscle_score", "Score describing the state of the pectoral muscle."),
    51: ("brood_patch", "State of the brood patch during the breeding season."),
    52: ("primary_moult_score", "Sum of the individual primary moult scores."),
    53: ("primary_moult", "Moult state of each individual primary feather (ten digits)."),
    54: ("old_greater_coverts", "Number of unmoulted (old) greater coverts retained after post-juvenile moult."),
    55: ("alula_moult_state", "Moult state of the alula feathers."),
    56: ("carpal_covert_moult_state", "Moult state of the carpal covert."),
    57: ("sexing_method", "Method used to determine the sex of the bird."),
    58: ("place_name", "Free-text name of the place of the encounter."),
    59: ("remarks", "Free-text remarks about the encounter."),
    60: ("scheme_reference", "The ringing scheme's own unique reference for this encounter."),
    61: ("latitude_decimal", "Latitude of the event location, in decimal degrees."),
    62: ("longitude_decimal", "Longitude of the event location, in decimal degrees."),
    63: ("current_place_code", "Current place code, used when the original place code becomes obsolete."),
    64: ("other_marks_extra", "Free-text field used when more than one type of other mark applies."),
}


def apply(path, mapping):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    updated = 0
    missing = []
    for field in data["field_definitions"]:
        pos = field["position"]
        if pos in mapping:
            canon, meaning = mapping[pos]
            field["canonical_name"] = canon
            field["semantic_meaning"] = meaning
            updated += 1
        else:
            missing.append((pos, field["name"]))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return updated, missing


if __name__ == "__main__":
    u2000, m2000 = apply(f"{BASE}/euring_2000.json", MAP_2000)
    u2020, m2020 = apply(f"{BASE}/euring_2020.json", MAP_2020)
    print(f"euring_2000.json: aggiornati {u2000} campi, non mappati: {m2000}")
    print(f"euring_2020.json: aggiornati {u2020} campi, non mappati: {m2020}")
