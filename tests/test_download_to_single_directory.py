import asyncio
import json
import os

import pytest
from PIL import Image

from scraper import Scraper

USERNAME = "animetoday"


@pytest.fixture
def scraper(tmp_path):
    return Scraper(USERNAME, str(tmp_path))


@pytest.fixture
def downloads(monkeypatch):
    """Replace the network download with one that writes a solid-colour image.

    Each post gets its own colour so a test can tell which post's image ended up
    on disk. Returns the list of filenames that were "downloaded".
    """

    class Downloads(list):
        """A list of downloaded filenames, plus the colour map keyed by post id."""

    calls = Downloads()
    colours = {}

    async def fake_download_image(self, media_url, filename, session=None):
        # mirror the real thing: the written extension comes from the content,
        # so an extension the format does not know becomes a jpg
        root, _, extension = filename.rpartition(".")
        if extension.lower() not in ("jpg", "jpeg", "png", "gif", "webp", "mp4"):
            filename = f"{root}.jpg"

        calls.append(filename)
        key = os.path.splitext(os.path.basename(media_url))[0]
        if filename.endswith(".mp4"):
            open(filename, "wb").write(b"fake mp4")
        else:
            Image.new("RGB", (4, 4), colours.get(key, (0, 0, 0))).save(filename)
        return filename

    monkeypatch.setattr(Scraper, "download_image", fake_download_image)
    calls.colours = colours
    return calls


def bulk(tmp_path):
    return tmp_path / "bulk"


def read_data_json(tmp_path):
    return json.loads((bulk(tmp_path) / "data.json").read_text())


def test_writes_one_image_and_one_entry_per_post(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment="{Cowboy Bebop}")
    make_post("bbb", month=12, day=25, comment="{Serial Experiments Lain}")

    asyncio.run(scraper.download_to_single_directory())

    assert (bulk(tmp_path) / "01_01.jpg").exists()
    assert (bulk(tmp_path) / "12_25.jpg").exists()
    assert read_data_json(tmp_path) == {
        "01_01": {"comment": "Cowboy Bebop", "file": "01_01.jpg", "video": None},
        "12_25": {
            "comment": "Serial Experiments Lain",
            "file": "12_25.jpg",
            "video": None,
        },
    }


@pytest.mark.parametrize("extension", ["jpg", "jpeg", "png", "gif", "webp"])
def test_the_source_extension_is_kept(
    scraper, tmp_path, downloads, make_post, extension
):
    """Re-encoding an already lossy source buys nothing and costs time and disk."""
    make_post("aaa", month=1, day=1, extension=extension)

    asyncio.run(scraper.download_to_single_directory())

    assert (bulk(tmp_path) / f"01_01.{extension}").exists()
    assert read_data_json(tmp_path)["01_01"]["file"] == f"01_01.{extension}"


def test_a_typod_extension_still_downloads(scraper, tmp_path, downloads, make_post):
    """Imgur serves the real jpeg from a .jpgg link, so it is not junk."""
    make_post("aaa", month=1, day=1, extension="jpgg")

    asyncio.run(scraper.download_to_single_directory())

    assert (bulk(tmp_path) / "01_01.jpg").exists()
    assert read_data_json(tmp_path)["01_01"]["file"] == "01_01.jpg"


def test_a_gifv_post_keeps_both_the_gif_and_the_mp4(
    scraper, tmp_path, downloads, make_post
):
    """A .gifv url is an html player, but the same id serves both real files."""
    make_post("aaa", month=1, day=1, extension="gifv")

    asyncio.run(scraper.download_to_single_directory())

    assert (bulk(tmp_path) / "01_01.gif").exists()
    assert (bulk(tmp_path) / "01_01.mp4").exists()
    assert read_data_json(tmp_path)["01_01"] == {
        "comment": "Some Anime",
        "file": "01_01.gif",
        "video": "01_01.mp4",
    }


def test_a_gifv_post_only_fetches_the_half_it_is_missing(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, extension="gifv")
    bulk(tmp_path).mkdir()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(bulk(tmp_path) / "01_01.gif")

    asyncio.run(scraper.download_to_single_directory())

    assert [os.path.basename(f) for f in downloads] == ["01_01.mp4"]
    assert read_data_json(tmp_path)["01_01"]["video"] == "01_01.mp4"


def test_posts_without_a_comment_get_an_empty_string(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment=None)

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path)["01_01"]["comment"] == ""


def test_newest_post_wins_a_duplicate_date(scraper, tmp_path, downloads, make_post):
    """Same calendar date in two years collides on the MM_DD key.

    The image and the caption must both come from the newer post, not one from
    each.
    """
    make_post("old", month=1, day=1, year=2023, comment="{Older Anime}")
    make_post("new", month=1, day=1, year=2025, comment="{Newer Anime}")
    downloads.colours.update({"old": (0, 0, 255), "new": (255, 0, 0)})

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path)["01_01"]["comment"] == "Newer Anime"
    assert len(downloads) == 1

    with Image.open(bulk(tmp_path) / "01_01.jpg") as img:
        red, green, blue = img.convert("RGB").getpixel((0, 0))
    assert red > blue, "image should come from the newer post"


