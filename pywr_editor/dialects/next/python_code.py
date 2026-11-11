import ast
import inspect
import json
import keyword
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

"""
 The Python code of the "Python" parameters of a pywr-next model, and the checks the
 editor does on it. No Qt in this module.

 A Python parameter names an object in a Python file (or module) and pywr-next calls
 it like this (checked against pywr-next 2.0.0rc1):
   - a function is called as function(info, *args, **kwargs) at each timestep and
     returns the value;
   - a class is created once per scenario as Class(*args, **kwargs). It needs a
     "before(self, info)" method, which returns the value used by the network, or an
     "after(self, info)" method, which returns a value calculated after the network
     is solved. It can also have an "after_hook(self, info)" method that updates its
     state after the network is solved and returns nothing; "after" and "after_hook"
     cannot be defined together.
   - "info" has "timestep", "scenario_index", "get_metric(name)" and
     "get_index(name)". The names are the keys of the "metrics" and "indices" of the
     parameter, whose values are metrics of the model.
 The editor keeps the code of the parameters of a model in the file
 "<model name>_parameters.py" next to the model.
"""

FILE_SUFFIX = "_parameters.py"
""" The end of the name of the file the editor creates for a model """
CLASS_PHASES = ("before", "after")
HOOK = "after_hook"


@dataclass(frozen=True)
class PythonTarget:
    """What a Python parameter calls, and what it passes."""

    kind: str
    """ "Function" or "Class" """
    name: str
    """ The name of the function or class """
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    metrics: tuple[str, ...] = ()
    """ The names of the metrics given to the parameter """
    indices: tuple[str, ...] = ()
    """ The names of the indices given to the parameter """

    @classmethod
    def from_parameter(cls, parameter: dict) -> "PythonTarget | None":
        """
        Reads the target from the dictionary of a Python parameter.
        :param parameter: The parameter dictionary, or form values.
        :return: The target, None if the object is not defined.
        """
        obj = parameter.get("object")
        if not isinstance(obj, dict):
            return None
        kind = obj.get("type")
        name = obj.get("class" if kind == "Class" else "function")
        if kind not in ("Class", "Function") or not isinstance(name, str) or not name:
            return None
        args = parameter.get("args")
        kwargs = parameter.get("kwargs")
        metrics = parameter.get("metrics")
        indices = parameter.get("indices")
        return cls(
            kind=kind,
            name=name,
            args=tuple(args) if isinstance(args, list) else (),
            kwargs=dict(kwargs) if isinstance(kwargs, dict) else {},
            metrics=tuple(metrics) if isinstance(metrics, dict) else (),
            indices=tuple(indices) if isinstance(indices, dict) else (),
        )


@dataclass(frozen=True)
class Diagnostic:
    """A problem found in the code."""

    line: int
    """ The line number, from 1. 0 if the problem is not at a line """
    message: str
    severity: str = "error"
    """ "error" or "warning" """
    column: int = 0

    def shifted(self, offset: int) -> "Diagnostic":
        """
        Returns the diagnostic with another line number.
        :param offset: The number to add to the line.
        :return: The new diagnostic.
        """
        return Diagnostic(self.line + offset, self.message, self.severity, self.column)


def module_file(model_file: str | Path) -> Path:
    """
    Returns the file the editor keeps the Python code of a model in.
    :param model_file: The path of the model file.
    :return: The path, next to the model: "<model name>_parameters.py".
    """
    model_file = Path(model_file)
    return model_file.with_name(model_file.stem + FILE_SUFFIX)


def python_identifier(text: str) -> str:
    """
    Turns a parameter name into a valid Python name.
    :param text: The name, such as "Carbon budget (remaining)".
    :return: The name, such as "carbon_budget_remaining".
    """
    name = re.sub(r"\W+", "_", text.strip()).strip("_").lower()
    if not name:
        return "parameter"
    if name[0].isdigit() or keyword.iskeyword(name):
        name = f"parameter_{name}"
    return name


def class_name(text: str) -> str:
    """
    Turns a parameter name into a class name.
    :param text: The name, such as "carbon budget".
    :return: The name, such as "CarbonBudget".
    """
    words = [w for w in re.split(r"\W+", text) if w]
    name = "".join(w[:1].upper() + w[1:] for w in words)
    if not name or name[0].isdigit() or keyword.iskeyword(name):
        return f"Parameter{name}"
    return name


