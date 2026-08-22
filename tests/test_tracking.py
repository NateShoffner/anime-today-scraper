import pytest

from scraper import Scraper

USERNAME = "animetoday"


@pytest.fixture
def scraper(tmp_path):
    return Scraper(USERNAME, str(tmp_path))


def test_processed_ids_are_exact(scraper, make_post):
    make_post("aaa", month=1, day=1)
    make_post("bbb", month=1, day=2)

    assert scraper.get_processed_ids() == {"aaa", "bbb"}


def test_other_users_posts_are_not_counted_as_processed(scraper, make_post):
    make_post("aaa", month=1, day=1)
    make_post("bbb", month=1, day=2, username="someone_else")

    assert scraper.get_processed_ids() == {"aaa"}


def test_a_gap_inside_the_stored_range_is_not_processed(scraper, make_post):
    """The old check asked whether created_utc fell between oldest and newest.

    A run interrupted partway leaves posts missing from the middle of that range,
    and the range check called them processed forever. Membership by id has no
    such hole.
    """
    make_post("oldest", month=1, day=1, year=2023)
    make_post("newest", month=1, day=1, year=2025)

    processed = scraper.get_processed_ids()

    assert processed == {"oldest", "newest"}
    assert "missing_middle" not in processed


def test_empty_database_has_nothing_processed(scraper, db):
    assert scraper.get_processed_ids() == set()


def test_index_ignores_files_that_are_not_images(scraper, tmp_path):
    (tmp_path / "01_01.jpg").touch()
    (tmp_path / "01_02.png").touch()
    (tmp_path / "data.json").touch()
    (tmp_path / "notes.txt").touch()

    assert scraper.index_existing_images(str(tmp_path)) == {"01_01.jpg", "01_02.png"}


def test_index_is_case_insensitive_about_the_extension(scraper, tmp_path):
    (tmp_path / "01_01.JPG").touch()

    assert scraper.index_existing_images(str(tmp_path)) == {"01_01.JPG"}


@pytest.mark.parametrize(
    "present, expected",
    [
        ({"01_01.jpg"}, "01_01.jpg"),
        ({"01_01.png"}, "01_01.png"),
        ({"01_01.gif"}, "01_01.gif"),
        ({"01_01.png", "01_01.jpg"}, "01_01.jpg"),
        ({"01_02.jpg"}, None),
        (set(), None),
    ],
)
def test_find_existing_image(scraper, present, expected):
    assert scraper.find_existing_image(present, "01_01") == expected
