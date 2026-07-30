"""Language-agnostic code intelligence index built on tree-sitter.

Extracts symbol definitions (functions, classes, methods) and references
(calls, imports) across the workspace, then ranks files for retrieval by
combining keyword overlap with PageRank on the file-level reference graph.

Why hybrid ranking?
    - Aider's repomap uses pure PageRank on the symbol graph.
    - Vegapunk's legacy retrieval used pure keyword regex.
    - Pure PageRank is query-independent and buries the actually relevant
      file when a query targets an obscure symbol.
    - Pure keyword misses transitively-related files.
    - Hybrid: `alpha * keyword + (1-alpha) * pagerank` (alpha=0.7 default).

Storage:
    In-memory. Workspaces are ephemeral in Vegapunk (one clone per run),
    so SQLite persistence would just add complexity for no gain. If we
    later want durable graphs across runs, swap _CACHE for a SQLite-backed
    store keyed by repo commit hash.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
from tree_sitter import Language, Node, Parser

logger = logging.getLogger(__name__)


# --- Language grammar registry -------------------------------------------------

def _load_languages() -> dict[str, Language]:
    """Load available tree-sitter grammars lazily.

    Grammars that fail to import (missing package, ABI mismatch) are
    logged but do not raise, so a repo with only Python still works even
    if the Rust grammar isn't available on this platform.
    """
    langs: dict[str, Language] = {}

    grammar_specs: list[tuple[tuple[str, ...], str, str]] = [
        (("py",),                       "tree_sitter_python",     "language"),
        (("ts", "tsx"),                 "tree_sitter_typescript", "language_typescript"),
        (("js", "jsx", "mjs", "cjs"),   "tree_sitter_javascript", "language"),
        (("go",),                       "tree_sitter_go",         "language"),
        (("rs",),                       "tree_sitter_rust",       "language"),
    ]

    for extensions, module_name, fn_name in grammar_specs:
        try:
            module = __import__(module_name)
            lang_fn = getattr(module, fn_name)
            language = Language(lang_fn())
            for ext in extensions:
                langs[ext] = language
        except Exception as e:  # noqa: BLE001 - grammar loading is best-effort
            logger.warning(f"[repo_graph] Grammar '{module_name}' unavailable: {e}")

    return langs


_LANGUAGES: dict[str, Language] = _load_languages()


def supported_extensions() -> list[str]:
    """Return the list of file extensions the graph currently indexes."""
    return sorted(_LANGUAGES.keys())


# --- Data model ---------------------------------------------------------------

@dataclass(frozen=True)
class Symbol:
    """A named definition (function, class, method) in the codebase."""
    name: str
    kind: str            # "function" | "class" | "method"
    file_path: str       # relative to workspace root
    start_line: int      # 1-indexed
    end_line: int


@dataclass(frozen=True)
class Reference:
    """A usage of a symbol - a call site, import, or type reference."""
    symbol_name: str
    file_path: str       # where the reference appears
    line: int


@dataclass
class FileMatch:
    """A file scored for relevance to a query."""
    path: str
    keyword_score: float         # 0..1 within the matched set
    pagerank_score: float        # 0..1 within the matched set
    combined_score: float        # alpha * keyword + (1-alpha) * pagerank
    matched_symbols: list[str] = field(default_factory=list)


@dataclass
class RepoGraphStats:
    files_parsed: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    symbols: int = 0
    references: int = 0
    edges: int = 0
    wall_time_ms: float = 0.0


# --- The graph ----------------------------------------------------------------

class RepoGraph:
    """In-memory code intelligence graph for a single workspace.

    Build once, then query. Not thread-safe for concurrent build; safe for
    concurrent reads after build completes.
    """

    IGNORED_DIRS: frozenset[str] = frozenset({
        "node_modules", "__pycache__", ".git", ".venv", "venv", "env",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
        ".next", ".nuxt", "target", "htmlcov", ".tox", "coverage",
    })

    MAX_FILE_SIZE = 1_000_000  # 1 MB - skip anything larger (minified, generated, etc.)

    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).resolve()
        self._symbols_by_name: dict[str, list[Symbol]] = defaultdict(list)
        self._references: list[Reference] = []
        self._file_graph: nx.DiGraph = nx.DiGraph()
        self._pagerank: dict[str, float] = {}
        self._stats = RepoGraphStats()

    # --- Build --------------------------------------------------------------

    async def build(self) -> RepoGraphStats:
        """Walk the workspace, parse source files, populate the graph."""
        start = time.perf_counter()

        if not self.workspace_path.is_dir():
            logger.error(f"[repo_graph] Workspace not a directory: {self.workspace_path}")
            return self._stats

        for file_path in self._iter_source_files():
            try:
                self._parse_file(file_path)
                self._stats.files_parsed += 1
            except Exception as e:  # noqa: BLE001 - per-file failures should not sink build
                self._stats.files_failed += 1
                logger.warning(f"[repo_graph] Failed to parse {file_path}: {e}")

        self._build_file_graph()
        self._compute_pagerank()

        self._stats.symbols = sum(len(v) for v in self._symbols_by_name.values())
        self._stats.references = len(self._references)
        self._stats.edges = self._file_graph.number_of_edges()
        self._stats.wall_time_ms = (time.perf_counter() - start) * 1000

        return self._stats

    def _iter_source_files(self) -> Iterator[Path]:
        for root, dirs, files in os.walk(self.workspace_path):
            # In-place prune so os.walk doesn't descend into ignored dirs
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS and not d.startswith(".")]
            for name in files:
                ext = name.rsplit(".", 1)[-1] if "." in name else ""
                if ext not in _LANGUAGES:
                    continue
                path = Path(root) / name
                try:
                    if path.stat().st_size > self.MAX_FILE_SIZE:
                        self._stats.files_skipped += 1
                        continue
                except OSError:
                    self._stats.files_skipped += 1
                    continue
                yield path

    def _parse_file(self, file_path: Path) -> None:
        ext = file_path.suffix.lstrip(".")
        language = _LANGUAGES.get(ext)
        if language is None:
            return

        try:
            source = file_path.read_bytes()
        except OSError as e:
            logger.debug(f"[repo_graph] Read failed for {file_path}: {e}")
            self._stats.files_failed += 1
            return

        rel_path = str(file_path.relative_to(self.workspace_path))
        parser = Parser(language)
        tree = parser.parse(source)
        root = tree.root_node

        self._extract_symbols(root, rel_path, ext, source)
        self._extract_references(root, rel_path, ext, source)

    # --- AST extraction -----------------------------------------------------

    _DEF_TYPES: dict[str, dict[str, str]] = {
        "py":  {"function_definition": "function", "class_definition": "class"},
        "ts":  {"function_declaration": "function", "class_declaration": "class",
                "method_definition": "method"},
        "tsx": {"function_declaration": "function", "class_declaration": "class",
                "method_definition": "method"},
        "js":  {"function_declaration": "function", "class_declaration": "class",
                "method_definition": "method"},
        "jsx": {"function_declaration": "function", "class_declaration": "class",
                "method_definition": "method"},
        "mjs": {"function_declaration": "function", "class_declaration": "class"},
        "cjs": {"function_declaration": "function", "class_declaration": "class"},
        "go":  {"function_declaration": "function", "method_declaration": "method",
                "type_declaration": "class"},
        "rs":  {"function_item": "function", "struct_item": "class",
                "impl_item": "class", "trait_item": "class"},
    }

    _REF_TYPES: dict[str, frozenset[str]] = {
        "py":  frozenset({"call", "import_from_statement", "import_statement"}),
        "ts":  frozenset({"call_expression", "new_expression", "import_statement"}),
        "tsx": frozenset({"call_expression", "new_expression", "import_statement"}),
        "js":  frozenset({"call_expression", "new_expression", "import_statement"}),
        "jsx": frozenset({"call_expression", "new_expression", "import_statement"}),
        "mjs": frozenset({"call_expression", "new_expression", "import_statement"}),
        "cjs": frozenset({"call_expression", "new_expression", "import_statement"}),
        "go":  frozenset({"call_expression", "import_declaration"}),
        "rs":  frozenset({"call_expression", "use_declaration"}),
    }

    def _extract_symbols(self, root: Node, rel_path: str, ext: str, source: bytes) -> None:
        capture = self._DEF_TYPES.get(ext, {})
        if not capture:
            return

        stack: list[Node] = [root]
        while stack:
            node = stack.pop()
            kind = capture.get(node.type)
            if kind is not None:
                name = self._extract_name(node, source)
                if name:
                    self._symbols_by_name[name].append(Symbol(
                        name=name,
                        kind=kind,
                        file_path=rel_path,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                    ))
            # Reverse so we visit children left-to-right (deterministic for tests)
            stack.extend(reversed(node.children))

    def _extract_references(self, root: Node, rel_path: str, ext: str, source: bytes) -> None:
        capture = self._REF_TYPES.get(ext, frozenset())
        if not capture:
            return

        stack: list[Node] = [root]
        while stack:
            node = stack.pop()
            if node.type in capture:
                for name in self._names_from_ref_node(node, source):
                    self._references.append(Reference(
                        symbol_name=name,
                        file_path=rel_path,
                        line=node.start_point[0] + 1,
                    ))
            stack.extend(reversed(node.children))

    @staticmethod
    def _extract_name(node: Node, source: bytes) -> str | None:
        """Extract the identifier name of a definition node.

        Prefer named field lookup (works for Python, TS, Go); fall back to
        first identifier-like child.
        """
        try:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

        for child in node.children:
            if child.type in ("identifier", "type_identifier", "name"):
                return source[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        return None

    @staticmethod
    def _names_from_ref_node(node: Node, source: bytes) -> list[str]:
        """Extract identifiers from a call or import node.

        Rules:
            - Collect identifier / property_identifier / field_identifier children
            - Expand dotted_name into its components (e.g. `src.auth` -> ["src", "auth"])
            - Stop descending into nested calls (they get their own top-level visit)
        """
        names: list[str] = []

        def _collect(n: Node) -> None:
            t = n.type
            if t in ("identifier", "type_identifier", "property_identifier", "field_identifier"):
                names.append(source[n.start_byte:n.end_byte].decode("utf-8", errors="replace"))
                return
            if t == "dotted_name":
                text = source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
                names.extend(part for part in text.split(".") if part)
                return
            if t in ("call", "call_expression", "new_expression"):
                # Nested call - stop; the outer walker visits it separately
                return
            for child in n.children:
                _collect(child)

        for child in node.children:
            _collect(child)

        return names

    # --- File-level graph ---------------------------------------------------

    def _build_file_graph(self) -> None:
        """Edge (a, b) means: file `a` references at least one symbol defined in `b`.

        Multiple references collapse to a single edge. Direction matters for
        PageRank: we want files that are heavily depended on (leaves like
        `auth.py`) to score high, so edges point from user -> definer.
        """
        # Register every file that has any symbol so orphan files still get PR mass
        for syms in self._symbols_by_name.values():
            for sym in syms:
                self._file_graph.add_node(sym.file_path)

        for ref in self._references:
            self._file_graph.add_node(ref.file_path)
            defining_files = {
                s.file_path for s in self._symbols_by_name.get(ref.symbol_name, [])
                if s.file_path != ref.file_path
            }
            for defining_file in defining_files:
                self._file_graph.add_edge(ref.file_path, defining_file)

    def _compute_pagerank(self) -> None:
        if self._file_graph.number_of_nodes() == 0:
            return
        try:
            self._pagerank = nx.pagerank(self._file_graph, alpha=0.85)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[repo_graph] PageRank failed: {e} - using uniform prior")
            nodes = list(self._file_graph.nodes)
            self._pagerank = {n: 1.0 / len(nodes) for n in nodes}

    # --- Public query API ---------------------------------------------------

    def symbols_matching(self, keyword: str, limit: int = 20) -> list[Symbol]:
        """Return symbols whose name contains the keyword (case-insensitive substring).

        Sort order: exact matches first, then substring matches alphabetically.
        """
        needle = keyword.lower()
        matches: list[Symbol] = []
        for name, syms in self._symbols_by_name.items():
            if needle in name.lower():
                matches.extend(syms)
        matches.sort(key=lambda s: (0 if s.name.lower() == needle else 1, s.name, s.file_path))
        return matches[:limit]

    def references_of(self, symbol_name: str) -> list[Reference]:
        """Return every reference to a symbol by exact name (case-sensitive)."""
        return [ref for ref in self._references if ref.symbol_name == symbol_name]

    def file_neighborhood(self, file_path: str, radius: int = 1) -> list[str]:
        """Return files within `radius` graph hops of `file_path`.

        Uses undirected reachability (both callers and callees are neighbors)
        because for retrieval both directions of context are useful.
        """
        if file_path not in self._file_graph:
            return []
        visited = {file_path}
        frontier = {file_path}
        for _ in range(radius):
            next_frontier: set[str] = set()
            for f in frontier:
                next_frontier.update(self._file_graph.successors(f))
                next_frontier.update(self._file_graph.predecessors(f))
            next_frontier -= visited
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        visited.discard(file_path)
        return sorted(visited)

    def relevant_files_for(
        self,
        query: str,
        limit: int = 15,
        alpha: float = 0.7,
    ) -> list[FileMatch]:
        """Rank files by combined keyword + PageRank score for a natural-language query.

        Args:
            query: natural-language text (issue title + body works well).
            limit: return at most this many files.
            alpha: weight of keyword score vs. PageRank in the range 0..1.
                   Default 0.7 biases toward keyword relevance because
                   PageRank is query-independent and would otherwise
                   dominate.
        """
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        # For each query term, find matching symbols and note their defining files
        file_matched_symbols: dict[str, set[str]] = defaultdict(set)
        for term in query_terms:
            for sym in self.symbols_matching(term, limit=100):
                file_matched_symbols[sym.file_path].add(sym.name)

        if not file_matched_symbols:
            # No keyword hits at all: return top files by PageRank
            files = sorted(self._pagerank.items(), key=lambda x: -x[1])[:limit]
            return [
                FileMatch(path=p, keyword_score=0.0, pagerank_score=s,
                          combined_score=s, matched_symbols=[])
                for p, s in files
            ]

        max_km = max(len(v) for v in file_matched_symbols.values()) or 1
        max_pr = max((self._pagerank.get(f, 0.0) for f in file_matched_symbols), default=1.0) or 1.0

        matches: list[FileMatch] = []
        for path, syms in file_matched_symbols.items():
            km = len(syms) / max_km
            pr = self._pagerank.get(path, 0.0) / max_pr
            combined = alpha * km + (1 - alpha) * pr
            matches.append(FileMatch(
                path=path,
                keyword_score=km,
                pagerank_score=pr,
                combined_score=combined,
                matched_symbols=sorted(syms),
            ))

        matches.sort(key=lambda m: (-m.combined_score, m.path))
        return matches[:limit]

    # --- Introspection ------------------------------------------------------

    @property
    def stats(self) -> RepoGraphStats:
        return self._stats

    @property
    def file_graph(self) -> nx.DiGraph:
        """The underlying networkx graph. Exposed for tests / debugging."""
        return self._file_graph

    @property
    def pagerank(self) -> dict[str, float]:
        return dict(self._pagerank)


# --- Module-level cache -------------------------------------------------------

_CACHE: dict[str, RepoGraph] = {}


async def get_or_build_graph(workspace_path: str) -> RepoGraph:
    """Return a cached RepoGraph for a workspace, building it on first call."""
    key = str(Path(workspace_path).resolve())
    if key in _CACHE:
        return _CACHE[key]
    graph = RepoGraph(workspace_path)
    stats = await graph.build()
    logger.info(
        f"[repo_graph] Built graph for {workspace_path}: "
        f"{stats.files_parsed} files, {stats.symbols} symbols, "
        f"{stats.references} refs, {stats.edges} edges, "
        f"{stats.wall_time_ms:.0f}ms"
    )
    _CACHE[key] = graph
    return graph


def clear_cache(workspace_path: str | None = None) -> None:
    """Evict cached graphs. Pass None to clear all entries."""
    if workspace_path is None:
        _CACHE.clear()
    else:
        _CACHE.pop(str(Path(workspace_path).resolve()), None)


# --- Helpers ------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "are", "was",
    "been", "have", "has", "had", "not", "but", "all", "can", "her",
    "his", "they", "them", "their", "would", "should", "could",
    "when", "where", "what", "which", "who", "how", "why", "there",
    "also", "some", "into", "about", "than", "then", "its", "like",
    "just", "over", "such", "after", "before", "more", "other",
    "will", "may", "might", "shall", "should", "must", "does", "did",
    "yes", "any", "one", "two", "three", "get", "set", "use", "used",
    "using",
})


def _tokenize(query: str) -> list[str]:
    """Extract meaningful tokens from a natural-language query.

    Splits on non-identifier characters, filters stop-words and length<3,
    de-duplicates while preserving order (so `symbols_matching` gets the
    highest-signal terms first).
    """
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]+", query)
    seen: set[str] = set()
    result: list[str] = []
    for t in raw:
        low = t.lower()
        if low in _STOP_WORDS or len(t) < 3:
            continue
        if low in seen:
            continue
        seen.add(low)
        result.append(t)
    return result
