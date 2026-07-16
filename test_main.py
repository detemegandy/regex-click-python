import re
import pytest
from main import format_regex_pattern, _tokenize_pattern


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


# ── _tokenize_pattern ─────────────────────────────────────────────────────────

def test_tokenize_single():
    assert _tokenize_pattern("apple") == ["apple"]

def test_tokenize_two_words():
    assert _tokenize_pattern("green blue") == ["green", "blue"]

def test_tokenize_quoted_phrase():
    assert _tokenize_pattern('"pack size"') == ['"pack size"']

def test_tokenize_mixed():
    assert _tokenize_pattern('"pack size" blue') == ['"pack size"', "blue"]

def test_tokenize_empty():
    assert _tokenize_pattern("") == []

def test_tokenize_roundtrip_words():
    # split then re-join should produce equivalent regex
    text = "apple orange pear"
    tokens = _tokenize_pattern(text)
    assert len(tokens) == 3
    joined = " ".join(tokens)
    assert format_regex_pattern(joined) == format_regex_pattern(text)

def test_tokenize_roundtrip_phrase():
    text = '"pack size" reflect'
    tokens = _tokenize_pattern(text)
    assert len(tokens) == 2
    joined = " ".join(tokens)
    assert format_regex_pattern(joined) == format_regex_pattern(text)