def test_existing_image_is_not_downloaded_again(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment="{Cowboy Bebop}")
    bulk(tmp_path).mkdir()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(bulk(tmp_path) / "01_01.jpg")

    asyncio.run(scraper.download_to_single_directory())

    assert downloads == []
    # the entry still has to be written, since data.json is rebuilt from scratch
    assert read_data_json(tmp_path) == {
        "01_01": {"comment": "Cowboy Bebop", "file": "01_01.jpg", "video": None}
    }


def test_an_existing_image_under_another_extension_is_reused(
    scraper, tmp_path, downloads, make_post
):
    """Images downloaded before this stopped forcing png must not be re-fetched."""
    make_post("aaa", month=1, day=1, extension="jpg", comment="{Cowboy Bebop}")
    bulk(tmp_path).mkdir()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(bulk(tmp_path) / "01_01.png")

    asyncio.run(scraper.download_to_single_directory())

    assert downloads == []
    assert read_data_json(tmp_path)["01_01"]["file"] == "01_01.png"
    assert not (bulk(tmp_path) / "01_01.jpg").exists()


def test_a_failed_download_records_no_file(scraper, tmp_path, monkeypatch, make_post):
    make_post("aaa", month=1, day=1, comment="{Cowboy Bebop}")

    async def failed_download(self, media_url, filename, session=None):
        return None

    monkeypatch.setattr(Scraper, "download_image", failed_download)

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {
        "01_01": {"comment": "Cowboy Bebop", "file": None, "video": None}
    }


def test_non_media_posts_are_skipped(scraper, tmp_path, downloads, make_post):
    """Bare links like gfycat.com/SomeSlug carry no media at all."""
    make_post("aaa", month=1, day=1, extension="jpg", comment="{Cowboy Bebop}")
    junk = make_post("bbb", month=2, day=2, comment="{Nope}")
    junk.non_media_post = True
    junk.save()

    asyncio.run(scraper.download_to_single_directory())

    assert list(read_data_json(tmp_path)) == ["01_01"]
    assert len(downloads) == 1


def test_stray_whitespace_is_stripped_from_the_caption(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment="{\t\nYama no Susume: Second Season}")

    asyncio.run(scraper.download_to_single_directory())

    assert (
        read_data_json(tmp_path)["01_01"]["comment"] == "Yama no Susume: Second Season"
    )


def test_one_session_serves_the_whole_run(
    scraper, tmp_path, downloads, make_post, monkeypatch
):
    """A session per image pays a fresh tcp and tls handshake each time."""
    import scraper as scraper_module

    sessions = []

    class FakeSession:
        def __init__(self, headers=None):
            sessions.append(headers)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(scraper_module.aiohttp, "ClientSession", FakeSession)
    for day in (1, 2, 3):
        make_post(f"post{day}", month=1, day=day)

    asyncio.run(scraper.download_to_single_directory())

    assert len(downloads) == 3
    assert sessions == [{"User-Agent": "script:post-scraper"}]


def test_other_users_posts_are_ignored(scraper, tmp_path, downloads, make_post):
    make_post("aaa", month=1, day=1, username="someone_else")

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {}
    assert downloads == []


def test_downloads_run_concurrently(scraper, tmp_path, monkeypatch, make_post):
    """The claiming pass is ordered, but the fetches it produces are not."""
    import scraper as scraper_module

    in_flight = 0
    peak = 0

    async def slow_download(self, media_url, filename, session=None):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        open(filename, "wb").write(b"\xff\xd8\xff body")
        return filename

    monkeypatch.setattr(Scraper, "download_image", slow_download)
    for day in range(1, 13):
        make_post(f"post{day:02}", month=1, day=day)

    asyncio.run(scraper.download_to_single_directory())

    assert peak > 1, "downloads should overlap"
    assert peak <= scraper_module.DOWNLOAD_CONCURRENCY
    assert len(read_data_json(tmp_path)) == 12


def test_a_failing_download_does_not_sink_the_others(
    scraper, tmp_path, monkeypatch, make_post
):
    async def flaky(self, media_url, filename, session=None):
        if "post02" in media_url:
            raise RuntimeError("connection reset")
        open(filename, "wb").write(b"\xff\xd8\xff body")
        return filename

    monkeypatch.setattr(Scraper, "download_image", flaky)
    for day in (1, 2, 3):
        make_post(f"post{day:02}", month=1, day=day)

    asyncio.run(scraper.download_to_single_directory())

    data = read_data_json(tmp_path)
    assert data["01_01"]["file"] == "01_01.jpg"
    assert data["01_02"]["file"] is None
    assert data["01_03"]["file"] == "01_03.jpg"