def starter_code(kind: str, name: str) -> str:
    """
    Returns the code of a new function or class.
    :param kind: "Function" or "Class".
    :param name: The name of the function or class.
    :return: The code.
    """
    if kind == "Class":
        return (
            f"class {name}:\n"
            '    """Returns the value of the parameter at each timestep."""\n\n'
            "    def __init__(self):\n"
            "        pass\n\n"
            "    def before(self, info):\n"
            "        return 0.0\n"
        )
    return (
        f"def {name}(info):\n"
        '    """Returns the value of the parameter at the timestep."""\n'
        "    return 0.0\n"
    )


def find_object(text: str, kind: str, name: str) -> tuple[int, int] | None:
    """
    Finds a function or class defined in a file.
    :param text: The content of the file.
    :param kind: "Function" or "Class".
    :param name: The name of the function or class.
    :return: The first and last line of its code (from 1, both included, with the
    decorators), or None if the file does not define it.
    """
    node_types = (
        (ast.ClassDef,)
        if kind == "Class"
        else (ast.FunctionDef, ast.AsyncFunctionDef)
    )
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _find_object_by_indent(text, kind, name)
    for node in tree.body:
        if isinstance(node, node_types) and node.name == name:
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            return first, node.end_lineno
    return None


def _find_object_by_indent(text: str, kind: str, name: str) -> tuple[int, int] | None:
    """
    Finds a function or class in a file that cannot be parsed, from the indentation.
    """
    keyword_ = "class" if kind == "Class" else r"(?:async\s+)?def"
    lines = text.splitlines()
    start = None
    for number, line in enumerate(lines, 1):
        if re.match(rf"{keyword_}\s+{re.escape(name)}\b", line):
            start = number
            break
    if start is None:
        return None
    first = start
    while first > 1 and lines[first - 2].startswith("@"):
        first -= 1
    end = start
    for number in range(start + 1, len(lines) + 1):
        line = lines[number - 1]
        if not line.strip():
            continue
        if line[0] in " \t":
            end = number
        else:
            break
    return first, end


def splice(
    text: str, span: tuple[int, int] | None, code: str
) -> tuple[str, tuple[int, int]]:
    """
    Puts code in a file, in place of a function or class, or at the end.
    :param text: The content of the file.
    :param span: The first and last line of the code to replace, as returned by
    find_object(). None adds the code at the end of the file.
    :param code: The new code.
    :return: The new content of the file and the first and last line of the code.
    """
    code = code.rstrip("\n")
    count = len(code.splitlines()) or 1
    lines = text.splitlines()
    if span is None:
        while lines and not lines[-1].strip():
            lines.pop()
        prefix = lines + [""] * 2 if lines else []
        start = len(prefix) + 1
        new_lines = prefix + code.splitlines()
    else:
        start = span[0]
        new_lines = lines[: span[0] - 1] + code.splitlines() + lines[span[1] :]
    return "\n".join(new_lines) + "\n", (start, start + count - 1)


