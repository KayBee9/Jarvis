import pytest

from app.main import strip_markdown_for_tts


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("plain words", "plain words"),
        ("*Hello*", "Hello"),
        ("**important**", "important"),
        ("`code`", "code"),
        ("~~old~~", "old"),
        ("[the docs](https://example.com)", "the docs"),
        ("1-4", "1 to 4"),
        ("100-200", "100 to 200"),
        ("aged 25-35 years", "aged 25 to 35 years"),
    ],
)
def test_symbols_become_speakable_text(text, spoken):
    assert strip_markdown_for_tts(text) == spoken


@pytest.mark.parametrize("text", ["2024-08-22", "COVID-19", "555-1234", "1-4-4", "check-in"])
def test_hyphens_that_are_not_ranges_are_left_alone(text):
    assert strip_markdown_for_tts(text) == text
