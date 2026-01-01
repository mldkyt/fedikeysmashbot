from sqlalchemy import Connection, select, update, delete, insert

from database import user_prefs_table


def get_user_pref(c: Connection, u: str | dict, k: str, default: str = None) -> str:
    if isinstance(u, dict):
        u = u["id"]

    a = c.execute(
        select(user_prefs_table.c.value)
        .where((user_prefs_table.c.user == u) & (user_prefs_table.c.key == k))
    ).fetchone()

    if a is not None:
        return a[0]
    else:
        return default

def set_user_pref(c: Connection, u: str | dict, k: str, value: str) -> None:
    if isinstance(u, dict):
        u = u["id"]

    a = c.execute(
        select(user_prefs_table.c.value)
        .where((user_prefs_table.c.user == u) & (user_prefs_table.c.key == k))
    ).fetchone()

    if a is not None:
        c.execute(
            update(user_prefs_table)
            .where((user_prefs_table.c.key == k) & (user_prefs_table.c.user == u))
            .values(value=value)
        )
    else:
        c.execute(
            insert(user_prefs_table)
            .values(user=u, key=k, value=value)
        )
