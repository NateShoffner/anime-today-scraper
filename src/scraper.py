import asyncio
from calendar import month_name, day_name
from contextlib import AsyncExitStack
import datetime
import json
import aiohttp
import os
import asyncpraw
from dotenv import load_dotenv
from urllib.parse import urlparse
from PIL import Image
from models import MediaPost

load_dotenv()


IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "gif", "webp")
VIDEO_EXTENSIONS = ("mp4",)
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS + VIDEO_EXTENSIONS


def get_permalink(submission: asyncpraw.models.Submission) -> str:
    return f"https://www.reddit.com{submission.permalink}"


class Scraper:
    def __init__(
        self, username: str, data_dir="data", user_agent: str = "script:post-scraper"
    ):
        self.username = username
        self.data_dir = data_dir
        self.user_agent = user_agent

    async def run(self):
        await self.get_posts()
        await self.download_to_single_directory()

    async def download_media(self):
        """Download all media posts from the target user"""
        for post in MediaPost.select().where(MediaPost.username == self.username):
            await self.download_image(post.media_url, self.data_dir)

    def get_download_urls(self, media_url: str) -> list:
        """The urls to fetch for a post.

        An imgur .gifv link serves an html player page rather than media, but the
        same id serves a real .gif and a .mp4. Both are kept: the gif is the
        image, the mp4 is the same thing at roughly a seventeenth of the size.
        """
        root, extension = os.path.splitext(urlparse(media_url).path)
        if extension.lower() == ".gifv":
            base = media_url[: -len(extension)]
            return [f"{base}.gif", f"{base}.mp4"]
        return [media_url]

    def open_session(self) -> aiohttp.ClientSession:
        """One session serves every download.

        A session per image pays a fresh tcp and tls handshake each time, which
        measured at 218ms against 73ms shared. The user agent matters too: imgur
        answers aiohttp's default with an empty 429.
        """
        return aiohttp.ClientSession(headers={"User-Agent": self.user_agent})

    def sniff_extension(self, data: bytes):
        """The format of the bytes, or None if it is not media we handle.

        Urls lie in both directions: imgur serves png content from .jpg links,
        and a .gifv link returns an html page. Deciding from the content means a
        mislabelled url costs nothing and a non-media response is never written.
        """
        if data.startswith(b"\xff\xd8\xff"):
            return "jpg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return "gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "webp"
        if data[4:8] == b"ftyp":
            return "mp4"
        return None

    def index_existing_images(self, directory: str) -> set:
        """The bulk directory listing, read once instead of stat-ing per post."""
        return {
            entry
            for entry in os.listdir(directory)
            if entry.rpartition(".")[2].lower() in MEDIA_EXTENSIONS
        }

    def find_existing_image(self, existing: set, name: str):
        """The already-downloaded image for a name, whatever extension it used."""
        for extension in IMAGE_EXTENSIONS:
            candidate = f"{name}.{extension}"
            if candidate in existing:
                return candidate
        return None

    def get_png_filename(self, filename: str) -> str:
        root, _ = os.path.splitext(filename)
        return f"{root}.png"

    def convert_to_png(self, filename: str):
        # check if the file is already a png
        if filename.endswith(".png"):
            return

        new_filename = self.get_png_filename(filename)

        try:
            with Image.open(filename) as img:
                img.save(new_filename, "PNG")
        except Exception as e:
            print(f"Error converting {filename} to PNG: {e}")
            # a partial png is worse than none, it would be mistaken for a
            # finished download on the next run
            if os.path.exists(new_filename):
                try:
                    os.remove(new_filename)
                except Exception as remove_error:
                    print(f"Error removing {new_filename}: {remove_error}")

        # the source goes either way: on success the png has replaced it, and on
        # failure it is unusable and would otherwise make download_image skip this
        # post on every future run
        try:
            os.remove(filename)
        except Exception as e:
            print(f"Error removing {filename}: {e}")

    def get_processed_ids(self) -> set:
        """Every submission id already stored.

        The primary key is the reddit submission id, so membership is exact. The
        previous check asked whether created_utc fell between the oldest and
        newest stored post, which skipped anything inside that window forever, so
        a run interrupted midway left a permanent hole.
        """
        return {
            post.id
            for post in MediaPost.select(MediaPost.id).where(
                MediaPost.username == self.username
            )
        }

    async def get_first_comment(self, submission):
        """The post's own {Anime Title} comment, or None.

        Costs one extra api call per post, hence the sleep.
        """
        print("Checking for comment...")
        # sleep to avoid rate limiting
        await asyncio.sleep(1)
        try:
            await submission.load()
            async for comment in submission.comments:
                if (
                    comment.author == self.username
                    and comment.body.startswith("{")
                    and comment.body.endswith("}")
                ):
                    print(f"Found comment: {comment.body}")
                    return comment.body
        except Exception as e:
            # TODO reddit will sometimes return a 429 error when trying to get the comments, we should retry
            print(f"Error getting comment: {e}")
        return None

    async def backfill_comments(self):
        """Fetch captions for stored posts that never got one.

        Not part of run(). A post whose caption is genuinely absent stays null,
        so calling this on every run would re-request those forever. It exists
        for the case where a post was stored under a classification that skipped
        the comment lookup and later turned out to be media after all.
        """
        missing = list(
            MediaPost.select().where(
                (MediaPost.username == self.username)
                & (MediaPost.non_media_post == False)  # noqa: E712 (peewee needs ==)
                & (MediaPost.first_comment.is_null())
            )
        )
        print(f"Backfilling comments for {len(missing)} posts")

        async with asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=self.user_agent,
        ) as reddit:
            for post in missing:
                print(f"Checking {post.title} - {post.permalink}")
                submission = await reddit.submission(post.id)
                comment = await self.get_first_comment(submission)
                if comment:
                    post.first_comment = comment
                    post.save()

    async def get_posts(self):
        """Get all posts from the target user"""
        processed_ids = self.get_processed_ids()
        print(f"Already processed: {len(processed_ids)} posts")

        async with asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=self.user_agent,
        ) as reddit:
            target_user = await reddit.redditor(self.username)

            month_names = [name.lower() for name in month_name if name]
            day_names = [name.lower() for name in day_name]

            async for submission in target_user.submissions.new(limit=None):
                # TODO account for possible updates to the post title and/or first comment

                if submission.id in processed_ids:
                    print(f"Post already processed: {submission.title}")
                    continue

                title = submission.title.lower()

                malformed_title = False
                non_media_post = False
                submission_comment = None

                if (
                    not any(month in title for month in month_names)
                    and not any(day in title for day in day_names)
                    and "today" not in title
                ):
                    malformed_title = True

                # the url only has to look like a file, the downloaded bytes
                # decide what it actually is. this accepts imgur's typo'd .jpgg
                # and its .gifv player links while still rejecting bare links
                # like gfycat.com/SomeSlug that carry no media at all
                if not os.path.splitext(urlparse(submission.url).path)[1]:
                    print(f"Skipping {submission.title} because it's not an image")
                    non_media_post = True

                if not malformed_title and not non_media_post:
                    submission_comment = await self.get_first_comment(submission)

                processed_ids.add(submission.id)
                MediaPost.create(
                    username=submission.author.name,
                    title=submission.title,
                    id=submission.id,
                    permalink=get_permalink(submission),
                    media_url=submission.url,
                    created_utc=submission.created_utc,
                    first_comment=submission_comment,
                    malformed_title=malformed_title,
                    non_media_post=non_media_post,
                )

    async def download_to_single_directory(self):
        posts = (
            MediaPost.select()
            .where(
                (MediaPost.username == self.username)
                & (MediaPost.non_media_post == False)  # noqa: E712 (peewee needs ==)
            )
            .order_by(MediaPost.created_utc.desc())
        )

        bulk_dir = os.path.join(self.data_dir, "bulk")
        if not os.path.exists(bulk_dir):
            os.makedirs(bulk_dir)

        posts_data = {}

        existing = self.index_existing_images(bulk_dir)
        print(f"Already downloaded: {len(existing)} images")

        async with self.open_session() as session:
            await self.download_posts(posts, bulk_dir, posts_data, session, existing)

        with open(os.path.join(bulk_dir, "data.json"), "w") as f:
            f.write(json.dumps(posts_data, indent=4))

    def get_slot(self, url: str) -> str:
        """Which data.json field a url is expected to fill."""
        extension = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
        return "video" if extension in VIDEO_EXTENSIONS else "file"

    async def download_posts(self, posts, bulk_dir, posts_data, session, existing):
        """Fill posts_data and the bulk directory, newest post per date wins."""
        for submission in posts:
            print(f"Processing {submission.title} - {submission.permalink}")

            comment = ""
            if submission.first_comment:
                # remove '{' at the beginning and '}' at the end
                comment = submission.first_comment[1:-1].strip()

            submission_date = datetime.datetime.utcfromtimestamp(submission.created_utc)
            submission_month = submission_date.strftime("%m")
            submission_day = submission_date.strftime("%d")
            date_key = f"{submission_month}_{submission_day}"

            # posts are ordered newest first, so the first one seen for a given
            # date wins and older posts for that same date are discarded
            if date_key in posts_data:
                print(f"Skipping {submission.title} because {date_key} is already taken")
                continue

            # a previous run may have stored this date under another extension
            video = f"{date_key}.mp4" if f"{date_key}.mp4" in existing else None
            posts_data[date_key] = {
                "comment": comment,
                "file": self.find_existing_image(existing, date_key),
                "video": video,
            }

            wanted = [
                url
                for url in self.get_download_urls(submission.media_url)
                if not posts_data[date_key][self.get_slot(url)]
            ]
            if not wanted:
                print(f"Skipping {submission.title} because it's already downloaded")
                continue

            for url in wanted:
                requested = f"{date_key}{os.path.splitext(urlparse(url).path)[1]}"
                downloaded = await self.download_image(
                    url, os.path.join(bulk_dir, requested), session
                )
                if not downloaded:
                    continue

                name = os.path.basename(downloaded)
                existing.add(name)
                slot = "video" if name.rpartition(".")[2] in VIDEO_EXTENSIONS else "file"
                posts_data[date_key][slot] = name

    async def download_to_organized_directories(self):
        posts = MediaPost.select().where(MediaPost.username == self.username)

        for submission in posts:
            print(f"Processing {submission.title} - {submission.permalink}")

            submission_date = datetime.datetime.utcfromtimestamp(submission.created_utc)
            submission_month = submission_date.strftime("%m_%B")

            submission_month_dir = os.path.join(self.data_dir, submission_month)
            if not os.path.exists(submission_month_dir):
                os.makedirs(submission_month_dir)

            submission_day = submission_date.strftime("%d")
            day_dir = os.path.join(submission_month_dir, submission_day)
            if not os.path.exists(day_dir):
                os.makedirs(day_dir)

            extension = submission.media_url.split(".")[-1]
            image_filename = os.path.join(day_dir, submission.id)
            image_filename = f"{image_filename}.{extension}"
            downloaded = await self.download_image(submission.media_url, image_filename)
            if downloaded:
                self.convert_to_png(downloaded)

            # save the comment to a file
            if submission.first_comment:
                comment_filename = os.path.join(day_dir, f"{submission.id}.txt")
                with open(comment_filename, "w", encoding="utf-8") as f:
                    f.write(submission.first_comment)

    async def download_image(self, media_url: str, filename: str, session=None):
        """Download one url, returning the path written or None on failure.

        The extension of the returned path is taken from the downloaded bytes,
        so it can differ from the one requested, and content that is not media we
        handle is refused rather than written. Passing a session reuses its
        connection pool; without one a throwaway session is opened per call.
        """
        if os.path.exists(filename):
            return filename

        async with AsyncExitStack() as stack:
            if session is None:
                session = await stack.enter_async_context(self.open_session())

            async with session.get(media_url) as response:
                if response.status != 200:
                    print(f"Error downloading {media_url}: HTTP {response.status}")
                    return None

                image_data = await response.read()

        if not image_data:
            print(f"Error downloading {media_url}: empty response")
            return None

        extension = self.sniff_extension(image_data)
        if extension is None:
            print(f"Error downloading {media_url}: not media we handle")
            return None

        filename = f"{os.path.splitext(filename)[0]}.{extension}"

        with open(filename, "wb") as image_file:
            image_file.write(image_data)

        return filename
