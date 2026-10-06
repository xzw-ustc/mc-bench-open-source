import pytest

from scripts.linux.patch_runtime import SOURCE, patch


def test_runtime_patch_rejects_unknown_source_without_modifying_it(tmp_path):
    path = tmp_path / SOURCE
    path.parent.mkdir(parents=True)
    path.write_text('class UnknownRuntime {}')
    with pytest.raises(ValueError, match='configured MineRL revision'):
        patch(tmp_path)
    assert path.read_text() == 'class UnknownRuntime {}'
