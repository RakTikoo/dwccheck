# dwccheck — check a Darwin Core occurrence file locally, before you upload it to GBIF

**Check a Darwin Core occurrence file locally — before you upload it to GBIF — and fix what GBIF would flag, using GBIF's own flag names.**

Today, finding out what GBIF thinks of your dataset means uploading it to the GBIF Data Validator website and reading the report there. `dwccheck` runs the subset of those checks that can be decided from the file alone, on your machine, in seconds: required terms present, controlled vocabularies, date sanity and format, coordinate sanity, duplicate occurrenceIDs, and whether `country` and `countryCode` agree with each other. Every per-record finding is reported under the same flag GBIF itself would use — `COORDINATE_INVALID`, `ZERO_COORDINATE`, `BASIS_OF_RECORD_INVALID`, `RECORDED_DATE_INVALID`, `COUNTRY_MISMATCH`, … — with the term and the row, so you can fix the file until the real validator has nothing left to say.

## Install

```console
$ pip install git+https://github.com/RakTikoo/dwccheck
```

Requires Python ≥ 3.10. **No dependencies** — standard library only. Everything runs offline; your file never leaves your machine.

Or from the release files (no registry involved): download
`dwccheck-0.1.0-py3-none-any.whl` from the
[v0.1.0 release](https://github.com/RakTikoo/dwccheck/releases/tag/v0.1.0)
(check it against the release's SHA256SUMS if you want) and install it:

```console
pip install dwccheck-0.1.0-py3-none-any.whl
```

Or install straight from GitHub at the v0.1.0 tag:

```console
pip install git+https://github.com/RakTikoo/dwccheck@v0.1.0
pipx install git+https://github.com/RakTikoo/dwccheck@v0.1.0
uv tool install git+https://github.com/RakTikoo/dwccheck@v0.1.0
```

With Homebrew (macOS/Linux):

```console
brew tap RakTikoo/tools
brew install RakTikoo/tools/dwccheck
```

With Scoop (Windows):

```powershell
scoop bucket add RakTikoo https://github.com/RakTikoo/scoop-bucket
scoop install dwccheck
```

## Demo

A clean file (6 synthetic records, `examples/occurrences_clean.csv`):

```console
$ dwccheck check examples/occurrences_clean.csv
file: examples/occurrences_clean.csv
rows checked: 6 data rows, 23 columns
summary: 0 error(s), 0 warning(s)
result: PASS — no errors found.
```

A messy one (`examples/occurrences_messy.csv` — every row has a different problem):

```console
$ dwccheck check examples/occurrences_messy.csv
file: examples/occurrences_messy.csv
rows checked: 10 data rows, 12 columns

file: DWCCHECK_MISSING_RECOMMENDED_TERM [institutionCode] — recommended term institutionCode is missing as a column.
file: DWCCHECK_MISSING_RECOMMENDED_TERM [kingdom] — recommended term kingdom is missing as a column.
file: DWCCHECK_MISSING_RECOMMENDED_TERM [taxonRank] — recommended term taxonRank is missing as a column.
row 2: BASIS_OF_RECORD_INVALID [basisOfRecord] — basisOfRecord 'sighting' is not in GBIF's BasisOfRecord vocabulary: PreservedSpecimen, FossilSpecimen, LivingSpecimen, Observation, HumanObservation, MachineObservation, MaterialSample, Literature, MaterialCitation, Occurrence, Unknown.
row 3: RECORDED_DATE_INVALID [eventDate] — eventDate is not a valid ISO 8601 date (expected YYYY, YYYY-MM, YYYY-MM-DD or a full ISO datetime).
row 4: ZERO_COORDINATE [decimalLatitude] — coordinate is exactly 0, 0, often a bad null coordinate.
row 5: DWCCHECK_DUPLICATE_OCCURRENCE_ID [occurrenceID] — occurrenceID 'urn:example:bad:0001' already appeared on row 2; occurrenceIDs must be unique.
row 6: OCCURRENCE_STATUS_UNPARSABLE [occurrenceStatus] — occurrenceStatus value 'common' cannot be parsed; GBIF's OccurrenceStatus vocabulary is present, absent, detected, not_detected.
row 6: PRESUMED_SWAPPED_COORDINATE [decimalLatitude] — latitude 151.2093 is outside -90..90 but would be a valid longitude, and longitude -33.8688 would be a valid latitude: the pair appears swapped.
row 7: COUNTRY_MISMATCH [countryCode] — country 'France' is FR but countryCode 'US' is US; the two contradict each other.
row 7: RECORDED_DATE_UNLIKELY [eventDate] — eventDate is in the future or before 1600.
row 8: INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS [individualCount] — individualCount is > 0 but occurrenceStatus is absent.
row 9: DWCCHECK_MISSING_VALUE [occurrenceID] — required term occurrenceID is empty on this row.
row 10: COORDINATE_OUT_OF_RANGE [decimalLatitude] — latitude 95.0000 is outside -90..90 or longitude 190.0000 is outside -180..180.
row 11: COORDINATE_UNCERTAINTY_METERS_INVALID [coordinateUncertaintyInMeters] — coordinateUncertaintyInMeters must be a non-negative number of metres.
row 11: GEODETIC_DATUM_INVALID [geodeticDatum] — geodeticDatum 'not-a-datum' could not be interpreted; use WGS84 (or an EPSG:NNNN code).

summary: 12 error(s), 4 warning(s)
result: FAIL — fix the errors before uploading to GBIF.
```

Row numbers are line numbers in the file (the header is row 1), so you can jump straight to the record; for a record whose quoted field spans several lines, the number is the line where the record ends. Exit code is 0 when there are no errors, 1 when there are, 2 when the file cannot be checked at all — so `dwccheck` drops into a script or CI job as a gate before upload.

## Usage

```
dwccheck check FILE [--format text|json|csv]
dwccheck flags
```

- Input is a single occurrence file, CSV or TSV (a `.txt` file's delimiter is sniffed from its first line). UTF-8, with or without a BOM.
- `--format json` or `--format csv` gives the same findings in machine-readable form (one finding per object/row: row, flag, severity, term, value, message).
- `dwccheck flags` lists every flag the tool can emit, with GBIF's definition of it. Flags named `DWCCHECK_…` are this tool's own file-level codes (missing column, duplicate ID, unknown header) — GBIF has no per-record flag for those, and the names keep the two apart.

## Use in CI

This repo is also a composite GitHub Action: it installs dwccheck from this repo at the ref you pin, and checks one occurrence file. The step fails when dwccheck exits 1 (errors found — fix them before uploading to GBIF) or 2 (the file cannot be checked at all).

```yaml
- uses: RakTikoo/dwccheck@main
  with:
    path: data/occurrences.csv
```

Set `format: json` (or `csv`) for machine-readable findings; the default is `text`.

## What it checks

File level:

- Required columns for a GBIF occurrence dataset — `occurrenceID`, `basisOfRecord`, `scientificName`, `eventDate` — are present, and recommended columns (`occurrenceStatus`, `decimalLatitude`, `decimalLongitude`, `countryCode`, `geodeticDatum`, `coordinateUncertaintyInMeters`, `institutionCode`, `kingdom`, `taxonRank`, `individualCount`) are not missing.
- Every header is a real Darwin Core term (the TDWG list), spelled exactly — Darwin Core terms are case-sensitive, so `DecimalLatitude` is flagged with the correction. Duplicate headers are an error.
- `occurrenceID` values are unique across the file. (`eventID` is *not* uniqueness-checked: in an occurrence file it is a link to a shared event, and repeats are normal.)

Per record, under GBIF's own flag names:

- **Vocabularies** — `basisOfRecord` against GBIF's 11-value BasisOfRecord enumeration (`BASIS_OF_RECORD_INVALID`); `occurrenceStatus` against present/absent/detected/not_detected (`OCCURRENCE_STATUS_UNPARSABLE`); `typeStatus` against GBIF's TypeStatus vocabulary (`TYPE_STATUS_INVALID`, or `SUSPECTED_TYPE` when it contains uncertainty words like "possible"); `continent` against GBIF's 7 continents (`CONTINENT_INVALID`). Vocabulary matching is spelling-tolerant the way GBIF's own parser is: `PreservedSpecimen`, `PRESERVED_SPECIMEN` and `preserved_specimen` are the same value; `sighting` is not a value at all.
- **Dates** — `eventDate` must be ISO 8601 (year, year-month, full date, basic `YYYYMMDD`, datetime with `T`/`t`/space separator, or a `start/end` interval) and a real calendar date: `2021-02-30` is `RECORDED_DATE_INVALID`. Future dates and dates before 1600 are `RECORDED_DATE_UNLIKELY` — a date is judged future at the precision it carries, so a full date next month counts, and so does a year-month ahead of the current month. `eventDate` is cross-checked against `year`/`month`/`day`/`startDayOfYear`/`endDayOfYear` (`RECORDED_DATE_MISMATCH`). `modified`, `dateIdentified` and `georeferencedDate` get the same treatment under their own GBIF flags.
- **Coordinates** — non-numeric values (`COORDINATE_INVALID`, including a latitude with no longitude), values outside ±90/±180 (`COORDINATE_OUT_OF_RANGE`), the exact 0, 0 pair (`ZERO_COORDINATE`), and the one swapped-pair signature that is decidable from the file alone — latitude outside ±90 that becomes valid when the pair is swapped (`PRESUMED_SWAPPED_COORDINATE`). `coordinateUncertaintyInMeters` must be a non-negative number; `coordinatePrecision` must lie between 0 and 1. A missing or uninterpretable `geodeticDatum` is `GEODETIC_DATUM_ASSUMED_WGS84` / `GEODETIC_DATUM_INVALID`.
- **Country** — `countryCode` must be an ISO 3166-1 code (`COUNTRY_INVALID`), `country` must be a recognisable country name or code, and when both are present they must agree (`COUNTRY_MISMATCH`). A stated `continent` must also be the continent of the row's own country (`CONTINENT_COUNTRY_MISMATCH`); transcontinental countries (Russia, Turkey, Egypt, …) are deliberately not continent-checked rather than risk a wrong call. This is a consistency check *inside your file*, using a bundled ISO 3166 name/code table — see the limits below for what it is not.
- **Footprints, references, verbatim units** — `footprintWKT` must be structurally valid Well-Known Text (`FOOTPRINT_WKT_INVALID`) and `footprintSRS` interpretable (`FOOTPRINT_SRS_INVALID`); `references` must be an absolute URI (`REFERENCES_URI_INVALID`); a `verbatimDepth`/`verbatimElevation` carrying imperial units ("120 ft") is `DEPTH_NOT_METRIC` / `ELEVATION_NOT_METRIC`.
- **Counts and ranges** — `individualCount` must be a non-negative integer (`INDIVIDUAL_COUNT_INVALID`) and must not contradict `occurrenceStatus` (`INDIVIDUAL_COUNT_CONFLICTS_WITH_OCCURRENCE_STATUS`); elevation and depth minima must not exceed their maxima (`ELEVATION_MIN_MAX_SWAPPED`, `DEPTH_MIN_MAX_SWAPPED`), must be numeric, and are warned about outside GBIF's plausibility bounds (`ELEVATION_UNLIKELY`, `DEPTH_UNLIKELY`).

## Honest limits

- **No border or gazetteer checks.** GBIF's `COUNTRY_COORDINATE_MISMATCH` — "your coordinates fall outside the country you named" — needs real map data. `dwccheck` does not have it and does not fake it: coordinates are never compared against any map, coastline or country boundary. The same goes for GBIF's negated-coordinate detection (`PRESUMED_NEGATED_LATITUDE`/`LONGITUDE`), which needs to know where the record *should* be, and for swapped-coordinate detection beyond the out-of-range signature above: a swapped pair that is still in range (Sydney's latitude in the longitude column, say) cannot be told from a genuine record in the Atlantic from the file alone, so no claim is made.
- **No taxon matching.** Whether `scientificName` matches GBIF's taxonomic backbone (`TAXON_MATCH_NONE`, `TAXON_MATCH_FUZZY`, …) needs GBIF's backbone on a server. Offline, a name is only checked for being present.
- **The country table is for internal consistency only.** The bundled ISO 3166 table answers one question: do `country` and `countryCode` in the same row name the same country? Name matching covers ISO common and official names plus common written variants ("USA", "Great Britain", "South Korea"); an unusual but legitimate name spelling can still be flagged `COUNTRY_INVALID` — if that happens, the code column is what GBIF keys on.
- **One file, not an archive.** `dwccheck` checks a single CSV/TSV occurrence file. Darwin Core Archives (zip with `meta.xml`) and multi-file datasets are not unpacked in this version.
- **Footprint geometry is not judged.** `footprintWKT` is checked for being interpretable WKT, but whether the footprint actually contains the record's coordinates (GBIF's `FOOTPRINT_WKT_MISMATCH`) needs a geometry engine that handles things like antimeridian-crossing polygons correctly; a partial version would false-flag valid data, so it is not attempted.
- **Geological and DNA terms are not checked.** The geological-context terms (eon/era/period/epoch/age hierarchies) and DNA-sequence terms have their own GBIF flags, decided against the geological timescale and sequence vocabularies; they are outside this version's occurrence pre-flight scope.
- **Vocabulary strictness is GBIF's, not the standard's letter.** Where GBIF's parser accepts spelling variants of a vocabulary value, so does `dwccheck`. Where a Darwin Core term has no GBIF occurrence flag (for example `sex` and `lifeStage`), it is not vocabulary-checked in this version rather than checked under an invented flag.
- **Uncertainty of exactly 0 is not flagged.** GBIF's definition of `COORDINATE_UNCERTAINTY_METERS_INVALID` does not pin a numeric threshold; negative and non-numeric values are flagged, and 0 is left alone rather than guessed at.

## Use with an AI agent

This repo ships a [SKILL.md](SKILL.md) written to the Agent Skills open standard. If your coding agent supports skills, point it at this repo and it can install dwccheck, run it on your occurrence files before upload, and read the findings for you. The skill works when the repo is cloned under its real name (`dwccheck`) — a skill's name must match its folder.

## Method and sources

The oracles are the published ones, pinned in the tests: the Darwin Core term list (TDWG, `tdwg/dwc` `dist/simple_dwc_vertical.csv`), GBIF's OccurrenceIssue vocabulary and flag definitions, and GBIF's BasisOfRecord / OccurrenceStatus / TypeStatus / Continent enumerations (GBIF API, read 2026-11-18). Country names and codes are ISO 3166-1 via the CC0 `datasets/country-codes` dataset. If GBIF or TDWG changes a vocabulary, the pinning tests fail and the tables get regenerated — run them and see.

## Tests

```console
$ python3 run_tests.py
```

79 tests (stdlib `unittest`, no dependencies): the oracle-pinning tests above; every check on valid and invalid values, including the adversarial cases (non-existent dates, swapped coordinates, duplicate IDs, vocabulary near-misses, a valid in-range pair that must *not* be called swapped, `eventID` repeats that must *not* be called duplicates); file problems (missing file, empty file, header-only, ragged rows, BOM + CRLF, TSV) all failing with clean one-line errors, never tracebacks; a generated valid corpus cycling all 249 countries in the bundled table, pinned at zero errors and zero warnings; and the two shipped examples, whose outputs above are pinned byte-for-byte against golden files by the golden-output tests.

## License

MIT. Free and open source, for science.
