"""Tests for dwccheck, pinned to the published oracles:

- the GBIF OccurrenceIssue vocabulary (108 values) and the GBIF
  BasisOfRecord / OccurrenceStatus / TypeStatus / Continent
  enumerations, read from https://api.gbif.org/v1/enumeration/basic/*
  on 2026-11-18;
- the Darwin Core term list (TDWG dwc dist/simple_dwc_vertical.csv,
  fetched 2026-11-18);
- GBIF's published flag definitions (gbif-api OccurrenceIssue docs).

If GBIF or TDWG changes a vocabulary, the pinning tests fail loudly so
the data modules get regenerated — that is the point of pinning.
"""

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dwccheck import cli, core  # noqa: E402
from dwccheck.countries_data import COUNTRIES  # noqa: E402
from dwccheck.terms_data import DWC_TERMS  # noqa: E402

BASE_HEADER = ["occurrenceID", "basisOfRecord", "scientificName",
               "eventDate", "occurrenceStatus", "decimalLatitude",
               "decimalLongitude", "geodeticDatum",
               "coordinateUncertaintyInMeters", "country", "countryCode",
               "institutionCode", "kingdom", "taxonRank", "individualCount"]
BASE_ROW = {
    "occurrenceID": "urn:test:1", "basisOfRecord": "HumanObservation",
    "scientificName": "Quercus robur", "eventDate": "2019-05-14",
    "occurrenceStatus": "present", "decimalLatitude": "48.8566",
    "decimalLongitude": "2.3522", "geodeticDatum": "WGS84",
    "coordinateUncertaintyInMeters": "30", "country": "France",
    "countryCode": "FR", "institutionCode": "EX",
    "kingdom": "Plantae", "taxonRank": "species", "individualCount": "1",
}


def write_csv(tmpdir, rows, header=None, name="occ.csv", delimiter=","):
    header = header if header is not None else BASE_HEADER
    path = Path(tmpdir) / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header,
                                delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def check_rows(tmpdir, rows, header=None, name="occ.csv", delimiter=","):
    path = write_csv(tmpdir, rows, header=header, name=name,
                     delimiter=delimiter)
    return core.check_file(path)


def flags_of(result, row=None):
    return [f.flag for f in result["findings"]
            if row is None or f.row == row]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def row(self, **overrides):
        r = dict(BASE_ROW)
        r.update(overrides)
        return r


# ---------------------------------------------------------------------------
# Oracle pinning
# ---------------------------------------------------------------------------

class TestOraclePinning(unittest.TestCase):
    def test_gbif_occurrence_issue_vocabulary_count(self):
        # Read from the live GBIF API on 2026-11-18: 108 values.
        self.assertEqual(len(core.GBIF_OCCURRENCE_ISSUES), 108)

    def test_every_gbif_flag_emitted_is_in_gbif_vocabulary(self):
        for flag in core.GBIF_FLAGS_EMITTED:
            self.assertIn(flag, core.GBIF_OCCURRENCE_ISSUES, flag)

    def test_dwccheck_codes_are_not_gbif_flags(self):
        for flag in core.FLAG_DEFINITIONS:
            if flag.startswith("DWCCHECK_"):
                self.assertNotIn(flag, core.GBIF_OCCURRENCE_ISSUES)

    def test_basis_of_record_matches_gbif_enumeration(self):
        # GBIF API /enumeration/basic/BasisOfRecord, 2026-11-18:
        # PRESERVED_SPECIMEN, FOSSIL_SPECIMEN, LIVING_SPECIMEN,
        # OBSERVATION, HUMAN_OBSERVATION, MACHINE_OBSERVATION,
        # MATERIAL_SAMPLE, LITERATURE, MATERIAL_CITATION, OCCURRENCE,
        # UNKNOWN — in Darwin Core (camel-case) spelling:
        self.assertEqual(set(core.BASIS_OF_RECORD), {
            "PreservedSpecimen", "FossilSpecimen", "LivingSpecimen",
            "Observation", "HumanObservation", "MachineObservation",
            "MaterialSample", "Literature", "MaterialCitation",
            "Occurrence", "Unknown"})

    def test_occurrence_status_matches_gbif_enumeration(self):
        # GBIF API: PRESENT, ABSENT, DETECTED, NOT_DETECTED.
        self.assertEqual(set(core.OCCURRENCE_STATUS),
                         {"present", "absent", "detected", "not_detected"})

    def test_type_status_count_matches_gbif_enumeration(self):
        self.assertEqual(len(core.TYPE_STATUS), 44)
        self.assertIn("HOLOTYPE", core.TYPE_STATUS)
        self.assertIn("PARATYPE", core.TYPE_STATUS)

    def test_continents_match_gbif_enumeration(self):
        self.assertEqual(set(core.CONTINENTS), {
            "Africa", "Antarctica", "Asia", "Oceania", "Europe",
            "North America", "South America"})

    def test_required_terms_are_dwc_terms(self):
        for term in core.REQUIRED_TERMS + core.RECOMMENDED_TERMS:
            self.assertIn(term, DWC_TERMS, term)

    def test_dwc_term_list_size(self):
        # TDWG simple_dwc_vertical.csv, fetched 2026-11-18, deduped.
        self.assertEqual(len(DWC_TERMS), 224)
        for term in ("occurrenceID", "decimalLatitude", "eventDate",
                     "basisOfRecord", "countryCode", "typeStatus"):
            self.assertIn(term, DWC_TERMS)

    def test_country_table_covers_gbif_country_codes(self):
        alpha2 = {row[0] for row in COUNTRIES}
        # Spot-check the codes a publisher will actually use, and the
        # table's provenance size (datasets/country-codes, 2026-11-18).
        self.assertEqual(len(COUNTRIES), 249)
        for code in ("FR", "US", "GB", "KE", "JP", "AU", "BR", "IN",
                     "ZA", "AQ"):
            self.assertIn(code, alpha2)

    def test_flag_definitions_cover_every_emitted_flag(self):
        for flag in core.GBIF_FLAGS_EMITTED:
            severity, definition = core.FLAG_DEFINITIONS[flag]
            self.assertIn(severity, ("error", "warning"))
            self.assertTrue(definition)


