import asyncio
import datetime
import re
from os import getenv
from random import choice

from dotenv import load_dotenv
from sqlalchemy import delete, insert, select, update
from zxcvbn import zxcvbn

from database import (engine, follows_table, last_scan_table, posts_table, quoted_posts_table, responded_dms_table, )
from logger import get_logger
from misskey import Misskey

keysmashbot_logger = get_logger("keysmashbot")


def sanitize_formatting(text: str) -> str:
    result = []
    i = 0
    n = len(text)

    open_tags = []
    open_parentheses = 0
    processed_closing_tags = []

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else None
        if c == "$" and nxt == "[":
            open_tags.append("$[")
            result.append("$[")
            i += 2
            continue
        if c == "<" and nxt == "i":
            if i + 2 < n and text[i + 2] == ">":
                open_tags.append("<i>")
                result.append("<i>")
                i += 3
            else:
                result.append("<")
                result.append("i")
                i += 2
            continue
        if c == "<" and nxt == "s":
            temp = ["<"]
            j = i + 1
            is_small_tag = False
            while j < n:
                temp.append(text[j])
                if "".join(temp) == "<small>":
                    open_tags.append("<small>")
                    is_small_tag = True
                    j += 1
                    break
                if text[j] == ">" or len(temp) >= 7:
                    j += 1
                    break
                j += 1
            if is_small_tag:
                result.append("<small>")
            else:
                result.append("".join(temp))
            i = j
            continue
        if c == "*" and nxt == "*":
            if "**" not in open_tags:
                open_tags.append("**")
            else:
                try:
                    open_tags.remove("**")
                except ValueError:
                    pass
                processed_closing_tags.append("**")
            result.append("**")
            i += 2
            continue
        if c == "(":
            open_parentheses += 1
            result.append("(")
            i += 1
            continue
        if c == ")":
            if open_parentheses > 0:
                open_parentheses -= 1
            result.append(")")
            i += 1
            continue
        if c == "]":
            if "$[" in open_tags:
                try:
                    open_tags.remove("$[")
                except ValueError:
                    pass
                processed_closing_tags.append("$[")
            result.append("]")
            i += 1
            continue
        if c == "<" and nxt == "/":
            temp = ["<", "/"]
            j = i + 2
            closing_tag_type = ""
            while j < n:
                temp.append(text[j])
                s = "".join(temp)
                if s == "</i>":
                    closing_tag_type = "<i>"
                    j += 1
                    break
                if s == "</small>":
                    closing_tag_type = "<small>"
                    j += 1
                    break
                if text[j] == ">" or len(temp) >= 8:
                    j += 1
                    break
                j += 1
            if closing_tag_type and closing_tag_type in open_tags:
                try:
                    open_tags.remove(closing_tag_type)
                except ValueError:
                    pass
                processed_closing_tags.append(closing_tag_type)
            result.append("".join(temp))
            i = j
            continue
        result.append(c)
        i += 1
    for tag in reversed(open_tags):
        if tag == "$[":
            result.append("]")
        elif tag == "<i>":
            result.append("</i>")
        elif tag == "<small>":
            result.append("</small>")
        elif tag == "**":
            result.append("**")
    if open_parentheses > 0:
        result.append(")" * open_parentheses)

    return "".join(result)


def sanitize_password(password: str) -> str:
    password = re.sub(r"@[a-zA-Z.\-_]+", "", password)
    password = re.sub(r"#\w+", "", password)
    password = re.sub(r":[a-zA-Z_\-0-9]+?:", "", password)
    password = re.sub(r"\[.+?]\(.+?\)", "", password)
    for i in range(10):
        password = re.sub(r"<i>(.+?)</i>", r"\1", password)
    for i in range(3):
        password = re.sub(r"`(.+?)`", r"\1", password)
    for i in range(10):
        password = re.sub(r"<plain>(.+?)</plain>", r"\1", password)
    for i in range(10):
        password = re.sub(r"<small>(.+?)</small>", r"\1", password)
    password = sanitize_formatting(password)
    for i in range(10):
        password = re.sub(r"\$\[.+?\s(.+)]", r"\1", password)
    password = re.sub(
        r"hr?ttps?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)", "",
        password, )

    return password


posts_to_handle = []
misskey = Misskey()


