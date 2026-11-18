"""Core checking logic for dwccheck.

Every per-record finding uses a flag name from GBIF's own published
OccurrenceIssue vocabulary (GBIF API 2.4.29, read 2026-11-18 via
https://api.gbif.org/v1/enumeration/basic/OccurrenceIssue — 108 values;
the definitions below are GBIF's, shortened where noted). The checker
only emits the subset of those flags that can be decided from the file
alone; anything needing GBIF's servers is listed as a non-goal in the
README and is never faked.

File-level structural findings (missing required column, duplicate
occurrenceID, unknown header, ...) have no GBIF per-record flag, so
they use dwccheck's own codes, marked with the DWCCHECK_ prefix in
`core.FLAG_DEFINITIONS` so the two namespaces can never be confused.

Vocabularies are pinned to their published sources:
- basisOfRecord: GBIF BasisOfRecord enumeration (11 values, API 2.4.29;
  LITERATURE and UNKNOWN are deprecated in the enum but still legal).
- occurrenceStatus: GBIF OccurrenceStatus enumeration (PRESENT, ABSENT,
  DETECTED, NOT_DETECTED), matched case-insensitively against the DwC
  spellings present/absent.
- typeStatus: GBIF TypeStatus enumeration (44 values).
- continent: GBIF Continent enumeration (7 values).
- countryCode: ISO 3166-1 alpha-2, with alpha-3 also accepted; the
  country-code set is the GBIF Country enumeration plus ISO alpha-3.
- Darwin Core term names: TDWG dwc dist/simple_dwc_vertical.csv
  (see terms_data.py).
- Country names: ISO 3166 names from datasets/country-codes (CC0),
  see countries_data.py. Used ONLY to test whether dwc:country and
  dwc:countryCode in the same row agree with each other.
"""

from __future__ import annotations

import calendar
import csv
import datetime as _dt
import difflib
import io
import re
import unicodedata
from pathlib import Path

from .countries_data import COUNTRIES, COUNTRY_CONTINENT
from .terms_data import DWC_TERMS


class DwcError(Exception):
    """A user-facing error: print the message, exit non-zero, no traceback."""


# ---------------------------------------------------------------------------
# Pinned vocabularies
# ---------------------------------------------------------------------------

# GBIF BasisOfRecord enumeration (API 2.4.29): the 11 legal values.
BASIS_OF_RECORD = (
    "PreservedSpecimen", "FossilSpecimen", "LivingSpecimen", "Observation",
    "HumanObservation", "MachineObservation", "MaterialSample",
    "Literature", "MaterialCitation", "Occurrence", "Unknown",
)

# GBIF OccurrenceStatus enumeration (API, /enumeration/basic/OccurrenceStatus).
OCCURRENCE_STATUS = ("present", "absent", "detected", "not_detected")

# GBIF TypeStatus enumeration (API, /enumeration/basic/TypeStatus).
TYPE_STATUS = (
    "TYPE", "TYPE_SPECIES", "TYPE_GENUS", "ALLOLECTOTYPE", "ALLONEOTYPE",
    "ALLOTYPE", "COTYPE", "EPITYPE", "EXEPITYPE", "EXHOLOTYPE",
    "EXISOTYPE", "EXLECTOTYPE", "EXNEOTYPE", "EXPARATYPE", "EXSYNTYPE",
    "EXTYPE", "HAPANTOTYPE", "HOLOTYPE", "HYPOTYPE", "ICONOTYPE",
    "ISOLECTOTYPE", "ISONEOTYPE", "ISOPARATYPE", "ISOSYNTYPE", "ISOTYPE",
    "LECTOTYPE", "NEOTYPE", "NOTATYPE", "ORIGINALMATERIAL",
    "PARALECTOTYPE", "PARANEOTYPE", "PARATYPE", "PLASTOHOLOTYPE",
    "PLASTOISOTYPE", "PLASTOLECTOTYPE", "PLASTONEOTYPE", "PLASTOPARATYPE",
    "PLASTOSYNTYPE", "PLASTOTYPE", "PLESIOTYPE", "SECONDARYTYPE",
    "SUPPLEMENTARYTYPE", "SYNTYPE", "TOPOTYPE",
)

# GBIF Continent enumeration (API, /enumeration/basic/Continent).
CONTINENTS = (
    "Africa", "Antarctica", "Asia", "Oceania", "Europe",
    "North America", "South America",
)

# Geodetic datums dwccheck treats as interpretable. WGS84 is the norm;
# EPSG:NNNN is accepted for any N (an EPSG code names a datum by
# definition). The other names are the common datums GBIF's datum
# dictionary recognises. Anything else is GEODETIC_DATUM_INVALID.
# "WGS" alone, "GPS" and free-text notes are not datums.
KNOWN_DATUMS = (
    "WGS84", "WGS 84", "WGS1984", "NAD83", "NAD27", "ED50", "ETRS89",
    "GRS80", "GDA94", "GDA2020", "AGD66", "AGD84", "OSGB36", "TOKYO",
    "PULKOVO1942", "PULKOVO1995", "DHDN", "NTF", "RGF93", "SAD69",
    "PSAD56", "CH1903", "CH1903+", "JGD2000", "JGD2011", "KGD2002",
    "NZGD2000", "MAGNA-SIRGAS", "SIRGAS2000",
)
_EPSG_RE = re.compile(r"^EPSG\s*:\s*\d+$", re.IGNORECASE)

# Terms GBIF requires for occurrence datasets (GBIF data-quality
# requirements for occurrences, quoted in the LivingNorwayR vignette
# and the OBIS/DwC publishing guides): a file missing one of these
# columns cannot be published as occurrence data.
REQUIRED_TERMS = ("occurrenceID", "basisOfRecord", "scientificName", "eventDate")

# Terms GBIF lists as recommended for occurrence datasets. A file
# missing one still publishes, so these are warnings, not errors.
RECOMMENDED_TERMS = (
    "occurrenceStatus", "decimalLatitude", "decimalLongitude",
    "countryCode", "geodeticDatum", "coordinateUncertaintyInMeters",
    "institutionCode", "kingdom", "taxonRank", "individualCount",
)