# ---------------------------------------------------------------------------
# Header / file structure
# ---------------------------------------------------------------------------

class TestHeaders(TempDirCase):
    def test_clean_base_row_passes(self):
        result = check_rows(self.tmp, [self.row()])
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["warnings"], 0)

    def test_missing_required_column(self):
        header = [h for h in BASE_HEADER if h != "scientificName"]
        result = check_rows(self.tmp, [self.row()], header=header)
        self.assertIn("DWCCHECK_MISSING_TERM", flags_of(result, row=0))

    def test_missing_recommended_column_is_warning(self):
        header = [h for h in BASE_HEADER if h != "kingdom"]
        result = check_rows(self.tmp, [self.row()], header=header)
        self.assertIn("DWCCHECK_MISSING_RECOMMENDED_TERM",
                      flags_of(result, row=0))
        self.assertEqual(result["summary"]["errors"], 0)

    def test_unknown_header_warns_with_case_suggestion(self):
        header = ["DecimalLatitude" if h == "decimalLatitude" else h
                  for h in BASE_HEADER]
        row = self.row()
        row["DecimalLatitude"] = row.pop("decimalLatitude")
        result = check_rows(self.tmp, [row], header=header)
        unknown = [f for f in result["findings"]
                   if f.flag == "DWCCHECK_UNKNOWN_TERM"]
        self.assertEqual(len(unknown), 1)
        self.assertIn("decimalLatitude", unknown[0].message)

    def test_duplicate_header_is_error(self):
        path = Path(self.tmp) / "dup.csv"
        path.write_text(
            "occurrenceID,occurrenceID,basisOfRecord,scientificName,"
            "eventDate\nx,x,HumanObservation,Quercus robur,2019-01-01\n",
            encoding="utf-8")
        result = core.check_file(path)
        self.assertIn("DWCCHECK_DUPLICATE_TERM", flags_of(result, row=0))

    def test_missing_value_in_required_term(self):
        result = check_rows(self.tmp, [self.row(scientificName="")])
        self.assertIn("DWCCHECK_MISSING_VALUE", flags_of(result, row=2))

    def test_duplicate_occurrence_id(self):
        result = check_rows(self.tmp, [self.row(), self.row()])
        self.assertIn("DWCCHECK_DUPLICATE_OCCURRENCE_ID",
                      flags_of(result, row=3))

    def test_distinct_occurrence_ids_pass(self):
        result = check_rows(self.tmp, [
            self.row(), self.row(occurrenceID="urn:test:2")])
        self.assertNotIn("DWCCHECK_DUPLICATE_OCCURRENCE_ID",
                         flags_of(result))

    def test_event_id_may_repeat(self):
        # eventID is a foreign key in an occurrence file: many
        # occurrences legitimately share one event. It must NOT be
        # uniqueness-checked.
        header = BASE_HEADER + ["eventID"]
        rows = [self.row(eventID="ev-1"),
                self.row(occurrenceID="urn:test:2", eventID="ev-1")]
        result = check_rows(self.tmp, rows, header=header)
        self.assertEqual(result["summary"]["errors"], 0)

    def test_tsv_file(self):
        result = check_rows(self.tmp, [self.row()], name="occ.tsv",
                            delimiter="\t")
        self.assertEqual(result["summary"]["errors"], 0)

    def test_bom_and_crlf(self):
        path = Path(self.tmp) / "bom.csv"
        path.write_bytes(
            b"\xef\xbb\xbf" +
            (",".join(BASE_HEADER) + "\r\n" +
             ",".join(BASE_ROW[h] for h in BASE_HEADER) + "\r\n")
            .encode("utf-8"))
        result = core.check_file(path)
        self.assertEqual(result["summary"]["errors"], 0)


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

