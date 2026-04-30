from __future__ import annotations


ECEF_TO_PIXEL_A = -3.39704
ECEF_TO_PIXEL_B = -4.60004
ECEF_TO_PIXEL_C = -7.74396
ECEF_TO_PIXEL_D = 5.92272

_DET = ECEF_TO_PIXEL_A * ECEF_TO_PIXEL_D - ECEF_TO_PIXEL_B * ECEF_TO_PIXEL_C
if _DET == 0.0:
    raise ValueError("ECEF to pixel transform matrix is singular")

PIXELS_PER_METER = abs(_DET) ** 0.5
if PIXELS_PER_METER <= 0.0:
    raise ValueError("Pixel-to-meter scale must be positive")


def local_meter_to_pixel(x_m: float, y_m: float) -> tuple[float, float]:
    """Convert local meter coordinates to image pixel coordinates.

    The local origin is the image origin. X is positive to the right in the
    image, and Y is positive upward for RViz-compatible map coordinates.
    """
    x_pixel = x_m * PIXELS_PER_METER
    y_pixel = -y_m * PIXELS_PER_METER
    return x_pixel, y_pixel


def pixel_to_local_meter(x_pixel: float, y_pixel: float) -> tuple[float, float]:
    """Convert image pixel coordinates to local meter coordinates."""
    x_m = x_pixel / PIXELS_PER_METER
    y_m = -y_pixel / PIXELS_PER_METER
    return x_m, y_m
