from pathlib import Path

from pywr_editor.utils import Settings


def test_tests_do_not_use_the_real_settings(isolated_editor_settings):
    settings = Settings("/some/model.json")
    for instance in (settings.instance, settings.global_instance):
        assert Path(instance.fileName()).is_relative_to(isolated_editor_settings)
    real = Path.home() / ".config" / "pywr-editor"
    assert not Path(settings.instance.fileName()).is_relative_to(real)


def test_recent_files_are_not_written_to_the_real_list(
    tmp_path, isolated_editor_settings
):
    Settings().save_recent_file(str(tmp_path / "model.json"))
    assert Path(Settings().global_instance.fileName()).is_relative_to(
        isolated_editor_settings
    )
