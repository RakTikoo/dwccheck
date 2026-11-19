# Contributing

Thanks for looking at dwccheck. Issues and pull requests are welcome.

## Before you start

- For a starter issue, claim it with a comment first, so two people do not build the same thing.
- Keep each change small and focused on one issue.

## Running the tests

```console
python3 run_tests.py
```

The full suite (79 tests, stdlib `unittest`, no dependencies) must pass before a pull request is reviewed. Two bars are absolute: the generated valid corpus (all 249 countries in the bundled table) must still check with zero errors and zero warnings, and the shipped examples' outputs are pinned byte-for-byte by golden tests — if your change alters them, say why in the pull request. Findings use GBIF's own flag names; never invent a flag — if GBIF has no flag for something, it is either a `DWCCHECK_` file-level code or out of scope. If your change alters the CLI or its output, update the README in the same pull request — and SKILL.md too, if install, commands, flags, exit codes or output wording changed.

## Pull requests

- Say what you changed and how you tested it.
