"""
Reviewer accounts for the online desk, made from the command line.

    python -m src.export --account glenn@nlb.gov.sg "Glenn Hong"
    python -m src.export --account test@nlb.gov.sg "Test account" --test
    python -m src.export --accounts
    python -m src.export --reset-password glenn@nlb.gov.sg

The dashboard does the same by hand (Authentication > Users > Add user);
this is one line per reviewer with the secret key already in `.env`.
A password is generated and printed once; Supabase keeps only a hash of it,
so a forgotten one is replaced, never looked up.
`--test` marks the account so its decisions are left out when decisions
are collected.
"""

import secrets

from src.shared.supabase_client import get_client

ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_password(length: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_test(user) -> bool:
    """A test account: marked in app_metadata, which only the service role can set.
    Older ones carry the mark in user_metadata, and still count."""
    return bool((getattr(user, "app_metadata", None) or {}).get("test")
                or (getattr(user, "user_metadata", None) or {}).get("test"))


def create(email: str, name: str, test: bool = False, password: str | None = None) -> dict:
    """Create the account, confirmed, with the name the desk will show."""
    password = password or new_password()
    attrs = {"email": email, "password": password, "email_confirm": True, "user_metadata": {"name": name}}
    if test:
        attrs["app_metadata"] = {"test": True}
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
    out = []
    for u in get_client().auth.admin.list_users():
        meta = u.user_metadata or {}
        out.append({"id": u.id, "email": u.email or "", "name": meta.get("name") or "",
                    "test": is_test(u), "last_sign_in": (u.last_sign_in_at or "")})
    return sorted(out, key=lambda r: r["email"])
