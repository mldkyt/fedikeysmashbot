import json
import os

import dotenv
from sqlalchemy import (
    VARCHAR,
    Column,
    DateTime,
    MetaData,
    Table,
    create_engine,
)

dotenv.load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///data/keysmash.db"
DATABASE_CONNECT_ARGS = os.getenv("DATABASE_CONNECT_ARGS") or '{"timeout": 30}'

engine = create_engine(DATABASE_URL, connect_args=json.loads(DATABASE_CONNECT_ARGS))

md_obj = MetaData()

posts_table = Table(
    "handled_posts",
    md_obj,
    Column("id", VARCHAR, primary_key=True),
    Column("author", VARCHAR),
)

quoted_posts_table = Table(
    "quoted_posts",
    md_obj,
    Column("id", VARCHAR, primary_key=True),
)

responded_dms_table = Table(
    "responded_dms", md_obj, Column("id", VARCHAR, primary_key=True)
)

follows_table = Table(
    "follows",
    md_obj,
    Column("id", VARCHAR, primary_key=True),
    Column("acct", VARCHAR, nullable=False),
)

last_scan_table = Table(
    "last_scan",
    md_obj,
    Column("id", VARCHAR, primary_key=True),
    Column("last_scan", DateTime, nullable=False),
)

md_obj.create_all(engine, checkfirst=True)
