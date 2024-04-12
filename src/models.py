from peewee import *

from db import BaseModel


class MediaPost(BaseModel):
    id = TextField(primary_key=True)
    username = TextField()
    title = TextField()
    permalink = TextField()
    media_url = TextField()
    created_utc = IntegerField()
    first_comment = TextField(null=True)

    malformed_title = BooleanField(default=False)
    non_media_post = BooleanField(default=False)

    class Meta:
        table_name = "media_posts"