class TestVocabularies(TempDirCase):
    def test_all_basis_of_record_values_accepted(self):
        rows = [self.row(occurrenceID=f"urn:t:{i}", basisOfRecord=v)
                for i, v in enumerate(core.BASIS_OF_RECORD)]
        result = check_rows(self.tmp, rows)
        self.assertNotIn("BASIS_OF_RECORD_INVALID", flags_of(result))

    def test_basis_of_record_spelling_variants_accepted(self):
        for value in ("PreservedSpecimen", "PRESERVED_SPECIMEN",
                      "preserved_specimen", "preservedspecimen"):
            result = check_rows(self.tmp, [self.row(basisOfRecord=value)])
            self.assertNotIn("BASIS_OF_RECORD_INVALID", flags_of(result),
                             value)

    def test_basis_of_record_invalid(self):
        for value in ("sighting", "specimen", "photo", "iNaturalist",
                      "field observation"):
            result = check_rows(self.tmp, [self.row(basisOfRecord=value)])
            self.assertIn("BASIS_OF_RECORD_INVALID", flags_of(result, row=2),
                          value)

    def test_occurrence_status_values(self):
        for value in ("present", "Present", "PRESENT", "absent",
                      "detected", "not_detected", "not detected"):
            result = check_rows(
                self.tmp, [self.row(occurrenceStatus=value,
                                    individualCount="1"
                                    if value != "absent" else "0")])
            self.assertNotIn("OCCURRENCE_STATUS_UNPARSABLE",
                             flags_of(result), value)
        for value in ("common", "yes", "1", "present?"):
            result = check_rows(self.tmp,
                                [self.row(occurrenceStatus=value)])
            self.assertIn("OCCURRENCE_STATUS_UNPARSABLE",
                          flags_of(result, row=2), value)

    def test_type_status(self):
        header = BASE_HEADER + ["typeStatus"]
        ok = check_rows(self.tmp, [self.row(typeStatus="holotype")],
                        header=header)
        self.assertNotIn("TYPE_STATUS_INVALID", flags_of(ok))
        bad = check_rows(self.tmp, [self.row(typeStatus="main specimen")],
                         header=header)
        self.assertIn("TYPE_STATUS_INVALID", flags_of(bad, row=2))
        unsure = check_rows(self.tmp,
                            [self.row(typeStatus="possible holotype")],
                            header=header)
        self.assertIn("SUSPECTED_TYPE", flags_of(unsure, row=2))
        self.assertNotIn("TYPE_STATUS_INVALID", flags_of(unsure))

    def test_continent(self):
        header = BASE_HEADER + ["continent"]
        for value in ("Africa", "North America", "north america",
                      "SOUTH_AMERICA"):
            result = check_rows(self.tmp, [self.row(continent=value)],
                                header=header)
            self.assertNotIn("CONTINENT_INVALID", flags_of(result), value)
        result = check_rows(self.tmp, [self.row(continent="Atlantis")],
                            header=header)
        self.assertIn("CONTINENT_INVALID", flags_of(result, row=2))


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

