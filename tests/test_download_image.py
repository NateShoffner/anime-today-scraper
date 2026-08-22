import asyncio

import pytest

import scraper as scraper_module
from scraper import Scraper

JPEG = b"\xff\xd8\xff\xe0 jpeg body"
PNG = b"\x89PNG\r\n\x1a\n png body"
GIF = b"GIF89a gif body"
WEBP = b"RIFF\x00\x00\x00\x00WEBP vp8 body"
MP4 = b"\x00\x00\x00\x18ftypmp42 video body"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    def __init__(self, response, record):
        self._response = response
        self._record = record

    def get(self, url):
        self._record["url"] = url
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def fake_http(monkeypatch):
    """Stand in for aiohttp. Returns the record of what the scraper sent."""
    record = {}

    def install(status=200, body=JPEG):
        def session_factory(headers=None):
            record["headers"] = headers
            return FakeSession(FakeResponse(status, body), record)

        monkeypatch.setattr(scraper_module.aiohttp, "ClientSession", session_factory)
        return record

    return install


URL = "https://i.imgur.com/abc123.jpg"


def test_sends_a_user_agent(tmp_path, fake_http):
    record = fake_http()
    scraper = Scraper("animetoday", str(tmp_path), user_agent="script:post-scraper")
    target = tmp_path / "01_01.jpg"

    assert asyncio.run(scraper.download_image(URL, str(target))) == str(target)

    # imgur answers the default aiohttp user agent with an empty 429
    assert record["headers"] == {"User-Agent": "script:post-scraper"}
    assert record["url"] == URL
    assert target.read_bytes() == JPEG


@pytest.mark.parametrize("status", [403, 429, 500])
def test_no_file_is_written_for_a_failed_response(tmp_path, fake_http, status):
    fake_http(status=status, body=b"")
    scraper = Scraper("animetoday", str(tmp_path))
    target = tmp_path / "01_01.jpg"

    assert asyncio.run(scraper.download_image(URL, str(target))) is None
    assert not target.exists()


def test_no_file_is_written_for_an_empty_body(tmp_path, fake_http):
    fake_http(status=200, body=b"")
    scraper = Scraper("animetoday", str(tmp_path))
    target = tmp_path / "01_01.jpg"

    assert asyncio.run(scraper.download_image(URL, str(target))) is None
    assert not target.exists()


@pytest.mark.parametrize(
    "body, expected",
    [
        (JPEG, "01_01.jpg"),
        (PNG, "01_01.png"),
        (GIF, "01_01.gif"),
        (WEBP, "01_01.webp"),
        (MP4, "01_01.mp4"),
    ],
)
def test_the_extension_comes_from_the_bytes(tmp_path, fake_http, body, expected):
    """Imgur serves png content from .jpg links, so the url cannot be trusted."""
    fake_http(status=200, body=body)
    scraper = Scraper("animetoday", str(tmp_path))

    written = asyncio.run(scraper.download_image(URL, str(tmp_path / "01_01.jpg")))

    assert written == str(tmp_path / expected)
    assert (tmp_path / expected).read_bytes() == body


def test_content_that_is_not_media_is_refused(tmp_path, fake_http):
    """A .gifv link answers with an html player page, not media."""
    fake_http(status=200, body=b"<!DOCTYPE html><html>imgur player</html>")
    scraper = Scraper("animetoday", str(tmp_path))

    assert asyncio.run(scraper.download_image(URL, str(tmp_path / "01_01.gifv"))) is None
    assert list(tmp_path.iterdir()) == []


def test_an_existing_file_is_not_downloaded_again(tmp_path, fake_http):
    record = fake_http()
    scraper = Scraper("animetoday", str(tmp_path))
    target = tmp_path / "01_01.jpg"
    target.write_bytes(b"already here")

    assert asyncio.run(scraper.download_image(URL, str(target))) == str(target)
    assert record == {}
    assert target.read_bytes() == b"already here"
