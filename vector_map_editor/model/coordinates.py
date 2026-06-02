from __future__ import annotations


PIXEL_TO_ENU_A = 0.1732124950837092
PIXEL_TO_ENU_B = 0.013293993882809219
PIXEL_TO_ENU_C = -96.52188755507068
PIXEL_TO_ENU_D = 0.016913960339493113
PIXEL_TO_ENU_E = -0.17385227537455333
PIXEL_TO_ENU_F = 47.57187927052827

_DET = PIXEL_TO_ENU_A * PIXEL_TO_ENU_E - PIXEL_TO_ENU_B * PIXEL_TO_ENU_D
if _DET == 0.0:
    raise ValueError("Pixel-to-ENU transform matrix is singular")

ENU_TO_PIXEL_A = PIXEL_TO_ENU_E / _DET
ENU_TO_PIXEL_B = -PIXEL_TO_ENU_B / _DET
ENU_TO_PIXEL_D = -PIXEL_TO_ENU_D / _DET
ENU_TO_PIXEL_E = PIXEL_TO_ENU_A / _DET
ENU_TO_PIXEL_C = -(ENU_TO_PIXEL_A * PIXEL_TO_ENU_C + ENU_TO_PIXEL_B * PIXEL_TO_ENU_F)
ENU_TO_PIXEL_F = -(ENU_TO_PIXEL_D * PIXEL_TO_ENU_C + ENU_TO_PIXEL_E * PIXEL_TO_ENU_F)

PIXEL_TO_ENU_MATRIX = (
    (PIXEL_TO_ENU_A, PIXEL_TO_ENU_B, PIXEL_TO_ENU_C),
    (PIXEL_TO_ENU_D, PIXEL_TO_ENU_E, PIXEL_TO_ENU_F),
    (0.0, 0.0, 1.0),
)
ENU_TO_PIXEL_MATRIX = (
    (ENU_TO_PIXEL_A, ENU_TO_PIXEL_B, ENU_TO_PIXEL_C),
    (ENU_TO_PIXEL_D, ENU_TO_PIXEL_E, ENU_TO_PIXEL_F),
    (0.0, 0.0, 1.0),
)


def pixel_to_enu(x_pixel: float, y_pixel: float) -> tuple[float, float]:
    """Convert image pixel coordinates to ENU meter coordinates."""
    east_m = PIXEL_TO_ENU_A * x_pixel + PIXEL_TO_ENU_B * y_pixel + PIXEL_TO_ENU_C
    north_m = PIXEL_TO_ENU_D * x_pixel + PIXEL_TO_ENU_E * y_pixel + PIXEL_TO_ENU_F
    return east_m, north_m


def enu_to_pixel(east_m: float, north_m: float) -> tuple[float, float]:
    """Convert ENU meter coordinates to image pixel coordinates."""
    x_pixel = ENU_TO_PIXEL_A * east_m + ENU_TO_PIXEL_B * north_m + ENU_TO_PIXEL_C
    y_pixel = ENU_TO_PIXEL_D * east_m + ENU_TO_PIXEL_E * north_m + ENU_TO_PIXEL_F
    return x_pixel, y_pixel
