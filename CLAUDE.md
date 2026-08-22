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

Both phases skip work they have already done, and both track it exactly rather than by
proxy:

- `get_processed_ids` loads every stored submission id in one query. `MediaPost.id` is
  the reddit id, so membership is exact and costs nothing per post. Newly created rows
  are added to the set as they go, which also means a duplicate in the listing cannot
  raise an integrity error mid-run.
- `index_existing_images` reads the bulk directory once into a set, and
  `find_existing_image` looks up each date against it in `IMAGE_EXTENSIONS` order.

An interrupted run therefore resumes cleanly. This replaced a check asking whether
`created_utc` fell between the oldest and newest stored rows, which treated everything
inside that window as done and so could never backfill a hole left by a run that died
partway. A full incremental render of 492 posts measures 0.04s with no network calls.

A `# TODO` in `get_posts` notes that later edits to a title or caption are still not
detected: tracking is by id, so an edited post stays skipped.

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

- `MM_DD.<ext>` per image, stored in whatever format the post used. Nothing is
  re-encoded: the sources are already lossy jpeg, so converting to png cost roughly
  310ms per image and 2.6x the disk for no quality gain.
- `data.json` mapping `"MM_DD"` to `{"comment": ..., "file": ...}`, with the surrounding
  braces stripped off the stored comment. `file` carries the basename because the
  extension now varies, and is `null` when the download failed.

The extension comes from `sniff_extension`, which reads the magic bytes rather than
trusting the url. Imgur serves png content from `.jpg` links, and at least one post in
this account's history does exactly that.

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
- `open_session` exists because a session per image pays a fresh tcp and tls handshake:
  247ms against 69ms measured over 12 real posts. `download_image` takes an optional
  session so the render pass can hold one open for the whole run.
- The "already downloaded" check must look for every extension, not one.
  `find_existing_image` takes the set from `index_existing_images` and does that, which
  is also what stops images fetched before this stopped forcing png from being
  downloaded a second time.
- `main.py` forces utf-8 on stdout. Captions contain characters cp1252 cannot encode,
  and the resulting error inside a `print` gets attributed to whatever call it
  interrupted.
- `scrape.py` at the repo root is the original single-file version, superseded by
  `src/` but still tracked.
- `data/`, `data_old*`, and `.env` are gitignored, so no scraped output is committed.
