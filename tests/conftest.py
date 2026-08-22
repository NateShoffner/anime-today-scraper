import datetime

import pytest
from peewee import SqliteDatabase

from db import database_proxy
from models import MediaPost

USERNAME = "animetoday"


@pytest.fixture
def db():
    """Bind the model proxy to a throwaway in-memory database."""
    database = SqliteDatabase(":memory:")
    database_proxy.initialize(database)
    database.connect()
    database.create_tables([MediaPost])
    yield database
    database.close()


@pytest.fixture
def make_post(db):
    def _make_post(
        post_id,
        month,
        day,
        year=2024,
        comment="{Some Anime}",
        extension="jpg",
        username=USERNAME,
    ):
        created = datetime.datetime(
            year, month, day, 12, 0, tzinfo=datetime.timezone.utc
        )
        return MediaPost.create(
            id=post_id,
            username=username,
            title=f"{created:%B} {day} today",
            permalink=f"https://www.reddit.com/r/anime/comments/{post_id}/",
            media_url=f"https://i.redd.it/{post_id}.{extension}",
            created_utc=int(created.timestamp()),
            first_comment=comment,
        )

    return _make_post