def _signature(arguments: ast.arguments, skip_first: bool = False) -> inspect.Signature:
    """
    Builds the signature of a function from its syntax tree.
    :param arguments: The arguments node.
    :param skip_first: Whether to leave out the first argument, such as "self".
    :return: The signature, with "..." as the default of an argument with a default.
    """
    parameters = []
    positional = arguments.posonlyargs + arguments.args
    first_default = len(positional) - len(arguments.defaults)
    for index, arg in enumerate(positional):
        kind = (
            inspect.Parameter.POSITIONAL_ONLY
            if index < len(arguments.posonlyargs)
            else inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        default = ... if index >= first_default else inspect.Parameter.empty
        parameters.append(inspect.Parameter(arg.arg, kind, default=default))
    if arguments.vararg:
        parameters.append(
            inspect.Parameter(arguments.vararg.arg, inspect.Parameter.VAR_POSITIONAL)
        )
    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        parameters.append(
            inspect.Parameter(
                arg.arg,
                inspect.Parameter.KEYWORD_ONLY,
                default=inspect.Parameter.empty if default is None else ...,
            )
        )
    if arguments.kwarg:
        parameters.append(
            inspect.Parameter(arguments.kwarg.arg, inspect.Parameter.VAR_KEYWORD)
        )
    if skip_first and parameters:
        if parameters[0].kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            parameters = parameters[1:]
    return inspect.Signature(parameters)


def _check_call(
    signature: inspect.Signature, args: tuple, kwargs: dict
) -> str | None:
    """
    Checks that a call matches a signature.
    :return: The problem, None if the call is valid.
    """
    try:
        signature.bind(*args, **kwargs)
    except TypeError as error:
        return str(error)
    return None


def _static_key(node: ast.expr) -> tuple[str, str] | None:
    """
    Reads the name given to get_metric() or get_index().
    :return: ("exact", name) for a string, ("prefix", start) for an f-string that
    starts with a text, or None for a name that is calculated.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "exact", node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        first = node.values[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return "prefix", first.value
    return None


def _check_keys(node: ast.AST, target: PythonTarget) -> list[Diagnostic]:
    """
    Checks the names given to get_metric() and get_index() in some code against the
    metrics and indices of the parameter.
    """
    diagnostics = []
    used = {"get_metric": set(), "get_index": set()}
    declared = {"get_metric": target.metrics, "get_index": target.indices}
    other = {"get_metric": target.indices, "get_index": target.metrics}
    labels = {"get_metric": "metric", "get_index": "index"}
    calculated = {"get_metric": False, "get_index": False}
    for call in ast.walk(node):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in used
            and call.args
        ):
            continue
        method = call.func.attr
        key = _static_key(call.args[0])
        if key is None:
            calculated[method] = True
            continue
        mode, text = key
        names = declared[method]
        matches = (
            [n for n in names if n == text]
            if mode == "exact"
            else [n for n in names if n.startswith(text)]
        )
        if matches:
            used[method].update(matches)
        elif mode == "prefix" and not text:
            calculated[method] = True
        else:
            wording = "starts with" if mode == "prefix" else "is"
            hint = ""
            if mode == "exact" and text in other[method]:
                alternative = "get_index" if method == "get_metric" else "get_metric"
                hint = f" It is declared in the {'metrics' if alternative == 'get_metric' else 'indices'}: use {alternative}()"
            diagnostics.append(
                Diagnostic(
                    call.lineno,
                    f'No {labels[method]} "{text}" is given to the parameter '
                    f"(the name {wording} that).{hint}",
                    column=call.col_offset,
                )
            )
    for method, names in declared.items():
        if calculated[method]:
            continue
        for name in names:
            if name not in used[method]:
                diagnostics.append(
                    Diagnostic(
                        getattr(node, "lineno", 0),
                        f'The {labels[method]} "{name}" is given to the parameter '
                        f"but the code never reads it with {method}()",
                        "warning",
                    )
                )
    return diagnostics


def _check_function(node: ast.FunctionDef, target: PythonTarget) -> list[Diagnostic]:
    problem = _check_call(
        _signature(node.args), (None,) + tuple(target.args), target.kwargs
    )
    if problem:
        return [
            Diagnostic(
                node.lineno,
                f"pywr-next calls {node.name}(info, *args, **kwargs) with the args "
                f"and kwargs of the parameter, but: {problem}",
            )
        ]
    return []


def _check_class(node: ast.ClassDef, target: PythonTarget) -> list[Diagnostic]:
    diagnostics = []
    methods = {
        n.name: n
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    inherits = any(
        not (isinstance(b, ast.Name) and b.id == "object") for b in node.bases
    )

    init = methods.get("__init__")
    if init is not None:
        problem = _check_call(
            _signature(init.args, skip_first=True), tuple(target.args), target.kwargs
        )
        if problem:
            diagnostics.append(
                Diagnostic(
                    init.lineno,
                    "pywr-next creates the class with the args and kwargs of the "
                    f"parameter, but: {problem}",
                )
            )
    elif (target.args or target.kwargs) and not inherits:
        diagnostics.append(
            Diagnostic(
                node.lineno,
                "The parameter has args or kwargs but the class has no __init__ to "
                "take them",
            )
        )

    if not inherits:
        if not any(phase in methods for phase in CLASS_PHASES):
            diagnostics.append(
                Diagnostic(
                    node.lineno,
                    'The class needs a "before(self, info)" method that returns the '
                    'value (or an "after(self, info)" method for a value calculated '
                    "after the network is solved)",
                )
            )
        if "after" in methods and HOOK in methods:
            diagnostics.append(
                Diagnostic(
                    methods[HOOK].lineno,
                    f'pywr-next does not accept both "after" and "{HOOK}" methods',
                )
            )
    for name in (*CLASS_PHASES, HOOK):
        method = methods.get(name)
        if method is None:
            continue
        problem = _check_call(_signature(method.args, skip_first=True), (None,), {})
        if problem:
            diagnostics.append(
                Diagnostic(
                    method.lineno,
                    f"pywr-next calls {name}(self, info), but: {problem}",
                )
            )
    return diagnostics


def run_pyflakes(code: str) -> list[Diagnostic]:
    """
    Looks for undefined names, unused imports and similar problems, when pyflakes is
    installed.
    :param code: The code of a file.
    :return: The problems found, as warnings (and errors for undefined names).
    """
    try:
        from pyflakes import api
    except ImportError:
        return []

    diagnostics: list[Diagnostic] = []

    class Reporter:
        def unexpectedError(self, filename, msg):  # noqa: N802
            pass

        def syntaxError(self, *args, **kwargs):  # noqa: N802
            pass  # reported by ast.parse

        def flake(self, message):
            text = message.message % message.message_args
            severity = "error" if "undefined name" in text else "warning"
            diagnostics.append(
                Diagnostic(message.lineno, text, severity, message.col)
            )

    api.check(code, "<code>", Reporter())
    return diagnostics


def analyse(code: str, target: PythonTarget | None) -> list[Diagnostic]:
    """
    Checks the code of a file against the Python parameter that uses it.
    :param code: The content of the file.
    :param target: What the parameter calls. None checks only the file.
    :return: The problems found, in order of line. The line numbers are in the file.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [
            Diagnostic(
                error.lineno or 0,
                f"Syntax error: {error.msg}",
                column=(error.offset or 1) - 1,
            )
        ]

    diagnostics = run_pyflakes(code)
    if target is not None:
        found = find_object(code, target.kind, target.name)
        if found is None:
            diagnostics.append(
                Diagnostic(
                    0,
                    f"The code does not define the "
                    f"{target.kind.lower()} {target.name}",
                )
            )
        else:
            node = next(
                n
                for n in tree.body
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == target.name
                and n.end_lineno == found[1]
            )
            if target.kind == "Class":
                diagnostics += _check_class(node, target)
            else:
                diagnostics += _check_function(node, target)
            diagnostics += _check_keys(node, target)
    return sorted(diagnostics, key=lambda d: (d.line, d.column, d.message))


DRY_RUN_PROGRAM = '''\
import contextlib, importlib.util, io, json, sys, traceback
from datetime import datetime, timedelta

request = json.load(sys.stdin)


def day_of_year(day):
    return day.timetuple().tm_yday


class Timestep:
    def __init__(self, date, index, days):
        self.date, self.index, self.days = date, index, float(days)
        self.is_first = index == 0
        self.day, self.month, self.year = date.day, date.month, date.year
        self.day_of_year = day_of_year(date)
        leap = date.year % 4 == 0 and (date.year % 100 != 0 or date.year % 400 == 0)
        self.is_leap_year = leap
        self.day_of_year_index = self.day_of_year - 1 + (
            1 if not leap and self.day_of_year > 59 else 0
        )
        self.fractional_day_of_year = float(self.day_of_year_index) + (
            date.hour * 3600 + date.minute * 60 + date.second
        ) / 86400.0


class ScenarioIndex:
    simulation_id = 0
    simulation_indices = [0]


class ParameterInfo:
    def __init__(self, timestep):
        self.timestep = timestep
        self.scenario_index = ScenarioIndex()

    def get_metric(self, name):
        if name not in request["metrics"]:
            raise KeyError(f"The metric {name!r} is not given to the parameter")
        return float(request["metrics"][name])

    def get_index(self, name):
        if name not in request["indices"]:
            raise KeyError(f"The index {name!r} is not given to the parameter")
        return int(request["indices"][name])


def convert(value):
    kind = request["return_type"]
    if kind == "Int":
        return int(value)
    if kind == "Dict":
        return {str(k): float(v) for k, v in dict(value).items()}
    return float(value)


output = io.StringIO()
result = {"values": [], "printed": "", "error": None}
try:
    sys.path.insert(0, request["folder"])
    spec = importlib.util.spec_from_file_location("pywr_editor_dry_run", request["path"])
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        spec.loader.exec_module(module)
        target = getattr(module, request["name"])
        step = timedelta(days=request["timestep_days"])
        when = datetime.fromisoformat(request["start"])
        if request["kind"] == "Class":
            instance = target(*request["args"], **request["kwargs"])
        for index in range(request["steps"]):
            info = ParameterInfo(Timestep(when, index, request["timestep_days"]))
            if request["kind"] == "Class":
                if hasattr(instance, "before"):
                    value = instance.before(info)
                    if hasattr(instance, "after_hook"):
                        instance.after_hook(info)
                else:
                    value = instance.after(info)
            else:
                value = target(info, *request["args"], **request["kwargs"])
            result["values"].append([when.isoformat(), convert(value)])
            when += step
except BaseException:
    result["error"] = traceback.format_exc()
result["printed"] = output.getvalue()
sys.stdout.write("\\n" + json.dumps(result))
'''
""" The program that runs a parameter with a stub of the information pywr-next gives
it. It is run in another process by the Python of the pywr-next environment """


@dataclass
class DryRunResult:
    values: list[tuple[str, Any]] = field(default_factory=list)
    """ The date and value at each timestep """
    printed: str = ""
    """ What the code printed """
    error: str | None = None
    """ The error with its traceback, if the run failed """


def dry_run_request(
    file: str | Path,
    kind: str,
    name: str,
    args: list | None = None,
    kwargs: dict | None = None,
    metrics: dict[str, float] | None = None,
    indices: dict[str, int] | None = None,
    return_type: str = "Float",
    start: date | datetime | None = None,
    steps: int = 5,
    timestep_days: float = 1.0,
) -> dict:
    """
    Returns what DRY_RUN_PROGRAM reads: the function or class to call and the values
    to give it.
    :param file: The file with the code.
    :param kind: "Function" or "Class".
    :param name: The function or class.
    :param args: The args of the parameter.
    :param kwargs: The kwargs of the parameter.
    :param metrics: The test value of each metric.
    :param indices: The test value of each index.
    :param return_type: "Float", "Int" or "Dict".
    :param start: The date of the first timestep. Defaults to today.
    :param steps: The number of timesteps to run.
    :param timestep_days: The length of a timestep.
    :return: The request dictionary.
    """
    file = Path(file)
    start = start or datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if not isinstance(start, datetime):
        start = datetime(start.year, start.month, start.day)
    return {
        "folder": str(file.parent),
        "path": str(file),
        "kind": kind,
        "name": name,
        "args": args or [],
        "kwargs": kwargs or {},
        "metrics": metrics or {},
        "indices": indices or {},
        "return_type": return_type,
        "start": start.isoformat(),
        "steps": steps,
        "timestep_days": timestep_days,
    }


def read_dry_run_reply(stdout: str, stderr: str = "") -> DryRunResult:
    """
    Reads what DRY_RUN_PROGRAM wrote.
    :param stdout: The standard output of the process.
    :param stderr: The standard error of the process.
    :return: The values, or the error.
    """
    lines = stdout.strip().splitlines()
    try:
        reply = json.loads(lines[-1])
    except (IndexError, ValueError):
        return DryRunResult(
            error=(stderr or stdout or "Python did not answer").strip()
        )
    return DryRunResult(
        values=[(d, v) for d, v in reply["values"]],
        printed=reply["printed"],
        error=reply["error"],
    )


def dry_run(python: str, *request_args, timeout: float = 60.0, **request_kwargs):
    """
    Calls a function or class in a separate process, for a few timesteps, with test
    values for the metrics and indices. The code is never run in the editor process.
    :param python: The Python interpreter to use.
    :param request_args: The arguments of dry_run_request().
    :param timeout: The seconds after which the process is stopped.
    :param request_kwargs: The keyword arguments of dry_run_request().
    :return: The values, or the error, as a DryRunResult.
    """
    request = dry_run_request(*request_args, **request_kwargs)
    try:
        process = subprocess.run(
            [python, "-c", DRY_RUN_PROGRAM],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=request["folder"],
        )
    except subprocess.TimeoutExpired:
        return DryRunResult(error=f"The code did not finish in {timeout:g} seconds")
    except OSError as error:
        return DryRunResult(error=f"Python could not be started: {error}")
    return read_dry_run_reply(process.stdout, process.stderr)


def dry_run_python() -> str | None:
    """
    Returns the Python to run the code of a parameter with: the one of the
    pywr-next environment if it is installed, otherwise the one of the editor (when
    it is not a packaged application).
    :return: The path to the interpreter, None if there is none.
    """
    from pywr_editor.environments import pywr_next_environment

    environment = pywr_next_environment()
    if environment.is_installed():
        return str(environment.python)
    if not getattr(sys, "frozen", False):
        return sys.executable
    return None
