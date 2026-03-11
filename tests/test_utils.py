"""Tests for p4cmd/utils.py — no mocking required."""
import logging

import pytest

from p4cmd.utils import (
    convert_to_list,
    decode_dictionaries,
    split_list_into_strings_of_length,
    validate_not_empty,
)


# ---------------------------------------------------------------------------
# split_list_into_strings_of_length
# ---------------------------------------------------------------------------

def test_split_under_max():
    result = split_list_into_strings_of_length(["a", "b", "c"], max_length=100)
    assert result == ["a b c"]


def test_split_over_max():
    # Each item is 5 chars; max=10 forces splits
    items = ["hello", "world", "foo", "bar"]
    result = split_list_into_strings_of_length(items, max_length=10)
    assert len(result) > 1
    # Every item still appears somewhere in the joined output
    combined = "".join(result)
    for item in items:
        assert item in combined


def test_split_single_oversized_item():
    # A single item longer than max should still be returned (not dropped)
    long_item = "a" * 200
    result = split_list_into_strings_of_length([long_item], max_length=10)
    assert any(long_item in chunk for chunk in result)


# ---------------------------------------------------------------------------
# decode_dictionaries
# ---------------------------------------------------------------------------

def test_decode_dictionaries():
    raw = [{b"depotFile": b"//depot/file.txt", b"haveRev": b"3"}]
    result = decode_dictionaries(raw)
    assert result == [{"depotFile": "//depot/file.txt", "haveRev": "3"}]


def test_decode_dictionaries_already_str():
    raw = [{"key": "value", b"bytes_key": b"bytes_val"}]
    result = decode_dictionaries(raw)
    assert result == [{"key": "value", "bytes_key": "bytes_val"}]


def test_decode_dictionaries_empty():
    assert decode_dictionaries([]) == []


# ---------------------------------------------------------------------------
# convert_to_list
# ---------------------------------------------------------------------------

def test_convert_to_list_str():
    assert convert_to_list("a") == ["a"]


def test_convert_to_list_list():
    assert convert_to_list(["a", "b"]) == ["a", "b"]


def test_convert_to_list_tuple():
    assert convert_to_list(("a", "b")) == ["a", "b"]


def test_convert_to_list_int():
    assert convert_to_list(5) == [5]


# ---------------------------------------------------------------------------
# validate_not_empty
# ---------------------------------------------------------------------------

def _make_wrapped():
    """Helper: a simple function wrapped by validate_not_empty."""
    @validate_not_empty
    def process(self_dummy, files):
        return files
    return process


def test_validate_not_empty_empty_list(caplog):
    process = _make_wrapped()
    with caplog.at_level(logging.WARNING):
        result = process(None, [])
    assert result == []
    assert "Empty file list" in caplog.text


def test_validate_not_empty_none(caplog):
    process = _make_wrapped()
    with caplog.at_level(logging.WARNING):
        result = process(None, None)
    assert result == []


def test_validate_not_empty_calls_function():
    process = _make_wrapped()
    result = process(None, ["file.txt"])
    assert result == ["file.txt"]


def test_validate_not_empty_preserves_name():
    @validate_not_empty
    def my_special_function(self_dummy, files):
        return files

    assert my_special_function.__name__ == "my_special_function"
