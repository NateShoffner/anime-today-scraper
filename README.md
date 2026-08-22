Anime Today Scraper
====================

Simple Reddit bot that scrapes every image posted by /u/AnimeToday, along with the
anime source title that the account posts as a comment on each one.

Scuffed wip

Setup
-----

Requires Python 3.10+ and Poetry.

    poetry install

Copy `.env.default` to `.env` and fill in credentials for a script-type app registered
at https://www.reddit.com/prefs/apps:

    REDDIT_CLIENT_ID=
    REDDIT_CLIENT_SECRET=

Usage
-----

Run from the repository root, since the output paths are relative to the working
directory:

    poetry run python src/main.py

Each run fetches posts newer or older than what has already been seen, records them in
`data/media_posts.db`, then writes the images out to disk. Images that are already
downloaded are left alone, so re-running is cheap. Delete the database to force a full
re-scrape.

Tests
-----

    poetry run pytest

The suite runs against an in-memory database with the image download stubbed out, so it
needs no credentials and makes no network calls.

Output
------

    data/
      media_posts.db
      bulk/
        01_01.jpg
        01_02.png
        ...
        data.json

Images are named by month and day and kept in whatever format the post used, so the
extension varies. `data.json` holds the caption and the filename for each date:

    {
        "01_01": {
            "comment": "Anime Source Title",
            "file": "01_01.jpg"
        }
    }

`file` is null if the image could not be downloaded.

Nothing under `data/` is committed.
