"""Template and collision correctness, including portable Windows restrictions."""

import pytest
from file_sorter.models import Problem
from file_sorter.naming import render_filename, allocate_destination


def test_template_keeps_compound_suffix():
    """Renaming changes only the stem and preserves the compound extension's spelling."""
    assert render_filename("backup.TAR.GZ", "tar.gz", "{date}_{stem}_{counter}", "2026-10-19", 2) == "2026-10-19_backup_2.TAR.GZ"


@pytest.mark.parametrize("template", ["{unknown}", "{stem.__class__}", "{counter:04}", "../{stem}", "CON", "name.", "{", ""])
def test_template_validation(template):
    """Unsafe templates fail, while an empty template intentionally preserves names."""
    if template == "":
        assert render_filename("a.JPG", "jpg", template, "2000-01-01", 1) == "a.JPG"
    else:
        with pytest.raises(Problem):
            render_filename("a.JPG", "jpg", template, "2000-01-01", 1)


def test_collision_reservations(tmp_path):
    """Existing files and earlier planned names are reserved before execution."""
    (tmp_path / "a.tar.gz").write_text("existing")
    reserved = set()
    assert allocate_destination(tmp_path, "a.tar.gz", "tar.gz", reserved, "keep_both").name == "a (1).tar.gz"
    assert allocate_destination(tmp_path, "a.tar.gz", "tar.gz", reserved, "keep_both").name == "a (2).tar.gz"
    assert allocate_destination(tmp_path, "a.tar.gz", "tar.gz", reserved, "skip") is None
