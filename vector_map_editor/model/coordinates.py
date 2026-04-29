from __future__ import annotations


ECEF_TO_PIXEL_A = -3.39704
ECEF_TO_PIXEL_B = -4.60004
ECEF_TO_PIXEL_C = -7.74396
ECEF_TO_PIXEL_D = 5.92272

_DET = ECEF_TO_PIXEL_A * ECEF_TO_PIXEL_D - ECEF_TO_PIXEL_B * ECEF_TO_PIXEL_C
if _DET == 0.0:
    raise ValueError("ECEF to pixel transform matrix is singular")


def local_meter_to_pixel(x_m: float, y_m: float) -> tuple[float, float]:
    """Convert local meter coordinates to image pixel coordinates.

    The local origin is the image origin. Only the linear part of the provided
    ECEF-to-pixel affine transform is used because local coordinates are
    relative to the image origin.
    """
    x_pixel = ECEF_TO_PIXEL_A * x_m + ECEF_TO_PIXEL_B * y_m
    y_pixel = ECEF_TO_PIXEL_C * x_m + ECEF_TO_PIXEL_D * y_m
    return x_pixel, y_pixel


def pixel_to_local_meter(x_pixel: float, y_pixel: float) -> tuple[float, float]:
    """Convert image pixel coordinates to local meter coordinates."""
    x_m = (ECEF_TO_PIXEL_D * x_pixel - ECEF_TO_PIXEL_B * y_pixel) / _DET
    y_m = (-ECEF_TO_PIXEL_C * x_pixel + ECEF_TO_PIXEL_A * y_pixel) / _DET
    return x_m, y_m
