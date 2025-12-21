from time import sleep
from tkinter.constants import N

from requests import post


def me(instance: str, token: str) -> str | None:
    me_api = post(
        f"https://{instance}/api/i",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    if not me_api.ok:
        return None

    me_api = me_api.json()
    return me_api["id"]


def me_detailed(instance: str, token: str):
    me_api = post(
        f"https://{instance}/api/i",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    if not me_api.ok:
        return None

    me_api = me_api.json()
    return me_api


def get_followers(instance: str, token: str, user_id: str):
    a = post(
        f"https://{instance}/api/users/followers",
        json={"limit": 100, "userId": user_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not a.ok:
        return

    a = a.json()

    if len(a) == 0:
        return

    lastfollowerid = "missingno"

    for i in a:
        lastfollowerid = i["followerId"]
        yield i["follower"]

    while True:
        sleep(0.5)

        next_followers = post(
            f"https://{instance}/api/users/followers",
            json={"limit": 100, "userId": user_id, "untilId": lastfollowerid},
            headers={"Authorization": f"Bearer {token}"},
        )

        if not next_followers.ok:
            break

        next_followers = next_followers.json()
        if len(next_followers) == 0:
            break

        for i in next_followers:
            lastfollowerid = i["followerId"]
            yield i["follower"]


def get_notes(instance: str, token: str, user_id: str):
    first_fetch_notes = post(
        f"https://{instance}/api/users/notes",
        json={
            "limit": 100,
            "userId": user_id,
            "withRenotes": False,
            "withQuotes": True,
            "withReplies": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    if not first_fetch_notes.ok:
        return

    first_fetch_notes = first_fetch_notes.json()

    if len(first_fetch_notes) == 0:
        return

    last_note = ""

    for i in first_fetch_notes:
        last_note = i["id"]
        if i["text"] is None:
            continue
        if i["cw"] is None:
            i["cw"] = ""
        yield i

    while True:
        sleep(0.5)

        next_notes = post(
            f"https://{instance}/api/users/notes",
            json={
                "limit": 100,
                "userId": user_id,
                "untilId": last_note,
                "withRenotes": False,
                "withQuotes": True,
                "withReplies": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        if not next_notes.ok:
            return

        next_notes = next_notes.json()
        if len(next_notes) == 0:
            return

        for i in next_notes:
            last_note = i["id"]
            if i["text"] is None:
                continue
            if i["cw"] is None:
                i["cw"] = ""
            yield i


def get_relationships(instance: str, token: str, user_id: str):
    req = post(
        f"https://{instance}/api/users/relation",
        headers={"Authorization": f"Bearer {token}"},
        json={"userId": user_id},
    )

    print(req)

    if not req.ok:
        return None

    return req.json()[0]


def follow(instance: str, token: str, user_id: str):
    req = post(
        f"https://{instance}/api/following/create",
        headers={"Authorization": f"Bearer {token}"},
        json={"userId": user_id},
    )
    print("follow", req)

    if req.status_code == 429:
        # Try again after a delay
        sleep(4)
        req = post(
            f"https://{instance}/api/following/create",
            headers={"Authorization": f"Bearer {token}"},
            json={"userId": user_id},
        )
        print("follow", req)

    return req.ok


def unfollow(instance: str, token: str, user_id: str):
    req = post(
        f"https://{instance}/api/following/delete",
        headers={"Authorization": f"Bearer {token}"},
        json={"userId": user_id},
    )
    print("unfollow", req)

    if req.status_code == 429:
        sleep(10)
        req = post(
            f"https://{instance}/api/following/delete",
            headers={"Authorization": f"Bearer {token}"},
            json={"userId": user_id},
        )
        print("unfollow", req)

    return req.ok


def dm(instance: str, token: str, user_id: str, text: str, replyId: str | None = None):
    body = {"text": text, "visibility": "specified", "visibleUserIds": [user_id]}
    if replyId is not None:
        body["replyId"] = replyId

    print(body)

    req = post(
        f"https://{instance}/api/notes/create",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    print("dm", req)

    return req.ok


def get_effective_name(i: dict):
    if i["host"] is None:
        return i["username"]
    return f"{i['username']}@{i['host']}"


def shitpost(instance: str, token: str, text: str):
    req = post(
        f"https://{instance}/api/notes/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "text": text,
        },
    )
    print("post", req)

    return req.ok


def quote(instance: str, token: str, post_id: str, text: str):
    req = post(
        f"https://{instance}/api/notes/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "renoteId": post_id,
            "text": text,
        },
    )
    print("post", req)

    return req.ok


def reply(instance: str, token: str, post_id: str, text: str):
    req = post(
        f"https://{instance}/api/notes/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "replyId": post_id,
            "text": text,
        },
    )

    return req.ok


def notifications(instance: str, token: str):
    req = post(
        f"https://{instance}/api/i/notifications",
        headers={
            "Authorization": f"Bearer {token}",
        },
        json={"limit": 10, "markAsRead": False, "includeTypes": ["reply", "mention"]},
    )

    if not req.ok:
        return []

    return req.json()


def get_user(instance: str, token: str, user_id: str):
    req = post(
        f"https://{instance}/api/users/show",
        headers={
            "Authorization": f"Bearer {token}",
        },
        json={"userId": user_id},
    )

    if not req.ok:
        return {}

    return req.json()