class TestDates(TempDirCase):
    def test_valid_event_dates(self):
        for value in ("2019", "2019-05", "2019-05-14",
                      "2019-05-14T08:40Z", "2019-05-14T08:40:00+02:00",
                      "2020-02-29", "2019-05-14/2019-05-20"):
            result = check_rows(self.tmp, [self.row(eventDate=value)])
            self.assertNotIn("RECORDED_DATE_INVALID", flags_of(result),
                             value)

    def test_invalid_event_dates(self):
        for value in ("2021-02-30", "2019-13-01", "2019-00-10",
                      "2019-05-00", "20/05/2019", "May 2019",
                      "2019.05.14", "2019-05-14T25:00Z",
                      "2019-05-20/2019-05-14", "not-a-date"):
            result = check_rows(self.tmp, [self.row(eventDate=value)])
            self.assertIn("RECORDED_DATE_INVALID", flags_of(result, row=2),
                          value)

    def test_unlikely_event_dates(self):
        for value in ("2999-01-01", "1500-01-01"):
            result = check_rows(self.tmp, [self.row(eventDate=value)])
            self.assertIn("RECORDED_DATE_UNLIKELY", flags_of(result, row=2),
                          value)
            self.assertEqual(result["summary"]["errors"], 0)

    def test_event_date_year_month_day_mismatch(self):
        header = BASE_HEADER + ["year", "month", "day"]
        row = self.row(year="2020", month="5", day="14")
        result = check_rows(self.tmp, [row], header=header)
        self.assertIn("RECORDED_DATE_MISMATCH", flags_of(result, row=2))
        ok = check_rows(self.tmp, [self.row(year="2019", month="5",
                                            day="14")], header=header)
        self.assertNotIn("RECORDED_DATE_MISMATCH", flags_of(ok))

    def test_standalone_date_parts(self):
        header = [h for h in BASE_HEADER if h != "eventDate"] + \
            ["year", "month", "day"]
        bad = check_rows(self.tmp,
                         [self.row(year="2021", month="2", day="30")],
                         header=header)
        self.assertIn("RECORDED_DATE_INVALID", flags_of(bad, row=2))
        bad2 = check_rows(self.tmp,
                          [self.row(year="2021", month="13", day="1")],
                          header=header)
        self.assertIn("RECORDED_DATE_INVALID", flags_of(bad2, row=2))

    def test_modified_and_identified_dates(self):
        header = BASE_HEADER + ["modified", "dateIdentified",
                                "georeferencedDate"]
        bad = check_rows(self.tmp, [self.row(modified="yesterday",
                                             dateIdentified="32/13/2000",
                                             georeferencedDate="never")],
                         header=header)
        self.assertIn("MODIFIED_DATE_INVALID", flags_of(bad, row=2))
        self.assertIn("IDENTIFIED_DATE_INVALID", flags_of(bad, row=2))
        self.assertIn("GEOREFERENCED_DATE_INVALID", flags_of(bad, row=2))
        old = check_rows(self.tmp, [self.row(modified="1960-01-01",
                                             dateIdentified="1650-01-01",
                                             georeferencedDate="1650-01-01")],
                         header=header)
        self.assertIn("MODIFIED_DATE_UNLIKELY", flags_of(old, row=2))
        self.assertIn("IDENTIFIED_DATE_UNLIKELY", flags_of(old, row=2))
        self.assertIn("GEOREFERENCED_DATE_UNLIKELY", flags_of(old, row=2))

    def test_day_of_year_checks(self):
        header = BASE_HEADER + ["startDayOfYear", "endDayOfYear"]
        bad = check_rows(self.tmp, [self.row(startDayOfYear="200",
                                             endDayOfYear="100")],
                         header=header)
        self.assertIn("RECORDED_DATE_MISMATCH", flags_of(bad, row=2))
        bad2 = check_rows(self.tmp, [self.row(startDayOfYear="400")],
                          header=header)
        self.assertIn("RECORDED_DATE_INVALID", flags_of(bad2, row=2))

    def test_future_date_within_current_year_is_unlikely(self):
        # Review fix (MEDIUM): the future test used to compare years
        # only, so a full date next month passed silently.
        import datetime as dt
        today = dt.date.today()
        future = (today + dt.timedelta(days=30)).isoformat()
        past = (today - dt.timedelta(days=30)).isoformat()
        result = check_rows(self.tmp, [self.row(eventDate=future)])
        self.assertIn("RECORDED_DATE_UNLIKELY", flags_of(result, row=2))
        result2 = check_rows(self.tmp, [self.row(eventDate=past)])
        self.assertNotIn("RECORDED_DATE_UNLIKELY", flags_of(result2))
        header = BASE_HEADER + ["modified"]
        result3 = check_rows(self.tmp, [self.row(modified=future)],
                             header=header)
        self.assertIn("MODIFIED_DATE_UNLIKELY", flags_of(result3, row=2))
        # A year-month ahead of the current month is future; the
        # current month is not.
        y, m = today.year, today.month
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        result4 = check_rows(self.tmp, [
            self.row(eventDate=f"{ny:04d}-{nm:02d}")])
        self.assertIn("RECORDED_DATE_UNLIKELY", flags_of(result4, row=2))
        result5 = check_rows(self.tmp, [
            self.row(eventDate=f"{y:04d}-{m:02d}")])
        self.assertNotIn("RECORDED_DATE_UNLIKELY", flags_of(result5))

    def test_lowercase_separators_and_basic_format(self):
        # Review fix (LOW): ISO 8601 permits lowercase t/z and the
        # basic YYYYMMDD form; both are now accepted.
        for value in ("2019-05-14t08:40z", "20190514", "20000229"):
            result = check_rows(self.tmp, [self.row(eventDate=value)])
            self.assertNotIn("RECORDED_DATE_INVALID", flags_of(result),
                             value)
        result = check_rows(self.tmp, [self.row(eventDate="20190230")])
        self.assertIn("RECORDED_DATE_INVALID", flags_of(result, row=2))
        result2 = check_rows(self.tmp, [self.row(eventDate="19000229")])
        self.assertIn("RECORDED_DATE_INVALID", flags_of(result2, row=2))


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------

