from od_platform.inference.pipeline import _fit_preview_size


def test_large_landscape_video_is_fitted_to_screen() -> None:
    assert _fit_preview_size(3840, 2160, 1920, 1080) == (1632, 918)


def test_large_portrait_video_is_fitted_to_screen() -> None:
    assert _fit_preview_size(2160, 3840, 1920, 1080) == (516, 918)


def test_small_video_is_not_upscaled() -> None:
    assert _fit_preview_size(640, 480, 1920, 1080) == (640, 480)
