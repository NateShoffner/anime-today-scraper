import asyncio
from calendar import month_name, day_name
import datetime
import aiohttp
import os
import asyncpraw
from dotenv import load_dotenv
from PIL import Image
from models import MediaPost

load_dotenv()


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
        await self.download_to_organized_directories()

    async def download_media(self):
        """Download all media posts from the target user"""
        for post in MediaPost.select().where(MediaPost.username == self.username):
            await self.download_image(post, self.data_dir)

    def convert_to_png(self, filename: str):
        # check if the file is already a png
        if filename.endswith(".png"):
            return

        # convert the image to a png
        new_filename = filename.replace(".jpg", ".png")

        converted = False
        try:
            with Image.open(filename) as img:
                img.save(new_filename, "PNG")

            converted = True
        except Exception as e:
            print(f"Error converting {filename} to PNG: {e}")
            return

        if converted:
            try:
                os.remove(filename)
            except Exception as e:
                print(f"Error removing {filename}: {e}")

    async def get_posts(self):
        """Get all posts from the target user"""
        most_recent_post = (
            MediaPost.select()
            .where(MediaPost.username == self.username)
            .order_by(MediaPost.created_utc.desc())
            .first()
        )
        oldest_post = (
            MediaPost.select()
            .where(MediaPost.username == self.username)
            .order_by(MediaPost.created_utc.asc())
            .first()
        )

        print(f"Most recent post: {most_recent_post}")
        print(f"Oldest post: {oldest_post}")

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

                already_processed = False

                if most_recent_post and oldest_post:
                    already_processed = (
                        submission.created_utc <= most_recent_post.created_utc
                        and submission.created_utc >= oldest_post.created_utc
                    )

                if already_processed:
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

                if not submission.url.endswith(("jpg", "jpeg", "png", "gif")):
                    print(f"Skipping {submission.title} because it's not an image")
                    non_media_post = True

                if not malformed_title and not non_media_post:
                    print("Checking for comment...")
                    submission_comment = None
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
                                submission_comment = comment.body
                                print(f"Found comment: {submission_comment}")
                                break
                    except Exception as e:
                        # TODO reddit will sometimes return a 429 error when trying to get the comments, we should retry
                        print(f"Error getting comment: {e}")

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
            await self.download_image(submission, image_filename)
            self.convert_to_png(image_filename)

            # save the comment to a file
            if submission.first_comment:
                comment_filename = os.path.join(day_dir, f"{submission.id}.txt")
                with open(comment_filename, "w", encoding="utf-8") as f:
                    f.write(submission.first_comment)

    async def download_image(self, submission: MediaPost, filename: str):
        """Download the image to the given directory"""
        if os.path.exists(filename):
            return

        async with aiohttp.ClientSession() as session:
            async with session.get(submission.media_url) as response:
                image_data = await response.read()
                with open(filename, "wb") as image_file:
                    image_file.write(image_data)
