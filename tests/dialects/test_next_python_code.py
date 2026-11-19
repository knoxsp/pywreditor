import json
import os
import subprocess
import sys
from datetime import datetime

import pytest

from pywr_editor.dialects.next.python_code import (
    PythonTarget,
    analyse,
    class_name,
    dry_run,
    find_object,
    module_file,
    python_identifier,
    splice,
    starter_code,
)

CODE = '''\
from collections import deque


def decorator(cls):
    return cls


def double(info, factor=2):
    """Doubles the metric."""
    return info.get_metric("flow") * factor


@decorator
class Budget:
    def __init__(self, n_options, window=4):
        self.history = deque(maxlen=window)

    def before(self, info):
        return info.get_metric("total")

    def after_hook(self, info):
        self.history.append(info.get_index("trigger"))


def last():
    return 1.0
'''


def messages(code: str, target: PythonTarget | None, severity: str | None = None):
    return [
        d.message
        for d in analyse(code, target)
        if severity is None or d.severity == severity
    ]


def test_module_file_is_next_to_the_model(tmp_path):
    assert module_file(tmp_path / "thames.json") == tmp_path / "thames_parameters.py"


@pytest.mark.parametrize(
    "text, identifier, klass",
    [
        ("Carbon budget (remaining)", "carbon_budget_remaining", "CarbonBudgetRemaining"),
        ("2 stage", "parameter_2_stage", "Parameter2Stage"),
        ("class", "parameter_class", "Class"),
        ("  ", "parameter", "Parameter"),
    ],
)
def test_names(text, identifier, klass):
    assert python_identifier(text) == identifier
    assert class_name(text) == klass


def test_find_object_includes_decorators():
    assert find_object(CODE, "Function", "double") == (8, 10)
    assert find_object(CODE, "Class", "Budget") == (13, 22)
    assert find_object(CODE, "Function", "missing") is None
    assert find_object(CODE, "Class", "double") is None


def test_find_object_in_a_file_with_a_syntax_error():
    code = CODE.replace("return 1.0", "return (")
    assert find_object(code, "Function", "double") == (8, 10)
    assert find_object(code, "Function", "last") == (25, 26)


def test_splice_replaces_and_appends():
    new, span = splice(CODE, (8, 10), "def double(info):\n    return 0.0\n")
    assert span == (8, 9)
    assert find_object(new, "Function", "double") == span
    assert find_object(new, "Class", "Budget") is not None
    assert new.endswith("return 1.0\n")

    new, span = splice(CODE, None, starter_code("Function", "added"))
    assert find_object(new, "Function", "added") == span
    assert new.count("\n\n\ndef added") == 1
    new, span = splice("", None, starter_code("Class", "First"))
    assert span[0] == 1 and find_object(new, "Class", "First") == span


def test_valid_code_has_no_problems():
    function = PythonTarget("Function", "double", (), {"factor": 3}, ("flow",))
    assert analyse(CODE, function) == []
    klass = PythonTarget(
        "Class", "Budget", (2,), {}, ("total",), ("trigger",)
    )
    assert analyse(CODE, klass) == []


def test_syntax_error():
    problems = analyse("def f(:\n  pass", PythonTarget("Function", "f"))
    assert len(problems) == 1
    assert problems[0].line == 1 and "Syntax error" in problems[0].message


def test_missing_object():
    assert "does not define the function nope" in messages(
        CODE, PythonTarget("Function", "nope")
    )[0]
    assert "does not define the class double" in messages(
        CODE, PythonTarget("Class", "double")
    )[0]


def test_function_arguments_must_match():
    target = PythonTarget("Function", "double", (1, 2, 3), {}, ("flow",))
    text = " ".join(messages(CODE, target, "error"))
    assert "double(info, *args, **kwargs)" in text and "too many" in text
    target = PythonTarget("Function", "double", (), {"nope": 1}, ("flow",))
    assert "unexpected keyword argument 'nope'" in " ".join(messages(CODE, target))


def test_class_arguments_and_methods():
    target = PythonTarget("Class", "Budget", (), {}, ("total",), ("trigger",))
    assert "missing a required argument: 'n_options'" in " ".join(messages(CODE, target))

    code = "class A:\n    def go(self, info):\n        return 1\n"
    assert "needs a \"before(self, info)\"" in messages(code, PythonTarget("Class", "A"))[0]

    code = (
        "class A:\n    def after(self, info):\n        return 1\n"
        "    def after_hook(self, info):\n        pass\n"
    )
    assert "both" in messages(code, PythonTarget("Class", "A"))[0]

    code = "class A:\n    def before(self):\n        return 1\n"
    assert "before(self, info)" in messages(code, PythonTarget("Class", "A"))[0]

    code = "class A:\n    def before(self, info):\n        return 1\n"
    assert "no __init__" in messages(code, PythonTarget("Class", "A", (1,)))[0]
    # a base class may define what is missing
    code = "class A(Base):\n    pass\n"
    found = messages(code, PythonTarget("Class", "A", (1,)))
    assert [m for m in found if "undefined name" not in m] == []


def test_metric_and_index_names_are_checked():
    code = (
        "def f(info):\n"
        "    a = info.get_metric('flwo')\n"
        "    b = info.get_index('level')\n"
        "    return a + b\n"
    )
    target = PythonTarget("Function", "f", (), {}, ("flow", "level"), ("trigger",))
    text = messages(code, target)
    assert any('No metric "flwo"' in m for m in text)
    # declared as a metric but read as an index
    assert any('No index "level"' in m and "use get_metric()" in m for m in text)
    # declared but never read
    assert any('"flow" is given to the parameter but' in m for m in text)
    assert any('"trigger" is given to the parameter but' in m for m in text)


