from sqlalchemy import create_engine, select, insert, MetaData, Table, VARCHAR, Column

from database import posts_table, quoted_posts_table, responded_dms_table, follows_table, last_scan_table, \
    user_prefs_table


_old_follows_table = Table(
    "follows",
    MetaData(),
    Column("id", VARCHAR, primary_key=True),
    Column("acct", VARCHAR, nullable=False),
)

engine_old = create_engine("sqlite:///data/keysmash.db")

posts = []
quoted_posts = []
responded_dms = []
follows = []
last_scan = []
user_prefs = []

with engine_old.begin() as c:
    posts.extend(c.execute(select(posts_table)).fetchall())
    quoted_posts.extend(c.execute(select(quoted_posts_table)).fetchall())
    responded_dms.extend(c.execute(select(responded_dms_table)).fetchall())
    follows.extend(c.execute(select(_old_follows_table)).fetchall())
    last_scan.extend(c.execute(select(last_scan_table)).fetchall())
    user_prefs.extend(c.execute(select(user_prefs_table)).fetchall())

engine_new = create_engine("sqlite:///data/keysmash2.db")

print("Migrating: ", len(posts), "posts", len(quoted_posts), "quoted posts", len(responded_dms), "responded dm's", len(follows), "follows", len(last_scan), "last scan records", len(user_prefs), "user prefs")

with engine_new.begin() as c:
    print("posts")
    for i in posts:
        c.execute(insert(posts_table).values(id=i[0], author=i[1]))
    print("quoted posts")
    for i in quoted_posts:
        c.execute(insert(quoted_posts_table).values(id=i[0]))
    print("responded dms")
    for i in responded_dms:
        c.execute(insert(responded_dms_table).values(id=i[0]))
    print("follows")
    for i in follows:
        c.execute(insert(follows_table).values(id=i[0], acct=i[1]))
    print("last scan")
    for i in last_scan:
        c.execute(insert(last_scan_table).values(id=i[0], last_scan=i[1]))
    print("user prefs")
    for i in user_prefs:
        c.execute(insert(user_prefs_table).values(user=i[0], key=i[1], value=i[2]))

print("migrate ok, please push the database to the latest revision")
