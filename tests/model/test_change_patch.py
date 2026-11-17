import copy
import json
import random

import pytest

from pywr_editor.model.change_log import ChangeLog, diff
from pywr_editor.model.change_patch import PatchError, apply_changes


def roundtrip(old: dict, new: dict) -> None:
    """Applies the diff of two models forwards and backwards."""
    changes = list(diff(old, new))
    forward = copy.deepcopy(old)
    apply_changes(forward, changes)
    # the order of the keys and the items is restored too
    assert json.dumps(forward) == json.dumps(new)
    backward = copy.deepcopy(new)
    apply_changes(backward, changes, reverse=True)
    assert json.dumps(backward) == json.dumps(old)


class TestPatch:
    def test_scalar_and_dictionary(self):
        roundtrip(
            {"a": 1, "b": {"c": 2, "d": [1, 2]}, "e": "x"},
            {"a": 5, "b": {"c": 2, "d": [1, 3], "f": 0}, "g": None},
        )

    def test_dictionary_order_is_restored(self):
        roundtrip({"a": 1, "b": 2, "c": 3, "d": 4}, {"b": 2, "x": 0, "d": 4, "y": 1})

    def test_named_items(self):
        old = [{"name": n, "v": i} for i, n in enumerate("ABCDEF")]
        new = [old[0], {"name": "X", "v": 9}, old[2], old[4], {"name": "Y"}, old[5]]
        roundtrip({"nodes": old}, {"nodes": new})

    def test_reordered_items(self):
        old = [{"name": n} for n in "ABCD"]
        new = [{"name": n} for n in "DBAC"]
        roundtrip({"nodes": old}, {"nodes": new})
        roundtrip({"nodes": old}, {"nodes": new[:3] + [{"name": "Z"}]})

    def test_edges(self):
        roundtrip(
            {"edges": [["A", "B"], ["B", "C"], ["C", "D"], ["B", "C"]]},
            {"edges": [["B", "C"], ["X", "Y"], ["C", "D"]]},
        )

    def test_type_change(self):
        roundtrip({"a": 1, "b": {"x": 1}}, {"a": True, "b": [1, 2]})

    def test_does_not_alias_values(self):
        old = {"nodes": []}
        new = {"nodes": [{"name": "A", "v": [1]}]}
        changes = list(diff(old, new))
        model = copy.deepcopy(old)
        apply_changes(model, changes)
        model["nodes"][0]["v"].append(2)
        assert changes[0].new == {"name": "A", "v": [1]}

    def test_model_is_untouched_when_the_changes_do_not_match(self):
        changes = list(
            diff({"nodes": [{"name": "A"}, {"name": "B"}]}, {"nodes": [{"name": "A"}]})
        )
        model = {"nodes": [{"name": "A"}, {"name": "C"}], "x": 1}
        before = copy.deepcopy(model)
        with pytest.raises(PatchError):
            apply_changes(model, changes)
        assert model == before

        # the change of a node that does not exist anymore
        changes = list(
            diff({"nodes": [{"name": "A", "v": 1}]}, {"nodes": [{"name": "A", "v": 2}]})
        )
        model = {"nodes": [{"name": "B"}]}
        with pytest.raises(PatchError):
            apply_changes(model, changes)
        assert model == {"nodes": [{"name": "B"}]}


def random_model(rng: random.Random) -> dict:
    names = list("ABCDEFGHIJ")
    rng.shuffle(names)
    return {
        "metadata": {"title": "t", "n": rng.randint(0, 3)},
        "nodes": [
            {"name": n, "v": rng.randint(0, 3), "p": {"x": rng.randint(0, 2)}}
            for n in names[: rng.randint(0, 8)]
        ],
        "edges": [
            [rng.choice("ABC"), rng.choice("DEF")] for _ in range(rng.randint(0, 6))
        ],
        "parameters": {
            f"p{i}": {"v": rng.randint(0, 2)} for i in range(5) if rng.random() < 0.6
        },
        "scenarios": [
            {"name": f"s{i}", "size": i} for i in range(3) if rng.random() < 0.7
        ],
        "list": [rng.randint(0, 3) for _ in range(rng.randint(0, 4))],
    }


class TestRandomised:
    @pytest.mark.parametrize("seed", range(300))
    def test_roundtrip(self, seed):
        rng = random.Random(seed)
        roundtrip(random_model(rng), random_model(rng))


class TestChangeLogDoesNotAlias:
    def test_logged_values_are_not_altered_by_later_edits(self):
        model = {"nodes": []}
        log = ChangeLog()
        log.start(model)
        model["nodes"].append({"name": "A", "max_flow": 1})
        first = log.record(model)
        model["nodes"][0]["max_flow"] = 99
        log.record(model)
        assert first.changes[0].new == {"name": "A", "max_flow": 1}