# The full GBIF OccurrenceIssue vocabulary (108 values, read from
# https://api.gbif.org/v1/enumeration/basic/OccurrenceIssue on
# 2026-11-18). dwccheck's GBIF-named flags must be a subset of this.
GBIF_OCCURRENCE_ISSUES = (
    "ZERO_COORDINATE", "COORDINATE_OUT_OF_RANGE", "COORDINATE_INVALID",
    "COORDINATE_ROUNDED", "GEODETIC_DATUM_INVALID",
    "GEODETIC_DATUM_ASSUMED_WGS84", "COORDINATE_REPROJECTED",
    "COORDINATE_REPROJECTION_FAILED", "COORDINATE_REPROJECTION_SUSPICIOUS",
    "COORDINATE_ACCURACY_INVALID", "COORDINATE_PRECISION_INVALID",
    "COORDINATE_UNCERTAINTY_METERS_INVALID",
    "COORDINATE_PRECISION_UNCERTAINTY_MISMATCH", "FOOTPRINT_SRS_INVALID",
    "FOOTPRINT_WKT_MISMATCH", "FOOTPRINT_WKT_INVALID",
    "COUNTRY_COORDINATE_MISMATCH", "COUNTRY_MISMATCH", "COUNTRY_INVALID",
    "COUNTRY_DERIVED_FROM_COORDINATES", "CONTINENT_COORDINATE_MISMATCH",
    "CONTINENT_COUNTRY_MISMATCH", "CONTINENT_INVALID",
    "CONTINENT_DERIVED_FROM_COUNTRY", "CONTINENT_DERIVED_FROM_COORDINATES",
    "PRESUMED_SWAPPED_COORDINATE", "PRESUMED_NEGATED_LONGITUDE",
    "PRESUMED_NEGATED_LATITUDE", "SUSPECTED_SWAPPED_COORDINATE",
    "SUSPECTED_NEGATED_LONGITUDE", "SUSPECTED_NEGATED_LATITUDE",
    "RECORDED_DATE_MISMATCH", "RECORDED_DATE_INVALID",
    "RECORDED_DATE_UNLIKELY", "TAXON_MATCH_FUZZY", "TAXON_MATCH_HIGHERRANK",
    "TAXON_MATCH_AGGREGATE", "TAXON_MATCH_SCIENTIFIC_NAME_ID_IGNORED",
    "TAXON_MATCH_TAXON_CONCEPT_ID_IGNORED", "TAXON_MATCH_TAXON_ID_IGNORED",
    "SCIENTIFIC_NAME_ID_NOT_FOUND", "TAXON_CONCEPT_ID_NOT_FOUND",
    "TAXON_ID_NOT_FOUND", "SCIENTIFIC_NAME_AND_ID_INCONSISTENT",
    "TAXON_MATCH_NONE", "TAXON_MATCH_NAME_AND_ID_AMBIGUOUS",
    "DEPTH_NOT_METRIC", "DEPTH_UNLIKELY", "DEPTH_MIN_MAX_SWAPPED",
    "DEPTH_NON_NUMERIC", "ELEVATION_UNLIKELY", "ELEVATION_MIN_MAX_SWAPPED",
    "ELEVATION_NOT_METRIC", "ELEVATION_NON_NUMERIC",
    "MODIFIED_DATE_INVALID", "MODIFIED_DATE_UNLIKELY",
    "IDENTIFIED_DATE_UNLIKELY", "IDENTIFIED_DATE_INVALID",
    "BASIS_OF_RECORD_INVALID", "TYPE_STATUS_INVALID", "SUSPECTED_TYPE",
    "MULTIMEDIA_DATE_INVALID", "MULTIMEDIA_URI_INVALID",
    "REFERENCES_URI_INVALID", "INTERPRETATION_ERROR",
    "INDIVIDUAL_COUNT_INVALID",
    "INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS",
    "OCCURRENCE_STATUS_UNPARSABLE",
    "OCCURRENCE_STATUS_INFERRED_FROM_INDIVIDUAL_COUNT",
    "OCCURRENCE_STATUS_INFERRED_FROM_BASIS_OF_RECORD",
    "GEOREFERENCED_DATE_UNLIKELY", "GEOREFERENCED_DATE_INVALID",
    "AMBIGUOUS_INSTITUTION", "AMBIGUOUS_COLLECTION",
    "INSTITUTION_MATCH_NONE", "COLLECTION_MATCH_NONE",
    "INSTITUTION_MATCH_FUZZY", "COLLECTION_MATCH_FUZZY",
    "INSTITUTION_COLLECTION_MISMATCH", "POSSIBLY_ON_LOAN",
    "DIFFERENT_OWNER_INSTITUTION",
    "ERA_OR_ERATHEM_INFERRED_FROM_PARENT_RANK",
    "PERIOD_OR_SYSTEM_INFERRED_FROM_PARENT_RANK",
    "EPOCH_OR_SERIES_INFERRED_FROM_PARENT_RANK",
    "AGE_OR_STAGE_INFERRED_FROM_PARENT_RANK",
    "EON_OR_EONOTHEM_RANK_MISMATCH", "ERA_OR_ERATHEM_RANK_MISMATCH",
    "PERIOD_OR_SYSTEM_RANK_MISMATCH", "EPOCH_OR_SERIES_RANK_MISMATCH",
    "AGE_OR_STAGE_RANK_MISMATCH", "EON_OR_EONOTHEM_INVALID_RANGE",
    "ERA_OR_ERATHEM_INVALID_RANGE", "PERIOD_OR_SYSTEM_INVALID_RANGE",
    "EPOCH_OR_SERIES_INVALID_RANGE", "AGE_OR_STAGE_INVALID_RANGE",
    "EON_OR_EONOTHEM_AND_ERA_OR_ERATHEM_MISMATCH",
    "ERA_OR_ERATHEM_AND_PERIOD_OR_SYSTEM_MISMATCH",
    "PERIOD_OR_SYSTEM_AND_EPOCH_OR_SERIES_MISMATCH",
    "EPOCH_OR_SERIES_AND_AGE_OR_STAGE_MISMATCH",
    "NUCLEOTIDE_SEQUENCE_NATURAL_LANGUAGE",
    "NUCLEOTIDE_SEQUENCE_ENDS_TRIMMED", "NUCLEOTIDE_SEQUENCE_GAPS_REMOVED",
    "NUCLEOTIDE_SEQUENCE_INVALID", "NUCLEOTIDE_SEQUENCE_HIGH_N_FRACTION",
    "NUCLEOTIDE_SEQUENCE_HIGH_AMBIGUITY", "TARGET_GENE_INVALID",
    "DUPLICATE_NUCLEOTIDE_SEQUENCES_COLLAPSED",
    "PARENT_EVENT_INFINITE_LINEAGE",
)

