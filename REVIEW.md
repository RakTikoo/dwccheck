# Independent adversarial review — dwccheck

Reviewer: independent subagent (did not build the tool). Date: 2026-11-18.
The gauntlet was run locally; at review time nothing had been published or
pushed. Documented design decisions were not treated as bugs (file-internal
checks only, no border/gazetteer or taxon matching, `DWCCHECK_` codes kept
separate from GBIF flags, uncertainty of exactly 0 not flagged).

## What was checked

- **Full test battery:** `python3 run_tests.py` — **67 tests, all OK.**
- **Independent oracle verification** against the live sources (GBIF API
  `/v1/enumeration/basic/*` and the TDWG dwc repository, fetched fresh
  during this review, not from the tool's own constants).
- **~55 adversarial probes** through the real CLI (dates, coordinates,
  countries, vocabularies, counts, and hostile file shapes), each checked
  for tracebacks, silent passes of bad values, and false flags on good
  values.
- **README audit:** both demo blocks diffed byte-for-byte against real
  output from a fresh-venv install; every factual claim re-checked;
  forbidden-claim and rival-name greps.
- **Fresh-venv install proof** (below).

## Oracle verification — no drift anywhere

| Oracle | Live source | Pinned in tool | Verdict |
|---|---|---|---|
| OccurrenceIssue | 108 values | 108 (`GBIF_OCCURRENCE_ISSUES`) | exact set match |
| BasisOfRecord | 11 (PRESERVED_SPECIMEN … UNKNOWN) | 11, camel-case DwC spelling | exact match after the documented case/underscore normalisation |
| OccurrenceStatus | 4 (PRESENT, ABSENT, DETECTED, NOT_DETECTED) | 4 | exact match |
| TypeStatus | 44 | 44 | exact set match |
| Continent | 7 | 7 | exact match |
| DwC terms | `simple_dwc_vertical.csv`: 236 lines, 224 unique | 224 (`DWC_TERMS`) | exact set match |
| Country alpha-2 | GBIF Country: 253 codes | table: 249 ISO codes | GBIF's 4 extra codes are exactly AA, XK, XZ, ZZ — the tool's documented `GBIF_EXTRA_COUNTRY_CODES` — so **every** GBIF country code is accepted as a `countryCode`; no code GBIF accepts is rejected |

Name-mapping spot checks through the tool's own maps: France→FR,
United Kingdom→GB, South Korea→KR, Côte d'Ivoire→CI (accents handled);
alpha-3 FRA/GBR/KOR/USA all resolve to the right alpha-2.

## Adversarial probes

Dates:

- `1900-02-29` → `RECORDED_DATE_INVALID`; `2000-02-29` → valid. The
  Gregorian century rule is right (via `calendar.monthrange`).
- Space-separated datetime (`2019-05-14 08:40:00`) accepted — ISO 8601
  permits the space by agreement and GBIF accepts it. Leap second
  `23:59:60Z` accepted.
- Intervals with an empty side (`2019-05-14/`, `/2019-05-14`, bare `/`)
  → `RECORDED_DATE_INVALID`. Reversed and malformed intervals also fail
  (covered by the suite).
- Year-0000 full dates (`0000-02-29`, `0000-06-15` in `modified`) →
  `*_DATE_UNLIKELY` warning, no crash. (A suspected `monthrange` crash
  on year 0 was tested for and does **not** occur.)
- A full date **30 days in the future within the current year**
  (2026-12-18, today being 2026-11-18) passes with **no** warning, in
  `eventDate`, in an interval end, and in `modified` — see Finding 1.
- Lowercase `t`/`z` and basic-format `20190514` → `RECORDED_DATE_INVALID`
  — see Finding 3.

Coordinates:

- All four ±90/±180 corners valid. `lat=90.0001, lon=10` →
  `PRESUMED_SWAPPED_COORDINATE`, which matches GBIF's own swap heuristic
  (latitude out of range, swapping makes the pair valid) — honest.
- `NaN`, `inf`, `-inf` → `COORDINATE_INVALID` (the float parser rejects
  them explicitly). `1e2` is parsed as 100.0 and reported swapped;
  scientific notation is float semantics, the same as GBIF's Java-side
  parsing — acceptable. A valid scientific-notation coordinate
  (`4.88566e1`) is accepted.
- Uncertainty `0` accepted (the README's documented limit); `1e5`
  accepted. Comma decimal (`48,5`) in a TSV → `COORDINATE_INVALID`.
- Datum: `EPSG: 4326` (space after colon) accepted; `WGS-84` / `WGS_84`
  → `GEODETIC_DATUM_INVALID` — see Finding 2.

Country, status, counts:

- `Côte d'Ivoire` + `CI` passes; + `FR` → `COUNTRY_MISMATCH`. Lowercase
  and alpha-3 codes accepted. Kosovo + `XK` accepted. `ZZ` (GBIF's
  "unknown") alongside a country name produces no mismatch — defensible,
  since ZZ asserts nothing. Country `UK` + code `GB` passes.
- `occurrenceStatus` "not detected" in five spellings (space, capitalised,
  underscore, hyphen, fused) — all accepted.
- `individualCount`: `+3`, `03`, `3 `, ` 3` accepted; `3.0` →
  `INDIVIDUAL_COUNT_INVALID`, consistent with GBIF's "not a positive
  integer" definition.

File shapes — **no traceback in any probe**; every file-level failure was
a one-line `error:` message on stderr with exit 2:

- Whitespace-only and comma-only rows are treated as records and flagged
  `DWCCHECK_MISSING_VALUE` ×4 each; header + blank lines only → exit 2,
  "contains no data rows". Semicolon-delimited `.txt` sniffed correctly;
  CRLF TSV clean; UTF-16 input → exit 2 with a clear UTF-8 message;
  a directory as the argument → exit 2, one line (the message says
  "not found", which is cosmetically imprecise for a directory).
- Header `eventDate ` (trailing space) → `DWCCHECK_UNKNOWN_TERM` with the
  correct "Did you mean 'eventDate'?" suggestion **plus**
  `DWCCHECK_MISSING_TERM` — loud and helpful, never silent.
- Duplicate occurrenceIDs: differing only by case → treated as distinct
  (correct; IDs are case-sensitive); differing only by surrounding
  whitespace → caught as duplicates (cells are stripped first).
- Required term empty-cell vs missing-column → two distinct codes
  (`DWCCHECK_MISSING_VALUE` / `DWCCHECK_MISSING_TERM`), both errors.
  Ragged short row → missing values flagged, no crash. Depth `" 10 "`
  accepted; `"10 m"` → `DEPTH_NON_NUMERIC`.
- Quoted fields containing commas and an embedded newline parse
  correctly — but see Finding 4 on the row numbers that follow one.
- Tab-delimited content in a `.csv` file fails loudly (never a silent
  pass) — see Finding 5 on the message quality.
- **20,000-row file checked in ~2.0 s** end-to-end, all 4 planted errors
  found. Runtime is sane.

## README audit

- Both demo blocks reproduce **byte-for-byte** from the fresh-venv
  install (clean example exit 0, messy example exit 1, 12 errors /
  4 warnings). The "67 tests" claim is exact.
- Vocabulary claims verified against the live API: 11-value
  BasisOfRecord, present/absent/detected/not_detected, 7 continents,
  TypeStatus (44, as stated in the code docs).
- `COUNTRY_COORDINATE_MISMATCH`, `PRESUMED_NEGATED_*` and `TAXON_MATCH_*`
  appear in the README **only** inside Honest limits, as things the tool
  does not do; `dwccheck flags` does not list them (also pinned by a
  test). No border/gazetteer or taxon-matching capability is claimed
  anywhere.
- No rival or adjacent-tool names appear in the README (the only service
  named is GBIF's own Data Validator website, which is the premise).
  Rival names live only in `BENCHMARK_INTERNAL.md`, as required.
- One overstatement found — see Finding 6.

## Fresh-venv install proof

Fresh venv (TMPDIR pointed at the workspace, as /tmp is a small tmpfs),
`pip install .` from the local tree: succeeded, `dwccheck` 0.1.0.
From the installed package: clean example → exit 0, PASS; messy example
→ exit 1, 12 errors / 4 warnings, output byte-identical to the README;
`dwccheck flags` → exit 0, lists only emittable flags; `--format json`
on the messy example parses and agrees (12 errors / 4 warnings).

## Findings

1. **MEDIUM — future dates within the current year pass silently.**
   The "future" half of every `*_DATE_UNLIKELY` check compares only the
   year (`year > today.year` in `_date_unlikely` and `_check_date_field`).
   A full date next month — `eventDate`, an interval end, `modified`,
   `dateIdentified`, `georeferencedDate` — gets no warning, although
   GBIF's definition is "falling … into the future" (a full-date
   comparison) and the README states flatly that "Future dates … are
   `RECORDED_DATE_UNLIKELY`". Warning-level only, and the window is
   tomorrow→Dec 31 of the current year, but it is a silent pass of a
   value GBIF would flag, against the tool's own documented claim.
   Fix direction: when a full date (or interval end) is known, compare
   the whole date against today; keep the year-only test for
   year/year-month values.
2. **LOW — `geodeticDatum` spelling variants `WGS-84` and `WGS_84` are
   flagged `GEODETIC_DATUM_INVALID`.** Datum normalisation strips spaces
   only, so two spellings publishers genuinely write for the WGS84 datum
   earn an error-level flag. This is inconsistent with the
   spelling-tolerant matching the tool (deliberately, and correctly)
   applies to every other vocabulary. A false flag on a good value,
   narrow but real.
3. **LOW — ISO 8601 strictness is narrower than the README's wording.**
   Lowercase `t`/`z` separators and the basic format (`20190514`) are
   rejected as `RECORDED_DATE_INVALID`, although ISO 8601 permits both.
   The accepted subset *is* documented precisely in `parse_iso_date`'s
   docstring and matches Darwin Core's extended-format practice, so
   this is a wording gap, not a logic bug: the README's "must be
   ISO 8601" should say "the ISO 8601 extended-format subset" the way
   the code does.
4. **LOW — row numbers are record numbers, not file line numbers, once
   a quoted field contains an embedded newline.** Probe: a bad record
   on physical line 4 (after a quoted field spanning lines 2–3) is
   reported as "row 3". The README says "Row numbers are line numbers
   in the file (the header is row 1)" without qualification. True for
   the overwhelmingly common no-embedded-newline file; the claim needs
   the qualification, or the wording "record number".
5. **LOW — tab-delimited content in a `.csv` file produces an unreadable
   finding.** The verdict is correct and loud (missing-term errors,
   exit 1 — no silent pass), but the `DWCCHECK_UNKNOWN_TERM` message
   embeds the entire tab-joined header as one multi-hundred-character
   "term". A truncated value or a "this file looks tab-delimited" hint
   would serve the publisher better. Cosmetic only.
6. **LOW — the Tests section overstates what the tests pin.** It says
   the examples' outputs are "reproduced byte-for-byte by the test
   run's subjects"; the tests actually pin row counts, error/warning
   counts and the flag set for the examples, not the full output text.
   The outputs *do* match the README byte-for-byte today — verified by
   diff in this review — but no test would catch a wording drift in a
   message. Either diff the text in a test or soften the sentence.

## Observations, not findings

- `individualCount` of `0` with `occurrenceStatus` absent is accepted,
  and GBIF's flag definition text ("not a positive integer") could be
  read as condemning 0 — but the tool's own conflict check and GBIF's
  inference behaviour (count 0 ⇒ absent) make accepting it the honest
  reading. No change recommended.
- `countryCode` values AA/XZ/ZZ are accepted without any name
  cross-check, as documented in the code; they are GBIF's own
  unknown/international-waters codes and assert nothing checkable.
- One ragged row with *more* values than the header aborts the whole
  check with exit 2 (suite-tested, one-line message). A defensible
  design call for a pre-flight gate; noted so it is a decision on
  record, not a surprise.

## After-state

`python3 run_tests.py` — **67 tests, all OK** (unchanged by this review;
the reviewer modified no file except this REVIEW.md, and removed the
`build/` / `egg-info` artifacts its own in-tree install created).
No HIGH findings. One MEDIUM (Finding 1, a warning-level silent pass in
a bounded date window) and five LOW findings, all fixable without
touching any documented design decision.

## Fix pass (builder, 2026-11-18 — after the review above)

All six findings were fixed and re-measured; none became a limit.

1. **Finding 1 (MEDIUM) — CLOSED.** `parse_iso_date` now returns a
   precision (`year` / `month` / `day`), and a new `_is_future` judges
   futureness at the precision the value carries: a full date is future
   if the day itself is ahead of today, a year-month if its month is
   ahead, a year if its year is ahead. Applied to `eventDate` (single
   and interval ends), `modified`, `dateIdentified`,
   `georeferencedDate` and the standalone `year` check. Regression
   tests compute dates relative to *today* (today+30d, today−30d,
   next month, current month) so the fix cannot silently rot.
   Re-probe: a full date 45 days ahead now raises
   `RECORDED_DATE_UNLIKELY`.
2. **Finding 2 — CLOSED.** Datum normalisation strips spaces,
   underscores and hyphens (same tolerance as the other vocabularies);
   `WGS-84` and `WGS_84` are accepted, and the datum vocabulary test
   now covers them.
3. **Finding 3 — CLOSED (fixed, not just reworded).** Lowercase `t`/`z`
   separators and the basic `YYYYMMDD` form are now accepted (ISO 8601
   permits both); non-existent basic dates (`20190230`, `19000229`)
   are still rejected. The README's Dates bullet now enumerates the
   accepted shapes exactly.
4. **Finding 4 — CLOSED (fixed, not just reworded).** Row numbers now
   come from the csv reader's `line_num` — the physical line where the
   record ends — so a record after an embedded-newline field is
   reported at its real file line. Regression test: bad record on
   physical line 4 is reported as row 4. README wording qualified to
   match.
5. **Finding 5 — CLOSED.** The unknown-term message truncates the
   displayed header at 60 characters; the tab-in-`.csv` probe now
   produces a 120-character message instead of a multi-hundred-
   character one. Verdict unchanged (loud, exit 1).
6. **Finding 6 — CLOSED.** Golden-output tests added: the CLI is run
   on both shipped examples and stdout is compared byte-for-byte
   against `tests/golden_clean.txt` / `tests/golden_messy.txt`, and
   the README sentence now says exactly that.

After-state of the fix pass: `python3 run_tests.py` — **72 tests, all
OK** (67 + 3 new regression tests + 2 golden-output tests). Demo
outputs unchanged (12 errors / 4 warnings on the messy example), so
the README demo blocks still match byte-for-byte.
