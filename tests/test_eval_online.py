"""The labelled sheets on the desk's Evaluation page (src/eval/online.py): what goes up, and the labels coming back
as the returned sheets the scorer has always read. Nothing here reaches Supabase or a news site."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.eval import online

REAL = Path("data/eval")
CNA, ST, ZB = "https://www.channelnewsasia.com/business/", "https://www.straitstimes.com/singapore/", "https://www.zaobao.com/news/singapore/"


def sheet(path: Path, rows: list[dict]) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        pd.DataFrame({"read me": ["fill in the last column"]}).to_excel(w, sheet_name="start here", index=False)
        pd.DataFrame(rows).to_excel(w, sheet_name="rows", index=False)


@pytest.fixture
def folder(tmp_path):
    sheet(tmp_path / "1-relevance.xlsx", [
        {"url": ST + "a", "source": "st", "title": "Library opens", "description": "A new library.", "published": "2026-09-01", "relevant": ""},
        {"url": ZB + "b", "source": "zb", "title": "图书馆", "description": "新图书馆", "published": "2026-09-02", "relevant": ""}])
    (tmp_path / "1-relevance-key.json").write_text(json.dumps([
        {"url": ST + "a", "app_said": True, "stratum": "app said yes", "weight": 1.0},
        {"url": ZB + "b", "app_said": False, "stratum": "named a TTE record", "weight": 3.0}]), encoding="utf-8")
    sheet(tmp_path / "2-matching.xlsx", [
        {"id": 7, "name": "Lee Theng Kiat", "name_in_english": "", "evidence": "Mr Lee Theng Kiat will chair it.", "article": "New chair",
         "url": CNA + "m", "tte_id": "185", "tte_name": "Lee, Theng Kiat", "tte_fields": "Occupation: Civil servant · Country: Singapore", "same": ""},
        {"id": 8, "name": "李", "name_in_english": "Li", "evidence": "李先生说", "article": "新主席", "url": ZB + "m",
         "tte_id": "186", "tte_name": "Li, Ming", "tte_fields": "", "same": ""}])
    (tmp_path / "2-matching-key.json").write_text(json.dumps([
        {"id": 7, "app_said_same": True, "tte_id": "185", "script": "latin"},
        {"id": 8, "app_said_same": False, "tte_id": "186", "script": "chinese"}]), encoding="utf-8")
    blank = {"entity": "", "type": "", "fields": "", "evidence": "", "verdict": "", "field_errors": "", "missed": ""}
    sheet(tmp_path / "3-extraction.xlsx", [
        {"article_url": CNA + "x", "language": "en", "article": "Robot maker raises funds", "entity": "Acme Robotics", "type": "ORGANISATION",
         "fields": "Country: Singapore · Founder: Chng Siew Hern", "evidence": "Acme Robotics raised $5 million.", "verdict": "", "field_errors": "", "missed": ""},
        {"article_url": CNA + "x", "language": "en", "article": "Robot maker raises funds", "entity": "Chng Siew Hern", "type": "PERSON",
         "fields": "", "evidence": "founded by Chng Siew Hern", "verdict": "", "field_errors": "", "missed": ""},
        {"article_url": CNA + "x", "language": "en", "article": "Robot maker raises funds", "entity": "Acme Robotics", "type": "ORGANISATION",
         "fields": "Country: Singapore", "evidence": "again", "verdict": "", "field_errors": "", "missed": ""},
        {"article_url": CNA + "x", "language": "en", "article": "Robot maker raises funds", **blank},
        {"article_url": ZB + "y", "language": "zh", "article": "图书馆重开", "entity": "兀兰区域图书馆", "type": "ORGANISATION",
         "fields": "Country: Singapore", "evidence": "兀兰区域图书馆重开", "verdict": "", "field_errors": "", "missed": ""},
        {"article_url": ZB + "y", "language": "zh", "article": "图书馆重开", **blank}])
    (tmp_path / "3-extraction-key.json").write_text(json.dumps([
        {"entity_id": 1, "article_id": 10, "language": "en", "entity": "Acme Robotics", "type": "ORGANISATION"}]), encoding="utf-8")
    return tmp_path


def test_a_fields_line_splits_at_each_field_name_only():
    assert online.fields("Country: Singapore · Founder: Chng Siew Hern") == [["Country", "Singapore"], ["Founder", "Chng Siew Hern"]]
    # a dot inside a value, not followed by a field name, stays in the value
    assert online.fields("Description: Robots · drones and more · Founded: 2019") == [
        ["Description", "Robots · drones and more"], ["Founded", "2019"]]
    assert online.fields("") == [] and online.fields(None) == []
    assert online.fields("just words") == [["", "just words"]]


def test_the_rows_carry_nothing_of_the_apps_answer(folder):
    rows = online.items(folder)
    by = {t: [r for r in rows if r["task"] == t] for t in online.TASKS}
    assert [len(by[t]) for t in online.TASKS] == [2, 2, 2]
    for r in rows:
        assert not set(r["body"]) & online.KEY_COLUMNS
        assert "app_said" not in json.dumps(r["body"])
    assert "relevant" not in by["relevance"][0]["body"] and "same" not in by["matching"][0]["body"]
    # each row in sheet order, in the language it is read in
    assert [r["ord"] for r in by["relevance"]] == [1, 2] and [r["lang"] for r in by["relevance"]] == ["en", "zh"]
    assert [r["lang"] for r in by["matching"]] == ["en", "zh"] and by["matching"][0]["item"] == "7"
    assert by["matching"][0]["body"]["tte_fields"] == [["Occupation", "Civil servant"], ["Country", "Singapore"]]
    # one row per article, each name once, the article's text beside it
    x = by["extraction"][0]
    assert x["item"] == CNA + "x" and [n["entity"] for n in x["body"]["names"]] == ["Acme Robotics", "Chng Siew Hern"]
    assert x["body"]["names"][0]["fields"] == [["Country", "Singapore"], ["Founder", "Chng Siew Hern"]]
    assert x["body"]["text"] == "" and by["extraction"][1]["lang"] == "zh"
    assert online.items(folder, {CNA + "x": "Acme Robotics, founded by"})[4]["body"]["text"] == "Acme Robotics, founded by"


def test_each_article_is_fetched_once_and_a_failed_one_again(folder):
    asked = []

    def fetch(url):
        asked.append(url)
        if url.startswith(ZB):
            raise RuntimeError("timed out")
        return "the text of " + url

    got = online.fetch_texts(folder, fetch=fetch, pause=0)
    assert asked == [CNA + "x", ZB + "y"] and got == {CNA + "x": "the text of " + CNA + "x"}
    asked.clear()
    online.fetch_texts(folder, fetch=fetch, pause=0)
    assert asked == [ZB + "y"]        # kept beside the sheets: only the one that failed is tried again


def labels():
    a, b = "aaaa1111-0000", "bbbb2222-0000"
    return [
        {"task": "relevance", "item": ST + "a", "labeller": a, "label": {"relevant": True}, "seconds": 50},
        {"task": "relevance", "item": ZB + "b", "labeller": a, "label": {"relevant": False}, "seconds": 70},
        {"task": "matching", "item": "7", "labeller": a, "label": {"same": "Y"}, "seconds": 10},
        {"task": "matching", "item": "8", "labeller": a, "label": {"same": "?"}, "seconds": 10},
        {"task": "matching", "item": "8", "labeller": b, "label": {"same": "N"}, "seconds": 5},
        {"task": "extraction", "item": CNA + "x", "labeller": a, "seconds": 120, "label": {
            "names": {"Acme Robotics": {"verdict": "ok", "wrong_fields": ["Founder"]}, "Chng Siew Hern": {"verdict": "not_worth", "wrong_fields": []}},
            "missed": ["Lim Bee Hoon", "Tan Ah Kow"]}},
    ]


def test_the_labels_come_back_as_sheets_the_scorer_reads(folder, capsys):
    from src.eval.score import report

    done = online.returned(folder, labels(), {"aaaa1111-0000": "Alex Tan", "bbbb2222-0000": "Alex Tan"})
    assert done == {"Alex-Tan": {"relevance": 2, "matching": 2, "extraction": 1}, "Alex-Tan-bbbb": {"matching": 1}}
    back = folder / "returned"
    rel = pd.read_excel(back / "1-relevance-Alex-Tan.xlsx", sheet_name="rows", dtype=str, keep_default_na=False)
    assert list(rel.relevant) == ["TRUE", "FALSE"]
    assert pd.read_excel(back / "1-relevance-Alex-Tan.xlsx", sheet_name="start here").iloc[0, 0] == 4   # 260 seconds
    ext = pd.read_excel(back / "3-extraction-Alex-Tan.xlsx", sheet_name="rows", dtype=str, keep_default_na=False)
    assert list(ext.verdict) == ["ok", "not_worth", "ok", "", "", ""]
    assert list(ext.field_errors) == ["Founder", "", "Founder", "", "", ""]
    # the missed names on the article's blank last row, one per line, and nowhere else
    assert list(ext.missed) == ["", "", "", "Lim Bee Hoon\nTan Ah Kow", "", ""]
    assert not (back / "3-extraction-Alex-Tan-bbbb.xlsx").exists()

    capsys.readouterr()
    assert report(back, folder) == 0
    said = capsys.readouterr().out
    assert "labelled 2 of 2 rows; cannot tell:" in said
    assert "entities marked 2, names reported missing 2" in said
    assert "split on proposal 8" in said            # both labellers' sheets were read


def test_pull_leaves_out_test_accounts(folder, monkeypatch):
    users = [SimpleNamespace(id="aaaa1111-0000", email="alex@nlb.gov.sg", user_metadata={"name": "Alex"}, app_metadata={"evaluator": True}),
             SimpleNamespace(id="bbbb2222-0000", email="test@nlb.gov.sg", user_metadata={}, app_metadata={"test": True, "evaluator": True})]
    client = SimpleNamespace(auth=SimpleNamespace(admin=SimpleNamespace(list_users=lambda: users)), from_=None)
    monkeypatch.setattr("src.shared.supabase_client.get_client", lambda: client)
    monkeypatch.setattr("src.shared.pagination.fetch_all", lambda build, order="id": labels())
    assert online.pull(folder) == {"Alex": {"relevance": 2, "matching": 2, "extraction": 1}}
    assert not list((folder / "returned").glob("*test*"))


@pytest.mark.skipif(not (REAL / "1-relevance.xlsx").exists(), reason="the evaluation sheets are not on this PC")
def test_the_real_sheets_go_up_without_their_keys():
    rows = online.items(REAL)
    assert {r["task"] for r in rows} == set(online.TASKS)
    assert not any(set(r["body"]) & online.KEY_COLUMNS for r in rows)
    assert len({(r["task"], r["item"]) for r in rows}) == len(rows)
    key = json.loads((REAL / "1-relevance-key.json").read_text(encoding="utf-8"))
    assert len([r for r in rows if r["task"] == "relevance"]) == len(key)


def test_marking_an_evaluator_keeps_the_accounts_other_marks(monkeypatch):
    from src.export import accounts

    users = [SimpleNamespace(id="u1", email="Alex@nlb.gov.sg", app_metadata={"test": True, "provider": "email"}, user_metadata={})]
    sent = []
    admin = SimpleNamespace(list_users=lambda: users, update_user_by_id=lambda uid, attrs: sent.append((uid, attrs)))
    monkeypatch.setattr(accounts, "get_client", lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)))
    assert accounts.mark_evaluator(" alex@nlb.gov.sg ") == "u1"
    assert sent == [("u1", {"app_metadata": {"test": True, "provider": "email", "evaluator": True}})]
    accounts.mark_evaluator("alex@nlb.gov.sg", on=False)
    assert sent[-1][1]["app_metadata"]["evaluator"] is False
    with pytest.raises(ValueError):
        accounts.mark_evaluator("nobody@nlb.gov.sg")
    assert accounts.is_evaluator(SimpleNamespace(app_metadata={"evaluator": True})) and not accounts.is_evaluator(SimpleNamespace(app_metadata=None))


def test_the_labelling_guide_was_written_from_the_prompts_as_they_are():
    """A prompt changed since the guide was written from it: labellers would be judging by the old rule."""
    from src.eval.guide import stale

    assert not stale(), "\n".join(stale())


def test_the_guide_has_rules_for_every_sheet_and_names_its_prompts():
    from src.eval.guide import ROOT, sections

    got = sections()
    assert set(got) == {"general", *online.TASKS}
    for task in online.TASKS:
        sec = got[task]
        assert sec["html"].count("<b>") >= 2 and len(sec["html"]) < 1500          # a few lines, not a manual
        assert sec["sources"] and all((ROOT / p).exists() for p, _ in sec["sources"])
    assert [p for p, _ in got["relevance"]["sources"]] == ["prompts/relevance.txt"]
    assert [p for p, _ in got["matching"]["sources"]] == ["prompts/resolution.txt"]
    assert "prompts/extraction.txt" in [p for p, _ in got["extraction"]["sources"]]
    assert "Written from" not in json.dumps(got)


def test_a_changed_prompt_is_caught(tmp_path):
    from src.eval.guide import stale, version

    guide = tmp_path / "guide.md"
    guide.write_text("## Relevance {#relevance}\n\nWritten from `prompts/relevance.txt` (version 00000000).\n", encoding="utf-8")
    said = stale(guide)
    assert len(said) == 1 and "prompts/relevance.txt" in said[0] and version("prompts/relevance.txt") in said[0]


def test_the_guide_markdown_becomes_safe_html():
    from src.eval.guide import to_html

    got = to_html("### Yes\n\n- **Yes:** a change\n  carried on\n  - nested <b>\n- `code` and *this*\n\nA <para>.")
    assert got == ("<h3>Yes</h3><ul><li><b>Yes:</b> a change carried on<ul><li>nested &lt;b&gt;</li></ul></li>"
                   "<li><code>code</code> and <i>this</i></li></ul><p>A &lt;para&gt;.</p>")


def test_the_online_page_carries_the_guide():
    from src.export.site import GUIDE_MARK, online_page

    page = online_page(Path("prototype/desk.template.html").read_text(encoding="utf-8"), "https://x.supabase.co", "anon")
    assert GUIDE_MARK not in page
    blob = page.split("const EV_GUIDE = ", 1)[1].split(";\n", 1)[0]
    assert "</" not in blob
    assert json.loads(blob.replace("<\\/", "</"))["matching"]["title"] == "Matching"
