import re
import pytest
from main import format_regex_pattern


# ── format_regex_pattern ──────────────────────────────────────────────────────

def test_single_word():
    assert format_regex_pattern("apple") == "apple"

def test_multiple_words():
    assert format_regex_pattern("apple orange") == "apple|orange"

def test_quoted_phrase():
    assert format_regex_pattern('"apple juice"') == "apple\\ juice"

def test_mixed_words_and_phrase():
    assert format_regex_pattern('apple "orange juice"') == "apple|orange\\ juice"

def test_multiple_quoted_phrases():
    assert format_regex_pattern('"foo bar" "baz qux"') == "foo\\ bar|baz\\ qux"

def test_extra_spaces_ignored():
    assert format_regex_pattern("apple  orange   pear") == "apple|orange|pear"

def test_special_chars_escaped():
    assert format_regex_pattern("c++") == r"c\+\+"

def test_special_chars_in_phrase():
    assert format_regex_pattern('"foo.bar"') == r"foo\.bar"

def test_empty_string():
    assert format_regex_pattern("") == ""

def test_unmatched_quote_raises():
    with pytest.raises(ValueError, match="Unmatched"):
        format_regex_pattern('"unclosed')

def test_empty_quotes_ignored():
    result = format_regex_pattern('apple "" orange')
    assert result == "apple|orange"


# ── easy mode: case-insensitive matching ──────────────────────────────────────

def compile_easy(text: str) -> re.Pattern:
    return re.compile(format_regex_pattern(text), re.IGNORECASE)

def test_easy_mode_case_insensitive():
    pat = compile_easy("Apple")
    assert pat.search("APPLE")
    assert pat.search("apple")
    assert pat.search("Apple")

def test_easy_mode_phrase_case_insensitive():
    pat = compile_easy('"Orange Juice"')
    assert pat.search("orange juice")
    assert pat.search("ORANGE JUICE")

def test_easy_mode_no_match():
    pat = compile_easy("apple")
    assert not pat.search("orange")

def test_easy_mode_alternation_matches_any():
    pat = compile_easy("apple orange")
    assert pat.search("I like orange")
    assert pat.search("fresh apple")
    assert not pat.search("banana")
