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
poetry run pytest
poetry run pytest tests/test_urls.py::test_sniff_extension
$(poetry env info --path)/Scripts/python.exe src/main.py
LOG_LEVEL=DEBUG $(poetry env info --path)/Scripts/python.exe src/main.py
```

**Do not time a run through `poetry run`.** `poetry run python -c "pass"` measures 13.3s
on this machine, against 0.1s for the venv interpreter directly. That overhead dwarfs
the entire incremental run and has repeatedly made the scraper look slow when it was
not: 22.5s through `poetry run`, 7s without. Use `poetry run` for pytest, where a few
seconds do not matter, and the interpreter path for anything you are measuring.

No linter or formatter is configured, and `pyproject.toml` defines no console script
entry point.

`[tool.pytest.ini_options]` puts `src` on `sys.path`, which is what lets the tests use
the same flat imports (`from scraper import Scraper`) as the application code. Tests
never touch the network or the real database: `tests/conftest.py` binds the model proxy
to a fresh in-memory SQLite database per test, and the `downloads` fixture in
`tests/test_download_to_single_directory.py` monkeypatches `Scraper.download_image` to
write a solid-colour image instead of fetching one. Giving each post its own colour is
how a test checks *which* post's image landed on disk. `tests/test_get_posts.py` fakes
the asyncpraw listings, so classification, caption assignment and the deferred caption
fetch are all covered without a network call.

Logging goes through the standard library. `main.py` calls `basicConfig` and honours
`LOG_LEVEL`; per-post chatter is at DEBUG and everything else at INFO, so a normal run
prints a handful of lines rather than one per post.

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

### Fetching captions in bulk

`get_captions` reads the account's own comment listing, 100 per request, and keys the
braced captions by `link_id`. That covers 499 of 500 posts here. The alternative, and
what this replaced, is `submission.load()` plus a comment walk per post, one api call
each with a 1s sleep to stay under Reddit's 100/minute limit. A cold scrape went from
roughly ten minutes to 13.7s.

`get_first_comment` is the remaining slow path, for posts the listing does not reach:
Reddit caps that listing at 1000 comments, which currently reaches back to 2021-11.

The listing walk is deferred until the first unprocessed submission appears, because an
incremental run normally finds nothing new and would otherwise pay 5s for a caption map
it never reads.

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
- `non_media_post` when the url's path carries no file extension at all. That is a
  deliberately loose test: the downloaded bytes decide what a response really is, so a
  mislabelled url costs nothing, while bare links like `gfycat.com/SomeSlug` are
  rejected before any request. Tightening this to a fixed extension list is what
  previously threw away imgur's typo'd `.jpgg` links, which serve ordinary jpegs.

Captions are taken from the bulk listing for every post regardless of flags, since a
dict lookup is free. Only the slow per-post fallback is still gated, and only for posts
unlikely to have a caption at all.

The render phase filters out `non_media_post` rows and nothing else. It does not filter
on `malformed_title`, since a typo'd title like "Junly 1st" still carries a real image
and a real caption.

### Output layout

Downloads run concurrently under a `DOWNLOAD_CONCURRENCY` semaphore. `plan_downloads`
does the claiming sequentially first, because the newest-post-per-date rule depends on
iteration order, and returns a flat work list whose fetches are independent. A failure
inside one fetch is caught there so it cannot cancel the rest of the batch.

`download_to_single_directory` writes a flat `data/bulk/`:

- `MM_DD.<ext>` per image, stored in whatever format the post used. Nothing is
  re-encoded: the sources are already lossy jpeg, so converting to png cost roughly
  310ms per image and 2.6x the disk for no quality gain.
- `MM_DD.mp4` alongside it for the handful of posts that were `.gifv`.
- `data.json` mapping `"MM_DD"` to `{"comment": ..., "file": ..., "video": ...}`, with
  the surrounding braces stripped off the stored comment. `file` and `video` carry
  basenames because the extension varies, and are `null` when absent.

The extension comes from `sniff_extension`, which reads magic bytes and returns None
for anything else, so a response that is not media is refused rather than written. Urls
lie in both directions here: imgur serves png content from `.jpg` links, and a `.gifv`
link returns an html player page. `get_download_urls` rewrites a `.gifv` into its `.gif`
and `.mp4` siblings, which are both real; the mp4 runs about a seventeenth of the gif's
size.

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

## Timings

Measured against this account, 500 posts and 365 dated images:

| | cold, nothing stored | incremental, nothing new |
|---|---|---|
| scrape | 13.7s | ~6s |
| download | ~27s (126 MB) | 0.04s |
| total | **41s** | **7s** |

The incremental case is now dominated by walking the submissions listing, about five
api calls. Before any of this, a cold run took roughly fifteen minutes.

These are measured with the venv interpreter. Add ~13s to every figure if invoked
through `poetry run`.

The asyncpraw clients pass `check_for_updates=False`. Otherwise every run makes a pypi
round trip and writes the result straight to stderr, producing the one console line
with no timestamp on it.

## Maintenance

`backfill_comments` fetches captions for stored posts that have none, and is
deliberately not wired into `run()`: a post whose caption is genuinely absent stays
null, so running it every time would re-request those forever. It exists for the case
where a post was stored under a classification that skipped the comment lookup and
later turned out to be media. Widening the `non_media_post` rule is exactly that case,
and needs the stored flag recomputed for existing rows, since id tracking means those
posts are never scraped again. It uses the same bulk caption listing as `get_posts` and
only falls back to the per-post lookup for what the listing misses.

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