# GBIF's own definitions (OccurrenceIssue API docs, 2026-11-18) for the
# flags dwccheck can emit. severity is dwccheck's call: "error" means
# GBIF cannot interpret the value / the record would be flagged as
# broken; "warning" means GBIF flags it as unlikely or inferred.
FLAG_DEFINITIONS = {
    "ZERO_COORDINATE": ("error",
        "Coordinate is the exact 0, 0 coordinate, often indicating a "
        "bad null coordinate."),
    "COORDINATE_OUT_OF_RANGE": ("error",
        "Coordinate has a latitude and/or longitude value beyond the "
        "maximum (or minimum) decimal value."),
    "COORDINATE_INVALID": ("error",
        "Coordinate value is given in some form but GBIF is unable to "
        "interpret it."),
    "GEODETIC_DATUM_INVALID": ("error",
        "The geodetic datum given could not be interpreted."),
    "GEODETIC_DATUM_ASSUMED_WGS84": ("warning",
        "The interpreted coordinates assume they are based on WGS84 "
        "datum as the datum was either not indicated or interpretable."),
    "COORDINATE_PRECISION_INVALID": ("error",
        "Indicates an invalid or very unlikely coordinatePrecision."),
    "COORDINATE_UNCERTAINTY_METERS_INVALID": ("error",
        "Indicates an invalid or very unlikely "
        "dwc:coordinateUncertaintyInMeters."),
    "COUNTRY_MISMATCH": ("error",
        "Interpreted country for dwc:country and dwc:countryCode "
        "contradict each other."),
    "COUNTRY_INVALID": ("error", "Uninterpretable country values found."),
    "CONTINENT_INVALID": ("error",
        "Uninterpretable continent values found."),
    "CONTINENT_COUNTRY_MISMATCH": ("error",
        "The interpreted continent and country do not match."),
    "REFERENCES_URI_INVALID": ("warning",
        "An invalid URI is given for dc:references."),
    "FOOTPRINT_WKT_INVALID": ("error",
        "The Footprint Well-Known-Text given could not be interpreted."),
    "FOOTPRINT_SRS_INVALID": ("error",
        "The Footprint Spatial Reference System given could not be "
        "interpreted."),
    "DEPTH_NOT_METRIC": ("warning",
        "Set if supplied depth is not given in the metric system, for "
        "example using feet instead of meters."),
    "ELEVATION_NOT_METRIC": ("warning",
        "Set if supplied elevation is not given in the metric system, "
        "for example using feet instead of meters."),
    "PRESUMED_SWAPPED_COORDINATE": ("error",
        "Latitude and longitude appear to be swapped."),
    "RECORDED_DATE_MISMATCH": ("error",
        "The recorded date specified as the eventDate string and the "
        "individual year, month, day and/or startDayOfYear, "
        "endDayOfYear are contradictory."),
    "RECORDED_DATE_INVALID": ("error",
        "A (partial) invalid date is given, such as a non-existent "
        "date, zero month, etc."),
    "RECORDED_DATE_UNLIKELY": ("warning",
        "The recorded date is highly unlikely, falling either into the "
        "future or representing a very old date before 1600 thus "
        "predating modern taxonomy."),
    "DEPTH_UNLIKELY": ("warning",
        "Set if depth is larger than 11,000m or negative."),
    "DEPTH_MIN_MAX_SWAPPED": ("error",
        "Set if supplied minimum depth > maximum depth."),
    "DEPTH_NON_NUMERIC": ("error", "Set if depth is a non-numeric value."),
    "ELEVATION_UNLIKELY": ("warning",
        "Set if elevation is above the troposphere (17km) or below "
        "11km (Mariana Trench)."),
    "ELEVATION_MIN_MAX_SWAPPED": ("error",
        "Set if supplied minimum elevation > maximum elevation."),
    "ELEVATION_NON_NUMERIC": ("error",
        "Set if elevation is a non-numeric value."),
    "MODIFIED_DATE_INVALID": ("error",
        "A (partial) invalid date is given for dc:modified, such as a "
        "nonexistent date, zero month, etc."),
    "MODIFIED_DATE_UNLIKELY": ("warning",
        "The date given for dc:modified is in the future or predates "
        "Unix time (1970)."),
    "IDENTIFIED_DATE_UNLIKELY": ("warning",
        "The date given for dwc:dateIdentified is in the future or "
        "before Linnean times (1700)."),
    "IDENTIFIED_DATE_INVALID": ("error",
        "The date given for dwc:dateIdentified is invalid and can't be "
        "interpreted at all."),
    "BASIS_OF_RECORD_INVALID": ("error",
        "The given basis of record is impossible to interpret or "
        "significantly different from the recommended vocabulary."),
    "TYPE_STATUS_INVALID": ("error",
        "The given type status is impossible to interpret or "
        "significantly different from the recommended vocabulary."),
    "SUSPECTED_TYPE": ("warning",
        "The given type status contains some words that express "
        "uncertainty."),
    "INDIVIDUAL_COUNT_INVALID": ("error",
        "The individual count value is not a positive integer."),
    "INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS": ("error",
        "Example: individual count value > 0, but occurrence status "
        "is absent."),
    "OCCURRENCE_STATUS_UNPARSABLE": ("error",
        "The occurrence status value cannot be parsed against GBIF's "
        "OccurrenceStatus vocabulary (present, absent, detected, "
        "not_detected)."),
    "GEOREFERENCED_DATE_UNLIKELY": ("warning",
        "The date given for dwc:georeferencedDate is in the future or "
        "before Linnean times (1700)."),
    "GEOREFERENCED_DATE_INVALID": ("error",
        "The date given for dwc:georeferencedDate is invalid and can't "
        "be interpreted at all."),
    # dwccheck's own file-level codes (no GBIF per-record flag exists).
    "DWCCHECK_MISSING_TERM": ("error",
        "A required Darwin Core term is missing as a column. "
        "(dwccheck file-level check; GBIF has no per-record flag for "
        "a missing column.)"),
    "DWCCHECK_MISSING_RECOMMENDED_TERM": ("warning",
        "A term GBIF recommends for occurrence datasets is missing as "
        "a column. (dwccheck file-level check.)"),
    "DWCCHECK_MISSING_VALUE": ("error",
        "A required term's cell is empty on this row. (dwccheck "
        "file-level check.)"),
    "DWCCHECK_DUPLICATE_OCCURRENCE_ID": ("error",
        "The same occurrenceID appears on more than one row; "
        "occurrenceIDs must be unique. (dwccheck file-level check; "
        "GBIF's validator reports duplicates as a dataset error.)"),
    "DWCCHECK_UNKNOWN_TERM": ("warning",
        "A header is not a Darwin Core term (TDWG simple_dwc list). "
        "It may be a typo or a local column GBIF will ignore. "
        "(dwccheck file-level check.)"),
    "DWCCHECK_DUPLICATE_TERM": ("error",
        "The same header appears twice. (dwccheck file-level check.)"),
}

# The flags dwccheck emits that come from GBIF's vocabulary.
GBIF_FLAGS_EMITTED = tuple(
    flag for flag in FLAG_DEFINITIONS if not flag.startswith("DWCCHECK_"))

# Country-code values GBIF accepts that are not ISO 3166-1: XK is
# Kosovo (ISO user-assigned), AA/XZ/ZZ are GBIF's own codes for
# unknown / international waters / not applicable. They cannot be
# cross-checked against a country name, so they are accepted as-is.
GBIF_EXTRA_COUNTRY_CODES = {"XK": "Kosovo", "AA": None, "XZ": None,
                            "ZZ": None}

# Extra country-name aliases not in the ISO common/official names,
# for names publishers actually write. Keys are normalised with
# _normalise_name.
COUNTRY_NAME_ALIASES = {
    "usa": "US", "u.s.a.": "US", "u.s.": "US", "united states": "US",
    "united states of america": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "great britain": "GB", "britain": "GB",
    "united kingdom": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB",
    "russia": "RU", "russian federation": "RU",
    "south korea": "KR", "republic of korea": "KR",
    "north korea": "KP", "democratic people's republic of korea": "KP",
    "iran": "IR", "vietnam": "VN", "viet nam": "VN",
    "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ",
    "syria": "SY", "laos": "LA", "moldova": "MD", "brunei": "BN",
    "palestine": "PS", "czech republic": "CZ", "czechia": "CZ",
    "swaziland": "SZ", "eswatini": "SZ", "macedonia": "MK",
    "north macedonia": "MK", "cape verde": "CV", "cabo verde": "CV",
    "east timor": "TL", "timor-leste": "TL", "ivory coast": "CI",
    "cote d'ivoire": "CI", "cote divoire": "CI",
    "the netherlands": "NL", "netherlands": "NL", "holland": "NL",
    "united arab emirates": "AE", "uae": "AE",
    "democratic republic of the congo": "CD", "drc": "CD",
    "republic of the congo": "CG",
    "central african republic": "CF", "sao tome and principe": "ST",
    "saint helena": "SH", "bosnia and herzegovina": "BA",
    "bosnia": "BA", "trinidad and tobago": "TT",
    "antigua and barbuda": "AG", "st. kitts and nevis": "KN",
    "st kitts and nevis": "KN", "saint lucia": "LC",
    "saint vincent and the grenadines": "VC",
    "dominican republic": "DO", "dominica": "DM",
    "south africa": "ZA", "new zealand": "NZ", "sri lanka": "LK",
    "costa rica": "CR", "el salvador": "SV", "puerto rico": "PR",
    "french guiana": "GF", "french polynesia": "PF",
    "new caledonia": "NC", "wallis and futuna": "WF",
    "saint pierre and miquelon": "PM", "faroe islands": "FO",
    "isle of man": "IM", "jersey": "JE", "guernsey": "GG",
    "aland islands": "AX", "svalbard and jan mayen": "SJ",
    "bouvet island": "BV", "heard island and mcdonald islands": "HM",
    "british indian ocean territory": "IO",
    "cocos (keeling) islands": "CC", "christmas island": "CX",
    "norfolk island": "NF", "niue": "NU", "tokelau": "TK",
    "cook islands": "CK", "samoa": "WS", "american samoa": "AS",
    "guam": "GU", "northern mariana islands": "MP",
    "united states minor outlying islands": "UM",
    "western sahara": "EH", "antarctica": "AQ",
    "south georgia and the south sandwich islands": "GS",
    "falkland islands (malvinas)": "FK", "falkland islands": "FK",
    "myanmar": "MM", "burma": "MM",
    "micronesia": "FM", "marshall islands": "MH", "palau": "PW",
    "kiribati": "KI", "tuvalu": "TV", "nauru": "NR", "tonga": "TO",
    "fiji": "FJ", "vanuatu": "VU", "solomon islands": "SB",
    "papua new guinea": "PG", "australia": "AU",
    "madagascar": "MG", "mauritius": "MU", "seychelles": "SC",
    "comoros": "KM", "mayotte": "YT", "reunion": "RE",
    "saint martin": "MF", "sint maarten": "SX", "curacao": "CW",
    "aruba": "AW", "bermuda": "BM", "cayman islands": "KY",
    "turks and caicos islands": "TC", "british virgin islands": "VG",
    "us virgin islands": "VI", "anguilla": "AI", "montserrat": "MS",
    "greenland": "GL", "iceland": "IS", "norway": "NO",
    "sweden": "SE", "finland": "FI", "denmark": "DK",
    "germany": "DE", "france": "FR", "spain": "ES", "italy": "IT",
    "portugal": "PT", "belgium": "BE", "switzerland": "CH",
    "austria": "AT", "poland": "PL", "greece": "GR",
    "turkey": "TR", "ukraine": "UA", "belarus": "BY",
    "romania": "RO", "hungary": "HU", "bulgaria": "BG",
    "croatia": "HR", "serbia": "RS", "albania": "AL",
    "bosnia-herzegovina": "BA", "montenegro": "ME", "kosovo": "XK",
    "moldavia": "MD", "georgia": "GE", "armenia": "AM",
    "azerbaijan": "AZ", "kazakhstan": "KZ", "uzbekistan": "UZ",
    "kyrgyzstan": "KG", "tajikistan": "TJ", "turkmenistan": "TM",
    "mongolia": "MN", "china": "CN", "japan": "JP", "india": "IN",
    "pakistan": "PK", "bangladesh": "BD", "nepal": "NP",
    "sri lanka": "LK", "thailand": "TH", "cambodia": "KH",
    "malaysia": "MY", "singapore": "SG", "indonesia": "ID",
    "philippines": "PH", "taiwan": "TW", "hong kong": "HK",
    "macao": "MO", "sri lanka": "LK",
}