def test_calculated_names_are_not_checked():
    code = (
        "def f(info):\n"
        "    total = sum(info.get_metric(f'flow_{i}') for i in range(3))\n"
        "    return total + info.get_metric(NAME)\n"
    )
    target = PythonTarget("Function", "f", (), {}, ("flow_0", "flow_1", "other"))
    assert [m for m in messages(code, target) if "undefined" not in m] == []
    code = "def f(info):\n    return info.get_metric(f'flow_{0}')\n"
    target = PythonTarget("Function", "f", (), {}, ("stock",))
    assert 'starts with that' in " ".join(messages(code, target, "error"))


def test_pyflakes_findings():
    pytest.importorskip("pyflakes")
    code = "import os\n\ndef f(info):\n    return missing\n"
    problems = {d.message: d.severity for d in analyse(code, PythonTarget("Function", "f"))}
    assert problems["undefined name 'missing'"] == "error"
    assert problems["'os' imported but unused"] == "warning"


def test_dry_run_function(tmp_path):
    file = tmp_path / "p_parameters.py"
    file.write_text(
        "def scale(info, factor):\n"
        "    print('day', info.timestep.day)\n"
        "    return info.get_metric('flow') * factor + info.get_index('i')\n"
    )
    result = dry_run(
        sys.executable, file, "Function", "scale", [2], {}, {"flow": 1.5}, {"i": 1},
        start=datetime(2020, 2, 28), steps=3,
    )
    assert result.error is None
    assert result.values == [
        ("2020-02-28T00:00:00", 4.0),
        ("2020-02-29T00:00:00", 4.0),
        ("2020-03-01T00:00:00", 4.0),
    ]
    assert result.printed.splitlines() == ["day 28", "day 29", "day 1"]


def test_dry_run_class_keeps_state(tmp_path):
    file = tmp_path / "p.py"
    file.write_text(
        "class Counter:\n"
        "    def __init__(self, start=0):\n"
        "        self.n = start\n"
        "    def before(self, info):\n"
        "        return self.n\n"
        "    def after_hook(self, info):\n"
        "        self.n += 1\n"
    )
    result = dry_run(sys.executable, file, "Class", "Counter", [10], steps=3)
    assert [v for _, v in result.values] == [10.0, 11.0, 12.0]
    result = dry_run(sys.executable, file, "Class", "Counter", [10], steps=2, return_type="Int")
    assert [v for _, v in result.values] == [10, 11]


def test_dry_run_reports_errors(tmp_path):
    file = tmp_path / "p.py"
    file.write_text("def f(info):\n    return info.get_metric('nope')\n")
    result = dry_run(sys.executable, file, "Function", "f")
    assert result.values == []
    assert "The metric 'nope' is not given to the parameter" in result.error
    assert "KeyError" in result.error

    file.write_text("def f(info:\n    pass\n")
    assert "SyntaxError" in dry_run(sys.executable, file, "Function", "f").error

    file.write_text("def f(info):\n    return 1\n")
    assert "AttributeError" in dry_run(sys.executable, file, "Function", "g").error


def test_dry_run_stops_a_loop(tmp_path):
    file = tmp_path / "p.py"
    file.write_text("def f(info):\n    while True:\n        pass\n")
    result = dry_run(sys.executable, file, "Function", "f", timeout=1)
    assert "did not finish" in result.error


def test_dry_run_with_a_missing_python(tmp_path):
    result = dry_run(str(tmp_path / "no-python"), tmp_path / "p.py", "Function", "f")
    assert "could not be started" in result.error


@pytest.mark.skipif(
    not os.environ.get("PYWR_NEXT_PYTHON"),
    reason="PYWR_NEXT_PYTHON is not set to a Python with pywr-next",
)
def test_starter_code_runs_in_pywr_next(tmp_path):
    """
    Tests that the code the editor creates is accepted and run by pywr-next.
    """
    (tmp_path / "m_parameters.py").write_text(
        starter_code("Function", "scaled") + "\n\n" + starter_code("Class", "Held")
    )
    parameter = {
        "type": "Python",
        "source": {"type": "Path", "path": "m_parameters.py"},
    }
    model = {
        "metadata": {"title": "t"},
        "time": {
            "start": "2020-01-01",
            "end": "2020-01-03",
            "timestep": {"type": "Days", "days": 1},
        },
        "network": {
            "nodes": [
                {
                    "type": "Input",
                    "meta": {"name": "in"},
                    "max_flow": {"type": "Parameter", "name": "a"},
                    "cost": {"type": "Parameter", "name": "b"},
                },
                {
                    "type": "Output",
                    "meta": {"name": "out"},
                    "max_flow": {"type": "Literal", "value": 5},
                    "cost": {"type": "Literal", "value": -10},
                },
            ],
            "edges": [{"from_node": "in", "to_node": "out"}],
            "parameters": [
                {
                    **parameter,
                    "meta": {"name": "a"},
                    "object": {"type": "Function", "function": "scaled"},
                },
                {
                    **parameter,
                    "meta": {"name": "b"},
                    "object": {"type": "Class", "class": "Held"},
                },
            ],
        },
    }
    (tmp_path / "m.json").write_text(json.dumps(model))
    (tmp_path / "out").mkdir()
    process = subprocess.run(
        [os.environ["PYWR_NEXT_PYTHON"], "-m", "pywr", "run", "m.json", "-d", ".", "-o", "out"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    # what the dry run does with the same code
    for kind, name in (("Function", "scaled"), ("Class", "Held")):
        result = dry_run(sys.executable, tmp_path / "m_parameters.py", kind, name)
        assert result.error is None
