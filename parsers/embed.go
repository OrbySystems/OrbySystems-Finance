// Package parsers embeds the bundled statement/transaction parsers
// (the Python dispatchers, the per-institution parser modules, and the
// shared parse() IO contract in parser_common.py) plus their standalone
// test suite, so a Go program - OrbySystems - can write the whole tree to disk
// and run it without carrying its own copy.
//
// The Python side of this directory runs standalone with no Go at all (see
// Makefile and pyproject.toml). The Go package lets OrbySystems embed the same tree
// directly rather than maintaining a build-time copy step.
package parsers

import (
	"embed"
	"io/fs"
	"os"
	"path/filepath"
)

// ScriptsFS holds everything under scripts/: the two dispatchers
// (bank_statement.py, csv_statement.py), parser_common.py (dispatch
// machinery + parse() IO-contract validation), vision_client.py, and the
// institutions/ and csv_institutions/ parser packages. The on-disk shape
// is significant: a dispatcher sits next to the institutions/ package so
// "from institutions import common" resolves - WriteScripts preserves it.
//
//go:embed scripts
var ScriptsFS embed.FS

// TestsFS holds the standalone pytest suite under tests/ - conftest.py,
// the converted regression tests, the committed synthetic fixtures, and
// the fixture generators. OrbySystems writes this alongside ScriptsFS when a
// user runs the parser test suite from the app (Build Transactions
// Extractor -> Manage Parsers -> Run Tests).
//
//go:embed tests
var TestsFS embed.FS

// DemoFS holds the bundled example household's statements: six brokerage
// statements and two credit-card statements for a household that does not
// exist, produced by tests/generators/gen-demo-household.py.
//
// Shipped as PDFs the user INGESTS rather than as rows loaded straight
// into a database, because the parse is both the step people doubt and
// the step that convinces them. Someone trying OrbySystems without handing it
// their own money should still watch it recognise an institution, pull
// out positions, and answer from them - a loader that skipped all that
// would prove only that we can render a table.
//
//go:embed demo
var DemoFS embed.FS

// WriteDemo writes the demo/ tree (minus the "demo/" prefix) into dir.
func WriteDemo(dir string) error { return writeTree(DemoFS, "demo", dir) }

// WriteScripts writes the scripts/ tree (minus the "scripts/" prefix)
// into dir. Existing files are overwritten.
func WriteScripts(dir string) error { return writeTree(ScriptsFS, "scripts", dir) }

// WriteTests writes the tests/ tree (minus the "tests/" prefix) into dir.
func WriteTests(dir string) error { return writeTree(TestsFS, "tests", dir) }

func writeTree(efs embed.FS, root, dir string) error {
	return fs.WalkDir(efs, root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		out := filepath.Join(dir, rel)
		if d.IsDir() {
			return os.MkdirAll(out, 0o700)
		}
		data, err := efs.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(out, data, 0o600)
	})
}
