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

`poetry run` adds around 13 seconds of its own startup on top of that. To avoid it,
call the virtualenv's interpreter directly:

    $(poetry env info --path)/Scripts/python.exe src/main.py

Each run fetches whatever it has not seen before, records it in `data/media_posts.db`,
then writes the images out to disk. Posts and images already accounted for are skipped,
so re-running is cheap: a full first run takes about 40 seconds, and a run with nothing
new about 10. Delete the database to force a full re-scrape.

Set `LOG_LEVEL=DEBUG` for per-post output.

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

Images are named by month and day and kept in whatever format the post used (jpg, png,
gif or webp), so the extension varies. A few posts are imgur `.gifv` links, which are
saved as both a gif and an mp4. `data.json` holds the caption and the filenames for
each date:

    {
        "01_01": {
            "comment": "Anime Source Title",
            "file": "01_01.jpg",
            "video": null
        }
    }

`file` is null if the image could not be downloaded, and `video` is set only for the
`.gifv` posts.

Nothing under `data/` is committed.
