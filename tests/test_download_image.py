import asyncio

import pytest

import scraper as scraper_module
from scraper import Scraper


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

    def install(status=200, body=b"image-bytes"):
        def session_factory(headers=None):
            record["headers"] = headers
            return FakeSession(FakeResponse(status, body), record)

        monkeypatch.setattr(scraper_module.aiohttp, "ClientSession", session_factory)
        return record

    return install


@pytest.fixture
def post(make_post):
    return make_post("aaa", month=1, day=1)


def test_sends_a_user_agent(tmp_path, fake_http, post):
    record = fake_http()
    scraper = Scraper("animetoday", str(tmp_path), user_agent="script:post-scraper")
    target = tmp_path / "01_01.jpg"

    assert asyncio.run(scraper.download_image(post, str(target))) == str(target)

    # imgur answers the default aiohttp user agent with an empty 429
    assert record["headers"] == {"User-Agent": "script:post-scraper"}
    assert record["url"] == post.media_url
    assert target.read_bytes() == b"image-bytes"


@pytest.mark.parametrize("status", [403, 429, 500])
def test_no_file_is_written_for_a_failed_response(tmp_path, fake_http, post, status):
    fake_http(status=status, body=b"")
    scraper = Scraper("animetoday", str(tmp_path))
    target = tmp_path / "01_01.jpg"

    assert asyncio.run(scraper.download_image(post, str(target))) is None
    assert not target.exists()


def test_no_file_is_written_for_an_empty_body(tmp_path, fake_http, post):
    fake_http(status=200, body=b"")
    scraper = Scraper("animetoday", str(tmp_path))
    target = tmp_path / "01_01.jpg"

    assert asyncio.run(scraper.download_image(post, str(target))) is None
    assert not target.exists()


@pytest.mark.parametrize(
    "body, expected",
    [
        (b"\xff\xd8\xff\xe0 jpeg", "01_01.jpg"),
        (b"\x89PNG\r\n\x1a\n png", "01_01.png"),
        (b"GIF89a gif", "01_01.gif"),
        (b"who knows", "01_01.jpg"),
    ],
)
def test_the_extension_comes_from_the_bytes(tmp_path, fake_http, post, body, expected):
    """Imgur serves png content from .jpg links, so the url cannot be trusted."""
    fake_http(status=200, body=body)
    scraper = Scraper("animetoday", str(tmp_path))

    written = asyncio.run(scraper.download_image(post, str(tmp_path / "01_01.jpg")))

    assert written == str(tmp_path / expected)
    assert (tmp_path / expected).read_bytes() == body


def test_an_existing_file_is_not_downloaded_again(tmp_path, fake_http, post):
    record = fake_http()
    scraper = Scraper("animetoday", str(tmp_path))
    target = tmp_path / "01_01.jpg"
    target.write_bytes(b"already here")

    assert asyncio.run(scraper.download_image(post, str(target))) == str(target)
    assert record == {}
    assert target.read_bytes() == b"already here"
