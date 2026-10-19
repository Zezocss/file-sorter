"""Rule input normalization and extension specificity."""

import pytest
from file_sorter.models import Problem
from file_sorter.rules import parse_extensions, validate_rules, match_rule
from conftest import rule


def test_normalization():
    """Optional dots, whitespace, case, and repeated entries normalize consistently."""
    assert parse_extensions(" JPG, .jpeg, png, jpg, tar.gz ") == ["jpg", "jpeg", "png", "tar.gz"]


@pytest.mark.parametrize("value", ["", "jpg,", ",pdf", "*.jpg", "..jpg", "tar.", "a/b", "a b", "a\\b"])
def test_invalid_extensions(value):
    """Malformed extension lists produce actionable validation errors."""
    with pytest.raises(Problem):
        parse_extensions(value)


def test_longest_match_and_dotfiles(folders):
    """Compound suffixes win; a bare dotfile is not its own extension."""
    root, _, target, state = folders
    rules = validate_rules([rule(target, "gz, tar.gz, env, json")], (root,), state)
    assert match_rule("BACKUP.TAR.GZ", rules)[1] == "tar.gz"
    assert match_rule(".env", rules) is None
    assert match_rule(".config.json", rules)[1] == "json"
    assert match_rule("noextension", rules) is None


def test_conflicting_rules(folders):
    """An extension cannot belong to multiple enabled rules but disabled rules are allowed."""
    root, _, target, state = folders
    items = [rule(target), rule(target, "JPG", id="second")]
    with pytest.raises(Problem, match="only one"):
        validate_rules(items, (root,), state)
    items[1]["enabled"] = False
    assert len(validate_rules(items, (root,), state)) == 2
