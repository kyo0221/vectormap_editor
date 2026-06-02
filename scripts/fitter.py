from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


WGS84_A_M = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
MIN_CONTROL_POINTS = 5
DEFAULT_IMAGE_PATH = Path(__file__).resolve().parents[1] / "sample_image" / "lane.png"


@dataclass(frozen=True)
class ControlPoint:
    pixel_x: float
    pixel_y: float
    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0


@dataclass(frozen=True)
class EnuOrigin:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float


@dataclass(frozen=True)
class FitResult:
    pixel_to_enu_matrix: np.ndarray
    enu_to_pixel_matrix: np.ndarray
    enu_points: np.ndarray
    up_m: np.ndarray
    residuals_m: np.ndarray
    rmse_m: float
    max_error_m: float


def geodetic_to_ecef(latitude_deg: float, longitude_deg: float, altitude_m: float) -> np.ndarray:
    lat = np.deg2rad(latitude_deg)
    lon = np.deg2rad(longitude_deg)
    sin_lat = np.sin(lat)
    cos_lat = np.cos(lat)
    sin_lon = np.sin(lon)
    cos_lon = np.cos(lon)

    prime_vertical_radius = WGS84_A_M / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (prime_vertical_radius + altitude_m) * cos_lat * cos_lon
    y = (prime_vertical_radius + altitude_m) * cos_lat * sin_lon
    z = (prime_vertical_radius * (1.0 - WGS84_E2) + altitude_m) * sin_lat
    return np.array([x, y, z], dtype=np.float64)