class TestCoordinates(TempDirCase):
    def test_valid_coordinates(self):
        for lat, lon in (("48.8566", "2.3522"), ("-33.8688", "151.2093"),
                         ("0.0", "2.3522"), ("48.8566", "0.0"),
                         ("-90", "-180"), ("90", "180")):
            result = check_rows(self.tmp, [self.row(
                decimalLatitude=lat, decimalLongitude=lon)])
            self.assertEqual(result["summary"]["errors"], 0, (lat, lon))

    def test_zero_coordinate(self):
        result = check_rows(self.tmp, [self.row(decimalLatitude="0",
                                                decimalLongitude="0.0")])
        self.assertIn("ZERO_COORDINATE", flags_of(result, row=2))

    def test_non_numeric_coordinate(self):
        result = check_rows(self.tmp, [self.row(decimalLatitude="north")])
        self.assertIn("COORDINATE_INVALID", flags_of(result, row=2))

    def test_single_coordinate(self):
        result = check_rows(self.tmp, [self.row(decimalLongitude="")])
        self.assertIn("COORDINATE_INVALID", flags_of(result, row=2))

    def test_out_of_range(self):
        result = check_rows(self.tmp, [self.row(decimalLatitude="95",
                                                decimalLongitude="190")])
        self.assertIn("COORDINATE_OUT_OF_RANGE", flags_of(result, row=2))
        result2 = check_rows(self.tmp, [self.row(decimalLatitude="-200",
                                                 decimalLongitude="0")])
        self.assertIn("COORDINATE_OUT_OF_RANGE", flags_of(result2, row=2))

    def test_presumed_swapped(self):
        result = check_rows(self.tmp, [self.row(
            decimalLatitude="151.2093", decimalLongitude="-33.8688")])
        self.assertIn("PRESUMED_SWAPPED_COORDINATE",
                      flags_of(result, row=2))
        self.assertNotIn("COORDINATE_OUT_OF_RANGE", flags_of(result, row=2))

    def test_valid_pair_is_never_called_swapped(self):
        # A pair that is already in range cannot be judged swapped from
        # the file alone; dwccheck must not claim it.
        result = check_rows(self.tmp, [self.row(
            decimalLatitude="2.3522", decimalLongitude="48.8566")])
        self.assertNotIn("PRESUMED_SWAPPED_COORDINATE", flags_of(result))
        self.assertEqual(result["summary"]["errors"], 0)

    def test_uncertainty_and_precision(self):
        bad = check_rows(self.tmp, [
            self.row(coordinateUncertaintyInMeters="-5")])
        self.assertIn("COORDINATE_UNCERTAINTY_METERS_INVALID",
                      flags_of(bad, row=2))
        bad2 = check_rows(self.tmp, [
            self.row(coordinateUncertaintyInMeters="far")])
        self.assertIn("COORDINATE_UNCERTAINTY_METERS_INVALID",
                      flags_of(bad2, row=2))
        header = BASE_HEADER + ["coordinatePrecision"]
        bad3 = check_rows(self.tmp, [self.row(coordinatePrecision="7")],
                          header=header)
        self.assertIn("COORDINATE_PRECISION_INVALID", flags_of(bad3, row=2))
        ok = check_rows(self.tmp, [self.row(coordinatePrecision="0.00001")],
                        header=header)
        self.assertNotIn("COORDINATE_PRECISION_INVALID", flags_of(ok))

    def test_geodetic_datum(self):
        for value in ("WGS84", "WGS 84", "EPSG:4326", "NAD83", "wgs84",
                      "WGS-84", "WGS_84"):
            result = check_rows(self.tmp, [self.row(geodeticDatum=value)])
            self.assertNotIn("GEODETIC_DATUM_INVALID", flags_of(result),
                             value)
        for value in ("not-a-datum", "WGS", "GPS", "the moon"):
            result = check_rows(self.tmp, [self.row(geodeticDatum=value)])
            self.assertIn("GEODETIC_DATUM_INVALID", flags_of(result, row=2),
                          value)

    def test_missing_datum_column_is_one_file_level_warning(self):
        header = [h for h in BASE_HEADER if h != "geodeticDatum"]
        result = check_rows(self.tmp, [self.row(), self.row(
            occurrenceID="urn:test:2")], header=header)
        datum_flags = [f for f in result["findings"]
                       if f.flag == "GEODETIC_DATUM_ASSUMED_WGS84"]
        self.assertEqual(len(datum_flags), 1)
        self.assertEqual(datum_flags[0].row, 0)

    def test_empty_datum_cell_warns_per_row(self):
        result = check_rows(self.tmp, [self.row(geodeticDatum="")])
        self.assertIn("GEODETIC_DATUM_ASSUMED_WGS84",
                      flags_of(result, row=2))
        self.assertEqual(result["summary"]["errors"], 0)


# ---------------------------------------------------------------------------
# Country checks
# ---------------------------------------------------------------------------

