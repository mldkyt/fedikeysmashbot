import asyncio
import datetime
import logging
import re
import typing
from os import getenv
from random import choice

import bs4
import sentry_sdk
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from mastodon import Mastodon
from mastodon.return_types import Notification
from sentry_sdk import capture_exception
from sentry_sdk.integrations.logging import LoggingIntegration
from sqlalchemy import delete, insert, select, update
from zxcvbn import zxcvbn

from database import (
    engine,
    follows_table,
    posts_table,
    quoted_posts_table,
    responded_dms_table,
)
from logger import get_logger
from user_prefs import get_user_pref, set_user_pref

load_dotenv()

keysmashbot_logger = get_logger("keysmashbot")

SENTRY_SDK = getenv("SENTRY_SDK")

if SENTRY_SDK is not None:
    sentry_sdk.init(
        dsn=SENTRY_SDK,
        auto_session_tracking=False,
        send_default_pii=True,
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ]
        # enable_logs=True,  # Opt-in: send logs to GlitchTip (uses disk space)
    )


# borrowed from https://stackoverflow.com/questions/30337528/make-beautifulsoup-handle-line-breaks-as-a-browser-would
def get_text(tag: bs4.Tag) -> str:
    _inline_elements = {
        "a",
        "span",
        "em",
        "strong",
        "u",
        "i",
        "font",
        "mark",
        "label",
        "s",
        "sub",
        "sup",
        "tt",
        "bdo",
        "button",
        "cite",
        "del",
        "b",
        "a",
        "font",
    }

    def _get_text(tag: bs4.Tag) -> typing.Generator:
        for child in tag.children:
            if isinstance(child, bs4.Tag):
                if child.name == "br":
                    yield "\n"
                    continue
                # if the tag is a block type tag then yield new lines before after
                is_block_element = child.name not in _inline_elements
                if is_block_element:
                    yield "\n"
                yield from _get_text(child)
                if is_block_element:
                    yield "\n"
            elif isinstance(child, bs4.NavigableString):
                yield child.string

    return "".join(_get_text(tag))


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
        r"hr?ttps?://(www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)",
        "",
        password,
    )

    return password


posts_to_handle = []
mastodon: Mastodon | None = None
acct: str = ""


def init_mastodon() -> None:
    global mastodon, acct
    mastodon = Mastodon(access_token="data/pytooter_usercred.secret")
    acct = mastodon.me().acct


