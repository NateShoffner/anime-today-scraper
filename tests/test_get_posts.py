import asyncio
import datetime

import pytest

import scraper as scraper_module
from models import MediaPost
from scraper import Scraper

USERNAME = "animetoday"


class FakeAuthor:
    def __init__(self, name):
        self.name = name


class FakeSubmission:
    def __init__(self, post_id, title, url, year=2024, month=1, day=1):
        self.id = post_id
        self.title = title
        self.url = url
        self.author = FakeAuthor(USERNAME)
        self.permalink = f"/r/AnimeCalendar/comments/{post_id}/"
        self.created_utc = datetime.datetime(
            year, month, day, 12, tzinfo=datetime.timezone.utc
        ).timestamp()


class FakeComment:
    def __init__(self, submission_id, body):
        self.link_id = f"t3_{submission_id}"
        self.body = body


class FakeListing:
    """Records how many times the listing was actually walked."""

    def __init__(self, items, counter, key):
        self._items = items
        self._counter = counter
        self._key = key

    def new(self, limit=None):
        self._counter[self._key] += 1

        async def iterator():
            for item in self._items:
                yield item

        return iterator()


class FakeRedditor:
    def __init__(self, submissions, comments, counter):
        self.submissions = FakeListing(submissions, counter, "submissions")
        self.comments = FakeListing(comments, counter, "comments")


class FakeReddit:
    def __init__(self, redditor):
        self._redditor = redditor

    async def redditor(self, name):
        return self._redditor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def reddit(monkeypatch):
    counter = {"submissions": 0, "comments": 0}

    def install(submissions, comments):
        redditor = FakeRedditor(submissions, comments, counter)
        monkeypatch.setattr(
            scraper_module.asyncpraw, "Reddit", lambda **kwargs: FakeReddit(redditor)
        )
        return counter

    return install


@pytest.fixture
def scraper(tmp_path):
    return Scraper(USERNAME, str(tmp_path))


def run_scrape(scraper):
    asyncio.run(scraper.get_posts())


def test_a_post_is_stored_with_its_caption(scraper, db, reddit):
    reddit(
        [FakeSubmission("aaa", "January 1st", "https://i.imgur.com/x.jpg")],
        [FakeComment("aaa", "{Cowboy Bebop}")],
    )

    run_scrape(scraper)

    post = MediaPost.get_by_id("aaa")
    assert post.first_comment == "{Cowboy Bebop}"
    assert post.media_url == "https://i.imgur.com/x.jpg"
    assert post.permalink == "https://www.reddit.com/r/AnimeCalendar/comments/aaa/"
    assert not post.malformed_title
    assert not post.non_media_post


def test_a_typod_title_still_gets_its_caption(scraper, db, reddit):
    """The caption lookup used to be skipped for these purely to save a request."""
    reddit(
        [FakeSubmission("aaa", "Junly 1st", "https://i.imgur.com/x.jpg")],
        [FakeComment("aaa", "{Hyouka}")],
    )

    run_scrape(scraper)

    post = MediaPost.get_by_id("aaa")
    assert post.malformed_title
    assert post.first_comment == "{Hyouka}"


def test_a_bare_link_is_marked_non_media(scraper, db, reddit):
    reddit(
        [FakeSubmission("aaa", "May 2nd", "https://gfycat.com/ColorfulUnnatural")],
        [],
    )

    run_scrape(scraper)

    assert MediaPost.get_by_id("aaa").non_media_post


def test_a_typod_extension_is_not_non_media(scraper, db, reddit):
    reddit(
        [FakeSubmission("aaa", "June 10th", "https://i.imgur.com/x.jpgg")],
        [FakeComment("aaa", "{Carole & Tuesday}")],
    )

    run_scrape(scraper)

    assert not MediaPost.get_by_id("aaa").non_media_post


def test_already_processed_posts_are_not_stored_twice(scraper, db, reddit, make_post):
    make_post("aaa", month=1, day=1)
    reddit([FakeSubmission("aaa", "January 1st", "https://i.imgur.com/x.jpg")], [])

    run_scrape(scraper)

    assert MediaPost.select().count() == 1


def test_the_caption_listing_is_not_walked_when_nothing_is_new(
    scraper, db, reddit, make_post
):
    """The listing walk is the most expensive thing left in this phase."""
    make_post("aaa", month=1, day=1)
    counter = reddit(
        [FakeSubmission("aaa", "January 1st", "https://i.imgur.com/x.jpg")],
        [FakeComment("aaa", "{Cowboy Bebop}")],
    )

    run_scrape(scraper)

    assert counter["submissions"] == 1
    assert counter["comments"] == 0, "captions should only be fetched when needed"


def test_the_caption_listing_is_walked_once_for_many_new_posts(scraper, db, reddit):
    counter = reddit(
        [
            FakeSubmission(f"p{i}", f"January {i}", "https://i.imgur.com/x.jpg", day=i)
            for i in range(1, 6)
        ],
        [FakeComment(f"p{i}", f"{{Anime {i}}}") for i in range(1, 6)],
    )

    run_scrape(scraper)

    assert MediaPost.select().count() == 5
    assert counter["comments"] == 1


def test_a_post_with_no_caption_anywhere_is_stored_without_one(
    scraper, db, reddit, monkeypatch
):
    """The per-post fallback runs for posts the listing did not reach."""

    async def no_slow_lookup(self, submission):
        return None

    monkeypatch.setattr(Scraper, "get_first_comment", no_slow_lookup)
    reddit([FakeSubmission("aaa", "January 1st", "https://i.imgur.com/x.jpg")], [])

    run_scrape(scraper)

    assert MediaPost.get_by_id("aaa").first_comment is None
