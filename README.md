# Orby systems

Community-maintained systems used by [Orby](https://github.com/edgexr/orby).
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

The repository has not yet been renamed, so its Go module remains
`github.com/edgexr/orby-parsers`. After the planned rename, update the module
path to `github.com/edgexr/orby-systems` and update consumers at the same time.