def _normalise_name(text):
    """Lower-case, strip accents and punctuation for name matching."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.lower().strip()
    t = re.sub(r"^the\s+", "", t)
    t = re.sub(r"[\s\-_]+", " ", t)
    t = re.sub(r"[.'’]", "", t)
    return t.strip()


def _build_country_maps():
    """(alpha2 set, alpha3->alpha2, normalised-name->alpha2)."""
    alpha2 = set()
    alpha3_to_2 = {}
    name_to_2 = {}
    for a2, a3, common, official in COUNTRIES:
        alpha2.add(a2)
        alpha3_to_2[a3] = a2
        for name in (common, official):
            if name:
                name_to_2.setdefault(_normalise_name(name), a2)
        # The CLDR display name for some countries is itself a code
        # alias GBIF would accept (e.g. "US" in the country field).
        name_to_2.setdefault(a2.lower(), a2)
        name_to_2.setdefault(a3.lower(), a2)
    for alias, code in COUNTRY_NAME_ALIASES.items():
        name_to_2.setdefault(_normalise_name(alias), code)
    for code in GBIF_EXTRA_COUNTRY_CODES:
        alpha2.add(code)
    return alpha2, alpha3_to_2, name_to_2


ALPHA2_CODES, ALPHA3_TO_ALPHA2, COUNTRY_NAME_TO_CODE = _build_country_maps()


def _norm_vocab(value):
    """Normalise a vocabulary value: strip, lower, drop spaces/underscores."""
    return re.sub(r"[\s_\-]+", "", (value or "").strip().lower())


_BASIS_NORM = {_norm_vocab(v): v for v in BASIS_OF_RECORD}
_TYPE_NORM = {_norm_vocab(v): v for v in TYPE_STATUS}
_CONTINENT_NORM = {_norm_vocab(v): v for v in CONTINENTS}
_STATUS_NORM = {_norm_vocab(v): v for v in OCCURRENCE_STATUS}

# Words that, in a typeStatus value, express uncertainty (GBIF's
# SUSPECTED_TYPE definition).
_UNCERTAINTY_WORDS = ("possible", "probable", "suspected", "maybe",
                      "uncertain", "cf", "aff", "?")


class Finding:
    """One check result. row is the file line number (header is row 1),
    or 0 for a file-level finding."""

    __slots__ = ("row", "flag", "severity", "term", "value", "message")

    def __init__(self, row, flag, term, value, message):
        self.row = row
        self.flag = flag
        self.severity = FLAG_DEFINITIONS[flag][0]
        self.term = term
        self.value = value
        self.message = message

    def as_dict(self):
        return {"row": self.row, "flag": self.flag,
                "severity": self.severity, "term": self.term,
                "value": self.value, "message": self.message}

    def __repr__(self):
        return (f"Finding(row={self.row}, flag={self.flag!r}, "
                f"term={self.term!r}, value={self.value!r})")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _sniff_delimiter(text, path):
    """Pick , or tab or ; from the first non-empty line, honouring the
    file extension first."""
    suffix = Path(path).suffix.lower()
    if suffix == ".tsv":
        return "\t"
    if suffix == ".csv":
        return ","
    first = ""
    for line in text.splitlines():
        if line.strip():
            first = line
            break
    if not first:
        return ","
    counts = {d: first.count(d) for d in (",", "\t", ";")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_occurrence_file(path):
    """Read a CSV/TSV occurrence file. Returns (fieldnames, rows) where
    rows are dicts keyed by the exact header, plus a 'row' (line number)
    entry. Raises DwcError with a one-line message on any file problem."""
    path = Path(path)
    if not path.is_file():
        raise DwcError(f"input file not found: {path}")
    if path.stat().st_size == 0:
        raise DwcError(f"input file is empty: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise DwcError(f"{path} is not valid UTF-8 text; Darwin Core "
                       "files must be UTF-8.")
    except Exception as exc:
        raise DwcError(f"could not read {path}: {exc}")
    delimiter = _sniff_delimiter(text, path)
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        fieldnames = reader.fieldnames
        rows = []
        for raw in reader:
            # reader.line_num is the physical line the record ends on
            # (a quoted field may embed newlines), so findings point at
            # real file lines, not record counts. (Review fix.)
            raw["__row__"] = reader.line_num
            rows.append(raw)
    except Exception as exc:
        raise DwcError(f"could not parse {path} as a delimited file: {exc}")
    if not fieldnames:
        raise DwcError(f"{path} has no header row.")
    # csv gives None for a blank header cell and restkey for extra cells.
    if any(f is None or str(f).strip() == "" for f in fieldnames):
        raise DwcError(f"{path} has an empty column header; every column "
                       "must be named with a Darwin Core term.")
    if not rows:
        raise DwcError(f"{path} contains no data rows.")
    for row in rows:
        if None in row:
            extra = row.pop(None)
            raise DwcError(
                f"row {row['__row__']} has {len(extra)} more value(s) "
                f"than the header has columns ({extra[0]!r}...); check "
                "the delimiter and quoting.")
    return fieldnames, rows


# ---------------------------------------------------------------------------
# Dates (ISO 8601 subset, as Darwin Core requires)
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(
    r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?)?$")
_ISO_BASIC_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def parse_iso_date(text):
    """Parse an ISO 8601 date/datetime to (year, month, day, precision)
    or None if unparseable. precision is "year", "month" or "day"
    (a datetime counts as "day").

    Accepts: YYYY, YYYY-MM, YYYY-MM-DD, YYYYMMDD, and datetimes
    YYYY-MM-DD[Tt ]hh:mm(:ss)?(Z|z|±hh:mm). Rejects non-existent
    calendar dates (2021-02-30, month 13, day 00), non-ISO shapes
    (20/02/2009, "Feb 2009") and impossible times.
    """
    if text is None:
        return None
    t = str(text).strip()
    basic = _ISO_BASIC_DATE_RE.match(t)
    if basic:
        year, month, day = (int(g) for g in basic.groups())
        if not 1 <= month <= 12:
            return None
        if not 1 <= day <= calendar.monthrange(year, month)[1]:
            return None
        return (year, month, day, "day")
    m = _ISO_DATE_RE.match(t)
    if not m:
        return None
    year = int(m.group(1))
    if m.group(2) is None:
        return (year, 1, 1, "year")
    month = int(m.group(2))
    if month < 1 or month > 12:
        return None
    if m.group(3) is None:
        return (year, month, 1, "month")
    day = int(m.group(3))
    if day < 1 or day > calendar.monthrange(year, month)[1]:
        return None
    if m.group(4) is not None:
        hour, minute = int(m.group(4)), int(m.group(5))
        second = int(m.group(6)) if m.group(6) else 0
        if hour > 23 or minute > 59 or second > 60:
            return None
        if m.group(7) and m.group(7) not in ("Z", "z"):
            off = m.group(7).replace(":", "")
            oh, om = int(off[1:3]), int(off[3:5])
            if oh > 23 or om > 59:
                return None
    return (year, month, day, "day")


def _is_future(parsed):
    """True if a parsed date lies in the future, judged at the
    precision the value actually carries: a year-only value is future
    only if its year is ahead, a year-month if its month is ahead, a
    full date if the day itself is ahead of today. (Review fix: the
    first version compared years only, so a full date next month
    passed silently.)"""
    year, month, day, precision = parsed
    today = _dt.date.today()
    if precision == "year":
        return year > today.year
    if precision == "month":
        return (year, month) > (today.year, today.month)
    return (year, month, day) > (today.year, today.month, today.day)


def _date_unlikely(parsed, before_year):
    """GBIF's *_DATE_UNLIKELY shape: in the future, or before a
    published threshold year (1600 / 1700 / 1970 depending on term)."""
    return parsed[0] < before_year or _is_future(parsed)


def _check_date_field(row, rowno, term, value, invalid_flag, unlikely_flag,
                      unlikely_before, findings):
    """Validate one date-bearing term. Returns the parsed year or None."""
    parsed = parse_iso_date(value)
    if parsed is None:
        findings.append(Finding(
            rowno, invalid_flag, term, value,
            f"{term} value {value!r} is not a valid ISO 8601 date."))
        return None
    if _date_unlikely(parsed, unlikely_before):
        findings.append(Finding(
            rowno, unlikely_flag, term, value,
            f"{term} value {value!r} is unlikely: "
            f"before {unlikely_before} or in the future."))
    return parsed[0]


def _check_event_date(row, rowno, findings):
    value = row.get("eventDate")
    if value is None:
        return
    value = str(value).strip()
    if not value:
        return  # empty cell is MISSING_VALUE, handled by the caller
    # Intervals: start/end separated by "/".
    if "/" in value:
        parts = value.split("/")
        if len(parts) != 2:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", "eventDate", value,
                "eventDate interval must have exactly one '/' "
                "separating start and end."))
            return
        start = parse_iso_date(parts[0].strip())
        end = parse_iso_date(parts[1].strip())
        if start is None or end is None:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", "eventDate", value,
                "eventDate interval start or end is not a valid ISO "
                "8601 date."))
            return
        if start[:3] > end[:3]:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", "eventDate", value,
                "eventDate interval ends before it starts."))
            return
        for part in (parts[0].strip(), parts[1].strip()):
            if _date_unlikely(parse_iso_date(part), 1600):
                findings.append(Finding(
                    rowno, "RECORDED_DATE_UNLIKELY", "eventDate", value,
                    "eventDate is in the future or before 1600."))
                break
        return
    parsed = parse_iso_date(value)
    if parsed is None:
        findings.append(Finding(
            rowno, "RECORDED_DATE_INVALID", "eventDate", value,
            "eventDate is not a valid ISO 8601 date (expected "
            "YYYY, YYYY-MM, YYYY-MM-DD or a full ISO datetime)."))
        return
    if _date_unlikely(parsed, 1600):
        findings.append(Finding(
            rowno, "RECORDED_DATE_UNLIKELY", "eventDate", value,
            "eventDate is in the future or before 1600."))
    # Cross-check against year/month/day/startDayOfYear/endDayOfYear.
    _check_date_parts(row, rowno, parsed, findings)


def _int_field(row, term):
    """Parse an integer field; returns (value, ok)."""
    raw = row.get(term)
    if raw is None or str(raw).strip() == "":
        return None, True
    try:
        return int(str(raw).strip()), True
    except ValueError:
        return None, False


def _check_date_parts(row, rowno, parsed, findings):
    year, month, day = parsed[0], parsed[1], parsed[2]
    has_full = parsed[3] == "day"
    y, y_ok = _int_field(row, "year")
    mo, mo_ok = _int_field(row, "month")
    d, d_ok = _int_field(row, "day")
    for term, val, ok in (("year", y, y_ok), ("month", mo, mo_ok),
                          ("day", d, d_ok)):
        if not ok:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", term, row.get(term),
                f"{term} value {row.get(term)!r} is not an integer."))
    if y is not None and y != year:
        findings.append(Finding(
            rowno, "RECORDED_DATE_MISMATCH", "year", row.get("year"),
            f"year {y} contradicts eventDate year {year}."))
    if mo is not None:
        if not 1 <= mo <= 12:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", "month", row.get("month"),
                "month must be 1-12."))
        elif has_full and mo != month:
            findings.append(Finding(
                rowno, "RECORDED_DATE_MISMATCH", "month", row.get("month"),
                f"month {mo} contradicts eventDate month {month}."))
    if d is not None:
        if has_full:
            if d != day:
                findings.append(Finding(
                    rowno, "RECORDED_DATE_MISMATCH", "day", row.get("day"),
                    f"day {d} contradicts eventDate day {day}."))
        elif not 1 <= d <= 31:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", "day", row.get("day"),
                "day must be 1-31."))
    s, s_ok = _int_field(row, "startDayOfYear")
    e, e_ok = _int_field(row, "endDayOfYear")
    for term, val, ok in (("startDayOfYear", s, s_ok),
                          ("endDayOfYear", e, e_ok)):
        if not ok:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", term, row.get(term),
                f"{term} value {row.get(term)!r} is not an integer."))
        elif val is not None and not 1 <= val <= 366:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", term, row.get(term),
                f"{term} must be 1-366."))
    if s is not None and e is not None and e < s:
        findings.append(Finding(
            rowno, "RECORDED_DATE_MISMATCH", "endDayOfYear",
            row.get("endDayOfYear"),
            "endDayOfYear is before startDayOfYear."))


def _check_standalone_date_parts(row, rowno, findings):
    """year/month/day given without eventDate: validate ranges only."""
    y, y_ok = _int_field(row, "year")
    mo, mo_ok = _int_field(row, "month")
    d, d_ok = _int_field(row, "day")
    for term, val, ok in (("year", y, y_ok), ("month", mo, mo_ok),
                          ("day", d, d_ok)):
        if not ok:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", term, row.get(term),
                f"{term} value {row.get(term)!r} is not an integer."))
    if y is not None and (y < 1600 or _is_future((y, 1, 1, "year"))):
        findings.append(Finding(
            rowno, "RECORDED_DATE_UNLIKELY", "year", row.get("year"),
            "year is in the future or before 1600."))
    if mo is not None and not 1 <= mo <= 12:
        findings.append(Finding(
            rowno, "RECORDED_DATE_INVALID", "month", row.get("month"),
            "month must be 1-12."))
    if d is not None:
        if y is not None and mo is not None and 1 <= mo <= 12:
            maxd = calendar.monthrange(y, mo)[1]
            if not 1 <= d <= maxd:
                findings.append(Finding(
                    rowno, "RECORDED_DATE_INVALID", "day", row.get("day"),
                    f"day {d} does not exist in {y:04d}-{mo:02d}."))
        elif not 1 <= d <= 31:
            findings.append(Finding(
                rowno, "RECORDED_DATE_INVALID", "day", row.get("day"),
                "day must be 1-31."))


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def _parse_number(value):
    """Parse a decimal number; returns float or None (rejects NaN/inf,
    empty strings and comma decimals)."""
    if value is None:
        return None
    t = str(value).strip()
    if t == "":
        return None
    try:
        num = float(t)
    except ValueError:
        return None
    if num != num or num in (float("inf"), float("-inf")):
        return None
    return num


def _parse_int_count(value):
    """Parse an individualCount: digits only, non-negative."""
    if value is None:
        return None
    t = str(value).strip()
    if t == "":
        return None
    if not re.fullmatch(r"\+?\d+", t):
        return None
    return int(t)


# ---------------------------------------------------------------------------
# Row checks
# ---------------------------------------------------------------------------

_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _is_absolute_uri(value):
    """True for an absolute URI: a scheme, no whitespace, no characters
    that are illegal in a URI. (GBIF: REFERENCES_URI_INVALID — "an
    invalid URI is given for dc:references".)"""
    if any(ch.isspace() for ch in value):
        return False
    if any(ch in value for ch in '<>{}|^`"\\'):
        return False
    return bool(_URI_SCHEME_RE.match(value))


_WKT_TYPES = ("POINT", "LINESTRING", "POLYGON", "MULTIPOINT",
              "MULTILINESTRING", "MULTIPOLYGON", "GEOMETRYCOLLECTION")
_WKT_HEAD_RE = re.compile(
    r"^(?:SRID=\d+\s*;\s*)?(" + "|".join(_WKT_TYPES) + r")\b",
    re.IGNORECASE)


def _wkt_is_plausible(value):
    """Structural Well-Known Text check: a known geometry type (with
    an optional SRID=…; prefix or EMPTY form), balanced parentheses,
    and nothing inside but numbers, commas, parentheses and nested
    geometry keywords. Well-formed WKT always passes; free text and
    truncated values fail. Full geometry semantics (ring closure,
    point-in-footprint) are NOT judged — see the README limits."""
    text = value.strip()
    m = _WKT_HEAD_RE.match(text)
    if not m:
        return False
    rest = text[m.end():].strip()
    if rest.upper() == "EMPTY":
        return True
    if not (rest.startswith("(") and rest.endswith(")")):
        return False
    if rest.count("(") != rest.count(")"):
        return False
    body = rest
    for kw in _WKT_TYPES:
        body = re.sub(kw, " ", body, flags=re.IGNORECASE)
    body = body.replace("(", " ").replace(")", " ").replace(",", " ")
    tokens = body.split()
    if not tokens:
        return False
    for tok in tokens:
        if tok.upper() in ("Z", "M", "ZM"):
            continue
        if _parse_number(tok) is None:
            return False
    return True


_WKT_CRS_PREFIXES = ("GEOGCS[", "PROJCS[", "GEODCRS[", "GEOGCRS[",
                     "VERT_CS[", "COMPD_CS[", "LOCAL_CS[")
_URN_CRS_RE = re.compile(r"^urn:ogc:def:crs:", re.IGNORECASE)


def _srs_is_interpretable(value):
    """footprintSRS accepts the same shapes as geodeticDatum, plus
    full WKT CRS strings and OGC URNs."""
    text = value.strip()
    if _EPSG_RE.match(text) or _URN_CRS_RE.match(text):
        return True
    if text.upper().startswith(_WKT_CRS_PREFIXES):
        return True
    dnorm = re.sub(r"[\s_\-]+", "", text.upper())
    known = {re.sub(r"[\s_\-]+", "", d.upper()) for d in KNOWN_DATUMS}
    return dnorm in known


_IMPERIAL_UNIT_RE = re.compile(
    r"[0-9]\s*(ft|feet|foot|fathoms?|in|inch|inches|yd|yards?)\b",
    re.IGNORECASE)


def _cell(row, term):
    """The row's value for a term, or None if the column is absent."""
    if term not in row:
        return None
    v = row.get(term)
    return None if v is None else str(v).strip()


def check_row(row, seen_occurrence_ids, findings):
    rowno = row["__row__"]

    # --- required-term values -------------------------------------------
    for term in REQUIRED_TERMS:
        if term in row and _cell(row, term) in (None, ""):
            findings.append(Finding(
                rowno, "DWCCHECK_MISSING_VALUE", term, "",
                f"required term {term} is empty on this row."))

    # --- occurrenceID uniqueness ----------------------------------------
    occ_id = _cell(row, "occurrenceID")
    if occ_id:
        if occ_id in seen_occurrence_ids:
            findings.append(Finding(
                rowno, "DWCCHECK_DUPLICATE_OCCURRENCE_ID", "occurrenceID",
                occ_id,
                f"occurrenceID {occ_id!r} already appeared on row "
                f"{seen_occurrence_ids[occ_id]}; occurrenceIDs must be "
                "unique."))
        else:
            seen_occurrence_ids[occ_id] = rowno

    # --- basisOfRecord ---------------------------------------------------
    bor = _cell(row, "basisOfRecord")
    if bor:
        if _norm_vocab(bor) not in _BASIS_NORM:
            findings.append(Finding(
                rowno, "BASIS_OF_RECORD_INVALID", "basisOfRecord", bor,
                f"basisOfRecord {bor!r} is not in GBIF's BasisOfRecord "
                "vocabulary: " + ", ".join(BASIS_OF_RECORD) + "."))

    # --- occurrenceStatus ------------------------------------------------
    status = _cell(row, "occurrenceStatus")
    status_norm = None
    if status:
        status_norm = _norm_vocab(status)
        if status_norm not in _STATUS_NORM:
            findings.append(Finding(
                rowno, "OCCURRENCE_STATUS_UNPARSABLE", "occurrenceStatus",
                status,
                "occurrenceStatus value "
                f"{status!r} cannot be parsed; GBIF's OccurrenceStatus "
                "vocabulary is present, absent, detected, not_detected."))
            status_norm = None

    # --- typeStatus ------------------------------------------------------
    tstatus = _cell(row, "typeStatus")
    if tstatus:
        if _norm_vocab(tstatus) in _TYPE_NORM:
            pass
        else:
            lowered = tstatus.lower()
            if "?" in tstatus or any(
                    w in lowered for w in _UNCERTAINTY_WORDS):
                findings.append(Finding(
                    rowno, "SUSPECTED_TYPE", "typeStatus", tstatus,
                    "typeStatus contains words expressing uncertainty."))
            else:
                findings.append(Finding(
                    rowno, "TYPE_STATUS_INVALID", "typeStatus", tstatus,
                    f"typeStatus {tstatus!r} is not in GBIF's TypeStatus "
                    "vocabulary."))

    # --- continent -------------------------------------------------------
    continent = _cell(row, "continent")
    if continent and _norm_vocab(continent) not in _CONTINENT_NORM:
        findings.append(Finding(
            rowno, "CONTINENT_INVALID", "continent", continent,
            f"continent {continent!r} is not one of: "
            + ", ".join(CONTINENTS) + "."))

    # --- dates -----------------------------------------------------------
    if "eventDate" in row:
        _check_event_date(row, rowno, findings)
    else:
        _check_standalone_date_parts(row, rowno, findings)
    for term, invalid, unlikely, before in (
            ("modified", "MODIFIED_DATE_INVALID", "MODIFIED_DATE_UNLIKELY",
             1970),
            ("dateIdentified", "IDENTIFIED_DATE_INVALID",
             "IDENTIFIED_DATE_UNLIKELY", 1700),
            ("georeferencedDate", "GEOREFERENCED_DATE_INVALID",
             "GEOREFERENCED_DATE_UNLIKELY", 1700)):
        value = _cell(row, term)
        if value:
            _check_date_field(row, rowno, term, value, invalid, unlikely,
                              before, findings)

    # --- coordinates -----------------------------------------------------
    lat_raw = _cell(row, "decimalLatitude")
    lon_raw = _cell(row, "decimalLongitude")
    lat = lon = None
    lat_present = lat_raw not in (None, "")
    lon_present = lon_raw not in (None, "")
    if lat_present != lon_present:
        findings.append(Finding(
            rowno, "COORDINATE_INVALID",
            "decimalLatitude" if lat_present else "decimalLongitude",
            lat_raw if lat_present else lon_raw,
            "only one of decimalLatitude and decimalLongitude is given; "
            "GBIF cannot interpret a coordinate from a single value."))
    elif lat_present:
        lat = _parse_number(lat_raw)
        lon = _parse_number(lon_raw)
        if lat is None or lon is None:
            bad_term = ("decimalLatitude" if lat is None
                        else "decimalLongitude")
            bad_val = lat_raw if lat is None else lon_raw
            findings.append(Finding(
                rowno, "COORDINATE_INVALID", bad_term, bad_val,
                f"{bad_term} value {bad_val!r} is not a number."))
        elif lat == 0.0 and lon == 0.0:
            findings.append(Finding(
                rowno, "ZERO_COORDINATE", "decimalLatitude",
                f"{lat_raw}, {lon_raw}",
                "coordinate is exactly 0, 0, often a bad null coordinate."))
        elif (abs(lat) > 90 and abs(lat) <= 180 and abs(lon) <= 90
              and abs(lon) <= 180):
            # Swapping the pair makes both values valid: the signature
            # GBIF calls PRESUMED_SWAPPED_COORDINATE. (A pair that is
            # already valid cannot be judged swapped from the file
            # alone, so no such claim is made.)
            findings.append(Finding(
                rowno, "PRESUMED_SWAPPED_COORDINATE", "decimalLatitude",
                f"{lat_raw}, {lon_raw}",
                f"latitude {lat_raw} is outside -90..90 but would be a "
                f"valid longitude, and longitude {lon_raw} would be a "
                "valid latitude: the pair appears swapped."))
        elif abs(lat) > 90 or abs(lon) > 180:
            findings.append(Finding(
                rowno, "COORDINATE_OUT_OF_RANGE", "decimalLatitude",
                f"{lat_raw}, {lon_raw}",
                f"latitude {lat_raw} is outside -90..90 or longitude "
                f"{lon_raw} is outside -180..180."))

    # --- coordinate precision / uncertainty ------------------------------
    prec_raw = _cell(row, "coordinatePrecision")
    if prec_raw:
        prec = _parse_number(prec_raw)
        if prec is None or prec < 0 or prec > 1:
            findings.append(Finding(
                rowno, "COORDINATE_PRECISION_INVALID",
                "coordinatePrecision", prec_raw,
                "coordinatePrecision must be a number between 0 and 1 "
                "(decimal degrees)."))
    unc_raw = _cell(row, "coordinateUncertaintyInMeters")
    if unc_raw:
        unc = _parse_number(unc_raw)
        if unc is None or unc < 0:
            findings.append(Finding(
                rowno, "COORDINATE_UNCERTAINTY_METERS_INVALID",
                "coordinateUncertaintyInMeters", unc_raw,
                "coordinateUncertaintyInMeters must be a non-negative "
                "number of metres."))

    # --- geodetic datum --------------------------------------------------
    datum = _cell(row, "geodeticDatum")
    has_coords = lat_present or lon_present
    if has_coords and not datum and "geodeticDatum" in row:
        findings.append(Finding(
            rowno, "GEODETIC_DATUM_ASSUMED_WGS84", "geodeticDatum", "",
            "no geodeticDatum given; GBIF will assume WGS84."))
    elif datum:
        dnorm = re.sub(r"[\s_\-]+", "", datum.upper())
        known = {re.sub(r"[\s_\-]+", "", d.upper()) for d in KNOWN_DATUMS}
        if not (_EPSG_RE.match(datum) or dnorm in known):
            findings.append(Finding(
                rowno, "GEODETIC_DATUM_INVALID", "geodeticDatum", datum,
                f"geodeticDatum {datum!r} could not be interpreted; use "
                "WGS84 (or an EPSG:NNNN code)."))

    # --- country / countryCode -------------------------------------------
    country = _cell(row, "country")
    code = _cell(row, "countryCode")
    code2 = None
    if code:
        cu = code.upper()
        if cu in ALPHA2_CODES:
            code2 = cu
        elif cu in ALPHA3_TO_ALPHA2:
            code2 = ALPHA3_TO_ALPHA2[cu]
        else:
            findings.append(Finding(
                rowno, "COUNTRY_INVALID", "countryCode", code,
                f"countryCode {code!r} is not an ISO 3166-1 alpha-2 or "
                "alpha-3 code."))
    country2 = None
    if country:
        country2 = COUNTRY_NAME_TO_CODE.get(_normalise_name(country))
        if country2 is None:
            findings.append(Finding(
                rowno, "COUNTRY_INVALID", "country", country,
                f"country {country!r} is not a recognised country name "
                "or ISO code."))
    if (country2 is not None and code2 is not None
            and country2 != code2
            and code2 not in GBIF_EXTRA_COUNTRY_CODES
            and country2 not in GBIF_EXTRA_COUNTRY_CODES):
        findings.append(Finding(
            rowno, "COUNTRY_MISMATCH", "countryCode", code,
            f"country {country!r} is {country2} but countryCode "
            f"{code!r} is {code2}; the two contradict each other."))

    # --- continent vs country --------------------------------------------
    # File-internal consistency only, like the country check: the
    # row's continent must be the continent of the row's own country.
    # Countries whose continent is convention-dependent (trans-
    # continental states) are absent from COUNTRY_CONTINENT and are
    # never checked, rather than risk a false flag.
    if continent:
        canon_continent = _CONTINENT_NORM.get(_norm_vocab(continent))
        alpha2 = code2 if code2 is not None else country2
        if (canon_continent is not None and alpha2 is not None
                and alpha2 in COUNTRY_CONTINENT
                and COUNTRY_CONTINENT[alpha2] != canon_continent):
            findings.append(Finding(
                rowno, "CONTINENT_COUNTRY_MISMATCH", "continent",
                continent,
                f"continent {continent!r} does not match the country "
                f"on this row ({alpha2} is in "
                f"{COUNTRY_CONTINENT[alpha2]})."))

    # --- references URI ----------------------------------------------------
    references = _cell(row, "references")
    if references and not _is_absolute_uri(references):
        findings.append(Finding(
            rowno, "REFERENCES_URI_INVALID", "references", references,
            f"references {references!r} is not a valid absolute URI "
            "(expected something like https://… or doi:…)."))

    # --- footprint WKT / SRS ------------------------------------------------
    footprint_wkt = _cell(row, "footprintWKT")
    if footprint_wkt and not _wkt_is_plausible(footprint_wkt):
        findings.append(Finding(
            rowno, "FOOTPRINT_WKT_INVALID", "footprintWKT", footprint_wkt,
            "footprintWKT could not be interpreted as Well-Known Text "
            "(expected e.g. POLYGON ((lon lat, …)) )."))
    footprint_srs = _cell(row, "footprintSRS")
    if footprint_srs and not _srs_is_interpretable(footprint_srs):
        findings.append(Finding(
            rowno, "FOOTPRINT_SRS_INVALID", "footprintSRS", footprint_srs,
            f"footprintSRS {footprint_srs!r} could not be interpreted; "
            "use a datum name, an EPSG code, or a WKT CRS string."))

    # --- verbatim depth / elevation units -----------------------------------
    verbatim_depth = _cell(row, "verbatimDepth")
    if verbatim_depth and _IMPERIAL_UNIT_RE.search(verbatim_depth):
        findings.append(Finding(
            rowno, "DEPTH_NOT_METRIC", "verbatimDepth", verbatim_depth,
            "verbatimDepth appears to be given in imperial units; "
            "GBIF expects metres."))
    verbatim_elev = _cell(row, "verbatimElevation")
    if verbatim_elev and _IMPERIAL_UNIT_RE.search(verbatim_elev):
        findings.append(Finding(
            rowno, "ELEVATION_NOT_METRIC", "verbatimElevation",
            verbatim_elev,
            "verbatimElevation appears to be given in imperial units; "
            "GBIF expects metres."))

    # --- individualCount -------------------------------------------------
    count_raw = _cell(row, "individualCount")
    count = None
    if count_raw:
        count = _parse_int_count(count_raw)
        if count is None:
            findings.append(Finding(
                rowno, "INDIVIDUAL_COUNT_INVALID", "individualCount",
                count_raw,
                "individualCount must be a non-negative integer."))
    if count is not None and status_norm is not None:
        if count == 0 and status_norm == "present":
            findings.append(Finding(
                rowno, "INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS",
                "individualCount", count_raw,
                "individualCount is 0 but occurrenceStatus is present."))
        elif count > 0 and status_norm == "absent":
            findings.append(Finding(
                rowno, "INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS",
                "individualCount", count_raw,
                "individualCount is > 0 but occurrenceStatus is absent."))

    # --- elevation / depth -----------------------------------------------
    _check_min_max(row, rowno, "minimumElevationInMeters",
                   "maximumElevationInMeters", "ELEVATION_NON_NUMERIC",
                   "ELEVATION_MIN_MAX_SWAPPED", findings)
    _check_min_max(row, rowno, "minimumDepthInMeters",
                   "maximumDepthInMeters", "DEPTH_NON_NUMERIC",
                   "DEPTH_MIN_MAX_SWAPPED", findings)
    for term in ("minimumElevationInMeters", "maximumElevationInMeters"):
        val = _cell(row, term)
        if val:
            num = _parse_number(val)
            if num is not None and (num > 17000 or num < -11000):
                findings.append(Finding(
                    rowno, "ELEVATION_UNLIKELY", term, val,
                    "elevation is above 17 km or below -11 km."))
    for term in ("minimumDepthInMeters", "maximumDepthInMeters"):
        val = _cell(row, term)
        if val:
            num = _parse_number(val)
            if num is not None and (num < 0 or num > 11000):
                findings.append(Finding(
                    rowno, "DEPTH_UNLIKELY", term, val,
                    "depth is negative or larger than 11,000 m."))


def _check_min_max(row, rowno, min_term, max_term, non_numeric_flag,
                   swapped_flag, findings):
    min_raw = _cell(row, min_term)
    max_raw = _cell(row, max_term)
    min_v = max_v = None
    if min_raw:
        min_v = _parse_number(min_raw)
        if min_v is None:
            findings.append(Finding(
                rowno, non_numeric_flag, min_term, min_raw,
                f"{min_term} value {min_raw!r} is not a number."))
    if max_raw:
        max_v = _parse_number(max_raw)
        if max_v is None:
            findings.append(Finding(
                rowno, non_numeric_flag, max_term, max_raw,
                f"{max_term} value {max_raw!r} is not a number."))
    if min_v is not None and max_v is not None and min_v > max_v:
        findings.append(Finding(
            rowno, swapped_flag, min_term, f"{min_raw} / {max_raw}",
            f"{min_term} ({min_raw}) is greater than {max_term} "
            f"({max_raw}); the values appear swapped."))


# ---------------------------------------------------------------------------
# Whole-file check
# ---------------------------------------------------------------------------

def check_file(path):
    """Check one occurrence file. Returns a dict with keys:
    file, rows, columns, findings (list of Finding), summary
    {errors, warnings, flags: {flag: count}}."""
    fieldnames, rows = read_occurrence_file(path)
    findings = []

    # --- header checks ---------------------------------------------------
    seen_headers = set()
    for header in fieldnames:
        if header in seen_headers:
            findings.append(Finding(
                0, "DWCCHECK_DUPLICATE_TERM", header, header,
                f"header {header!r} appears more than once."))
        seen_headers.add(header)
    known = set(DWC_TERMS) | {"id"}
    for header in fieldnames:
        if header not in known:
            shown = header if len(header) <= 60 else header[:57] + "..."
            suggestion = ""
            lower_map = {t.lower(): t for t in DWC_TERMS}
            if header.lower() in lower_map:
                suggestion = (f" Did you mean {lower_map[header.lower()]!r} "
                              "(Darwin Core terms are case-sensitive)?")
            else:
                close = difflib.get_close_matches(header, DWC_TERMS, n=1,
                                                  cutoff=0.8)
                if close:
                    suggestion = f" Did you mean {close[0]!r}?"
            findings.append(Finding(
                0, "DWCCHECK_UNKNOWN_TERM", header, header,
                f"header {shown!r} is not a Darwin Core term; GBIF "
                f"will ignore this column.{suggestion}"))
    for term in REQUIRED_TERMS:
        if term not in fieldnames:
            findings.append(Finding(
                0, "DWCCHECK_MISSING_TERM", term, "",
                f"required term {term} is missing as a column."))
    for term in RECOMMENDED_TERMS:
        if term not in fieldnames:
            findings.append(Finding(
                0, "DWCCHECK_MISSING_RECOMMENDED_TERM", term, "",
                f"recommended term {term} is missing as a column."))
    if "geodeticDatum" not in fieldnames and (
            "decimalLatitude" in fieldnames
            or "decimalLongitude" in fieldnames):
        findings.append(Finding(
            0, "GEODETIC_DATUM_ASSUMED_WGS84", "geodeticDatum", "",
            "no geodeticDatum column; GBIF will assume WGS84 for every "
            "coordinate in this file."))

    # --- row checks ------------------------------------------------------
    seen_occurrence_ids = {}
    for row in rows:
        check_row(row, seen_occurrence_ids, findings)

    findings.sort(key=lambda f: (f.row, f.flag))
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    flag_counts = {}
    for f in findings:
        flag_counts[f.flag] = flag_counts.get(f.flag, 0) + 1
    return {
        "file": str(path),
        "rows": len(rows),
        "columns": list(fieldnames),
        "findings": findings,
        "summary": {"errors": errors, "warnings": warnings,
                    "flags": flag_counts},
    }


def flag_definitions():
    """The flags dwccheck emits, with severity and GBIF's definition."""
    out = []
    for flag in sorted(FLAG_DEFINITIONS):
        severity, definition = FLAG_DEFINITIONS[flag]
        origin = ("GBIF OccurrenceIssue" if not flag.startswith("DWCCHECK_")
                  else "dwccheck file-level code")
        out.append({"flag": flag, "severity": severity,
                    "origin": origin, "definition": definition})
    return out