async def check_followers() -> list:
    while True:
        keysmashbot_logger.debug("Handling follows")

        for account in mastodon.pagination_iterator(
            mastodon.account_followers(mastodon.me())
        ):
            try:
                with engine.begin() as c:
                    a = c.execute(
                        select(follows_table).where(follows_table.c.id == account.id)
                    ).fetchone()

                if a is not None:
                    continue

                rel = mastodon.account_relationships(account)

                # Account Move
                if account.moved is not None:
                    try:
                        new_account = account.moved
                        while True:
                            if new_account.moved is None:
                                break

                            new_account = new_account.moved

                        print("Account migrated", account.acct, "to", new_account.acct)
                        mastodon.account_remove_from_followers(account)

                        with engine.begin() as c2:
                            new_account_followed = (
                                c2.execute(
                                    select(follows_table).where(
                                        follows_table.c.acct == new_account.acct
                                    )
                                ).fetchone()
                                is not None
                            )

                        if not new_account_followed:
                            print(
                                "New account is not following keysmashbot, begging for follow"
                            )
                            mastodon.status_post(
                                f"Hi @{new_account.acct}! It looks like you moved from {account.acct}. In order for this bot to interact with you, you have to consent by following this bot on your new account.",
                                visibility="private",
                            )
                    except Exception as e:
                        capture_exception(e)

                    continue

                if (
                    len(rel) > 0
                    and not rel[0].following
                    and not rel[0].requested
                    and not rel[0].blocked_by
                ):
                    mastodon.account_follow(account.id)
                    with engine.begin() as c:
                        c.execute(
                            insert(follows_table).values(
                                id=account.id,
                                acct=account.acct,
                                followed=datetime.datetime.now(),
                            )
                        )
                    keysmashbot_logger.info("Followed %s successfully", account.acct)
                    mastodon.status_post(
                        f'@{account.acct} Hi! The keysmash bot will not quote any of your posts by default. If you want to opt-in, reply "quote my posts".',
                        visibility="direct",
                    )

                    await asyncio.sleep(4)
            except Exception as e:
                keysmashbot_logger.exception("fail to follow %s", account.acct)
                continue

        with engine.begin() as c:
            a = c.execute(select(follows_table.c.id, follows_table.c.acct)).all()

        for account in a:
            rel = mastodon.account_relationships(account[0])
            if len(rel) == 0:
                continue

            if not rel[0].followed_by:
                try:
                    if rel[0].following:
                        if not mastodon.account_unfollow(account[0]):
                            await asyncio.sleep(1)
                            continue

                        keysmashbot_logger.info("unfollowed %s", account[1])

                    with engine.begin() as c:
                        c.execute(
                            delete(posts_table).where(
                                (posts_table.c.author == account[1])
                            )
                        )
                        c.execute(
                            delete(follows_table).where(
                                (follows_table.c.id == account[0])
                            )
                        )

                        keysmashbot_logger.info(
                            "Deleted all posts of %s", account[1]
                        )

                    await asyncio.sleep(1)
                except Exception as e:
                    keysmashbot_logger.exception("failed to unfollow %s", account[1])
                    pass

        await asyncio.sleep(180)


async def get_posts_to_quote():
    global posts_to_handle, mastodon

    while True:
        for post in mastodon.pagination_iterator(
            mastodon.timeline_home(limit=40)
        ):
            if post.visibility == 'direct' or post.visibility == 'private':
                continue

            if post.account.acct == acct:
                continue

            if post.reblog is not None:
                continue

            with engine.begin() as c:
                try:
                    # Existing post check
                    existing = c.execute(
                        select(posts_table).where(posts_table.c.id == str(post.id))
                    ).fetchone()

                    if existing is not None:
                        continue

                    if get_user_pref(c, post.account.acct, "consent", "no") == "no":
                        keysmashbot_logger.debug(
                            "Skipping user %s: No consent", post.account.acct
                        )
                        continue

                    # History check
                    b = c.execute(
                        select(follows_table.c.followed).where(
                            follows_table.c.acct == post.account.acct
                        )
                    ).fetchone()
                    if b is not None:
                        history = get_user_pref(c, post.account.acct, "history", "no")
                        if history != "yes" and post.created_at.replace(tzinfo=None) < b[0].replace(tzinfo=None):
                            keysmashbot_logger.debug("Skipping: Before follow date")
                            continue

                    # Visibility check
                    unlisted_visibility = (
                        get_user_pref(c, post.account.acct, "unlisted", "no") == "yes"
                    )

                    if post.visibility != "public" and not (
                        post.visibility == "unlisted" and unlisted_visibility
                    ):
                        c.execute(
                            insert(posts_table).values(
                                id=str(post.id), author=post.account.acct
                            )
                        )
                        keysmashbot_logger.debug(
                            "Not handling post %s: It is private or followers only",
                            post.id,
                        )
                        continue

                    # CW check
                    cw_posts = get_user_pref(c, post.account.acct, "cw", "no") == "yes"
                    if not cw_posts and (
                        post.spoiler_text is not None
                        and len(post.spoiler_text.strip()) > 0
                    ):
                        c.execute(
                            insert(posts_table).values(
                                id=str(post.id), author=post.account.acct
                            )
                        )
                        keysmashbot_logger.debug(
                            "Not handling post %s: It has a CW", post.id
                        )
                        continue

                    b = c.execute(
                        select(quoted_posts_table.c.id).where(
                            (quoted_posts_table.c.id == str(post.id))
                        )
                    ).fetchone()
                    if b is not None:
                        keysmashbot_logger.debug(
                            "Post %s is already quoted, skipping", post.id
                        )
                        continue

                    text = get_text(
                        bs4.BeautifulSoup(post.content, features="html.parser")
                    ).strip()

                    text = sanitize_password(text)

                    for k in re.split(r"[,.\s;:_\-/]", text):
                        if len(k.strip()) == 0:
                            continue
                        if "\n" in k:
                            continue
                        if "$INSTANCE$" in k:  # fedicrimes
                            continue
                        password = zxcvbn(k[:71])

                        if (
                            password["crack_times_seconds"][
                                "offline_fast_hashing_1e10_per_second"
                            ]
                            < 2630000
                        ):
                            continue

                        keysmashbot_logger.debug(
                            "Post %s is gonna get quoted", post.id
                        )

                        affirming_text = [
                            "is cute",
                            "is a good entity",
                            "is a pretty entity",
                            "is a good password generator",
                            "is such a good entity",
                            "is such a pretty entity",
                            "is such a good password generator",
                        ]

                        data = {
                            "id": post.id,
                            "text": f"""Password found: `{k}`

This password would take {password["crack_times_display"]["offline_fast_hashing_1e10_per_second"]} to crack, @{post.account.acct} {choice(affirming_text)} :3

QT: {post.url}""",
                        }

                        if (
                            post.spoiler_text is not None
                            and len(post.spoiler_text.strip()) > 0
                        ):
                            data["cw"] = "cw quote: " + post.spoiler_text
                        posts_to_handle.append(data)
                        break
                    c.execute(
                        insert(posts_table).values(
                            id=str(post.id), author=post.account.acct
                        )
                    )
                except Exception as e:
                    keysmashbot_logger.exception(
                        "Failed to query posts for %s", post.account.acct
                    )

        await asyncio.sleep(60)