async def check_followers() -> list:
    global misskey

    while True:
        keysmashbot_logger.debug("Handling follows")

        for i in misskey.get_followers():
            try:
                if not i["isFollowing"] and not i["hasPendingFollowRequestFromYou"] and not i["isBlocking"]:
                    while True:
                        follow = misskey.follow(i["id"])
                        if follow:
                            with engine.begin() as c:
                                c.execute(insert(follows_table).values(id=i["id"], acct=misskey.get_effective_name(i)))
                            keysmashbot_logger.info("Followed %s successfully", misskey.get_effective_name(i))
                            break
                        await asyncio.sleep(4)
            except Exception:
                print("fail to follow", i["name"])
                keysmashbot_logger.exception("fail to follow %s", i["name"])
                break

        with engine.begin() as c:
            a = c.execute(select(follows_table.c.id, follows_table.c.acct)).all()

        for i in a:
            rel = misskey.get_user(i[0])
            if not rel:
                continue

            if not rel["isFollowed"] and rel["isFollowing"]:
                try:
                    unfollow_ok = misskey.unfollow(i[0])
                    if unfollow_ok:
                        keysmashbot_logger.info("unfollowed %s", i[0])

                        with engine.begin() as c:
                            c.execute(delete(posts_table).where((posts_table.c.author == i[1])))
                            c.execute(delete(follows_table).where((follows_table.c.id == i[0])))

                            keysmashbot_logger.info("Deleted all posts of %s", i[0])

                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"failed to unfollow {i[0]}: {str(e)}")
                    keysmashbot_logger.exception("failed to unfollow %s", i[0])
                    pass

        await asyncio.sleep(180)


async def get_posts_to_quote():
    global posts_to_handle, misskey

    while True:
        with engine.begin() as c:
            for user in misskey.get_followers():
                try:
                    a = c.execute(
                        select(last_scan_table.c.last_scan).where((last_scan_table.c.id == user["id"]))).fetchone()
                    if a is None:
                        c.execute(insert(last_scan_table).values(id=user["id"], last_scan=datetime.datetime.now()))

                        do_full_scan = False
                    else:
                        if (datetime.datetime.now() - a[0]).total_seconds() > 1209600:
                            do_full_scan = True
                            c.execute(update(last_scan_table).where((last_scan_table.c.id == user["id"])).values(
                                last_scan=datetime.datetime.now()))

                            keysmashbot_logger.info("Full-scan performing on %s", misskey.get_effective_name(user))
                        else:
                            do_full_scan = False

                    for j in misskey.get_notes(user["id"]):
                        a = c.execute(select(posts_table.c.id).where((posts_table.c.id == str(j["id"])))).fetchone()
                        if a is not None:
                            if do_full_scan:
                                continue
                            else:
                                keysmashbot_logger.debug("Got to end of notes for %s, skipping",
                                    misskey.get_effective_name(user), )
                                break

                        if j["visibility"] != "home" and j["visibility"] != "public":
                            c.execute(insert(posts_table).values(id=str(j["id"]),
                                author=misskey.get_effective_name(j["user"]), ))
                            keysmashbot_logger.debug("Not handling post %s: It is private or followers only", j["id"], )
                            continue

                        b = c.execute(
                            select(quoted_posts_table.c.id).where((quoted_posts_table.c.id == str(j["id"])))).fetchone()
                        if b is not None:
                            keysmashbot_logger.debug("Post %s is already quoted, skipping", j["id"])
                            continue

                        text = j["text"]

                        text = sanitize_password(text)

                        for k in re.split(r",|\.|\s|;|:|_|-|/", text):
                            if len(k.strip()) == 0:
                                continue
                            if "\n" in k:
                                continue
                            if "$INSTANCE$" in k:  # fedicrimes
                                continue
                            password = zxcvbn(k[:71])

                            if password["crack_times_seconds"]["offline_fast_hashing_1e10_per_second"] < 2630000:
                                continue

                            keysmashbot_logger.debug("Post %s is gonna get quoted", j["id"])

                            affirming_text = ["is cute", "is a good entity", "is a pretty entity",
                                "is a good password generator", "is such a good entity", "is such a pretty entity",
                                "is such a good password generator", ]

                            posts_to_handle.append({"id": j["id"], "text": f"""Password found: `{k}`
    
        This password would take {password["crack_times_display"]["offline_fast_hashing_1e10_per_second"]} to crack, @{misskey.get_effective_name(user)} {choice(affirming_text)} :3""", })
                            break
                        c.execute(
                            insert(posts_table).values(id=str(j["id"]), author=misskey.get_effective_name(j["user"]), ))
                except Exception:
                    keysmashbot_logger.exception("Failed to query posts for %s", misskey.get_effective_name(user))

        await asyncio.sleep(60)


