import json

from pywr_editor.model import pywr_data
from pywr_editor.model.pywr_parameters_data import PywrParametersData
from pywr_editor.model.pywr_recorders_data import PywrRecordersData


class TestPywrDataCache:
    def test_resource_is_parsed_once(self, monkeypatch):
        pywr_data._RESOURCE_CACHE.clear()
        calls = []
        real_loads = json.loads
        monkeypatch.setattr(
            pywr_data.json,
            "loads",
            lambda *a, **k: calls.append(1) or real_loads(*a, **k),
        )
        for _ in range(50):
            PywrParametersData()
            PywrRecordersData()
        assert len(calls) == 2  # one per resource, not per instance

    def test_cached_instances_behave_like_fresh_ones(self):
        pywr_data._RESOURCE_CACHE.clear()
        first = PywrParametersData()
        second = PywrParametersData()
        assert first.names == second.names
        assert first.keys == second.keys
        assert first.names == sorted(first.names, key=str.lower) or first.names
        assert first.exists("constant") and not first.exists("not-a-parameter")
        assert first.humanise_name("constant") == second.humanise_name("constant")
        assert first.is_custom("my.custom.Thing")

    def test_parameters_and_recorders_do_not_mix(self):
        params, recorders = PywrParametersData(), PywrRecordersData()
        assert params.suffix == "parameter" and recorders.suffix == "recorder"
        assert params.names != recorders.names

    def test_lookups_do_not_modify_the_shared_data(self):
        data = PywrParametersData()
        before = json.dumps([data.key_lookup, data.data], sort_keys=True)
        data.keys_with_parent_class("IndexParameter")
        data.humanise_name("constant")
        data.names, data.classes, data.values
        assert json.dumps([data.key_lookup, data.data], sort_keys=True) == before
        assert (
            json.dumps(
                [PywrParametersData().key_lookup, PywrParametersData().data],
                sort_keys=True,
            )
            == before
        )

    def test_data_sorted_by_key(self):
        data = PywrParametersData()
        assert list(data.data.keys()) == sorted(data.data.keys())
