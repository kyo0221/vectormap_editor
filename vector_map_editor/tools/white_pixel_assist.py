from __future__ import annotations

import heapq

import numpy as np


WHITE_PIXEL_THRESHOLD = 40
WHITE_PIXEL_SNAP_RADIUS = 30


def create_white_mask(image: np.ndarray, threshold: int = WHITE_PIXEL_THRESHOLD) -> np.ndarray:
    if image.ndim == 3:
        gray = np.mean(image[:, :, :3], axis=2)
    else:
        gray = image
    return gray > threshold


def trace_white_pixel_path(
    white_mask: np.ndarray,
    start_pixel: tuple[float, float],
    end_pixel: tuple[float, float],
) -> list[tuple[int, int]]:
    start = snap_to_white_pixel(white_mask, start_pixel)
    goal = snap_to_white_pixel(white_mask, end_pixel)
    if start == goal:
        return [start]

    height, width = white_mask.shape
    open_heap: list[tuple[float, float, tuple[int, int]]] = []
    heapq.heappush(open_heap, (pixel_distance(start, goal), 0.0, start))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    best_cost: dict[tuple[int, int], float] = {start: 0.0}
    neighbors = [
        (-1, 0, 1.0),
        (1, 0, 1.0),
        (0, -1, 1.0),
        (0, 1, 1.0),
        (-1, -1, 2**0.5),
        (-1, 1, 2**0.5),
        (1, -1, 2**0.5),
        (1, 1, 2**0.5),
    ]

    while open_heap:
        _, current_cost, current = heapq.heappop(open_heap)
        if current == goal:
            return reconstruct_pixel_path(came_from, current)
        if current_cost > best_cost[current]:
            continue

        cx, cy = current
        for dx, dy, step_cost in neighbors:
            nx = cx + dx
            ny = cy + dy
            if nx < 0 or ny < 0 or nx >= width or ny >= height:
                continue
            if not white_mask[ny, nx]:
                continue
            next_point = (nx, ny)
            new_cost = current_cost + step_cost
            if new_cost >= best_cost.get(next_point, float("inf")):
                continue
            best_cost[next_point] = new_cost
            came_from[next_point] = current
            priority = new_cost + pixel_distance(next_point, goal)
            heapq.heappush(open_heap, (priority, new_cost, next_point))

    raise RuntimeError("No connected white-pixel path found between the selected points")


def snap_to_white_pixel(
    white_mask: np.ndarray,
    pixel: tuple[float, float],
    max_radius: int = WHITE_PIXEL_SNAP_RADIUS,
) -> tuple[int, int]:
    x = int(round(pixel[0]))
    y = int(round(pixel[1]))
    height, width = white_mask.shape
    if x < 0 or y < 0 or x >= width or y >= height:
        raise RuntimeError("Selected point is outside the loaded image")
    if white_mask[y, x]:
        return x, y

    best: tuple[int, int] | None = None
    best_distance = float("inf")
    x_min = max(0, x - max_radius)
    x_max = min(width - 1, x + max_radius)
    y_min = max(0, y - max_radius)
    y_max = min(height - 1, y + max_radius)
    for yy in range(y_min, y_max + 1):
        for xx in range(x_min, x_max + 1):
            if not white_mask[yy, xx]:
                continue
            distance = pixel_distance((x, y), (xx, yy))
            if distance < best_distance:
                best_distance = distance
                best = (xx, yy)
    if best is None:
        raise RuntimeError("No white pixel found near the selected point")
    return best


def reconstruct_pixel_path(
    came_from: dict[tuple[int, int], tuple[int, int]],
    current: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path


def pixel_distance(p1: tuple[int, int], p2: tuple[int, int]) -> float:
    return float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
