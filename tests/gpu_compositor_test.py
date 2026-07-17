from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rm_client.ui.gpu_frame_compositor import (
    compose_premultiplied_pixel,
    normalize_premultiplied_pixel,
)


def test_premultiplied_composition() -> None:
    background = (0.20, 0.40, 0.60)
    glass = (0.10, 0.15, 0.20, 0.50)
    ui = (0.40, 0.10, 0.00, 0.50)
    result = compose_premultiplied_pixel(background, glass, ui)
    expected_scene = (0.20, 0.35, 0.50)
    expected = (0.50, 0.275, 0.25)
    assert all(abs(result[index] - expected[index]) < 1e-9 for index in range(3))
    assert expected_scene == (0.20, 0.35, 0.50)

    dynamic = (0.0, 0.30, 0.0, 0.50)
    result = compose_premultiplied_pixel(background, glass, ui, dynamic)
    expected = tuple(dynamic[index] + expected[index] * 0.50 for index in range(3))
    assert all(abs(result[index] - expected[index]) < 1e-9 for index in range(3))


def test_transparent_rgb_cannot_expose_texture_bounds() -> None:
    background = (0.18, 0.32, 0.47)
    transparent_leak = (1.0, 0.25, 0.10, 0.0)
    normalized = normalize_premultiplied_pixel(transparent_leak)
    assert normalized == (0.0, 0.0, 0.0, 0.0)

    result = compose_premultiplied_pixel(
        background,
        (0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0),
        transparent_leak,
    )
    assert result == background

    straight_alpha_white = normalize_premultiplied_pixel((1.0, 1.0, 1.0, 0.25))
    assert straight_alpha_white == (0.25, 0.25, 0.25, 0.25)


if __name__ == "__main__":
    test_premultiplied_composition()
    test_transparent_rgb_cannot_expose_texture_bounds()
    print("gpu compositor test passed")
