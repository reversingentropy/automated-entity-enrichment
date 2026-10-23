"""
Reviewer accounts for the online desk, made from the command line.

    python -m src.export --account glenn@nlb.gov.sg "Glenn Hong"
    python -m src.export --account test@nlb.gov.sg "Test account" --test
    python -m src.export --accounts
    python -m src.export --reset-password glenn@nlb.gov.sg
    python -m src.export --account someone@nlb.gov.sg "Their Name" --password   # choose it yourself
    python -m src.export --mark-evaluator glenn@nlb.gov.sg
    python -m src.export --mark-admin EMAIL     # Approve and Decline on the Team page
    python -m src.export --approve EMAIL        # the same Approve, from here

The dashboard does the same by hand (Authentication > Users > Add user);
this is one line per reviewer with the secret key already in `.env`.
A password is generated and printed once; Supabase keeps only a hash of it,
so a forgotten one is replaced, never looked up. With `--password` (on
`--account` or `--reset-password`) you type one yourself instead, at a hidden
prompt, so it stays out of the shell's history and is not printed back.
`--test` marks the account so its decisions are left out when decisions
are collected. `--mark-evaluator` gives an account the desk's Evaluation page,
where the evaluation's sheets are labelled (sql/19_evaluation.sql).

People can also make their own account on the desk's sign-in screen. Such an account waits, reaching nothing,
until an admin approves it (sql/20_self_signup.sql); one made here is approved as it is made.
"""

import getpass
import secrets
from datetime import datetime

from src.shared.supabase_client import get_client

ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_password(length: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


SHORTEST = 8


def ask_password(ask=None) -> str:
    """A password typed twice at a hidden prompt; asked again until the two match and it is long enough."""
    ask = ask or getpass.getpass
    while True:
        first = ask(f"Password (at least {SHORTEST} characters, not shown): ")
        if len(first) < SHORTEST:
            print(f"  Too short: at least {SHORTEST} characters.")
            continue
        if ask("Same password again: ") == first:
            return first
        print("  The two did not match. Again:")


def is_test(user) -> bool:
    """A test account: marked in app_metadata, which only the service role can set.
    Older ones carry the mark in user_metadata, and still count."""
    return bool((getattr(user, "app_metadata", None) or {}).get("test")
                or (getattr(user, "user_metadata", None) or {}).get("test"))


def create(email: str, name: str, test: bool = False, password: str | None = None) -> dict:
    """Create the account, confirmed, with the name the desk will show."""
    password = password or new_password()
    attrs = {"email": email, "password": password, "email_confirm": True, "user_metadata": {"name": name},
             "app_metadata": {"approved": True, **({"test": True} if test else {})}}
    user = get_client().auth.admin.create_user(attrs).user
    return {"id": user.id, "email": email, "name": name, "test": test, "password": password}


def mark_test(email: str) -> str:
    """Make an existing account a test account: it can look at the desk but not write."""
    admin = get_client().auth.admin
    user = next((u for u in admin.list_users() if (u.email or "").lower() == email.strip().lower()), None)
    if user is None:
        raise ValueError(f"No account for {email}. `--accounts` lists them.")
    admin.update_user_by_id(user.id, {"app_metadata": {**(user.app_metadata or {}), "test": True}})
    return user.id


def _when(value) -> datetime | None:
    if not value:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def waiting_since() -> datetime | None:
    """When accounts made on the page started to wait for approval; None before sql/20 has run."""
    try:
        rows = get_client().from_("account_gate").select("since").execute().data
    except Exception:
        return None
    return _when(rows[0]["since"]) if rows else None


def is_waiting(user, since: datetime | None) -> bool:
    """Made on the page and not approved yet: the same rule as account_waiting() in sql/20."""
    meta = getattr(user, "app_metadata", None) or {}
    made = _when(getattr(user, "created_at", None))
    return bool(since and made and made > since and not meta.get("approved") and not meta.get("test"))


def mark(email: str, **flags) -> str:
    """Set marks in an account's app_metadata, keeping the rest. They count from the next sign-in."""
    admin = get_client().auth.admin
    user = next((u for u in admin.list_users() if (u.email or "").lower() == email.strip().lower()), None)
    if user is None:
        raise ValueError(f"No account for {email}. `--accounts` lists them.")
    admin.update_user_by_id(user.id, {"app_metadata": {**(user.app_metadata or {}), **flags}})
    return user.id


def is_evaluator(user) -> bool:
    """An account that labels the evaluation's sheets: marked in app_metadata, like a test account."""
    return bool((getattr(user, "app_metadata", None) or {}).get("evaluator"))


def mark_evaluator(email: str, on: bool = True) -> str:
    """Give an existing account the Evaluation page, or take it away. It shows from their next sign-in."""
    admin = get_client().auth.admin
    user = next((u for u in admin.list_users() if (u.email or "").lower() == email.strip().lower()), None)
    if user is None:
        raise ValueError(f"No account for {email}. `--accounts` lists them.")
    admin.update_user_by_id(user.id, {"app_metadata": {**(user.app_metadata or {}), "evaluator": on}})
    return user.id


def reset_password(email: str, password: str | None = None) -> dict:
    """Give an existing account a new password; the old one stops working."""
    admin = get_client().auth.admin
    user = next((u for u in admin.list_users() if (u.email or "").lower() == email.strip().lower()), None)
    if user is None:
        raise ValueError(f"No account for {email}. `--accounts` lists them.")
    password = password or new_password()
    admin.update_user_by_id(user.id, {"password": password})
    return {"id": user.id, "email": user.email, "password": password}


def holds() -> list[dict]:
    """Which card each reviewer has on their desk, and since when."""
    client = get_client()
    emails = {u["id"]: u["email"] for u in listing()}
    names = {r["key"]: r["entity"] for r in client.from_("deck").select("key, entity").execute().data}
    rows = client.from_("claims").select("card_key, reviewer, claimed_at").order("claimed_at").execute().data
    return [{"email": emails.get(r["reviewer"], r["reviewer"]), "entity": names.get(r["card_key"], r["card_key"]),
             "since": r["claimed_at"]} for r in rows]


def release(email: str) -> int:
    """Put a reviewer's held card back in the pile, for when they are away."""
    user = next((u for u in listing() if u["email"].lower() == email.strip().lower()), None)
    if user is None:
        raise ValueError(f"No account for {email}. `--accounts` lists them.")
    return len(get_client().from_("claims").delete().eq("reviewer", user["id"]).execute().data or [])


def listing() -> list[dict]:
    out, since = [], waiting_since()
    for u in get_client().auth.admin.list_users():
        meta = u.user_metadata or {}
        out.append({"id": u.id, "email": u.email or "", "name": meta.get("name") or "",
                    "test": is_test(u), "evaluator": is_evaluator(u), "waiting": is_waiting(u, since),
                    "admin": bool((u.app_metadata or {}).get("admin")), "last_sign_in": (u.last_sign_in_at or "")})
    return sorted(out, key=lambda r: r["email"])
