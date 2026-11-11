import copy
import json
import os
import subprocess
import sys
from datetime import datetime

import pytest

from pywr_editor.dialects.next import scenarios as sc
from pywr_editor.dialects.next import time_domain as td


def time(start="2015-01-01", end="2015-01-31", timestep=None):
    return {
        "start": start,
        "end": end,
        "timestep": timestep or {"type": "Days", "days": 1},
    }


class TestTime:
    def test_parse(self):
        assert td.parse_time("2015-01-31") == datetime(2015, 1, 31)
        assert td.parse_time("2015-01-31T06:30:00") == datetime(2015, 1, 31, 6, 30)
        assert td.parse_time("2015-01-31 06:30") == datetime(2015, 1, 31, 6, 30)
        for bad in ("31/01/2015", "2015-13-01", "", None, 5):
            assert td.parse_time(bad) is None
        assert td.has_time_of_day("2015-01-31T06:00:00")
        assert not td.has_time_of_day("2015-01-31")

    def test_describe(self):
        assert td.describe_timestep({"type": "Days", "days": 1}) == "1 day"
        assert td.describe_timestep({"type": "Days", "days": 7}) == "7 days"
        assert td.describe_timestep({"type": "Hours", "hours": 6}) == "6 hours"
        assert td.describe_timestep({"type": "Frequency", "freq": "1mo"}) == "every 1mo"
        assert td.describe_timestep({"type": "Other"}) == "not set"
        assert td.describe_timestep(None) == "not set"

    def test_count_steps(self):
        assert td.count_steps(time()) == 31
        assert td.count_steps(time(timestep={"type": "Days", "days": 7})) == 5
        assert td.count_steps(
            time("2015-01-01T00:00:00", "2015-01-02T00:00:00", {"type": "Hours", "hours": 6})
        ) == 5
        assert td.count_steps(time(timestep={"type": "Frequency", "freq": "7d"})) is None
        assert td.count_steps(time(end="2014-01-01")) is None

    def test_valid(self):
        assert td.validate_time(time()) == []
        assert td.validate_time(time(timestep={"type": "Frequency", "freq": "1 month"})) == []
        assert td.validate_time(time("2015-01-01T06:00:00", "2015-01-02T06:00:00")) == []

    @pytest.mark.parametrize(
        "section, text",
        [
            (time(start="01/01/2015"), "start date"),
            (time(end=""), "end date is required"),
            (time(end="2014-12-31"), "before the start"),
            (time(timestep={"type": "Days", "days": 0}), "whole number above 0"),
            (time(timestep={"type": "Hours", "hours": 1.5}), "whole number above 0"),
            (time(timestep={"type": "Frequency", "freq": ""}), "frequency is required"),
            (time(timestep={"type": "Frequency", "freq": "often"}), "not recognised"),
            (time(timestep={"type": "Weeks"}), "days, hours or a frequency"),
            (None, "missing"),
        ],
    )
    def test_invalid(self, section, text):
        problems = td.validate_time(section)
        assert any(text in problem for problem in problems), problems

    @pytest.mark.skipif(
        not os.environ.get("PYWR_NEXT_PYTHON"),
        reason="PYWR_NEXT_PYTHON is not set to a Python with pywr-next",
    )
    def test_agrees_with_pywr_next(self):
        cases = [
            time(),
            time("2015-01-01T06:00", "2015-01-02T06:00", {"type": "Hours", "hours": 6}),
            time(timestep={"type": "Frequency", "freq": "1mo"}),
            time(timestep={"type": "Frequency", "freq": "P7D"}),
            time(timestep={"type": "Frequency", "freq": "1 month, 2 days"}),
            time(timestep={"type": "Frequency", "freq": "nonsense"}),
            time(end="2014-01-01"),
        ]
        program = (
            "import json, sys\nfrom pywr import ModelSchema\n"
            "for t in json.load(sys.stdin):\n"
            "    m = {'metadata': {'title': 't'}, 'time': t, 'network': {'nodes': [], 'edges': []}}\n"
            "    try:\n        ModelSchema.from_json_string(json.dumps(m)).build()\n        print('ok')\n"
            "    except Exception:\n        print('error')\n"
        )
        process = subprocess.run(
            [os.environ["PYWR_NEXT_PYTHON"], "-c", program],
            input=json.dumps(cases),
            capture_output=True,
            text=True,
        )
        results = process.stdout.split()
        assert len(results) == len(cases), process.stderr
        for case, result in zip(cases, results):
            assert (td.validate_time(case) == []) == (result == "ok"), case


