import asyncio
from calendar import month_name, day_name
import datetime
import json
from typing import Optional
import aiohttp
import os
import asyncpraw
import calendar
from attr import dataclass
from dotenv import load_dotenv

load_dotenv()

reddit_username = "animetoday"
data_dir = "data"
submissions_urls_file = os.path.join(data_dir, "submissions_urls.json")


@dataclass
class DailyAnimePost:
    title: str
    id: str
    permalink: str
    media_url: str
    created_utc: int
    first_comment: Optional[str]


def get_permalink(submission: asyncpraw.models.Submission) -> str:
    return f"https://www.reddit.com{submission.permalink}"


async def download_image(submission: DailyAnimePost, directory: str):
    image_filename = os.path.join(directory, submission.id)
    extension = submission.media_url.split(".")[-1]
    image_filename = f"{image_filename}.{extension}"

    if os.path.exists(image_filename):
        return

    async with aiohttp.ClientSession() as session:
        async with session.get(submission.media_url) as response:
            image_data = await response.read()
            with open(image_filename, "wb") as image_file:
                image_file.write(image_data)


async def get_submissions(reddit) -> list[DailyAnimePost]:
    """Get all daily anime posts"""

    target_user = await reddit.redditor(reddit_username)

    posts = []

    month_names = [name.lower() for name in month_name if name]
    day_names = [name.lower() for name in day_name]

    async for submission in target_user.submissions.new(limit=None):
        title = submission.title.lower()
        if (
            not any(month in title for month in month_names)
            and not any(day in title for day in day_names)
            and "today" not in title
        ):
            print(
                f"Skipping '{submission.title}' because it doesn't contain a known date indicator in the title - {get_permalink(submission)}"
            )
            continue

        if not submission.url.endswith(("jpg", "jpeg", "png", "gif")):
            print(f"Skipping {submission.title} because it's not an image")
            continue

        print("Checking for comment...")
        submission_comment = None
        # sleep to avoid rate limiting
        await asyncio.sleep(1)
        try:
            await submission.load()
            async for comment in submission.comments:
                if (
                    comment.author == reddit_username
                    and comment.body.startswith("{")
                    and comment.body.endswith("}")
                ):
                    submission_comment = comment.body
                    print(f"Found comment: {submission_comment}")
                    break
        except Exception as e:
            # TODO reddit will sometimes return a 429 error when trying to get the comments, we should retry
            print(f"Error getting comment: {e}")

        p = DailyAnimePost(
            title=submission.title,
            id=submission.id,
            permalink=get_permalink(submission),
            media_url=submission.url,
            created_utc=submission.created_utc,
            first_comment=submission_comment,
        )
        posts.append(p)

    return posts


def save_submissions_urls(submissions: list[DailyAnimePost]):
    with open(submissions_urls_file, "w") as f:
        json.dump(submissions, f, default=lambda o: o.__dict__, indent=4)


def load_submissions_urls() -> list[DailyAnimePost]:
    with open(submissions_urls_file, "r") as f:
        submissions = json.load(f)
        return [DailyAnimePost(**s) for s in submissions]


def perform_audit():
    """Check for empty directories"""
    for month in os.listdir(data_dir):
        month_dir = os.path.join(data_dir, month)
        if not os.path.isdir(month_dir):
            continue
        for day in os.listdir(month_dir):
            day_dir = os.path.join(month_dir, day)
            if not os.listdir(day_dir):
                print(f"Empty directory: {day_dir}")
    print("Audit complete")


async def main():
    reddit = asyncpraw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent="script:animetoday",
    )

    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    cache_exists = os.path.exists(submissions_urls_file)
    daily_submissions = (
        load_submissions_urls() if cache_exists else await get_submissions(reddit)
    )

    for submission in daily_submissions:
        print(f"Processing {submission.title} - {submission.permalink}")

        submission_date = datetime.datetime.utcfromtimestamp(submission.created_utc)
        submission_month = submission_date.strftime("%m_%B")

        submission_month_dir = os.path.join(data_dir, submission_month)
        if not os.path.exists(submission_month_dir):
            os.makedirs(submission_month_dir)

        submission_day = submission_date.strftime("%d")
        day_dir = os.path.join(submission_month_dir, submission_day)
        if not os.path.exists(day_dir):
            os.makedirs(day_dir)

        await download_image(submission, day_dir)

        # save the comment to a file
        if submission.first_comment:
            comment_filename = os.path.join(day_dir, f"{submission.id}.txt")
            with open(comment_filename, "w", encoding="utf-8") as f:
                f.write(submission.first_comment)


if __name__ == "__main__":
    asyncio.run(main())
