# OrbySystems Finance development

This repository contains independently organized systems consumed by OrbySystems.
Keep each system's implementation, tests, dependencies, contracts, and detailed
contribution instructions within its own directory.

## Current systems

- [`parsers/`](parsers/) — statement parser runtime, fixtures, tests, and Go
  embedding package. See [`parsers/CLAUDE.md`](parsers/CLAUDE.md) before adding
  or changing a parser.

Run all available tests with `make test` from the repository root. Add new
system-specific targets to the root Makefile rather than placing their build
logic at the repository root.
