import math
from typing import Any

"""
 The scenario domain of a pywr-next model ("scenarios" at the top level): groups of
 scenarios, each with a size, optional labels and an optional subset to simulate, and
 optionally a list of combinations of the groups to simulate. No Qt in this module.

 {"groups": [{"name": "Climate", "size": 3, "labels": ["dry", "median", "wet"],
              "subset": {"type": "Indices", "indices": [0, 2]}}],
  "combinations": [["dry", 0], ["wet", 1]]}

 The subset of a group is a "Slice" ({"start", "end"}, the end excluded), "Indices" or
 "Labels". A model cannot have both a slice and combinations.
"""

SUBSET_TYPES = ("Slice", "Indices", "Labels")
SCENARIO_KEYS = ("scenario_group", "scenario")
""" The keys of the network components that name a scenario group """


def groups_of(domain: Any) -> list[dict]:
    """
    Returns the groups of a domain.
    :param domain: The "scenarios" dictionary, or None.
    :return: The list of group dictionaries.
    """
    groups = domain.get("groups") if isinstance(domain, dict) else None
    return [g for g in groups if isinstance(g, dict)] if isinstance(groups, list) else []


def subset_indices(group: dict) -> list[int] | None:
    """
    Returns the scenarios of a group that are simulated.
    :param group: The group dictionary.
    :return: The indices in the order of the subset, all of them if the group has no
    subset, or None if the subset is invalid.
    """
    size = group.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return None
    subset = group.get("subset")
    if not subset:
        return list(range(size))
    kind = subset.get("type") if isinstance(subset, dict) else None
    if kind == "Slice":
        start, end = subset.get("start"), subset.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        return list(range(start, min(end, size))) if 0 <= start < end <= size else None
    if kind == "Indices":
        indices = subset.get("indices")
        if isinstance(indices, list) and all(
            isinstance(i, int) and 0 <= i < size for i in indices
        ):
            return list(indices)
        return None
    if kind == "Labels":
        labels = group.get("labels") or []
        chosen = subset.get("labels")
        if isinstance(chosen, list) and all(label in labels for label in chosen):
            return [labels.index(label) for label in chosen]
        return None
    return None


def total_scenarios(domain: Any) -> int | None:
    """
    Counts the simulations of a domain.
    :param domain: The "scenarios" dictionary, or None.
    :return: The number of scenarios simulated: the number of combinations, or the
    product of the sizes of the subsets. 1 if there are no groups, None if the domain
    is not valid.
    """
    groups = groups_of(domain)
    combinations = domain.get("combinations") if isinstance(domain, dict) else None
    if combinations:
        return len(combinations)
    sizes = [subset_indices(group) for group in groups]
    if any(size is None for size in sizes):
        return None
    return math.prod(len(size) for size in sizes)


def validate_domain(domain: Any) -> list[str]:
    """
    Checks a scenario domain.
    :param domain: The "scenarios" dictionary.
    :return: The problems found, as sentences. An empty list if it is valid.
    """
    if domain is None:
        return []
    if not isinstance(domain, dict) or not isinstance(domain.get("groups"), list):
        return ["The scenarios must have a list of groups"]
    problems = []
    groups = domain["groups"]
    names = set()
    has_slice = False
    for number, group in enumerate(groups, 1):
        if not isinstance(group, dict):
            problems.append(f"Group {number} is not valid")
            continue
        name = group.get("name")
        label = f'"{name}"' if isinstance(name, str) and name else f"Group {number}"
        if not isinstance(name, str) or not name.strip():
            problems.append(f"Group {number} has no name")
        elif name in names:
            problems.append(f"The group name {name!r} is used twice")
        else:
            names.add(name)
        size = group.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            problems.append(f"The size of {label} must be a whole number above 0")
            continue
        labels = group.get("labels")
        if labels:
            if len(labels) != size:
                problems.append(
                    f"{label} has {len(labels)} labels for {size} scenarios"
                )
            elif len(set(labels)) != len(labels):
                problems.append(f"The labels of {label} must be different")
        subset = group.get("subset")
        if subset:
            kind = subset.get("type") if isinstance(subset, dict) else None
            has_slice = has_slice or kind == "Slice"
            if kind not in SUBSET_TYPES:
                problems.append(f"The subset of {label} is not valid")
            elif subset_indices(group) is None:
                problems.append(_subset_problem(label, group, size))
    combinations = domain.get("combinations")
    if combinations:
        if has_slice:
            problems.append("A model cannot have both a slice and combinations")
        if not isinstance(combinations, list):
            problems.append("The combinations must be a list")
        else:
            for number, combination in enumerate(combinations, 1):
                problems += _combination_problems(number, combination, groups)
    return problems


def _subset_problem(label: str, group: dict, size: int) -> str:
    subset = group["subset"]
    kind = subset["type"]
    if kind == "Slice":
        return (
            f"The slice of {label} must start before it ends, within 0 and {size}"
        )
    if kind == "Indices":
        return f"The indices of {label} must be between 0 and {size - 1}"
    if not group.get("labels"):
        return f"{label} needs labels to choose a subset by label"
    return f"The subset of {label} uses a label the group does not have"


def _combination_problems(number: int, combination: Any, groups: list) -> list[str]:
    if not isinstance(combination, list) or len(combination) != len(groups):
        return [f"Combination {number} must have one value for each group"]
    problems = []
    for value, group in zip(combination, groups):
        if not isinstance(group, dict):
            continue
        size = group.get("size")
        labels = group.get("labels") or []
        name = group.get("name")
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            problems.append(f"Combination {number} has an invalid value for {name!r}")
        elif isinstance(value, int) and isinstance(size, int) and not 0 <= value < size:
            problems.append(
                f"Combination {number}: {value} is outside the {size} scenarios of "
                f"{name!r}"
            )
        elif isinstance(value, str) and value not in labels:
            problems.append(
                f"Combination {number}: {name!r} has no label {value!r}"
            )
    return problems


def rename_group_references(model: dict, old_name: str, new_name: str) -> int:
    """
    Renames a scenario group in the components of the network that use it.
    :param model: The model dictionary, changed in place.
    :param old_name: The current name of the group.
    :param new_name: The new name.
    :return: The number of references changed.
    """
    count = 0
    for container, key in _group_references(model.get("network"), old_name):
        container[key] = new_name
        count += 1
    return count


def count_group_references(model: dict, name: str) -> int:
    """
    Counts the components of the network that use a scenario group.
    :param model: The model dictionary.
    :param name: The name of the group.
    :return: The number of references.
    """
    return len(_group_references(model.get("network"), name))


def _group_references(node: Any, name: str) -> list[tuple[dict, str]]:
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SCENARIO_KEYS and value == name:
                found.append((node, key))
            else:
                found += _group_references(value, name)
    elif isinstance(node, list):
        for item in node:
            found += _group_references(item, name)
    return found
