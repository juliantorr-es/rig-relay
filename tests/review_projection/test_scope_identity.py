from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from git import Repo

from rig_relay.review_projection.python_projection import PythonPseudonymizer


def _build_repo_with_python(tmp_path: Path, code: str) -> Repo:
    repo = Repo.init(tmp_path)
    repo.git.config("user.name", "test")
    repo.git.config("user.email", "test@test.test")
    (tmp_path / "src.py").write_text(code)
    repo.index.add(["src.py"])
    repo.index.commit("baseline")
    return repo


def test_method_local_consistent_pseudonym():
    """A method parameter and its uses receive one stable pseudonym."""
    code = """\
class Worker:
    def process(self, data):
        result = data.strip()
        return result
"""
    with TemporaryDirectory() as td:
        tmp_path = Path(td)
        _ = _build_repo_with_python(tmp_path, code)
        # Make a small modification
        src = tmp_path / "src.py"
        modified = code.replace("return result", "return result.upper()")
        src.write_text(modified)

        pseudonymizer = PythonPseudonymizer()
        base_entries, _, _ = pseudonymizer.inventory(code, "src.py")
        dirty_entries, _, _ = pseudonymizer.inventory(modified, "src.py")

        # All 'result' entries (LOCAL in method) should have the same scope_name
        result_scopes = set()
        for e in base_entries:
            if e.identity.original_spelling == "result":
                result_scopes.add(e.identity.scope_name)
        # 'result' in the method should be pseudonymized (scope != "retained")
        assert len(result_scopes) == 1, (
            f"Expected one scope for 'result', got {result_scopes}"
        )
        sc = next(iter(result_scopes))
        assert sc != "retained", "'result' should be pseudonymized, not retained"
        assert "function" in sc, f"Owner scope should be function type: {sc}"


def test_unrelated_locals_get_different_pseudonyms():
    """Two unrelated functions each declaring 'result' get different pseudonyms."""
    code = """\
def helper_a():
    result = 1
    return result

def helper_b():
    result = 2
    return result
"""
    with TemporaryDirectory() as td:
        tmp_path = Path(td)
        _build_repo_with_python(tmp_path, code)
        src = tmp_path / "src.py"
        modified = code.replace("result = 1", "result = 10")
        src.write_text(modified)

        pseudonymizer = PythonPseudonymizer()
        base_entries, _, _ = pseudonymizer.inventory(code, "src.py")
        dirty_entries, _, _ = pseudonymizer.inventory(modified, "src.py")
        _ = pseudonymizer.build_ledger("src.py", base_entries, dirty_entries)

        # Get unique ScopeIdentity for 'result' entries
        result_idents: set[str] = set()
        for e in base_entries:
            if e.identity.original_spelling == "result":
                # Scope identity is the owner scope
                result_idents.add(e.identity.scope_name)

        # Should have two different scopes (helper_a and helper_b)
        assert len(result_idents) >= 2, (
            f"Expected at least 2 distinct 'result' scopes, got {result_idents}"
        )
        retained_count = sum(1 for s in result_idents if s == "retained")
        assert retained_count == 0, "No 'result' should be retained"


def test_closure_free_gets_same_pseudonym_as_outer():
    """Inner closure reference to outer 'captured' gets same pseudonym as binding."""
    code = """\
def outer():
    captured = 42
    def inner():
        return captured
    return inner()
"""
    with TemporaryDirectory() as td:
        tmp_path = Path(td)
        _build_repo_with_python(tmp_path, code)
        src = tmp_path / "src.py"
        modified = code.replace("captured = 42", "captured = 99")
        src.write_text(modified)

        pseudonymizer = PythonPseudonymizer()
        base_entries, _, _ = pseudonymizer.inventory(code, "src.py")
        dirty_entries, _, _ = pseudonymizer.inventory(modified, "src.py")
        _ = pseudonymizer.build_ledger("src.py", base_entries, dirty_entries)

        # 'captured' entries — check scope_name consistency
        captured_scopes: set[str] = set()
        captured_kinds: set[str] = set()
        for e in base_entries:
            if e.identity.original_spelling == "captured":
                captured_scopes.add(e.identity.scope_name)
                captured_kinds.add(e.identity.binding_kind)

        # Both occurrences normalize to the owner's binding kind (LOCAL)
        # so they share the same ledger key and pseudonym.
        assert "local" in captured_kinds, f"Expected LOCAL binding: {captured_kinds}"
        # But they should resolve to the SAME owner scope
        assert len(captured_scopes) == 1, (
            f"LOCAL and FREE 'captured' should share same owner scope, "
            f"got {captured_scopes}"
        )
        scope = next(iter(captured_scopes))
        assert scope != "retained", "Closure variable should be pseudonymized"
        assert "function" in scope


def test_class_body_name_not_closure_captured():
    """A class-body name must not be treated as a closure capture in a method."""
    code = """\
value = "module"

class Container:
    value = "class"
    def method(self):
        return value
"""
    with TemporaryDirectory() as td:
        tmp_path = Path(td)
        _build_repo_with_python(tmp_path, code)
        src = tmp_path / "src.py"
        modified = code.replace('"module"', '"module_level"')
        src.write_text(modified)

        pseudonymizer = PythonPseudonymizer()
        base_entries, _, _ = pseudonymizer.inventory(code, "src.py")

        # 'value' in method → should resolve to GLOBAL (module scope), not class
        method_value_scopes: set[str] = set()
        for e in base_entries:
            if e.identity.original_spelling == "value":
                method_value_scopes.add(e.identity.scope_name)

        # In v1, GLOBAL is retained
        retained_count = sum(1 for s in method_value_scopes if s == "retained")
        assert retained_count >= 1, (
            f"GLOBAL 'value' in method should be retained (not pseudonymized). "
            f"Got scopes: {method_value_scopes}"
        )


def test_public_api_names_retained():
    """Public module-level functions and classes are retained."""
    code = """\
def public_api():
    local_var = 1
    return local_var

class PublicClass:
    def method(self):
        return 1
"""
    with TemporaryDirectory() as td:
        tmp_path = Path(td)
        _build_repo_with_python(tmp_path, code)
        src = tmp_path / "src.py"
        modified = code.replace("local_var = 1", "local_var = 2")
        src.write_text(modified)

        pseudonymizer = PythonPseudonymizer()
        base_entries, _, _ = pseudonymizer.inventory(code, "src.py")

        # 'public_api' function name should not be pseudonymized
        pub_entries = [
            e for e in base_entries if e.identity.original_spelling == "public_api"
        ]
        for e in pub_entries:
            assert e.identity.scope_name == "retained", (
                f"'public_api' should be retained: {e.identity}"
            )

        # 'local_var' should be pseudonymized
        local_entries = [
            e for e in base_entries if e.identity.original_spelling == "local_var"
        ]
        for e in local_entries:
            assert e.identity.scope_name != "retained", (
                f"'local_var' should be pseudonymized: {e.identity}"
            )