class TestCountry(TempDirCase):
    def test_matching_country_and_code(self):
        for country, code in (("France", "FR"), ("france", "FRA"),
                              ("United States", "US"), ("USA", "US"),
                              ("Japan", "JP"), ("United Kingdom", "GB"),
                              ("South Korea", "KR"), ("Kenya", "ke")):
            result = check_rows(self.tmp, [self.row(country=country,
                                                    countryCode=code)])
            self.assertNotIn("COUNTRY_MISMATCH", flags_of(result),
                             (country, code))
            self.assertNotIn("COUNTRY_INVALID", flags_of(result),
                             (country, code))

    def test_continent_country_mismatch(self):
        header = BASE_HEADER + ["continent"]
        bad = check_rows(self.tmp, [
            self.row(continent="Asia", country="France",
                     countryCode="FR")], header=header)
        self.assertIn("CONTINENT_COUNTRY_MISMATCH", flags_of(bad, row=2))
        good = check_rows(self.tmp, [
            self.row(continent="Europe", country="France",
                     countryCode="FR")], header=header)
        self.assertNotIn("CONTINENT_COUNTRY_MISMATCH", flags_of(good))
        # Central America counts as NORTH_AMERICA in GBIF's model.
        ca = check_rows(self.tmp, [
            self.row(continent="North America", country="Mexico",
                     countryCode="MX")], header=header)
        self.assertNotIn("CONTINENT_COUNTRY_MISMATCH", flags_of(ca))
        # Transcontinental countries are never continent-checked.
        ru = check_rows(self.tmp, [
            self.row(continent="Asia", country="Russia",
                     countryCode="RU")], header=header)
        self.assertNotIn("CONTINENT_COUNTRY_MISMATCH", flags_of(ru))

    def test_references_uri(self):
        header = BASE_HEADER + ["references"]
        for value in ("https://example.org/paper/1", "doi:10.1234/abc"):
            result = check_rows(self.tmp, [self.row(references=value)],
                                header=header)
            self.assertNotIn("REFERENCES_URI_INVALID", flags_of(result),
                             value)
        for value in ("www.example.org/paper", "see the lab notebook",
                      "https://example.org/a b"):
            result = check_rows(self.tmp, [self.row(references=value)],
                                header=header)
            self.assertIn("REFERENCES_URI_INVALID", flags_of(result),
                          value)

    def test_footprint_checks(self):
        header = BASE_HEADER + ["footprintWKT", "footprintSRS"]
        good = check_rows(self.tmp, [self.row(
            footprintWKT="POLYGON ((2.0 48.0, 3.0 48.0, 3.0 49.0, "
                         "2.0 48.0))",
            footprintSRS="WGS84")], header=header)
        self.assertNotIn("FOOTPRINT_WKT_INVALID", flags_of(good))
        self.assertNotIn("FOOTPRINT_SRS_INVALID", flags_of(good))
        point = check_rows(self.tmp, [self.row(
            footprintWKT="POINT (2.35 48.85)",
            footprintSRS='GEOGCS["GCS_WGS_1984"]')], header=header)
        self.assertNotIn("FOOTPRINT_WKT_INVALID", flags_of(point))
        self.assertNotIn("FOOTPRINT_SRS_INVALID", flags_of(point))
        bad = check_rows(self.tmp, [self.row(
            footprintWKT="somewhere near the river",
            footprintSRS="the blue grid")], header=header)
        self.assertIn("FOOTPRINT_WKT_INVALID", flags_of(bad, row=2))
        self.assertIn("FOOTPRINT_SRS_INVALID", flags_of(bad, row=2))
        truncated = check_rows(self.tmp, [self.row(
            footprintWKT="POLYGON ((2.0 48.0, 3.0 48.0")], header=header)
        self.assertIn("FOOTPRINT_WKT_INVALID", flags_of(truncated, row=2))

    def test_verbatim_imperial_units(self):
        header = BASE_HEADER + ["verbatimDepth", "verbatimElevation"]
        result = check_rows(self.tmp, [self.row(
            verbatimDepth="120 ft", verbatimElevation="5,280 feet")],
            header=header)
        self.assertIn("DEPTH_NOT_METRIC", flags_of(result, row=2))
        self.assertIn("ELEVATION_NOT_METRIC", flags_of(result, row=2))
        metric = check_rows(self.tmp, [self.row(
            verbatimDepth="120 m", verbatimElevation="1600 metres")],
            header=header)
        self.assertNotIn("DEPTH_NOT_METRIC", flags_of(metric))
        self.assertNotIn("ELEVATION_NOT_METRIC", flags_of(metric))

    def test_footprint_mismatch_is_a_documented_limit(self):
        # FOOTPRINT_WKT_MISMATCH needs a geometry engine; it must be
        # in GBIF's vocabulary, must NOT be emitted, and the README
        # must carry the limit.
        self.assertIn("FOOTPRINT_WKT_MISMATCH", core.GBIF_OCCURRENCE_ISSUES)
        self.assertNotIn("FOOTPRINT_WKT_MISMATCH", core.FLAG_DEFINITIONS)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("FOOTPRINT_WKT_MISMATCH", readme)

    def test_continent_table_is_sane(self):
        from dwccheck.countries_data import COUNTRY_CONTINENT
        self.assertEqual(COUNTRY_CONTINENT["FR"], "Europe")
        self.assertEqual(COUNTRY_CONTINENT["MX"], "North America")
        self.assertEqual(COUNTRY_CONTINENT["BR"], "South America")
        self.assertEqual(COUNTRY_CONTINENT["PG"], "Oceania")
        self.assertEqual(COUNTRY_CONTINENT["AQ"], "Antarctica")
        for excluded in ("RU", "TR", "EG", "KZ"):
            self.assertNotIn(excluded, COUNTRY_CONTINENT)
        for value in COUNTRY_CONTINENT.values():
            self.assertIn(value, core.CONTINENTS)

    def test_country_mismatch(self):
        result = check_rows(self.tmp, [self.row(country="France",
                                                countryCode="US")])
        self.assertIn("COUNTRY_MISMATCH", flags_of(result, row=2))

    def test_invalid_country_code(self):
        result = check_rows(self.tmp, [self.row(countryCode="XX")])
        self.assertIn("COUNTRY_INVALID", flags_of(result, row=2))

    def test_invalid_country_name(self):
        result = check_rows(self.tmp, [self.row(country="Narnia",
                                                countryCode="")])
        self.assertIn("COUNTRY_INVALID", flags_of(result, row=2))

    def test_code_only_or_country_only_is_fine(self):
        result = check_rows(self.tmp, [self.row(country="")])
        self.assertNotIn("COUNTRY_INVALID", flags_of(result))
        self.assertNotIn("COUNTRY_MISMATCH", flags_of(result))
        result2 = check_rows(self.tmp, [self.row(countryCode="")])
        self.assertNotIn("COUNTRY_INVALID", flags_of(result2))


# ---------------------------------------------------------------------------
# Counts, elevation, depth
# ---------------------------------------------------------------------------

