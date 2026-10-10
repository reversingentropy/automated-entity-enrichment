"""
Re-ingestion of a later TTE snapshot.

TTE ships updated exports roughly every two months, so this path runs far more
often than the initial load, and gets it wrong silently if it gets it wrong.
Snapshot 2 renames one entity, adds a field to another, drops two, adds one,
and changes a link target.
"""

from datetime import date

import pytest

from src.load_tte.loader import MAX_MISSING_FRACTION, checksum
from src.load_tte.parse import parse

SNAP1 = "tests/fixtures/TTE-ORGANISATIONS_FULL_20260603.csv"
SNAP2 = "tests/fixtures/snapshot2/TTE-ORGANISATIONS_FULL_20260803.csv"


@pytest.fixture(scope="module")
def snapshots():
    return parse(SNAP1), parse(SNAP2)


def test_the_snapshot_date_advances(snapshots):
    a, b = snapshots
    assert a.snapshot == date(2026, 6, 3)
    assert b.snapshot == date(2026, 8, 3)


def test_key_uid_is_stable_so_updates_are_upserts_not_duplicates(snapshots):
    a, b = snapshots
    # A renamed entity keeps its uid, so it updates in place rather than
    # creating a second record under the new name.
    assert a.entities["300"].name == "33 Auction"
    assert b.entities["300"].name == "33 Auction Pte Ltd"


def test_a_new_field_appears_on_the_later_snapshot(snapshots):
    a, b = snapshots
    assert "Year Started" not in a.entities["100"].fields
    assert b.entities["100"].fields["Year Started"] == "1985"


def test_a_revised_value_replaces_the_earlier_one(snapshots):
    a, b = snapshots
    assert a.entities["100"].fields["Description"] == "A Singapore award."
    assert b.entities["100"].fields["Description"] == "A Singapore award, revised."


def test_entities_dropped_from_the_export_are_detectable(snapshots):
    a, b = snapshots
    # These are what the loader removes: deleted, or kept inactive if a
    # proposal still points at them.
    assert sorted(set(a.entities) - set(b.entities)) == ["500", "600"]


def test_new_entities_are_picked_up(snapshots):
    a, b = snapshots
    assert sorted(set(b.entities) - set(a.entities)) == ["700"]


def test_links_are_rebuilt_from_the_new_snapshot(snapshots):
    a, b = snapshots
    # Snapshot 2 drops entity 500, so its link goes with it. replace_links
    # deletes the previous set first, so stale links cannot survive an import.
    assert ("500", "300", "TAMtoENG") in a.links
    assert ("500", "300", "TAMtoENG") not in b.links
    assert ("200", "300", "CHItoENG") in b.links


def test_an_unchanged_file_has_an_identical_checksum():
    # The ledger skips re-ingesting identical content, but a corrected
    # re-upload under the same filename changes the checksum and is re-read.
    with open(SNAP1, encoding="utf-8-sig") as fh:
        content = fh.read()
    assert checksum(content) == checksum(content)
    assert checksum(content) != checksum(content + "\n")


def test_a_truncated_export_would_exceed_the_abort_threshold(snapshots):
    a, b = snapshots
    missing = len(set(a.entities) - set(b.entities)) / len(a.entities)
    # This fixture drops 2 of 7 (29%), which is above the 10% guard -- exactly
    # the case the threshold exists to stop from silently retiring live data.
    assert missing > MAX_MISSING_FRACTION


def test_a_night_with_no_new_export_downloads_nothing_and_requeues_nothing(monkeypatch):
    import src.job3_resolution.requeue as requeue
    from src.load_tte import __main__ as cli, loader, source

    reads, asked = [], []
    monkeypatch.setattr(source, "list_bucket", lambda: ["TTE-PEOPLE_FULL_20260902.csv"])
    monkeypatch.setattr(source, "read_bucket", lambda name: reads.append(name) or "")
    monkeypatch.setattr(loader, "loaded_names", lambda: {"TTE-PEOPLE_FULL_20260902.csv"})
    monkeypatch.setattr(requeue, "stale_entities", lambda: asked.append(1) or [])
    assert cli.main(["--new-only", "--requeue-stale"]) == 0
    assert reads == [] and asked == []


def _entities(pf):
    return list(pf.entities.values())


def _stored(pf):
    """Snapshot 1 as the loader would have stored it."""
    from src.load_tte.loader import stored_canonical
    return {e.uid: {"name": e.name, "vocabulary": e.vocabulary, "entity_type": e.entity_type,
                    "language": e.language, "fields": dict(e.fields), "canonical_uid": stored_canonical(e),
                    "is_active": True} for e in pf.entities.values()}


def test_a_reload_of_the_same_dump_rewrites_nothing(snapshots):
    from src.load_tte.loader import changed, dropped

    a, _ = snapshots
    assert changed(_entities(a), _stored(a)) == []
    assert dropped(_entities(a), set(), _stored(a)) == set()


def test_the_next_dump_writes_only_what_changed_and_drops_what_it_left_out(snapshots):
    from src.load_tte.loader import changed, dropped

    a, b = snapshots
    written = {e.uid for e in changed(_entities(b), _stored(a))}
    assert "700" in written                      # new
    assert written < set(b.entities)             # not everything
    assert dropped(_entities(b), set(), _stored(a)) == {"500", "600"}


def test_a_dropped_record_a_proposal_points_at_is_kept_not_deleted(snapshots):
    from src.load_tte.loader import removable

    a, b = snapshots
    delete, keep = removable({"500", "600"}, {"500"}, _entities(b), _stored(a))
    assert delete == {"600"} and keep == {"500"}


def test_the_delete_list_removes_a_record_the_dump_still_covers(snapshots):
    from src.load_tte.loader import check_plausible, dropped

    a, _ = snapshots
    stored = _stored(a)
    kept_in_file = [e for e in _entities(a) if e.uid != "300"]
    gone = dropped(kept_in_file, {"300"}, stored)
    assert gone == {"300"}
    check_plausible(kept_in_file, gone, {"300"}, stored)   # listed for deletion: not suspicious


def test_a_dump_zip_yields_only_our_vocabularies_and_its_delete_list():
    import io
    import zipfile

    from src.load_tte.dump import expand

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("LDMS/TTE/2026-09-01/mod/TTE-PEOPLE_FULL_20260902.csv", "Key UID,Key Descriptor\n1,A\n")
        z.writestr("LDMS/TTE/2026-09-01/mod/TTE-KOS_SUBJECTS_FULL_20260902.csv", "huge\n")
        z.writestr("LDMS/TTE/2026-09-01/del/TTE-DELETE_DELTA_20260901.txt", "5170635\n5170638\n")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("TTE-DELTA_20260901/LDMS.zip", inner.getvalue())
    csvs, deletes, skipped = expand(outer.getvalue())
    assert [name for name, _ in csvs] == ["TTE-PEOPLE_FULL_20260902.csv"]
    assert deletes == {"5170635", "5170638"} and skipped == ["TTE-KOS_SUBJECTS_FULL_20260902.csv"]
