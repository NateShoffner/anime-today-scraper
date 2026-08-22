# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Scrapes every image post from the Reddit account /u/AnimeToday. Each post is a daily
anime screenshot, and the account replies to its own post with a comment wrapped in
braces (`{Source Title}`) naming the anime the screenshot came from. This project
collects both the images and those captions.

## Commands

Poetry-managed, Python ^3.10.

```
poetry install
poetry run python src/main.py
poetry run pytest
poetry run pytest tests/test_convert_to_png.py::test_get_png_filename_handles_any_extension
```

No linter or formatter is configured, and `pyproject.toml` defines no console script
entry point.

`[tool.pytest.ini_options]` puts `src` on `sys.path`, which is what lets the tests use
the same flat imports (`from scraper import Scraper`) as the application code. Tests
never touch the network or the real database: `tests/conftest.py` binds the model proxy
to a fresh in-memory SQLite database per test, and the `downloads` fixture in
`tests/test_download_to_single_directory.py` monkeypatches `Scraper.download_image` to
write a solid-colour image instead of fetching one. Giving each post its own colour is
how a test checks *which* post's image landed on disk. `Scraper.get_posts` has no
coverage, since its scrape, classify, and persist steps are one asyncpraw-driven loop
that cannot be exercised without a Reddit fixture.

Credentials come from a `.env` at the repo root (see `.env.default`):
`REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`. It is a read-only script-type Reddit
app, so there is no refresh token or user login.

**Run from the repo root.** `src/main.py` resolves `data_dir` as the relative path
`"data"`, so the working directory decides where the database and images land. The
modules under `src/` import each other flat (`from db import ...`), which works
because Python puts the entry script's own directory on `sys.path`.

## Architecture

Two phases, deliberately decoupled by a SQLite database at `data/media_posts.db`:

1. **Scrape** (`Scraper.get_posts`) walks the user's submissions via asyncpraw and
   writes one `MediaPost` row per post. Nothing touches the filesystem here except
   the database.
2. **Render** (`Scraper.download_to_single_directory`) reads those rows back and
   materializes them as files.

Because the database is the intermediate, the on-disk layout can be changed and
re-rendered without hitting Reddit's API again. Deleting `data/media_posts.db` forces
a full re-scrape.

`src/db.py` uses a peewee `DatabaseProxy` so `models.py` can declare `MediaPost`
without importing a concrete database, and `main.py` binds the real `SqliteDatabase`
at startup.

### Incremental scraping

`get_posts` skips a submission when its `created_utc` falls *between* the oldest and
newest rows already stored. That is a range check, not a set-membership check, so it
picks up posts newer or older than the known window but will never backfill a gap
inside it. A `# TODO` in the same function notes that later edits to a title or
caption are not detected either.

### Post classification

Every submission is stored, with two boolean flags:

- `malformed_title` when the title contains no month name, no weekday name, and not
  the word "today".
- `non_media_post` when the URL does not end in jpg/jpeg/png/gif.

The comment lookup costs one extra API call per post and sleeps 1s to stay under rate
limits, so it only runs for posts that pass both checks. The render phase filters out
`non_media_post` rows, which is what keeps gifv, gfycat and typo'd `.jpgg` links from
being downloaded and then failing to convert. It does not filter on `malformed_title`,
since those posts still carry a usable image.

### Output layout

`download_to_single_directory` writes a flat `data/bulk/`:

- `MM_DD.png` per image, converted from the downloaded original via Pillow. The source
  file is deleted after a successful convert.
- `data.json` mapping `"MM_DD"` to `{"comment": ...}`, with the surrounding braces
  stripped off the stored comment.

Keys are month and day only, so posts from the same calendar date in different years
collide. Posts are iterated newest-first and the first post seen for a date claims it,
so both the image and the caption come from the newest post and older duplicates are
discarded outright. Keep that first-wins rule intact when touching this loop: an
earlier version recorded the caption on every iteration, which left the image from the
newest post paired with the caption from the oldest.

`download_to_organized_directories` is the previous layout
(`data/MM_Month/DD/<post_id>.png` plus a sibling `.txt` caption). It still works but
is no longer called by `run()`. The `data/` tree checked out locally is in this older
format.

## Known landmines

- Imgur, which hosts most of this account's older posts, answers aiohttp's default user
  agent with an empty `429`. `download_image` sends `self.user_agent` for that reason.
  Dropping the header does not raise, it silently yields empty files.
- A source file that never converts must not be left on disk. `download_image` returns
  early when the source exists while the caller only checks for the png, so a leftover
  corrupt source is never re-downloaded and never converts, on every future run.
- `main.py` forces utf-8 on stdout. Captions contain characters cp1252 cannot encode,
  and the resulting error inside a `print` gets attributed to whatever call it
  interrupted.
- `scrape.py` at the repo root is the original single-file version, superseded by
  `src/` but still tracked.
- `data/`, `data_old*`, and `.env` are gitignored, so no scraped output is committed.
