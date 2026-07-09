from od_platform.common.string_utils import get_display_width, pad_to_width


def test_ansi_color_sequences_do_not_consume_display_width() -> None:
    colored = "\x1b[92m0.8515 ▲\x1b[0m"

    assert get_display_width(colored) == 8
    assert pad_to_width(colored, 10).endswith("\x1b[0m  ")
