"""Tests for tools/repo_graph.py.

Fixture: tests/fixtures/mini_py - a small Python repo with a designed
reference structure. auth.py is the leaf everything imports from, so it
should rank highest on both keyword and PageRank scores. orphan_helper()
has zero call sites - covers the unused-symbol path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.repo_graph import (
    RepoGraph,
    _tokenize,
    clear_cache,
    get_or_build_graph,
    supported_extensions,
)

FIXTURES = Path(__file__).parent / "fixtures"
MINI_PY = FIXTURES / "mini_py"


@pytest.fixture(autouse=True)
def _isolate_graph_cache():
    """Prevent test-to-test pollution of the module-level graph cache."""
    clear_cache()
    yield
    clear_cache()


async def _mini_py_graph() -> RepoGraph:
    return await get_or_build_graph(str(MINI_PY))


# --- Grammar loading -------------------------------------------------------

def test_supported_extensions_covers_common_languages():
    ext = supported_extensions()
    for lang in ("py", "ts", "js", "go", "rs"):
        assert lang in ext, f"expected {lang} to be a supported extension; got {ext}"


# --- Build stats -----------------------------------------------------------

async def test_build_reports_expected_stats():
    g = await _mini_py_graph()
    s = g.stats
    # 4 source files + 2 __init__.py + test_auth.py = 7, but empty __init__.py
    # files still count as parsed (they just contribute nothing).
    assert s.files_parsed == 6
    assert s.files_failed == 0
    assert s.symbols >= 8
    assert s.references > 0
    assert s.edges > 0
    assert s.wall_time_ms > 0


async def test_build_is_idempotent_via_module_cache():
    g1 = await _mini_py_graph()
    g2 = await _mini_py_graph()
    assert g1 is g2, "cache should return the same RepoGraph instance"


async def test_clear_cache_forces_rebuild():
    g1 = await _mini_py_graph()
    clear_cache()
    g2 = await _mini_py_graph()
    assert g1 is not g2


# --- symbols_matching ------------------------------------------------------

async def test_symbols_matching_exact_ranks_first():
    g = await _mini_py_graph()
    results = g.symbols_matching("hash_password")
    assert results, "expected at least one match for 'hash_password'"
    assert results[0].name == "hash_password"
    assert results[0].file_path == "src/auth.py"
    assert results[0].kind == "function"


async def test_symbols_matching_substring_returns_multiple():
    g = await _mini_py_graph()
    names = {s.name for s in g.symbols_matching("password")}
    assert "hash_password" in names
    assert "verify_password" in names


async def test_symbols_matching_is_case_insensitive():
    g = await _mini_py_graph()
    lower = {s.name for s in g.symbols_matching("password")}
    upper = {s.name for s in g.symbols_matching("PASSWORD")}
    assert lower == upper and lower


async def test_symbols_matching_unknown_returns_empty():
    g = await _mini_py_graph()
    assert g.symbols_matching("no_such_symbol_zzz") == []


# --- references_of ---------------------------------------------------------

async def test_references_of_finds_callers_across_files():
    g = await _mini_py_graph()
    ref_files = {r.file_path for r in g.references_of("hash_password")}
    # Called from tests/test_auth.py and src/db.py; also referenced internally
    # in src/auth.py (verify_password body).
    assert "tests/test_auth.py" in ref_files
    assert "src/db.py" in ref_files


async def test_references_of_orphan_returns_empty():
    """orphan_helper is defined but never called - regression against
    accidentally counting definitions as references."""
    g = await _mini_py_graph()
    assert g.references_of("orphan_helper") == []


async def test_references_of_unknown_returns_empty():
    g = await _mini_py_graph()
    assert g.references_of("this_symbol_does_not_exist") == []


# --- file_neighborhood ----------------------------------------------------

async def test_file_neighborhood_finds_direct_imports():
    g = await _mini_py_graph()
    neighbors = g.file_neighborhood("src/api.py", radius=1)
    # api.py imports from src.auth and src.db
    assert "src/auth.py" in neighbors
    assert "src/db.py" in neighbors


async def test_file_neighborhood_radius_2_is_superset_of_radius_1():
    g = await _mini_py_graph()
    r1 = set(g.file_neighborhood("tests/test_auth.py", radius=1))
    r2 = set(g.file_neighborhood("tests/test_auth.py", radius=2))
    assert r1.issubset(r2)


async def test_file_neighborhood_unknown_file_returns_empty():
    g = await _mini_py_graph()
    assert g.file_neighborhood("does/not/exist.py") == []


# --- relevant_files_for ---------------------------------------------------

async def test_relevant_files_for_ranks_central_module_first():
    g = await _mini_py_graph()
    matches = g.relevant_files_for("user login and password verification")
    assert matches, "expected at least one ranked file"
    # auth.py has all three matched symbols (User, hash_password, verify_password)
    # AND the highest PageRank (all other files import from it).
    assert matches[0].path == "src/auth.py"
    # Combined score must include contributions from both signals.
    assert matches[0].keyword_score > 0
    assert matches[0].pagerank_score > 0


async def test_relevant_files_for_returns_matched_symbols():
    g = await _mini_py_graph()
    matches = g.relevant_files_for("password")
    top = matches[0]
    assert "hash_password" in top.matched_symbols or "verify_password" in top.matched_symbols


async def test_relevant_files_for_empty_query_returns_empty():
    g = await _mini_py_graph()
    assert g.relevant_files_for("") == []
    # A query composed entirely of stop-words tokenizes to nothing.
    assert g.relevant_files_for("the and or with") == []


async def test_relevant_files_for_no_keyword_hits_falls_back_to_pagerank():
    """When the query matches no symbol, we still return top files by
    PageRank alone so downstream can at least see the repo shape."""
    g = await _mini_py_graph()
    matches = g.relevant_files_for("quantum entanglement blockchain zeitgeist")
    assert matches, "should fall back to top-pagerank files, not empty"
    # auth.py should still rank first on pure PageRank.
    assert matches[0].path == "src/auth.py"
    assert matches[0].keyword_score == 0.0


async def test_pagerank_is_non_uniform_regression():
    """Regression: nx.pagerank silently falls back to uniform values if
    scipy is missing. That kills the whole point of the hybrid ranking.
    """
    g = await _mini_py_graph()
    pr = list(g.pagerank.values())
    assert pr, "pagerank map should be populated after build"
    assert max(pr) - min(pr) > 0.01, (
        f"PageRank looks uniform ({pr}) - scipy likely missing; "
        "nx.pagerank quietly degraded to a uniform prior"
    )


async def test_alpha_zero_yields_pure_pagerank_order():
    """alpha=0 should ignore keyword score and rank purely by PageRank."""
    g = await _mini_py_graph()
    matches = g.relevant_files_for("password", alpha=0.0)
    # auth.py still wins because it has the highest PR AND matched syms
    assert matches[0].path == "src/auth.py"
    # combined_score should equal pagerank_score when alpha=0
    for m in matches:
        assert abs(m.combined_score - m.pagerank_score) < 1e-9


# --- Robustness: bad or hostile inputs ------------------------------------

async def test_handles_syntax_error_without_crashing(tmp_path):
    (tmp_path / "broken.py").write_text("def foo(:  # deliberately broken\n")
    g = RepoGraph(str(tmp_path))
    stats = await g.build()
    # Tree-sitter emits ERROR nodes rather than raising; either way we
    # want no unhandled exception to escape.
    assert stats.files_parsed + stats.files_failed >= 1


async def test_handles_empty_file(tmp_path):
    (tmp_path / "empty.py").write_text("")
    g = RepoGraph(str(tmp_path))
    stats = await g.build()
    assert stats.files_parsed == 1
    assert stats.symbols == 0


async def test_handles_binary_file_gracefully(tmp_path):
    """A .py that's actually binary shouldn't crash the parser."""
    (tmp_path / "fake.py").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    g = RepoGraph(str(tmp_path))
    stats = await g.build()
    assert stats.files_parsed + stats.files_failed >= 1


async def test_ignores_common_infrastructure_dirs(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config.py").write_text("def secret(): pass\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("def junk(): pass\n")
    (tmp_path / "src.py").write_text("def real(): pass\n")

    g = RepoGraph(str(tmp_path))
    await g.build()

    assert len(g.symbols_matching("real")) >= 1
    assert g.symbols_matching("secret") == []
    assert g.symbols_matching("junk") == []


async def test_files_over_max_size_are_skipped(tmp_path):
    (tmp_path / "huge.py").write_text("x = 1\n" * 200_000)  # > 1 MB
    g = RepoGraph(str(tmp_path))
    stats = await g.build()
    assert stats.files_skipped >= 1
    assert stats.files_parsed == 0


async def test_missing_workspace_dir_returns_empty_stats(tmp_path):
    """A path that doesn't exist should not crash - just log and return."""
    bogus = tmp_path / "does" / "not" / "exist"
    g = RepoGraph(str(bogus))
    stats = await g.build()
    assert stats.files_parsed == 0
    assert stats.symbols == 0


# --- Tokenizer -------------------------------------------------------------

def test_tokenize_filters_stop_words():
    tokens = [t.lower() for t in _tokenize("the user should login with a password")]
    assert "the" not in tokens
    assert "with" not in tokens
    assert "user" in tokens
    assert "login" in tokens
    assert "password" in tokens


def test_tokenize_dedups_preserving_first_occurrence():
    tokens = _tokenize("user login user login")
    assert tokens == ["user", "login"]


def test_tokenize_filters_short_tokens():
    tokens = _tokenize("a bb ccc dddd")
    assert "a" not in tokens
    assert "bb" not in tokens
    assert "ccc" in tokens
    assert "dddd" in tokens


def test_tokenize_empty_string_returns_empty():
    assert _tokenize("") == []


# --- Perf budget (soft - logs, does not fail CI) -------------------------

async def test_perf_budget_small_fixture_under_3_seconds():
    g = await _mini_py_graph()
    # mini_py has 6 files. If this exceeds 3s something is seriously off.
    assert g.stats.wall_time_ms < 3000, f"build took {g.stats.wall_time_ms:.0f}ms (>3s)"
