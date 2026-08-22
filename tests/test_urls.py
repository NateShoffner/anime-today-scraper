import pytest

from scraper import Scraper


@pytest.fixture
def scraper(tmp_path):
    return Scraper("animetoday", str(tmp_path))


@pytest.mark.parametrize(
    "media_url, expected",
    [
        ("https://i.imgur.com/abc.jpg", ["https://i.imgur.com/abc.jpg"]),
        ("https://i.imgur.com/abc.png", ["https://i.imgur.com/abc.png"]),
        # imgur's typo'd extension still serves the real jpeg
        ("https://i.imgur.com/abc.jpgg", ["https://i.imgur.com/abc.jpgg"]),
    ],
)
def test_most_posts_are_a_single_download(scraper, media_url, expected):
    assert scraper.get_download_urls(media_url) == expected


def test_a_gifv_expands_to_the_gif_and_the_mp4(scraper):
    """The .gifv url itself answers with an html player page, not media."""
    assert scraper.get_download_urls("https://i.imgur.com/dgeA9FH.gifv") == [
        "https://i.imgur.com/dgeA9FH.gif",
        "https://i.imgur.com/dgeA9FH.mp4",
    ]


def test_gifv_matching_is_case_insensitive(scraper):
    assert scraper.get_download_urls("https://i.imgur.com/abc.GIFV") == [
        "https://i.imgur.com/abc.gif",
        "https://i.imgur.com/abc.mp4",
    ]


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://i.imgur.com/abc.jpg", "file"),
        ("https://i.imgur.com/abc.gif", "file"),
        ("https://i.imgur.com/abc.webp", "file"),
        ("https://i.imgur.com/abc.mp4", "video"),
        ("https://i.imgur.com/abc.MP4", "video"),
    ],
)
def test_the_slot_a_url_fills(scraper, url, expected):
    assert scraper.get_slot(url) == expected


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"\xff\xd8\xff\xe0 rest", "jpg"),
        (b"\x89PNG\r\n\x1a\n rest", "png"),
        (b"GIF87a rest", "gif"),
        (b"GIF89a rest", "gif"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", "webp"),
        (b"\x00\x00\x00\x18ftypisom rest", "mp4"),
        (b"<!DOCTYPE html>", None),
        (b"", None),
    ],
)
def test_sniff_extension(scraper, data, expected):
    assert scraper.sniff_extension(data) == expected
