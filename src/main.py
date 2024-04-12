import asyncio
import os
from db import database_proxy
from peewee import *
from models import MediaPost
from dotenv import load_dotenv

from scraper import Scraper

load_dotenv()

data_dir = "data"
if not os.path.exists(data_dir):
    os.makedirs(data_dir)

db_path = os.path.join(data_dir, "media_posts.db")

database = SqliteDatabase(db_path)
database_proxy.initialize(database)
database.connect()

scraper = Scraper("animetoday", data_dir)


async def main():
    database.create_tables([MediaPost])
    await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())