async def reply_handle_keysmashes(i: Notification | typing.Any, debug: bool = False):
    if i.type != "mention":
        return
    if i.status is None:
        return
    if i.status.account.acct == acct:
        # this might make sense.
        return

    # Check reply visibility
    if i.status.visibility != "unlisted" and i.status.visibility != "public":
        keysmashbot_logger.debug(
            "Not reply to post %s: It is private or followers only", i.status.id
        )
        return

    with engine.begin() as c:
        if get_user_pref(c, i.status.account.acct, "consent", "no") == "no":
            keysmashbot_logger.debug(
                "Not replying to post %s: No consent", i.status.id
            )
            return

    text = get_text(BeautifulSoup(i.status.content)).strip()
    text = sanitize_password(text)

    for j in re.split(r"[,.\s;:_\-/]", text):
        if len(j.strip()) == 0:
            continue
        if "\n" in j:
            continue
        if "$INSTANCE$" in j:  # fedicrimes
            continue
        password = zxcvbn(j[:71])

        try:
            if (
                password["crack_times_seconds"]["offline_fast_hashing_1e10_per_second"]
                < 2630000
            ):
                continue
        except Exception:
            keysmashbot_logger.exception("Error measuring password length")
            continue

        keysmashbot_logger.debug("Post %s is gonna get replied to", i.status.id)

        affirming_text = [
            "is cute",
            "is a good entity",
            "is a pretty entity",
            "is a good password generator",
            "is such a good entity",
            "is such a pretty entity",
            "is such a good password generator",
        ]

        if debug:
            keysmashbot_logger.debug("Reply to %s", i.status.id)
            keysmashbot_logger.debug(f"""Password found: `{j}`

This password would take {password["crack_times_display"]["offline_fast_hashing_1e10_per_second"]} to crack, @{i.status.account.acct} {choice(affirming_text)} :3""")
        else:
            mastodon.status_post(
                f"""Password found: `{j}`

This password would take {password["crack_times_display"]["offline_fast_hashing_1e10_per_second"]} to crack, @{i.status.account.acct} {choice(affirming_text)} :3""",
                in_reply_to_id=i.status.id,
                visibility=i.status.visibility
                if i.status.visibility != "public"
                else "unlisted",
                spoiler_text=i.status.spoiler_text,
            )
            with engine.begin() as c:
                c.execute(
                    insert(quoted_posts_table).values(
                        id=str(i.status.id),
                    )
                )
        break
    else:
        keysmashbot_logger.debug(
            "Not replying to %s: This reply doesn't have any keysmashes",
            i.status.id,
        )


