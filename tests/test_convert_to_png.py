import os

import pytest
from PIL import Image

from scraper import Scraper, get_permalink


@pytest.fixture
def scraper(tmp_path):
    return Scraper("animetoday", str(tmp_path))


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("01_01.jpg", "01_01.png"),
        ("01_01.jpeg", "01_01.png"),
        ("01_01.gif", "01_01.png"),
        ("01_01.png", "01_01.png"),
        (os.path.join("data", "bulk", "01_01.jpg"), os.path.join("data", "bulk", "01_01.png")),
    ],
)
def test_get_png_filename_handles_any_extension(scraper, filename, expected):
    assert scraper.get_png_filename(filename) == expected


@pytest.mark.parametrize("extension", ["jpg", "jpeg", "gif"])
def test_convert_to_png_replaces_the_source_file(scraper, tmp_path, extension):
    source = tmp_path / f"01_01.{extension}"
    Image.new("RGB", (4, 4), (10, 20, 30)).save(source)

    scraper.convert_to_png(str(source))

    converted = tmp_path / "01_01.png"
    assert converted.exists()
    assert not source.exists()
    with Image.open(converted) as img:
        assert img.format == "PNG"


def test_convert_to_png_leaves_an_existing_png_alone(scraper, tmp_path):
    source = tmp_path / "01_01.png"
    Image.new("RGB", (4, 4), (10, 20, 30)).save(source)
    before = source.read_bytes()

    scraper.convert_to_png(str(source))

    assert source.read_bytes() == before


def test_convert_to_png_keeps_the_source_when_conversion_fails(scraper, tmp_path):
    source = tmp_path / "01_01.jpg"
    source.write_text("not an image")

    scraper.convert_to_png(str(source))

    assert source.exists()
    assert not (tmp_path / "01_01.png").exists()


def test_get_permalink_prefixes_the_reddit_host():
    class Submission:
        permalink = "/r/anime/comments/abc123/"

    assert (
        get_permalink(Submission())
        == "https://www.reddit.com/r/anime/comments/abc123/"
    )
