from __future__ import annotations

from rig_relay.review_projection.transformer import PythonTransformer


def test_deterministic_opaque_mapping():
    source = "class MySecretClass:\n    def do_secret_thing(self, my_secret_arg):\n        pass"
    transformer = PythonTransformer()
    res, mapping = transformer.transform(source)
    assert "MySecretClass" not in res
    assert "do_secret_thing" not in res
    assert "my_secret_arg" not in res
    
    assert mapping["MySecretClass"] == "C_0001"
    assert mapping["do_secret_thing"] == "M_0001"
    assert mapping["my_secret_arg"] == "V_0001"
    
    # Check deterministic behavior
    transformer2 = PythonTransformer()
    res2, mapping2 = transformer2.transform(source)
    assert res == res2
    assert mapping == mapping2

def test_docstring_and_comment_removal():
    source = '''
# A comment before
class A:
    """This docstring should be removed."""
    # Another comment
    def func():
        """This too."""
        return "value" # inline comment
    '''
    transformer = PythonTransformer()
    res, _ = transformer.transform(source)
    
    assert "comment before" not in res
    assert "docstring should be removed" not in res
    assert "Another comment" not in res
    assert "This too" not in res
    assert "inline comment" not in res

def test_semantic_leakage_sanitation():
    source = '''
def test_confidential_leak():
    my_dict = {"confidential_key": "secret_value"}
    assert False, "This exposes mechanism"
    print("some artifact label")
'''
    transformer = PythonTransformer()
    res, _ = transformer.transform(source)
    
    assert "test_confidential_leak" not in res
    assert "confidential_key" not in res
    assert "secret_value" not in res
    assert "This exposes mechanism" not in res
    assert "some artifact label" not in res
    
    # Strings get replaced by S_XXXX
    assert "S_0001" in res
    assert "S_0002" in res

def test_syntactic_preservation():
    source = '''
import sys

def main():
    try:
        x = sys.argv
    except Exception as e:
        raise ValueError() from e
    return x
'''
    transformer = PythonTransformer()
    res, _ = transformer.transform(source)
    
    # structural keywords should remain
    assert "import sys" in res
    assert "try:" in res
    assert "except Exception" in res
    assert "raise ValueError" in res
    assert "return" in res