def geodetic_to_enu(
    latitude_deg: float,
    longitude_deg: float,
    altitude_m: float,
    origin: EnuOrigin,
) -> np.ndarray:
    origin_ecef = geodetic_to_ecef(origin.latitude_deg, origin.longitude_deg, origin.altitude_m)
    point_ecef = geodetic_to_ecef(latitude_deg, longitude_deg, altitude_m)
    delta = point_ecef - origin_ecef

    origin_lat = np.deg2rad(origin.latitude_deg)
    origin_lon = np.deg2rad(origin.longitude_deg)
    sin_lat = np.sin(origin_lat)
    cos_lat = np.cos(origin_lat)
    sin_lon = np.sin(origin_lon)
    cos_lon = np.cos(origin_lon)

    rotation = np.array(
        [
            [-sin_lon, cos_lon, 0.0],
            [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
            [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
        ],
        dtype=np.float64,
    )
    return rotation @ delta


def fit_pixel_to_enu(control_points: list[ControlPoint], origin: EnuOrigin) -> FitResult:
    if len(control_points) < MIN_CONTROL_POINTS:
        raise ValueError(f"At least {MIN_CONTROL_POINTS} control points are required")

    pixel_points = np.array([[p.pixel_x, p.pixel_y] for p in control_points], dtype=np.float64)
    enu3_points = np.array(
        [
            geodetic_to_enu(p.latitude_deg, p.longitude_deg, p.altitude_m, origin)
            for p in control_points
        ],
        dtype=np.float64,
    )
    enu_points = enu3_points[:, :2]

    design = np.column_stack(
        [
            pixel_points[:, 0],
            pixel_points[:, 1],
            np.ones(len(control_points), dtype=np.float64),
        ]
    )
    coefficients, _, rank, _ = np.linalg.lstsq(design, enu_points, rcond=None)
    if rank < 3:
        raise ValueError("Control point pixels are degenerate for affine fitting")

    pixel_to_enu_matrix = np.array(
        [
            [coefficients[0, 0], coefficients[1, 0], coefficients[2, 0]],
            [coefficients[0, 1], coefficients[1, 1], coefficients[2, 1]],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    linear = pixel_to_enu_matrix[:2, :2]
    determinant = float(np.linalg.det(linear))
    if determinant == 0.0:
        raise ValueError("Estimated pixel-to-ENU transform matrix is singular")

    enu_to_pixel_matrix = np.linalg.inv(pixel_to_enu_matrix)
    predicted_enu = transform_points(pixel_to_enu_matrix, pixel_points)
    residuals_m = predicted_enu - enu_points
    errors_m = np.linalg.norm(residuals_m, axis=1)

    return FitResult(
        pixel_to_enu_matrix=pixel_to_enu_matrix,
        enu_to_pixel_matrix=enu_to_pixel_matrix,
        enu_points=enu_points,
        up_m=enu3_points[:, 2],
        residuals_m=residuals_m,
        rmse_m=float(np.sqrt(np.mean(errors_m * errors_m))),
        max_error_m=float(np.max(errors_m)),
    )


def transform_points(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    homogeneous = np.column_stack([points, np.ones(points.shape[0], dtype=np.float64)])
    transformed = homogeneous @ matrix.T
    return transformed[:, :2]


def load_control_points(path: Path) -> list[ControlPoint]:
    if not path.exists():
        raise FileNotFoundError(f"Control point file does not exist: {path}")
    if path.suffix.lower() == ".json":
        return load_json_control_points(path)
    if path.suffix.lower() == ".csv":
        return load_csv_control_points(path)
    raise ValueError("Control point file must be .csv or .json")


def input_control_points(point_count: int = MIN_CONTROL_POINTS) -> list[ControlPoint]:
    control_points: list[ControlPoint] = []
    for index in range(1, point_count + 1):
        print(f"Control point {index}/{point_count}")
        pixel_x = input_float("  pixel_x: ")
        pixel_y = input_float("  pixel_y: ")
        latitude = input_float("  latitude: ")
        longitude = input_float("  longitude: ")
        control_points.append(
            ControlPoint(
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                latitude_deg=latitude,
                longitude_deg=longitude,
                altitude_m=0.0,
            )
        )
    return control_points


def input_float(prompt: str) -> float:
    value = input(prompt)
    if value == "":
        raise ValueError(f"Empty input is not allowed for {prompt.strip()}")
    return float(value)


def load_json_control_points(path: Path) -> list[ControlPoint]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("JSON control point file must contain a list")
    return [control_point_from_mapping(item) for item in data]


def load_csv_control_points(path: Path) -> list[ControlPoint]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        return [control_point_from_mapping(row) for row in reader]


def control_point_from_mapping(data: Any) -> ControlPoint:
    if not isinstance(data, dict):
        raise ValueError("Each control point must be an object or CSV row")
    return ControlPoint(
        pixel_x=read_float(data, "pixel_x"),
        pixel_y=read_float(data, "pixel_y"),
        latitude_deg=read_float(data, "latitude"),
        longitude_deg=read_float(data, "longitude"),
        altitude_m=read_float(data, "altitude", default=0.0),
    )


def read_float(data: dict[str, Any], key: str, default: float | None = None) -> float:
    value = data.get(key)
    if value is None or value == "":
        if default is None:
            raise ValueError(f"Missing required field: {key}")
        return default
    return float(value)


def validate_image_points(image_path: Path, control_points: list[ControlPoint]) -> None:
    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(f"Image cannot be read: {image_path}")
    height, width = image.shape[:2]
    for index, point in enumerate(control_points, start=1):
        if not (0.0 <= point.pixel_x < width and 0.0 <= point.pixel_y < height):
            raise ValueError(
                f"Control point {index} pixel is outside image bounds: "
                f"({point.pixel_x}, {point.pixel_y}) not in width={width}, height={height}"
            )


def matrix_to_list(matrix: np.ndarray) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]


def result_to_dict(
    control_points: list[ControlPoint],
    origin: EnuOrigin,
    fit_result: FitResult,
) -> dict[str, Any]:
    control_point_results = []
    for point, enu, up_m, residual in zip(
        control_points,
        fit_result.enu_points,
        fit_result.up_m,
        fit_result.residuals_m,
    ):
        control_point_results.append(
            {
                "pixel": {"x": point.pixel_x, "y": point.pixel_y},
                "geodetic": {
                    "latitude": point.latitude_deg,
                    "longitude": point.longitude_deg,
                    "altitude": point.altitude_m,
                },
                "enu_m": {"east": float(enu[0]), "north": float(enu[1]), "up": float(up_m)},
                "residual_m": {"east": float(residual[0]), "north": float(residual[1])},
                "residual_norm_m": float(np.linalg.norm(residual)),
            }
        )

    return {
        "origin": {
            "latitude": origin.latitude_deg,
            "longitude": origin.longitude_deg,
            "altitude": origin.altitude_m,
        },
        "pixel_to_enu_matrix": matrix_to_list(fit_result.pixel_to_enu_matrix),
        "enu_to_pixel_matrix": matrix_to_list(fit_result.enu_to_pixel_matrix),
        "rmse_m": fit_result.rmse_m,
        "max_error_m": fit_result.max_error_m,
        "control_points": control_point_results,
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2, ensure_ascii=False)
        file.write("\n")


def print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fit an affine correspondence between image pixels and ENU coordinates "
            "from at least five pixel/latitude/longitude control points."
        )
    )
    parser.add_argument(
        "points",
        type=Path,
        nargs="?",
        help=(
            "CSV or JSON file with pixel_x,pixel_y,latitude,longitude[,altitude]. "
            "If omitted, five control points are read with input()."
        ),
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_IMAGE_PATH,
        help=f"Image path used for pixel bound validation. Default: {DEFAULT_IMAGE_PATH}",
    )
    parser.add_argument("--origin-latitude", type=float, default=None)
    parser.add_argument("--origin-longitude", type=float, default=None)
    parser.add_argument("--origin-altitude", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    return parser.parse_args()


def choose_origin(args: argparse.Namespace, control_points: list[ControlPoint]) -> EnuOrigin:
    has_origin_lat = args.origin_latitude is not None
    has_origin_lon = args.origin_longitude is not None
    if has_origin_lat != has_origin_lon:
        raise ValueError("Both --origin-latitude and --origin-longitude must be provided")
    if has_origin_lat and has_origin_lon:
        return EnuOrigin(args.origin_latitude, args.origin_longitude, args.origin_altitude)

    first_point = control_points[0]
    return EnuOrigin(first_point.latitude_deg, first_point.longitude_deg, first_point.altitude_m)


def main() -> None:
    args = parse_args()
    if args.points is None:
        control_points = input_control_points()
    else:
        control_points = load_control_points(args.points)
    validate_image_points(args.image, control_points)
    origin = choose_origin(args, control_points)
    fit_result = fit_pixel_to_enu(control_points, origin)
    result = result_to_dict(control_points, origin, fit_result)

    if args.output is not None:
        write_result(args.output, result)
    print_result(result)


if __name__ == "__main__":
    main()
