# OrbySystems Finance

Community-maintained financial systems used by OrbySystems.
The repository currently contains statement parsers and is structured to also
host recipes and statement downloaders.

## Systems

| System | Description | Documentation |
|---|---|---|
| Parsers | Bank, credit-card, brokerage, CSV, and spreadsheet statement parsers | [`parsers/`](parsers/) |
| Recipes | Reusable financial analysis recipes | Not yet added |
| Downloaders | Institution statement downloaders | Not yet added |

Each system owns its implementation, tests, dependencies, documentation, and
Go embedding package. Repository-level commands delegate to those systems.

## Development

Run every system's tests from the repository root:

```sh
make test
```

Parser-specific workflows and contribution instructions are documented in
[`parsers/README.md`](parsers/README.md) and
[`parsers/CLAUDE.md`](parsers/CLAUDE.md).

The Go module path is `github.com/OrbySystems/OrbySystems-Finance`.
