"""
The desk's queue (sql/15_desk_queue.sql, sql/16_desk_groups.sql), what the page's key can reach (sql/17) and the feeds (sql/18) in a real Postgres: who is given which record, for how long, and who may decide it.

Runs the desk's own SQL (sql/11, sql/15, sql/16, sql/17) in a throwaway Postgres 16 container, on top of just enough of Supabase
(tests/sql/supabase_stub.sql): each call is made as a signed-in reviewer, through the same role and request
settings Supabase uses. Needs Docker; skipped without it. Nothing reaches the project's database.
"""

import json
import shutil
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKER = shutil.which("docker")
NAME = f"tte-desk-queue-test-{uuid.uuid4().hex[:8]}"


def docker_up() -> bool:
    if not DOCKER:
        return False
    try:
        return subprocess.run([DOCKER, "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not docker_up(), reason="needs Docker for a throwaway Postgres")

A, B, C = (f"00000000-0000-0000-0000-00000000000{n}" for n in (1, 2, 3))
TESTER = "00000000-0000-0000-0000-000000000009"


@pytest.fixture(scope="module")
def db():
    subprocess.run([DOCKER, "run", "-d", "--rm", "--name", NAME, "-e", "POSTGRES_PASSWORD=test", "postgres:16-alpine"],
                   check=True, capture_output=True, timeout=300)
    try:
        for _ in range(60):
            if subprocess.run([DOCKER, "exec", NAME, "pg_isready", "-U", "postgres", "-q"]).returncode == 0:
                break
            time.sleep(1)
        time.sleep(1)
        # sql/15 and sql/16 twice each: they must be safe to run again, in either order
        for f in ("tests/sql/supabase_stub.sql", "sql/11_desk_online.sql", "sql/15_desk_queue.sql", "sql/15_desk_queue.sql",
                  "sql/16_desk_groups.sql", "sql/15_desk_queue.sql", "sql/16_desk_groups.sql",
                  "sql/17_article_private.sql", "sql/17_article_private.sql",
                  "sql/18_malay_tamil_feeds.sql", "sql/18_malay_tamil_feeds.sql"):
            run_sql((ROOT / f).read_text(encoding="utf-8"))
        run_sql("insert into auth.users (id) values " + ",".join(f"('{u}')" for u in (A, B, C, TESTER)))
        yield
    finally:
        subprocess.run([DOCKER, "rm", "-f", NAME], capture_output=True)


def run_sql(sql: str, user: str | None = None, test: bool = False) -> str:
    """Run SQL as the database owner, or, given a user, as that signed-in reviewer."""
    if user:
        claims = json.dumps({"sub": user, "role": "authenticated", "app_metadata": {"test": True} if test else {}})
        sql = (f"begin; set local role authenticated; set local request.jwt.claims to '{claims}';\n{sql}\ncommit;")
    done = subprocess.run([DOCKER, "exec", "-i", NAME, "psql", "-U", "postgres", "-tAq", "-v", "ON_ERROR_STOP=1"],
                          input=sql, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError(done.stderr.strip())
    return done.stdout.strip()


def call(user: str, fn: str, *args, test: bool = False):
    """One of the desk's functions, as a reviewer; the result as Python."""
    out = run_sql(f"select to_jsonb({fn}({', '.join(args)}));", user, test)
    return json.loads(out) if out else None


def langs(*codes) -> str:
    return "array[" + ",".join(f"'{c}'" for c in codes) + "]::text[]"


def lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def deck(*cards):
    """Fresh deck, no holds, no decisions. Each card: (key, type, date, language, pids), and True for a new record."""
    rows = []
    for i, (key, kind, date, lang, pids, *new) in enumerate(cards):
        link = "https://www.zaobao.com/news/singapore/story1" if lang == "zh" else "https://www.straitstimes.com/singapore/a"
        card = {"key": key, "i": i, "pids": pids, "sources": [{"link": link, "date": date}], "isNew": bool(new and new[0])}
        rows.append(f"({lit(key)}, {lit(kind)}, {lit(key)}, {lit(json.dumps(card))}::jsonb)")
    run_sql("truncate public.claims, public.reviews; delete from public.deck;"
            "insert into public.deck (key, type, entity, card) values " + ",".join(rows) + ";")


def holds() -> dict[str, str]:
    out = run_sql("select coalesce(jsonb_object_agg(card_key, reviewer), '{}') from public.claims;")
    return json.loads(out)


def rows(*pids, verdict="approve") -> str:
    return lit(json.dumps([{"pid": p, "verdict": verdict, "decision": {"kind": verdict}} for p in pids])) + "::jsonb"


def test_the_next_record_is_the_newest_in_your_languages_and_type_and_you_hold_one_at_a_time(db):
    deck(("old", "PERSON", "2026-10-01", "en", [1]), ("new", "PERSON", "2026-10-11", "en", [2]),
         ("zh", "PERSON", "2026-10-12", "zh", [3]), ("org", "ORGANISATION", "2026-10-12", "en", [4]))
    assert call(A, "take_next", langs("en")) == "org"                       # newest first, Chinese skipped
    assert call(A, "take_next", langs("en"), "'people'") == "new"           # the type chosen
    assert holds() == {"new": A}                                            # taking the next gave back the last
    for _ in range(5):                                                      # switching quickly: still one
        call(A, "take_next", langs("en", "zh"))
        call(A, "take_next", langs("en"), "'organisations'")
    assert list(holds().values()) == [A]


def test_updating_and_creating_are_separate_groups(db):
    """A new person is under "new records", not "people"; a change to a building is one of the "other changes"."""
    deck(("p", "PERSON", "2026-10-12", "en", [1]), ("p-new", "PERSON", "2026-10-13", "en", [2], True),
         ("b", "FACILITY", "2026-10-11", "en", [3]), ("act-new", "LEGAL_ACT", "2026-10-10", "en", [4], True))
    assert dict(line.split("|") for line in run_sql("select key, grp from public.deck order by key;").splitlines()) == \
        {"act-new": "new records", "b": "other changes", "p": "people", "p-new": "new records"}
    assert call(A, "take_next", langs("en"), "'people'") == "p"             # the newer new person is not offered
    assert call(A, "take_next", langs("en"), "'other changes'") == "b"
    assert call(A, "take_next", langs("en"), "'new records'") == "p-new"
    assert call(B, "take_next", langs("en"), "'new records'") == "act-new"
    assert call(C, "take_next", langs("en"), "'new records'") is None


def test_two_reviewers_asking_at_the_same_instant_get_different_records(db):
    deck(*[(f"k{n:02}", "PERSON", f"2026-10-{n % 28 + 1:02}", "en", [100 + n]) for n in range(25)])
    users = [str(uuid.UUID(int=1000 + n)) for n in range(12)]
    run_sql("insert into auth.users (id) values " + ",".join(f"('{u}')" for u in users) + " on conflict do nothing;")
    start = time.time() + 3
    sql = f"select pg_sleep_until(to_timestamp({start})); select take_next({langs('en')});"
    with ThreadPoolExecutor(len(users)) as pool:
        got = list(pool.map(lambda u: run_sql(sql, u).splitlines()[-1], users))
    assert all(got) and len(set(got)) == len(users)                        # everyone got one, no two the same
    held = holds()
    assert len(held) == len(users) and sorted(held.values()) == sorted(users)


def test_a_record_left_alone_for_an_hour_goes_back_to_the_pile_and_its_late_decision_is_refused(db):
    deck(("x", "PERSON", "2026-10-12", "en", [1]), ("y", "PERSON", "2026-10-11", "en", [2]))
    assert call(A, "take_next", langs("en")) == "x"
    assert call(B, "take_next", langs("en")) == "y"                         # A's hold is live: B is given the next
    assert call(A, "renew_card", "'x'") is True
    run_sql("update public.claims set claimed_at = now() - interval '61 minutes' where card_key = 'x';")
    assert call(C, "take_next", langs("en")) == "x"                         # lapsed: back in the pile
    assert call(A, "renew_card", "'x'") is False
    assert call(A, "decide", "'x'", rows(1)) == {"saved": 0, "reason": "not held"}
    assert call(C, "decide", "'x'", rows(1))["saved"] == 1


def test_a_decision_gives_the_record_back_and_hands_over_the_next_in_one_step(db):
    deck(("x", "PERSON", "2026-10-12", "en", [1, 2]), ("y", "PERSON", "2026-10-11", "en", [3]))
    call(A, "take_next", langs("en"))
    out = call(A, "decide", "'x'", rows(1, 2), langs("en"), "'all'")
    assert out == {"saved": 2, "refused": [], "next": "y"} and holds() == {"y": A}
    assert call(B, "take_next", langs("en")) is None                        # x is decided, y is A's: nothing for B
    assert call(A, "decide", "'y'", rows(99)) == {"saved": 0, "refused": [99], "next": None}   # not y's proposal


def test_new_news_about_a_decided_record_brings_it_back_for_the_new_proposal_only(db):
    deck(("x", "PERSON", "2026-10-10", "en", [1]))
    call(A, "take_next", langs("en")); call(A, "decide", "'x'", rows(1))
    assert call(B, "take_next", langs("en")) is None
    run_sql("""update public.deck set card = jsonb_set(card, '{pids}', '[1, 2]') where key = 'x';""")   # tonight's publish
    assert call(B, "take_next", langs("en")) == "x"
    out = call(B, "decide", "'x'", rows(1, 2, verdict="reject"))
    assert out["saved"] == 1 and out["refused"] == [1]                      # A's decision is not overwritten
    assert run_sql("select reviewer || ':' || verdict from public.reviews order by pid;").splitlines() == [f"{A}:approve", f"{B}:reject"]


def test_a_record_kept_for_review_goes_to_someone_else_never_back_to_who_kept_it(db):
    deck(("x", "PERSON", "2026-10-12", "en", [1]), ("y", "PERSON", "2026-10-01", "en", [2]))
    call(A, "take_next", langs("en"))
    assert call(A, "decide", "'x'", rows(1, verdict="unsure"), langs("en"), "'all'")["next"] == "y"
    call(A, "release_card", "'y'")
    assert call(A, "take_next", langs("en")) == "y"                         # A is not given x again
    assert call(B, "take_next", langs("en")) == "x"                         # B is
    call(B, "decide", "'x'", rows(1, verdict="unsure"))                     # B unsure too: a third person
    assert call(C, "take_next", langs("en")) == "x"
    call(C, "decide", "'x'", rows(1))
    kept = json.loads(run_sql("select decision->'kept_by' from public.reviews where pid = 1;"))
    assert run_sql("select reviewer from public.reviews where pid = 1;") == C and kept == [A, B]


def test_you_can_change_your_own_decision_until_it_is_done_in_tte_but_never_a_colleagues(db):
    deck(("x", "PERSON", "2026-10-12", "en", [1]))
    call(A, "take_next", langs("en")); call(A, "decide", "'x'", rows(1))
    assert call(B, "claim_card", "'x'") is False                            # B did not decide it: not B's to change
    assert call(A, "claim_card", "'x'") is True
    assert call(B, "claim_card", "'x'") is False                            # and A holds it now
    assert call(A, "decide", "'x'", rows(1, verdict="reject"))["saved"] == 1
    assert call(A, "mark_done", "array[1]::bigint[]", "true") == 1
    call(A, "claim_card", "'x'")
    assert call(A, "decide", "'x'", rows(1))["refused"] == [1]              # done in TTE: fixed
    assert run_sql("select verdict from public.reviews where pid = 1;") == "reject"


def test_reviewers_cannot_write_decisions_or_holds_directly_and_a_test_account_writes_nothing(db):
    deck(("x", "PERSON", "2026-10-12", "en", [1]))
    with pytest.raises(RuntimeError, match="permission denied"):
        run_sql(f"insert into public.reviews (pid, card_key, reviewer, verdict, decision) values (1, 'x', '{A}', 'approve', '{{}}');", A)
    with pytest.raises(RuntimeError, match="permission denied"):
        run_sql(f"insert into public.claims (card_key, reviewer) values ('x', '{A}');", A)
    assert call(TESTER, "take_next", langs("en"), test=True) is None
    assert call(TESTER, "claim_card", "'x'", test=True) is False
    assert call(TESTER, "decide", "'x'", rows(1), test=True)["reason"] == "not allowed"
    assert holds() == {} and run_sql("select count(*) from public.reviews;") == "0"


def test_taking_the_next_record_stays_fast_with_ten_thousand_records(db):
    # Worked out from each card's JSON, this took up to 5 seconds at 10,000 records; on the stored, indexed columns
    # 24 to 30 ms, and 90 ms with the newest 9,500 all decided. A generous limit, so a slow machine does not fail it.
    run_sql("""truncate public.claims, public.reviews; delete from public.deck;
      insert into public.deck (key, type, entity, card)
      select 'k' || n, case n % 3 when 0 then 'PERSON' when 1 then 'ORGANISATION' else 'FACILITY' end, 'e' || n,
             jsonb_build_object('key', 'k' || n, 'i', n, 'pids', jsonb_build_array(n * 2, n * 2 + 1),
               'sources', jsonb_build_array(jsonb_build_object('pid', n * 2,
                 'date', to_char(date '2026-10-12' - n / 100, 'YYYY-MM-DD'),
                 'link', case when n % 3 = 0 then 'https://www.zaobao.com/x' else 'https://www.straitstimes.com/x' end)))
      from generate_series(1, 10000) n;
      insert into public.reviews (pid, card_key, reviewer, verdict, decision)
      select p, 'k' || (p / 2), 'REVIEWER', 'approve', '{}'::jsonb from generate_series(2, 19001) p;   -- the newest 9,500 decided
      analyze public.deck; analyze public.reviews;
      create or replace function public.ms_to_take_next(langs text[], grp text) returns jsonb language plpgsql as $$
        declare t timestamptz := clock_timestamp(); k text;
        begin k := public.take_next(langs, grp);
              return jsonb_build_object('key', k, 'ms', extract(epoch from clock_timestamp() - t) * 1000); end $$;
      grant execute on function public.ms_to_take_next(text[], text) to authenticated;""".replace("REVIEWER", C))
    for langs_, grp in ((langs("en"), "'all'"), (langs("en", "zh"), "'people'"), (langs("zh"), "'all'")):
        got = call(A, "ms_to_take_next", langs_, grp)
        assert got["key"] and int(got["key"][1:]) > 9500, got     # the newest record still open
        assert got["ms"] < 1000, got


def test_a_record_is_settled_when_every_proposal_has_a_final_decision_and_unsettled_by_new_news(db):
    deck(("x", "PERSON", "2026-10-12", "en", [1, 2]))
    settled = lambda: run_sql("select settled from public.deck where key = 'x';")
    call(A, "take_next", langs("en"))
    call(A, "decide", "'x'", lit(json.dumps([{"pid": 1, "verdict": "approve", "decision": {}},
                                              {"pid": 2, "verdict": "unsure", "decision": {}}])) + "::jsonb")
    assert settled() == "f"                                                 # one kept for review: still open
    call(B, "take_next", langs("en")); call(B, "decide", "'x'", rows(2))
    assert settled() == "t"
    run_sql("update public.deck set card = jsonb_set(card, '{pids}', '[1, 2, 3]') where key = 'x';")   # tonight's publish
    assert settled() == "f" and call(C, "take_next", langs("en")) == "x"


def test_the_pages_key_reads_no_article_and_no_feed(db):
    """The public key in the desk's page could read every article: a policy from before this repository, and a grant."""
    run_sql('grant select on public.article to anon, service_role; insert into public.article (id) values (1) on conflict do nothing;'
            'drop policy if exists "read for all" on public.article;'
            'create policy "read for all" on public.article for select to anon using (true);')
    assert run_sql("set role anon; select count(*) from public.article;").splitlines()[-1] == "1"       # the hole, as it was
    run_sql((ROOT / "sql" / "17_article_private.sql").read_text(encoding="utf-8"))
    for role, table in (("anon", "article"), ("authenticated", "article"), ("anon", "rss_feeds"), ("authenticated", "rss_feeds")):
        with pytest.raises(RuntimeError, match="permission denied"):
            run_sql(f"set role {role}; select count(*) from public.{table};")
    assert run_sql("set role service_role; select count(*) from public.article;").splitlines()[-1] == "1"   # the jobs still can


def test_the_malay_and_tamil_feeds_are_added_once_and_keep_only_singapore_links(db):
    """sql/18, run twice by the fixture: two feeds after the three, each with the pattern Job 0 filters its links by."""
    feeds = run_sql("select id || '|' || source || '|' || coalesce(keep, '-') from public.rss_feeds order by id;").splitlines()
    assert feeds == ["1|Channel News Asia|-", "2|Straits Times|-", "3|Lianhe Zaobao|-",
                     "4|Berita Harian|\\.sg/singapura/", "5|Tamil Murasu|\\.sg/(singapore|community)/"]
    kept = run_sql("""select string_agg(split_part(u, '/', 4), ',' order by u) from public.rss_feeds f,
        unnest(array['https://www.beritaharian.sg/singapura/a', 'https://www.beritaharian.sg/malaysia/b',
                     'https://www.tamilmurasu.com.sg/singapore/c', 'https://www.tamilmurasu.com.sg/community/d',
                     'https://www.tamilmurasu.com.sg/india/e']) u
        where f.keep is not null and u ~ f.keep;""").splitlines()[-1]
    assert kept == "singapura,community,singapore"   # by link: Berita Harian first; malaysia and india left out
