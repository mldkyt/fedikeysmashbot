import datetime
import re
from os import getenv
from time import sleep

from dotenv import load_dotenv
from password_strength import PasswordStats
from sqlalchemy import delete, insert, select, update

from database import (
    engine,
    follows_table,
    last_scan_table,
    posts_table,
    quoted_posts_table,
)
from logger import get_logger
from misskey import (
    dm,
    follow,
    get_effective_name,
    get_followers,
    get_notes,
    get_relationships,
    me,
    quote,
    unfollow,
)


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


def main():
    print("Hello from fedikeysmashbot!")

    keysmashbot_logger = get_logger("keysmashbot")

    load_dotenv()

    MISSKEY_INSTANCE = getenv("MISSKEY_INSTANCE")
    MISSKEY_TOKEN = getenv("MISSKEY_TOKEN")

    if not isinstance(MISSKEY_INSTANCE, str) or not isinstance(MISSKEY_TOKEN, str):
        print("Invalid MISSKEY_INSTANCE or MISSKEY_TOKEN")
        exit(1)

    DEBUG = getenv("DEBUG", "0") == "1"

    me_id = me(MISSKEY_INSTANCE, MISSKEY_TOKEN)

    if not isinstance(me_id, str):
        print("Invalid token, unable to fetch account")
        exit(1)

    for i in get_followers(MISSKEY_INSTANCE, MISSKEY_TOKEN, me_id):
        with engine.begin() as c:
            rel = get_relationships(MISSKEY_INSTANCE, MISSKEY_TOKEN, i["id"])
            if not rel:
                continue

            if (
                not rel["isFollowing"]
                and not rel["hasPendingFollowRequestFromYou"]
                and not rel["isBlocking"]
            ):
                while True:
                    try:
                        follow(MISSKEY_INSTANCE, MISSKEY_TOKEN, i["id"])
                        c.execute(
                            insert(follows_table).values(
                                id=i["id"], acct=get_effective_name(i)
                            )
                        )
                        keysmashbot_logger.info(
                            "Followed %s successfully", get_effective_name(i)
                        )
                        break
                    except Exception:
                        print("fail to follow", i["name"])
                        keysmashbot_logger.exception("fail to follow %s", i["name"])
                        break

            try:
                a = c.execute(
                    select(last_scan_table.c.last_scan).where(
                        (last_scan_table.c.id == i["id"])
                    )
                ).fetchone()
                if a is None:
                    c.execute(
                        insert(last_scan_table).values(
                            id=i["id"], last_scan=datetime.datetime.now()
                        )
                    )

                    do_full_scan = False
                else:
                    if (datetime.datetime.now() - a[0]).total_seconds() > 1209600:
                        do_full_scan = True
                        c.execute(
                            update(last_scan_table)
                            .where((last_scan_table.c.id == i["id"]))
                            .values(last_scan=datetime.datetime.now())
                        )

                        keysmashbot_logger.info(
                            "Full-scan performing on %s", get_effective_name(i)
                        )
                    else:
                        do_full_scan = False

                print("do_full_scan", do_full_scan)

                for j in get_notes(MISSKEY_INSTANCE, MISSKEY_TOKEN, i["id"]):
                    a = c.execute(
                        select(posts_table.c.id).where(
                            (posts_table.c.id == str(j["id"]))
                        )
                    ).fetchone()
                    if a is not None:
                        if do_full_scan:
                            continue
                        else:
                            break

                    b = c.execute(
                        select(quoted_posts_table.c.id).where(
                            (quoted_posts_table.c.id == str(j["id"]))
                        )
                    ).fetchone()
                    if b is not None:
                        continue

                    text = j["text"]

                    text = re.sub(r"@[a-zA-Z.\-_]+", "", text)
                    text = re.sub(r"#\w+", "", text)
                    text = re.sub(r":[a-zA-Z_\-0-9]+?:", "", text)
                    text = re.sub(r"\[.+?\]\(.+?\)", "", text)
                    text = re.sub(r"<i>(.+?)</i>", r"\1", text)
                    text = re.sub(r"`(.+?)`", r"\1", text)
                    text = re.sub(r"<plain>(.+?)</plain>", r"\1", text)
                    text = re.sub(r"<small>(.+?)</small>", r"\1", text)
                    text = sanitize_formatting(text)
                    text = re.sub(r"$\[\w+(.+?)\]", r"\1", text)
                    text = re.sub(
                        r"hr?ttps?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)",
                        "",
                        text,
                    )

                    for k in text.split(" "):
                        if len(k.strip()) == 0:
                            continue
                        if "\n" in k:
                            continue
                        if "$INSTANCE$" in k:  # fedicrimes
                            continue
                        password = PasswordStats(k)

                        try:
                            if password.strength() < 0.7:
                                continue
                        except Exception:
                            keysmashbot_logger.exception(
                                "Error measuring password length"
                            )
                            continue

                        contains = []
                        if password.letters_lowercase > 0:
                            contains.append("lowercase letters")
                        if password.letters_uppercase > 0:
                            contains.append("uppercase letters")
                        if password.numbers > 0:
                            contains.append("numbers")
                        if password.special_characters:
                            contains.append("special characters")

                        if DEBUG:
                            print(
                                f"""Password found: {k}\n\nPassword contains {", ".join(contains)} and the entropy is {round(password.entropy_bits)} bits."""
                            )

                            c.execute(
                                insert(quoted_posts_table).values(id=str(j["id"]))
                            )
                            break
                        else:
                            quote(
                                MISSKEY_INSTANCE,
                                MISSKEY_TOKEN,
                                j["id"],
                                f"""Password found: {k}\n\nPassword contains {", ".join(contains)} and the entropy is {round(password.entropy_bits)} bits.""",
                            )

                            c.execute(
                                insert(quoted_posts_table).values(id=str(j["id"]))
                            )

                            sleep(30 * 60)  # sleep for 30 minutes (don't spam)

                            break

                    c.execute(
                        insert(posts_table).values(
                            id=str(j["id"]),
                            author=get_effective_name(j["user"]),
                        )
                    )
            except Exception:
                keysmashbot_logger.exception(
                    "Failed to query posts for %s", get_effective_name(i)
                )

    with engine.begin() as c:
        a = c.execute(select(follows_table.c.id, follows_table.c.acct)).all()

        for i in a:
            rel = get_relationships(MISSKEY_INSTANCE, MISSKEY_TOKEN, i[0])

            if not rel:
                continue

            if not rel["isFollowed"]:
                try:
                    if rel["isFollowing"]:
                        unfollow(MISSKEY_INSTANCE, MISSKEY_TOKEN, i[0])
                        keysmashbot_logger.info("unfollowed %s", i[0])

                    with engine.begin() as c:
                        c.execute(
                            delete(posts_table).where((posts_table.c.author == i[1]))
                        )
                        c.execute(
                            delete(follows_table).where((follows_table.c.id == i[0]))
                        )

                        keysmashbot_logger.info("Deleted all posts of %s", i[0])

                except Exception as e:
                    print(f"failed to unfollow {i[0]}: {str(e)}")
                    keysmashbot_logger.exception("failed to unfollow %s", i[0])
                    pass


if __name__ == "__main__":
    main()
