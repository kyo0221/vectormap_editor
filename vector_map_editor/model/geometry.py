from __future__ import annotations

import numpy as np


ASSIST_RESAMPLE_SPACING_M = 3.0


def resample_polyline(points: list[tuple[float, float]], spacing_m: float) -> list[tuple[float, float]]:
    if spacing_m <= 0.0:
        raise ValueError("Resampling spacing must be positive")
    if len(points) < 2:
        return points.copy()

    distances = [0.0]
    for p1, p2 in zip(points, points[1:]):
        distances.append(distances[-1] + point_distance(p1, p2))
    total_length = distances[-1]
    if total_length == 0.0:
        raise RuntimeError("Cannot resample a zero-length polyline")

    sample_distances = list(np.arange(0.0, total_length, spacing_m))
    if not sample_distances or sample_distances[-1] != total_length:
        sample_distances.append(total_length)

    samples: list[tuple[float, float]] = []
    segment_index = 0
    for target_distance in sample_distances:
        while segment_index < len(distances) - 2 and distances[segment_index + 1] < target_distance:
            segment_index += 1
        start_distance = distances[segment_index]
        end_distance = distances[segment_index + 1]
        p1 = points[segment_index]
        p2 = points[segment_index + 1]
        if end_distance == start_distance:
            samples.append(p1)
            continue
        ratio = (target_distance - start_distance) / (end_distance - start_distance)
        samples.append((p1[0] + (p2[0] - p1[0]) * ratio, p1[1] + (p2[1] - p1[1]) * ratio))
    return samples


def infer_centerline_points(
    left_points: list[tuple[float, float]],
    right_points: list[tuple[float, float]],
    spacing_m: float,
) -> list[tuple[float, float]]:
    if len(left_points) < 2 or len(right_points) < 2:
        raise RuntimeError("Centerline inference requires at least two points per boundary")
    left_length = polyline_length(left_points)
    right_length = polyline_length(right_points)
    if left_length == 0.0 or right_length == 0.0:
        raise RuntimeError("Centerline inference requires non-zero-length boundaries")

    right_points = orient_right_boundary(left_points, right_points)
    average_length = (left_length + right_length) / 2.0
    sample_distances = list(np.arange(0.0, average_length, spacing_m))
    if not sample_distances or sample_distances[-1] != average_length:
        sample_distances.append(average_length)

    center_points: list[tuple[float, float]] = []
    for distance in sample_distances:
        ratio = distance / average_length
        left_point = interpolate_polyline_at_distance(left_points, left_length * ratio)
        right_point = interpolate_polyline_at_distance(right_points, right_length * ratio)
        center_points.append(((left_point[0] + right_point[0]) / 2.0, (left_point[1] + right_point[1]) / 2.0))
    return center_points


def orient_right_boundary(
    left_points: list[tuple[float, float]],
    right_points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    same_direction_cost = point_distance(left_points[0], right_points[0]) + point_distance(
        left_points[-1],
        right_points[-1],
    )
    reverse_direction_cost = point_distance(left_points[0], right_points[-1]) + point_distance(
        left_points[-1],
        right_points[0],
    )
    if reverse_direction_cost < same_direction_cost:
        return list(reversed(right_points))
    return right_points


def polyline_length(points: list[tuple[float, float]]) -> float:
    return float(sum(point_distance(p1, p2) for p1, p2 in zip(points, points[1:])))


def point_distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))


def interpolate_polyline_at_distance(
    points: list[tuple[float, float]],
    distance: float,
) -> tuple[float, float]:
    if distance <= 0.0:
        return points[0]
    remaining = distance
    for p1, p2 in zip(points, points[1:]):
        segment_length = point_distance(p1, p2)
        if segment_length == 0.0:
            continue
        if remaining <= segment_length:
            ratio = remaining / segment_length
            return (p1[0] + (p2[0] - p1[0]) * ratio, p1[1] + (p2[1] - p1[1]) * ratio)
        remaining -= segment_length
    return points[-1]