async def reply_to_keysmash_detections(debug=False):
    global misskey

    while True:
        notifs = misskey.notifications()

        keysmashbot_logger.debug("Notification count: %s", str(len(notifs)))

        with engine.begin() as c:
            for i in notifs:
                try:
                    if i["note"]["visibility"] != "home" and i["note"]["visibility"] != "public":
                        keysmashbot_logger.debug("Not reply to post %s: It is private or followers only",
                            i["note"]["id"], )
                        continue

                    is_replied = (c.execute(select(responded_dms_table).where(
                        (responded_dms_table.c.id == str(i["id"])))).fetchone() is not None)

                    if is_replied:
                        keysmashbot_logger.debug("Not replying to post %s: It is already replied to", i["note"]["id"], )
                        continue

                    text = i["note"]["text"]

                    text = sanitize_password(text)

                    for j in re.split(r",|\.|\s|;|:|_|-|/", text):
                        if len(j.strip()) == 0:
                            continue
                        if "\n" in j:
                            continue
                        if "$INSTANCE$" in j:  # fedicrimes
                            continue
                        password = zxcvbn(j[:71])

                        try:
                            if password["crack_times_seconds"]["offline_fast_hashing_1e10_per_second"] < 2630000:
                                continue
                        except Exception:
                            keysmashbot_logger.exception("Error measuring password length")
                            continue

                        keysmashbot_logger.debug("Post %s is gonna get replied to", i["note"]["id"])

                        affirming_text = ["is cute", "is a good entity", "is a pretty entity",
                            "is a good password generator", "is such a good entity", "is such a pretty entity",
                            "is such a good password generator", ]

                        if debug:
                            keysmashbot_logger.debug("Reply to %s", i["note"]["id"])
                            keysmashbot_logger.debug(f"""Password found: `{j}`

    This password would take {password["crack_times_display"]["offline_fast_hashing_1e10_per_second"]} to crack, @{misskey.get_effective_name(i["user"])} {choice(affirming_text)} :3""")
                        else:
                            misskey.post(f"""Password found: `{j}`

    This password would take {password["crack_times_display"]["offline_fast_hashing_1e10_per_second"]} to crack, @{misskey.get_effective_name(i["user"]["id"])} {choice(affirming_text)} :3""",
                                         reply_id=i["note"]["id"])

                        break
                    else:
                        keysmashbot_logger.debug("Not replying to %s: This reply doesn't have any keysmashes",
                            i["note"]["id"], )

                    c.execute(insert(responded_dms_table).values(id=str(i["id"])))
                except Exception:
                    keysmashbot_logger.exception("Error responding to DM")

        await asyncio.sleep(10)


async def post_posts_to_handle():
    global posts_to_handle

    while True:
        if len(posts_to_handle) > 0:
            post = posts_to_handle.pop(0)

            misskey.post(post["text"], quote_id=post["id"])

            with engine.begin() as c:
                c.execute(insert(quoted_posts_table).values(id=str(post["id"])))

        await asyncio.sleep(10)


async def main():
    print("Hello from fedikeysmashbot!")

    load_dotenv()

    MISSKEY_INSTANCE = getenv("MISSKEY_INSTANCE")
    MISSKEY_TOKEN = getenv("MISSKEY_TOKEN")

    if not isinstance(MISSKEY_INSTANCE, str) or not isinstance(MISSKEY_TOKEN, str):
        print("Invalid MISSKEY_INSTANCE or MISSKEY_TOKEN")
        exit(1)

    global misskey

    misskey = Misskey()
    misskey.log_in(MISSKEY_INSTANCE, MISSKEY_TOKEN)

    # start tasks

    tasks = [asyncio.create_task(check_followers()), asyncio.create_task(get_posts_to_quote()),
        asyncio.create_task(reply_to_keysmash_detections()), asyncio.create_task(post_posts_to_handle())]

    print("Starting tasks")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
