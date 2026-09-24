# Contributing to OrbySystems Finance

Thank you for helping improve OrbySystems Finance. Contributions of parser
support, bug fixes, tests, documentation, and financial analysis systems are
welcome.

## Before you start

- Search existing issues and pull requests to avoid duplicating work.
- Open an issue before a large architectural change so the approach can be
  discussed early.
- Never commit real financial statements, credentials, account numbers,
  personally identifying information, or other private data.
- Read the instructions for the area you are changing. Parser contributors
  should start with [`parsers/CLAUDE.md`](parsers/CLAUDE.md) and
  [`parsers/CONTRACT.md`](parsers/CONTRACT.md).

## Development setup

You need Go 1.26 or newer and Python 3.11 or newer. From the repository root,
run:

```sh
make test
```

The parser Makefile creates `parsers/.venv`, installs the test dependencies,
and runs the standalone parser suite. You can run only the Go checks with:

```sh
go test ./...
```

## Parser contributions

Keep parser implementations within `parsers/` and follow the detection and
output rules in the parser contract. New or changed parsers should include:

- Narrow, reliable format detection that does not claim unrelated statements.
- Tests for successful parsing and important failure cases.
- Wholly synthetic fixtures and their generator scripts.
- Privacy-safe diagnostics that do not expose statement contents or personal
  and financial data.
- Documentation updates when support or behavior changes.

Do not submit a redacted production statement. Redaction can leave recoverable
data or identifying document metadata. Instead, create a synthetic fixture
that reproduces the relevant layout and values without copying private data.

Run the parser suite from the repository root with `make test`. If a fixture
generator changes, rebuild the generated fixtures with:

```sh
make -C parsers regen-fixtures
```

Commit the generator and its generated fixtures together.

## Code and documentation changes

- Keep changes focused and avoid unrelated refactoring.
- Match the style and organization of neighboring code.
- Add or update tests for behavior changes.
- Update documentation when commands, contracts, or supported formats change.
- Run `git diff --check` before submitting a pull request.

## Pull requests

A pull request should explain what changed, why it changed, and how it was
tested. Mention any known limitations or follow-up work. Keep commits reviewable
and ensure automated checks pass.

By submitting a contribution, you agree that it is licensed under the Apache
License, Version 2.0, as described in [`LICENSE`](LICENSE).

## Reporting security or privacy issues

Do not include sensitive financial data in a public issue. If a report cannot
be demonstrated safely with synthetic data, contact the maintainers privately
through the repository owner's security contact before sharing details.
