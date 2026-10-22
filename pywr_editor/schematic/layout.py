import numpy as np


def force_directed_layout(
    names: list[str],
    edges: list[tuple[str, str]],
    initial: dict[str, tuple[float, float]] | None = None,
    spacing: float = 90.0,
    iterations: int = 300,
    seed: int = 0,
) -> dict[str, list[float]]:
    """
    Computes a force-directed (Fruchterman-Reingold) layout: connected nodes attract
    each other and all the nodes repel each other, which pushes the nodes apart
    while keeping the connected ones close.
    :param names: The node names.
    :param edges: The (source, target) node names. Unknown names are ignored.
    :param initial: The current positions, used as the starting point. Nodes that
    are missing or that share the same position are scattered randomly.
    :param spacing: The ideal distance between connected nodes, in pixels.
    :param iterations: The number of iterations.
    :param seed: The seed of the random generator, so the layout is repeatable.
    :return: A dictionary with the new [x, y] position of each node, centred on the
    centre of the initial positions (or on the origin).
    """
    count = len(names)
    if count == 0:
        return {}

    rng = np.random.default_rng(seed)
    index = {name: i for i, name in enumerate(names)}
    radius = spacing * np.sqrt(count) / 2

    pos = rng.uniform(-radius, radius, size=(count, 2))
    centre = np.zeros(2)
    if initial:
        known = np.array([initial[n] for n in names if n in initial], dtype=float)
        if len(known) > 0:
            centre = known.mean(axis=0)
            # keep the existing layout only if the nodes are not stacked
            if len(np.unique(known.round(1), axis=0)) > 1:
                for name in names:
                    if name in initial:
                        pos[index[name]] = np.array(initial[name], float) - centre
                pos += rng.normal(scale=1.0, size=pos.shape)

    pairs = np.array(
        sorted(
            {
                (min(index[a], index[b]), max(index[a], index[b]))
                for a, b in edges
                if a in index and b in index and a != b
            }
        ),
        dtype=int,
    ).reshape(-1, 2)

    k = spacing
    temperature = radius / 5
    cooling = temperature / (iterations + 1)
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.maximum(np.linalg.norm(delta, axis=2), 0.01)
        # repulsion k^2 / d
        disp = (delta * (k * k / dist**2)[:, :, None]).sum(axis=1)
        # attraction d^2 / k along the edges
        if len(pairs) > 0:
            d = pos[pairs[:, 0]] - pos[pairs[:, 1]]
            length = np.maximum(np.linalg.norm(d, axis=1), 0.01)
            force = d * (length / k)[:, None]
            np.add.at(disp, pairs[:, 0], -force)
            np.add.at(disp, pairs[:, 1], force)
        norm = np.maximum(np.linalg.norm(disp, axis=1), 0.01)
        pos += disp / norm[:, None] * np.minimum(norm, temperature)[:, None]
        temperature -= cooling

    pos += centre - pos.mean(axis=0)
    return {name: [round(float(pos[i, 0]), 4), round(float(pos[i, 1]), 4)]
            for name, i in index.items()}


def snap_to_grid(
    positions: dict[str, list[float]], grid_size: int
) -> dict[str, list[float]]:
    """
    Moves each node to a grid point, as the snap-to-grid setting does when a node is
    dragged. Two nodes are never put on the same point: a node whose nearest point
    is taken goes to the closest free one, so the relative arrangement is kept.
    :param positions: The [x, y] position of each node.
    :param grid_size: The grid size, in pixels.
    :return: The snapped [x, y] positions.
    """
    grid = max(int(grid_size), 1)
    taken: set[tuple[int, int]] = set()
    snapped = {}
    # nodes closest to a grid point get it first
    def error(item):
        x, y = item[1]
        return abs(x / grid - round(x / grid)) + abs(y / grid - round(y / grid))

    for name, (x, y) in sorted(positions.items(), key=error):
        cx, cy = round(x / grid), round(y / grid)
        best, best_dist, ring = None, None, 0
        # search the rings of cells around the nearest one; stop once the next ring
        # cannot hold a closer cell than the best found
        while best is None or ring <= best_dist**0.5 + 1:
            for i in range(-ring, ring + 1):
                for j in range(-ring, ring + 1):
                    if max(abs(i), abs(j)) != ring or (cx + i, cy + j) in taken:
                        continue
                    d = (x / grid - cx - i) ** 2 + (y / grid - cy - j) ** 2
                    if best is None or d < best_dist:
                        best, best_dist = (cx + i, cy + j), d
            ring += 1
        taken.add(best)
        snapped[name] = [float(best[0] * grid), float(best[1] * grid)]
    return snapped


def infer_positions(
    known: dict[str, tuple[float, float]],
    names: list[str],
    edges: list[tuple[str, str]],
    iterations: int = 200,
    spread: float = 0.0,
) -> dict[str, tuple[float, float]]:
    """
    Estimates the position of the nodes without one from the positions of the
    connected nodes: each node is placed at the average position of its neighbours,
    which is repeated until the positions settle, so chains of unlocated nodes are
    spread between the located nodes at their ends. Nodes in a group that is not
    connected to any located node cannot be placed and are left out.
    :param known: The (x, y) position of the located nodes, in a metric CRS.
    :param names: The names of all the nodes.
    :param edges: The (source, target) node names.
    :param iterations: The maximum number of averaging iterations.
    :param spread: The radius used to separate nodes that are inferred to be at the
    same position, in the units of the CRS. Zero keeps them stacked.
    :return: The estimated (x, y) position of the nodes that were not located.
    """
    neighbours: dict[str, set[str]] = {name: set() for name in names}
    for source, target in edges:
        if source in neighbours and target in neighbours and source != target:
            neighbours[source].add(target)
            neighbours[target].add(source)

    # seed: breadth-first from the located nodes
    inferred: dict[str, tuple[float, float]] = {}
    current = {name: pos for name, pos in known.items() if name in neighbours}
    frontier = list(current)
    while frontier:
        found = {}
        for name in frontier:
            for other in neighbours[name]:
                if other not in current and other not in inferred:
                    found.setdefault(other, []).append(current.get(name) or inferred[name])
        frontier = []
        for name, points in found.items():
            inferred[name] = (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
            )
            frontier.append(name)

    # relax: the position of each node is the mean of its neighbours
    def position(name: str) -> tuple[float, float]:
        return current[name] if name in current else inferred[name]

    for _ in range(iterations):
        largest_move = 0.0
        for name in list(inferred):
            points = [position(n) for n in neighbours[name] if n in current or n in inferred]
            x = sum(p[0] for p in points) / len(points)
            y = sum(p[1] for p in points) / len(points)
            largest_move = max(largest_move, abs(x - inferred[name][0]), abs(y - inferred[name][1]))
            inferred[name] = (x, y)
        if largest_move < 1e-6:
            break

    if spread > 0:
        groups: dict[tuple[int, int], list[str]] = {}
        for name, (x, y) in inferred.items():
            groups.setdefault((round(x / spread), round(y / spread)), []).append(name)
        for members in groups.values():
            if len(members) < 2:
                continue
            for i, name in enumerate(sorted(members)):
                angle = 2 * np.pi * i / len(members)
                ring = spread * (1 + i // 12)
                x, y = inferred[name]
                inferred[name] = (x + ring * np.cos(angle), y + ring * np.sin(angle))
    return inferred