async def reply_handle_dms(i: Notification, debug: bool = False):
    # Check reply visibility
    if i.type != "mention":
        return
    if i.status is None:
        return
    if i.status.visibility != "direct":
        keysmashbot_logger.debug("Not handling reply %s: Not a DM", i.status.id)
        return
    if i.status.account.acct == acct:
        # this might make sense.
        return

    text = get_text(BeautifulSoup(i.status.content)).strip()

    if not text.startswith(f"@{acct}"):
        return

    output = ""

    for command in text.splitlines():
        command = " ".join([i for i in command.split(" ") if len(i.strip()) > 0])
        if command.startswith(f"@{acct}"):
            command = " ".join(command.split(" ")[1:])

        command = command.strip()

        if command == "help":
            output += f""" Available commands:
- `quote my posts`: Enables keysmashbot to interact with your posts
- `don't quote my posts`: Disables keysmashbot frm interacting with your posts
- `include CWd posts`: Include posts with CW's in keysmashing (the quoted posts will have CW)
- `don't include CWd posts`: Don't include posts with CW's in keysmashing
- `include unlisted posts`: Include unlisted posts
- `don't include unlisted posts`: Don't include unlisted posts
- `include post history`: Post all posts in history
- `don't include post history`: Don't include posts in history (note this won't undo posts)
- `show settings`: Show the current settings the user has set.\n\n"""

        elif re.match(r"^(quotes?|includes?|uses?) (my )?posts?$", command):
            output += f"The bot will now take your posts and include them\n\n"
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "consent", "yes")
        elif re.match(r"^don'?t (quotes?|includes?|uses?) (my )?posts?$", command):
            output += f"The bot will no longer take your posts and include them\n\n"
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "consent", "no")
        elif re.match(r"^(includes?|uses?|quotes?) CW'?d? posts?$", command):
            output += f"The bot will now take CW'd posts and include them\n\n"
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "cw", "yes")
        elif re.match(r"^don'?t (includes?|uses?|quotes?) CW'?d? posts?$", command):
            output += f"The bot will stop taking CW'd posts and including them\n\n"
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "cw", "no")
        elif re.match(
            r"^(includes?|uses?|quotes?) (unlisted|private|home) posts?$", command
        ):
            output += f"The bot will now take unlisted posts and include them\n\n"
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "unlisted", "yes")
        elif re.match(
            r"^don'?t (includes?|uses?|quotes?) (unlisted|private|home) posts?$",
            command,
        ):
            output += f"The bot will stop taking unlisted posts and including them\n\n"
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "unlisted", "no")
        elif re.match(r"^(includes?|uses?|quotes?) posts? history$", command):
            output += (
                f"The bot will now quote all your posts it can see on its instance\n\n"
            )
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "history", "yes")
        elif re.match(r"^don'?t (includes?|uses?|quotes?) posts? history$", command):
            output += (
                f"The bot will not quote any posts that are found on the instance\n\n"
            )
            with engine.begin() as c:
                set_user_pref(c, i.status.account.acct, "history", "no")
        elif re.match(r"^(show|get) settings?$", command):
            with engine.begin() as c:
                consent = get_user_pref(c, i.status.account.acct, "consent", "no")
                history = get_user_pref(c, i.status.account.acct, "history", "no")
                unlisted = get_user_pref(c, i.status.account.acct, "unlisted", "no")
                cw = get_user_pref(c, i.status.account.acct, "cw", "no")

            output += f"""Current settings:

- Consent: {consent}
- History: {history}
- Unlisted: {unlisted}
- CW: {cw}\n\n"""
        elif command == "meow":
            output += f"meow"

    if len(output.strip()) > 0:
        mastodon.status_post(
            output,
            visibility="direct",
            in_reply_to_id=i.status,
            content_type="text/markdown",
        )
    else:
        mastodon.status_post(
            "Incorrect command(s), use `help` to get help",
            visibility="direct",
            in_reply_to_id=i.status,
            content_type="text/markdown",
        )