class TestCountsAndRanges(TempDirCase):
    def test_individual_count(self):
        for value in ("0", "1", "250"):
            result = check_rows(self.tmp, [self.row(
                individualCount=value,
                occurrenceStatus="absent" if value == "0" else "present")])
            self.assertNotIn("INDIVIDUAL_COUNT_INVALID", flags_of(result),
                             value)
        for value in ("-1", "2.5", "many", "1e3"):
            result = check_rows(self.tmp,
                                [self.row(individualCount=value)])
            self.assertIn("INDIVIDUAL_COUNT_INVALID",
                          flags_of(result, row=2), value)

    def test_count_status_conflicts(self):
        result = check_rows(self.tmp, [self.row(
            individualCount="0", occurrenceStatus="present")])
        self.assertIn("INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS",
                      flags_of(result, row=2))
        result2 = check_rows(self.tmp, [self.row(
            individualCount="3", occurrenceStatus="absent")])
        self.assertIn("INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS",
                      flags_of(result2, row=2))

    def test_elevation_depth(self):
        header = BASE_HEADER + ["minimumElevationInMeters",
                                "maximumElevationInMeters",
                                "minimumDepthInMeters",
                                "maximumDepthInMeters"]
        bad = check_rows(self.tmp, [self.row(
            minimumElevationInMeters="500", maximumElevationInMeters="100",
            minimumDepthInMeters="deep", maximumDepthInMeters="50")],
            header=header)
        self.assertIn("ELEVATION_MIN_MAX_SWAPPED", flags_of(bad, row=2))
        self.assertIn("DEPTH_NON_NUMERIC", flags_of(bad, row=2))
        unlikely = check_rows(self.tmp, [self.row(
            minimumElevationInMeters="20000", minimumDepthInMeters="-3")],
            header=header)
        self.assertIn("ELEVATION_UNLIKELY", flags_of(unlikely, row=2))
        self.assertIn("DEPTH_UNLIKELY", flags_of(unlikely, row=2))
        self.assertEqual(unlikely["summary"]["errors"], 0)


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------

