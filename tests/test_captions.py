import asyncio

import pytest

from scraper import Scraper


class FakeComment:
    def __init__(self, submission_id, body):
        self.link_id = f"t3_{submission_id}"
        self.body = body


class FakeListing:
    def __init__(self, comments):
        self._comments = comments

    def new(self, limit=None):
        async def iterator():
            for comment in self._comments:
                yield comment

        return iterator()


class FakeUser:
    def __init__(self, comments):
        self.comments = FakeListing(comments)


@pytest.fixture
def scraper(tmp_path):
    return Scraper("animetoday", str(tmp_path))


def test_captions_are_keyed_by_submission_id(scraper):
    user = FakeUser(
        [
            FakeComment("aaa", "{Cowboy Bebop}"),
            FakeComment("bbb", "{Steins;Gate}"),
        ]
    )

    assert asyncio.run(scraper.get_captions(user)) == {
        "aaa": "{Cowboy Bebop}",
        "bbb": "{Steins;Gate}",
    }


def test_comments_that_are_not_captions_are_ignored(scraper):
    user = FakeUser(
        [
            FakeComment("aaa", "thanks for watching"),
            FakeComment("bbb", "{Serial Experiments Lain}"),
            FakeComment("ccc", "{unclosed"),
            FakeComment("ddd", "unopened}"),
        ]
    )

    assert asyncio.run(scraper.get_captions(user)) == {
        "bbb": "{Serial Experiments Lain}"
    }


def test_the_first_caption_for_a_submission_wins(scraper):
    """The listing is newest first, so an edit or a repeat keeps the latest."""
    user = FakeUser(
        [
            FakeComment("aaa", "{Corrected Title}"),
            FakeComment("aaa", "{Older Title}"),
        ]
    )

    assert asyncio.run(scraper.get_captions(user)) == {"aaa": "{Corrected Title}"}


def test_no_comments_gives_no_captions(scraper):
    assert asyncio.run(scraper.get_captions(FakeUser([]))) == {}
