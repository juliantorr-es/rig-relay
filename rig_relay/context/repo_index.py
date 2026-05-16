"""DuckDB-backed repository context index.

Phase 3: deterministic repo maps before any retrieval layer. Maps source
files to their tests, docs, schemas, and related paths using naming
conventions and directory structure. No embeddings.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any, cast

try:
    import duckdb

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False
    duckdb = None  # type: ignore[assignment]


def _git_ls_files(root: Path) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], text=True, stderr=subprocess.DEVNULL, cwd=root
        )
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def _git_head_hash(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL, cwd=root
        ).strip()[:16]
    except Exception:
        return "no-git"


def _is_test_file(path: str) -> bool:
    return path.startswith("test_") or path.endswith("_test.py") or "/test_" in path


def _is_doc_file(path: str) -> bool:
    return path.startswith("docs/") or "/docs/" in path


def _is_schema_file(path: str) -> bool:
    return path.endswith(".schema.json")


def _stem(path: str) -> str:
    return Path(path).stem


def _compute_mtimes_fingerprint(root: Path, paths: list[str]) -> str:
    h = hashlib.sha256()
    for p in paths:
        fp = root / p
        try:
            mtime = str(fp.stat().st_mtime_ns)
        except Exception:
            mtime = "0"
        h.update(f"{p}:{mtime}".encode())
    return h.hexdigest()[:16]


class RepoContextIndex:
    """DuckDB-backed index of repository files and their relationships.

    Populated by scanning git-tracked files. Supports queries for test
    files, doc files, schema files, and related paths. Built fresh per
    session; fingerprint-based caching avoids redundant rebuilds.
    """

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = (workspace_root or Path.cwd()).resolve()
        self._con: Any = None
        self._populated = False
        self._fingerprint = ""
        self._error: str | None = None

    def _connect(self) -> Any:
        if self._con is None:
            if not HAS_DUCKDB:
                self._error = "DuckDB not available"
                return None
            self._con = cast(Any, duckdb).connect(database=":memory:")
        return self._con

    @property
    def is_available(self) -> bool:
        return HAS_DUCKDB

    @property
    def error(self) -> str | None:
        return self._error

    def populate(self) -> str:
        """Scan git-tracked files and populate the index.

        Returns the fingerprint for caching. If DuckDB is not available,
        returns empty string and sets error.
        """
        try:
            con = self._connect()
            if con is None:
                return ""
            root = self._workspace_root
            files = _git_ls_files(root)
            if not files:
                self._error = "No git-tracked files found"
                self._populated = True
                return _git_head_hash(root)

            self._fingerprint = _compute_mtimes_fingerprint(root, files)

            con.execute("DROP TABLE IF EXISTS files")
            con.execute("DROP TABLE IF EXISTS relations")

            con.execute("""
                CREATE TABLE files (
                    path VARCHAR PRIMARY KEY,
                    extension VARCHAR,
                    is_test BOOLEAN,
                    is_doc BOOLEAN,
                    is_schema BOOLEAN
                )
            """)

            con.execute("""
                CREATE TABLE relations (
                    source_path VARCHAR,
                    related_path VARCHAR,
                    relation_type VARCHAR,
                    PRIMARY KEY (source_path, related_path)
                )
            """)

            insert = []
            for f in files:
                ext = Path(f).suffix
                insert.append((
                    f,
                    ext,
                    _is_test_file(f),
                    _is_doc_file(f),
                    _is_schema_file(f),
                ))

            con.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?)", insert)

            self._build_relations(con, files)
            self._populated = True
            return self._fingerprint

        except Exception as exc:
            self._error = str(exc)
            return ""

    def close(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None

    def _build_relations(self, con: Any, files: list[str]) -> None:
        """Discover relationships: source -> test, doc, schema, same_package."""
        relations: list[tuple[str, str, str]] = []
        testable_exts = {".py", ".js", ".ts", ".rs", ".go", ".java"}
        file_set = set(files)

        for f in files:
            s = _stem(f)
            ext = Path(f).suffix
            if ext not in testable_exts:
                continue
            fp = Path(f)
            prefix = str(fp.parent) if str(fp.parent) != "." else ""
            candidates = [
                (f"{prefix}/test_{s}{ext}", "test"),
                (f"{prefix}/{s}_test{ext}", "test"),
                (f"docs/{s}.md", "doc"),
                (f"docs/schemas/{s}.schema.json", "schema"),
            ]
            for c, rtype in candidates:
                c = c.lstrip("/")
                if c in file_set and c != f:
                    relations.append((f, c, rtype))
            for other in file_set:
                if other == f:
                    continue
                op = Path(other)
                op_prefix = str(op.parent) if str(op.parent) != "." else ""
                if op_prefix == prefix and op.suffix == ext and op.stem != s:
                    relations.append((f, other, "same_package"))

        seen = set()
        unique: list[tuple[str, str, str]] = []
        for r in relations:
            key = (r[0], r[1])
            if key not in seen:
                seen.add(key)
                unique.append(r)
        if unique:
            con.executemany("INSERT INTO relations VALUES (?, ?, ?)", unique)

    def find_tests(self, paths: list[str]) -> list[str]:
        if not self._populated or self._con is None:
            return []
        try:
            ph = ",".join("?" for _ in paths)
            rows = self._con.execute(
                f"SELECT related_path FROM relations "
                f"WHERE source_path IN ({ph}) AND relation_type = 'test'",
                paths,
            ).fetchall()
            return sorted(set(r[0] for r in rows))
        except Exception:
            return []

    def find_docs(self, paths: list[str]) -> list[str]:
        if not self._populated or self._con is None:
            return []
        try:
            ph = ",".join("?" for _ in paths)
            rows = self._con.execute(
                f"SELECT related_path FROM relations "
                f"WHERE source_path IN ({ph}) AND relation_type = 'doc'",
                paths,
            ).fetchall()
            return sorted(set(r[0] for r in rows))
        except Exception:
            return []

    def find_schemas(self, paths: list[str]) -> list[str]:
        if not self._populated or self._con is None:
            return []
        try:
            ph = ",".join("?" for _ in paths)
            rows = self._con.execute(
                f"SELECT related_path FROM relations "
                f"WHERE source_path IN ({ph}) AND relation_type = 'schema'",
                paths,
            ).fetchall()
            return sorted(set(r[0] for r in rows))
        except Exception:
            return []

    def find_related(self, paths: list[str]) -> dict[str, list[str]]:
        if not self._populated or self._con is None:
            return {}
        try:
            ph = ",".join("?" for _ in paths)
            rows = self._con.execute(
                f"SELECT relation_type, related_path FROM relations "
                f"WHERE source_path IN ({ph})",
                paths,
            ).fetchall()
            result: dict[str, list[str]] = {}
            for rel_type, rel_path in rows:
                result.setdefault(rel_type, []).append(rel_path)
            for k in result:
                result[k] = sorted(set(result[k]))
            return result
        except Exception:
            return {}

    def summary(self) -> dict[str, Any]:
        if not self._populated or self._con is None:
            return {
                "available": False,
                "error": self._error,
                "file_count": 0,
                "relation_count": 0,
            }
        try:
            fc = self._con.execute("SELECT count(*) FROM files").fetchone()[0]
            rc = self._con.execute("SELECT count(*) FROM relations").fetchone()[0]
            return {
                "available": True,
                "fingerprint": self._fingerprint,
                "file_count": fc,
                "relation_count": rc,
            }
        except Exception:
            return {"available": False, "error": "query failed"}


__all__ = ["RepoContextIndex"]
