import asyncio
import json

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

    async def fake_download_image(self, submission, filename):
        calls.append(filename)
        Image.new("RGB", (4, 4), colours.get(submission.id, (0, 0, 0))).save(filename)
        return True

    monkeypatch.setattr(Scraper, "download_image", fake_download_image)
    calls.colours = colours
    return calls


def bulk(tmp_path):
    return tmp_path / "bulk"


def read_data_json(tmp_path):
    return json.loads((bulk(tmp_path) / "data.json").read_text())


def test_writes_one_png_and_one_entry_per_post(scraper, tmp_path, downloads, make_post):
    make_post("aaa", month=1, day=1, comment="{Cowboy Bebop}")
    make_post("bbb", month=12, day=25, comment="{Serial Experiments Lain}")

    asyncio.run(scraper.download_to_single_directory())

    assert (bulk(tmp_path) / "01_01.png").exists()
    assert (bulk(tmp_path) / "12_25.png").exists()
    assert read_data_json(tmp_path) == {
        "01_01": {"comment": "Cowboy Bebop"},
        "12_25": {"comment": "Serial Experiments Lain"},
    }


def test_posts_without_a_comment_get_an_empty_string(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment=None)

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {"01_01": {"comment": ""}}


def test_newest_post_wins_a_duplicate_date(scraper, tmp_path, downloads, make_post):
    """Same calendar date in two years collides on the MM_DD key.

    The image and the caption must both come from the newer post, not one from
    each.
    """
    make_post("old", month=1, day=1, year=2023, comment="{Older Anime}")
    make_post("new", month=1, day=1, year=2025, comment="{Newer Anime}")
    downloads.colours.update({"old": (0, 0, 255), "new": (255, 0, 0)})

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {"01_01": {"comment": "Newer Anime"}}
    assert len(downloads) == 1

    with Image.open(bulk(tmp_path) / "01_01.png") as img:
        red, green, blue = img.convert("RGB").getpixel((0, 0))
    assert red > blue, "image should come from the newer post"


def test_existing_image_is_not_downloaded_again(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment="{Cowboy Bebop}")
    bulk(tmp_path).mkdir()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(bulk(tmp_path) / "01_01.png")

    asyncio.run(scraper.download_to_single_directory())

    assert downloads == []
    # the entry still has to be written, since data.json is rebuilt from scratch
    assert read_data_json(tmp_path) == {"01_01": {"comment": "Cowboy Bebop"}}


def test_non_media_posts_are_skipped(scraper, tmp_path, downloads, make_post):
    """gifv, gfycat links and typo'd extensions are not downloadable images."""
    make_post("aaa", month=1, day=1, extension="jpg", comment="{Cowboy Bebop}")
    junk = make_post("bbb", month=2, day=2, extension="gifv", comment="{Nope}")
    junk.non_media_post = True
    junk.save()

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {"01_01": {"comment": "Cowboy Bebop"}}
    assert len(downloads) == 1


def test_stray_whitespace_is_stripped_from_the_caption(
    scraper, tmp_path, downloads, make_post
):
    make_post("aaa", month=1, day=1, comment="{\t\nYama no Susume: Second Season}")

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {
        "01_01": {"comment": "Yama no Susume: Second Season"}
    }


def test_other_users_posts_are_ignored(scraper, tmp_path, downloads, make_post):
    make_post("aaa", month=1, day=1, username="someone_else")

    asyncio.run(scraper.download_to_single_directory())

    assert read_data_json(tmp_path) == {}
    assert downloads == []