async def reply_to_keysmash_detections(debug=False):
    global mastodon

    last_seen_id = None

    while True:
        notifs = mastodon.notifications()

        # A single page only holds the newest notifications. If more arrived than
        # fit on one page since the last check, walk back until we catch up.
        page = notifs
        while (
            last_seen_id is not None
            and page
            and min(int(n.id) for n in page) > last_seen_id
        ):
            page = mastodon.fetch_next(page)
            if page is not None:
                notifs.extend(page)

        if len(notifs) > 0:
            last_seen_id = int(notifs[0].id)

        for i in notifs:
            # Check reply state
            with engine.begin() as c:
                is_replied = (
                    c.execute(
                        select(responded_dms_table).where(
                            (responded_dms_table.c.id == str(i.id))
                        )
                    ).fetchone()
                    is not None
                )

            if is_replied:
                continue

            handled = True

            # Handle replying to keysmashes (public, unlisted posts)
            try:
                await reply_handle_keysmashes(i, debug=debug)
            except Exception as e:
                handled = False
                keysmashbot_logger.exception("Error responding to reply")

            # Handle replying to commands (DM's)
            try:
                await reply_handle_dms(i, debug=debug)
            except Exception as e:
                handled = False
                keysmashbot_logger.exception("Error responding to DM")

            # Only mark it handled if nothing failed, so failures are retried.
            if handled:
                with engine.begin() as c:
                    c.execute(insert(responded_dms_table).values(id=str(i["id"])))

        await asyncio.sleep(5)


async def post_posts_to_handle():
    global posts_to_handle

    while True:
        if len(posts_to_handle) > 0:
            post = posts_to_handle[0]

            try:
                mastodon.status_post(
                    post["text"],
                    spoiler_text=None if "cw" not in post else post["cw"],
                    visibility="unlisted",
                )

                posts_to_handle.pop(0)

                with engine.begin() as c:
                    c.execute(insert(quoted_posts_table).values(id=str(post["id"])))
            except Exception as e:
                keysmashbot_logger.exception(
                    "Failed to quote post %s, will retry", post["id"]
                )

        await asyncio.sleep(10)


async def status():
    HEARTBEAT_URL = getenv("HEARTBEAT_URL", "")

    if len(HEARTBEAT_URL.strip()) == 0:
        return

    while True:
        async with ClientSession() as session:
            async with session.post(HEARTBEAT_URL, timeout=5):
                pass

        await asyncio.sleep(60)


async def run_forever(task: typing.Callable[[], typing.Awaitable]):
    """Restart a background loop if it crashes, so one error can't stop the bot."""
    while True:
        try:
            await task()
        except Exception as e:
            keysmashbot_logger.exception(
                "Task %s crashed, restarting", getattr(task, "__name__", task)
            )
            await asyncio.sleep(5)
        else:
            # The task finished on its own (e.g. no HEARTBEAT_URL); don't restart it.
            return


async def main():
    print("Hello from fedikeysmashbot!")

    init_mastodon()

    tasks = [
        asyncio.create_task(run_forever(check_followers)),
        asyncio.create_task(run_forever(get_posts_to_quote)),
        asyncio.create_task(run_forever(reply_to_keysmash_detections)),
        asyncio.create_task(run_forever(post_posts_to_handle)),
        asyncio.create_task(run_forever(status)),
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