DOMAIN = {
    "groups": [
        {"name": "Climate", "size": 3, "labels": ["dry", "median", "wet"]},
        {"name": "Demand", "size": 2},
    ]
}


class TestScenarios:
    def test_totals(self):
        assert sc.total_scenarios(None) == 1
        assert sc.total_scenarios(DOMAIN) == 6
        domain = copy.deepcopy(DOMAIN)
        domain["groups"][0]["subset"] = {"type": "Indices", "indices": [0, 2]}
        assert sc.total_scenarios(domain) == 4
        domain["groups"][0]["subset"] = {"type": "Slice", "start": 1, "end": 3}
        assert sc.total_scenarios(domain) == 4
        domain["groups"][0]["subset"] = {"type": "Labels", "labels": ["wet"]}
        assert sc.total_scenarios(domain) == 2
        assert sc.subset_indices(domain["groups"][0]) == [2]
        domain = {**DOMAIN, "combinations": [["dry", 0], ["wet", 1], ["median", 1]]}
        assert sc.total_scenarios(domain) == 3

    def test_valid(self):
        assert sc.validate_domain(None) == []
        assert sc.validate_domain(DOMAIN) == []
        assert sc.validate_domain({"groups": []}) == []
        assert sc.validate_domain({**DOMAIN, "combinations": [["dry", 0], [2, 1]]}) == []

    @pytest.mark.parametrize(
        "mutate, text",
        [
            (lambda d: d["groups"][0].update(name=""), "has no name"),
            (lambda d: d["groups"][1].update(name="Climate"), "used twice"),
            (lambda d: d["groups"][1].update(size=0), "size of"),
            (lambda d: d["groups"][0].update(labels=["a", "b"]), "2 labels for 3"),
            (lambda d: d["groups"][0].update(labels=["a", "a", "b"]), "must be different"),
            (lambda d: d["groups"][0].update(subset={"type": "Slice", "start": 2, "end": 9}), "slice of"),
            (lambda d: d["groups"][0].update(subset={"type": "Indices", "indices": [3]}), "indices of"),
            (lambda d: d["groups"][1].update(subset={"type": "Labels", "labels": ["x"]}), "needs labels"),
            (lambda d: d["groups"][0].update(subset={"type": "Labels", "labels": ["x"]}), "label the group does not have"),
            (lambda d: d.update(combinations=[["dry"]]), "one value for each group"),
            (lambda d: d.update(combinations=[["dry", 5]]), "outside the 2 scenarios"),
            (lambda d: d.update(combinations=[["nope", 0]]), "no label 'nope'"),
            (
                lambda d: (
                    d["groups"][0].update(subset={"type": "Slice", "start": 0, "end": 2}),
                    d.update(combinations=[["dry", 0]]),
                ),
                "both a slice and combinations",
            ),
        ],
    )
    def test_invalid(self, mutate, text):
        domain = copy.deepcopy(DOMAIN)
        mutate(domain)
        problems = sc.validate_domain(domain)
        assert any(text in problem for problem in problems), problems

    def test_group_references(self):
        model = {
            "network": {
                "parameters": [
                    {"type": "ConstantScenario", "meta": {"name": "a"}, "scenario_group": "Climate", "values": [1]},
                    {"type": "Other", "meta": {"name": "b"}, "scenario": "Climate"},
                    {"type": "Other", "meta": {"name": "c"}, "scenario": {"type": "Mean"}},
                    {"type": "Other", "meta": {"name": "Climate"}},
                ]
            }
        }
        assert sc.count_group_references(model, "Climate") == 2
        assert sc.rename_group_references(model, "Climate", "Rain") == 2
        assert model["network"]["parameters"][0]["scenario_group"] == "Rain"
        assert model["network"]["parameters"][1]["scenario"] == "Rain"
        # the parameter that has the same name is not a reference
        assert model["network"]["parameters"][3]["meta"]["name"] == "Climate"
        assert sc.count_group_references(model, "Climate") == 0
