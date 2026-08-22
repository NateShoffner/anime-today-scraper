import asyncio
import os
import sys
from db import database_proxy
from peewee import *
from models import MediaPost
from dotenv import load_dotenv

from scraper import Scraper

load_dotenv()

# captions contain characters the default Windows console encoding cannot represent
# (the triangle in "Yuru Camp△", for one), and an encoding failure inside a print
# surfaces as a misleading error from whatever call it interrupts
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