class TestCli(TempDirCase):
    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_check_clean_exit_0(self):
        path = write_csv(self.tmp, [self.row()])
        code, out, _ = self.run_cli(["check", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("result: PASS", out)

    def test_check_dirty_exit_1(self):
        path = write_csv(self.tmp, [self.row(basisOfRecord="sighting")])
        code, out, _ = self.run_cli(["check", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("BASIS_OF_RECORD_INVALID", out)
        self.assertIn("result: FAIL", out)

    def test_missing_file_is_one_line_error(self):
        code, _, err = self.run_cli(["check", "/nonexistent/nope.csv"])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error:"))
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_empty_file_is_one_line_error(self):
        path = Path(self.tmp) / "empty.csv"
        path.write_text("", encoding="utf-8")
        code, _, err = self.run_cli(["check", str(path)])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_no_rows_is_one_line_error(self):
        path = Path(self.tmp) / "hdr.csv"
        path.write_text("occurrenceID,basisOfRecord\n", encoding="utf-8")
        code, _, err = self.run_cli(["check", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("no data rows", err)

    def test_extra_values_row_is_one_line_error(self):
        path = Path(self.tmp) / "extra.csv"
        path.write_text("occurrenceID,basisOfRecord\nx,HumanObservation,"
                        "surprise\n", encoding="utf-8")
        code, _, err = self.run_cli(["check", str(path)])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_json_format(self):
        path = write_csv(self.tmp, [self.row(basisOfRecord="sighting")])
        code, out, _ = self.run_cli(["check", str(path), "--format", "json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["rows"], 1)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["findings"][0]["flag"],
                         "BASIS_OF_RECORD_INVALID")

    def test_csv_format(self):
        path = write_csv(self.tmp, [self.row(basisOfRecord="sighting")])
        code, out, _ = self.run_cli(["check", str(path), "--format", "csv"])
        self.assertEqual(code, 1)
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[0], ["row", "flag", "severity", "term",
                                   "value", "message"])
        self.assertEqual(rows[1][1], "BASIS_OF_RECORD_INVALID")

    def test_flags_command(self):
        code, out, _ = self.run_cli(["flags"])
        self.assertEqual(code, 0)
        self.assertIn("ZERO_COORDINATE", out)
        self.assertIn("COUNTRY_MISMATCH", out)
        self.assertIn("DWCCHECK_MISSING_TERM", out)
        # COUNTRY_COORDINATE_MISMATCH needs border data and must never
        # be emitted; it must not even be listed as a flag we emit.
        self.assertNotIn("COUNTRY_COORDINATE_MISMATCH", out)
        self.assertNotIn("TAXON_MATCH_NONE", out)

    def test_no_subcommand_is_usage_error(self):
        code, _, _ = self.run_cli([])
        self.assertEqual(code, 2)

    def test_console_script_via_subprocess(self):
        path = write_csv(self.tmp, [self.row()])
        proc = subprocess.run(
            [sys.executable, "-m", "dwccheck", "check", str(path)],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("result: PASS", proc.stdout)

    def test_embedded_newline_reports_physical_line(self):
        # Review fix (LOW): row numbers are physical file lines. A
        # quoted field embedding a newline pushes the next record to
        # line 4, and its finding must say row 4, not row 3.
        path = Path(self.tmp) / "multi.csv"
        header = ",".join(BASE_HEADER)
        row1 = ",".join(
            '"Quercus\nrobur"' if h == "scientificName" else BASE_ROW[h]
            for h in BASE_HEADER)
        bad_row = dict(BASE_ROW, occurrenceID="urn:test:2",
                       basisOfRecord="sighting")
        row2 = ",".join(bad_row[h] for h in BASE_HEADER)
        path.write_text(header + "\n" + row1 + "\n" + row2 + "\n",
                        encoding="utf-8")
        result = core.check_file(path)
        bad = [f for f in result["findings"]
               if f.flag == "BASIS_OF_RECORD_INVALID"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].row, 4)


# ---------------------------------------------------------------------------
# Shipped examples (the README demo)
# ---------------------------------------------------------------------------

class TestExamples(unittest.TestCase):
    def test_clean_example_passes(self):
        result = core.check_file(ROOT / "examples" / "occurrences_clean.csv")
        self.assertEqual(result["rows"], 6)
        self.assertEqual(result["summary"]["errors"], 0)
        self.assertEqual(result["summary"]["warnings"], 0)

    def test_messy_example_counts(self):
        result = core.check_file(ROOT / "examples" / "occurrences_messy.csv")
        self.assertEqual(result["rows"], 10)
        self.assertEqual(result["summary"]["errors"], 12)
        self.assertEqual(result["summary"]["warnings"], 4)
        expected = {
            "BASIS_OF_RECORD_INVALID", "RECORDED_DATE_INVALID",
            "ZERO_COORDINATE", "DWCCHECK_DUPLICATE_OCCURRENCE_ID",
            "OCCURRENCE_STATUS_UNPARSABLE", "PRESUMED_SWAPPED_COORDINATE",
            "COUNTRY_MISMATCH", "RECORDED_DATE_UNLIKELY",
            "INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS",
            "DWCCHECK_MISSING_VALUE", "COORDINATE_OUT_OF_RANGE",
            "GEODETIC_DATUM_INVALID",
            "COORDINATE_UNCERTAINTY_METERS_INVALID",
            "DWCCHECK_MISSING_RECOMMENDED_TERM",
        }
        self.assertEqual(set(result["summary"]["flags"]), expected)


class ZeroFalsePositiveCorpusTests(unittest.TestCase):
    """Headline metric: a broad, real-world-shaped VALID corpus must
    produce zero errors and zero warnings. Rows cycle every country
    in the bundled table (with matching name, code and continent),
    every basisOfRecord value, valid dates, footprints, references
    and metric verbatim values."""

    def test_generated_valid_corpus_is_clean(self):
        from dwccheck.countries_data import COUNTRIES, COUNTRY_CONTINENT
        header = BASE_HEADER + [
            "continent", "references", "footprintWKT", "footprintSRS",
            "verbatimDepth", "verbatimElevation", "typeStatus"]
        rows = []
        for i, (code, _a3, name, _official) in enumerate(COUNTRIES):
            row = dict(BASE_ROW)
            row["occurrenceID"] = f"urn:corpus:{i}"
            row["country"] = name
            row["countryCode"] = code
            row["basisOfRecord"] = core.BASIS_OF_RECORD[
                i % len(core.BASIS_OF_RECORD)]
            row["eventDate"] = f"20{10 + i % 10}-0{1 + i % 9}-15"
            row["references"] = f"https://example.org/records/{i}"
            row["footprintWKT"] = "POINT (2.3522 48.8566)"
            row["footprintSRS"] = "WGS84"
            row["verbatimDepth"] = "120 m"
            row["verbatimElevation"] = "35 m"
            row["typeStatus"] = ""
            if code in COUNTRY_CONTINENT:
                row["continent"] = COUNTRY_CONTINENT[code]
            else:
                row["continent"] = ""
            rows.append(row)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_csv(tmp, rows, header=header)
            result = core.check_file(path)
        self.assertEqual(result["summary"]["errors"], 0,
                         result["findings"][:5])
        self.assertEqual(result["summary"]["warnings"], 0,
                         result["findings"][:5])


class GoldenOutputTests(unittest.TestCase):
    """The README's demo outputs are pinned byte-for-byte (review
    fix: the suite used to pin only counts and flag sets, so message
    wording could drift away from the README unnoticed)."""

    def _run(self, example):
        return subprocess.run(
            [sys.executable, "-m", "dwccheck", "check",
             f"examples/{example}"],
            capture_output=True, text=True, cwd=str(ROOT))

    def test_clean_example_output_matches_golden(self):
        proc = self._run("occurrences_clean.csv")
        golden = (ROOT / "tests" / "golden_clean.txt").read_text(
            encoding="utf-8")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, golden)

    def test_messy_example_output_matches_golden(self):
        proc = self._run("occurrences_messy.csv")
        golden = (ROOT / "tests" / "golden_messy.txt").read_text(
            encoding="utf-8")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, golden)


if __name__ == "__main__":
    unittest.main()
