"""Synthetic PDFs must regenerate without creating timestamp-only diffs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import time


GENERATORS = Path(__file__).parent / "generators"


def _load_generator(name: str, module_name: str):
    path = GENERATORS / name
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_investment_fixture_generators_are_byte_deterministic(tmp_path) -> None:
    cases = [
        (
            _load_generator(
                "gen-etrade-at-work-synthetic-sample.py",
                "etrade_at_work_fixture_generator",
            ),
            "build",
            "etrade-at-work-synthetic-202406",
        ),
        (
            _load_generator(
                "gen-edward-jones-brokerage-synthetic-sample.py",
                "edward_jones_fixture_generator",
            ),
            "generate",
            "edward-jones-synthetic-202608",
        ),
        (
            _load_generator(
                "gen-schwab-401k-brokerage-synthetic-sample.py",
                "schwab_401k_fixture_generator",
            ),
            "build",
            "schwab-401k-synthetic-202606",
        ),
    ]

    first_outputs: dict[str, tuple[bytes, bytes]] = {}
    for module, entry_point, stem in cases:
        module.OUT = tmp_path / f"{stem}.pdf"
        module.EXPECT = tmp_path / f"{stem}.expectations.json"
        getattr(module, entry_point)()
        first_outputs[stem] = (module.OUT.read_bytes(), module.EXPECT.read_bytes())

    # ReportLab's default PDF metadata uses wall-clock time. Crossing a
    # timestamp boundary ensures this test fails if invariant output is
    # accidentally removed from either generator.
    time.sleep(1.1)

    for module, entry_point, stem in cases:
        getattr(module, entry_point)()
        assert module.OUT.read_bytes() == first_outputs[stem][0]
        assert module.EXPECT.read_bytes() == first_outputs[stem][1]
