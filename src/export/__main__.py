"""
Export resolution proposals to CSV for human review.

Stage 6 in miniature. `entities` is a read-only mirror of TTE, so approved
changes leave as a spreadsheet for librarians to apply in TTE proper rather
than being written back here -- the next authority import would overwrite them.

Eight columns by default, in reading order: which entity, what change, what the
record says now, which TTE record, which article, then your verdict and an
optional note. Flags sort to the top, since they are rare and need a person.

Fill in `verdict` as one of:

  yes     apply this change to TTE
  no      wrong match, or a change that should not be made
  edit    right record, but the wording needs fixing -- say how in `note`

Leave `verdict` blank on anything you are unsure about; a blank is a real
answer and means "someone else should look".

Pass --format full for uids, similarity scores and the model's reasoning.

A labelled file is also the seed of an evaluation set: freeze these cases and
any future prompt change can be checked against them instead of eyeballed.

  python -m src.export                      # writes proposals.csv
  python -m src.export --format full        # everything, for debugging
  python -m src.export --action FLAG_AMBIGUOUS

To collect what the librarians decided, from the desk's CSVs in a folder or
from the online desk's `reviews` table:

  python -m src.export --reviews reviews_dir/ --out decisions.csv
  python -m src.export --reviews table --out decisions.csv
  python -m src.export --weekly [--since YYYY-MM-DD]  # the week's changes, as the Excel file
  python -m src.export --numbers                     # every count the documents quote, dated
  python -m src.export --logs                        # the evaluation's change and weekly logs, as CSVs
  python -m src.export --notify [--print-only]       # the daily email, only to reviewers with something to do

That writes one row per reviewer per proposal, so where two people disagreed
both verdicts are visible rather than one having replaced the other.

The online desk:

  python -m src.export --publish             # the deck to the database, nightly
  python -m src.export --site data/dist/site # index.html, served locally or anywhere
  python -m src.export --requests            # who has asked for an account
  python -m src.export --account EMAIL NAME  # make one; --test for the test account
  python -m src.export --accounts            # list them
  python -m src.export --reset-password EMAIL  # a new password, printed once
  python -m src.export --mark-test EMAIL     # an existing account can look but not write
  python -m src.export --holds               # which card each reviewer has on their desk
  python -m src.export --release EMAIL       # put someone's held card back in the pile
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from src.export.proposals import (
    FULL_COLUMNS,
    REVIEW_COLUMNS,
    REVIEW_HEADERS,
    build_rows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.export")
    parser.add_argument("--out", default="proposals.csv", help="output path")
    parser.add_argument("--action", default=None,
                        help="only export one resolution action")
    parser.add_argument("--template", metavar="HTML", default=None,
                        help="the review page to build: the first desk for --package "
                             "(src/export/desk_template.html), the second for --site (prototype/desk.template.html)")
    parser.add_argument("--package", metavar="ZIP",
                        help="build a standalone review file to send to reviewers")
    parser.add_argument("--backfill", action="store_true",
                        help="deal the historical backfill's proposals instead of the nightly ones")
    parser.add_argument("--publish", action="store_true",
                        help="write the deck to the database and the search index to the bucket, "
                             "for the online desk")
    parser.add_argument("--site", metavar="DIR",
                        help="write index.html for the online desk into DIR")
    parser.add_argument("--requests", action="store_true",
                        help="list the access requests made from the online desk's sign-in screen")
    parser.add_argument("--account", nargs=2, metavar=("EMAIL", "NAME"),
                        help="create a reviewer account for the online desk; the password is printed once")
    parser.add_argument("--test", action="store_true",
                        help="with --account: a test account, whose decisions are not collected")
    parser.add_argument("--accounts", action="store_true",
                        help="list the reviewer accounts")
    parser.add_argument("--reset-password", metavar="EMAIL",
                        help="give an account a new password, printed once")
    parser.add_argument("--mark-test", metavar="EMAIL",
                        help="make an existing account a test account: it can look but not write")
    parser.add_argument("--holds", action="store_true",
                        help="which card each reviewer has on their desk")
    parser.add_argument("--release", metavar="EMAIL",
                        help="put a reviewer's held card back in the pile (when they are away)")
    parser.add_argument("--slides", metavar="PPTX", nargs="?", const="data/dist/slides.pptx",
                        help="build the conference deck on the symposium template")
    parser.add_argument("--proposal", metavar="DOCX", nargs="?",
                        const="data/Custom System Evaluation Proposal.docx",
                        help="write the evaluation proposal for the team as a Word document")
    parser.add_argument("--reviews", metavar="DIR",
                        help="collect librarians' decisions from a folder of the desk's "
                             "CSVs, or from the online desk's table with DIR=table")
    parser.add_argument("--notify", action="store_true",
                        help="the daily email, to each reviewer with something to act on")
    parser.add_argument("--print-only", action="store_true",
                        help="with --notify: print the emails instead of sending them")
    parser.add_argument("--logs", action="store_true",
                        help="the evaluation's change log and weekly log, as CSVs (use --out for the folder)")
    parser.add_argument("--numbers", action="store_true",
                        help="every count the documents quote, dated, to docs/numbers.md")
    parser.add_argument("--weekly", action="store_true",
                        help="the week's approved changes as the reviewers' Excel file")
    parser.add_argument("--since", metavar="YYYY-MM-DD",
                        help="with --weekly: from this date (default: the last seven days)")
    parser.add_argument("--format", choices=("review", "full"), default="review",
                        help="review: the eight columns a decision needs. "
                             "full: adds uids, scores and the model's reasoning.")
    args = parser.parse_args(argv)

    if args.notify:
        from src.export.notify import gather, messages, send
        from src.shared.config import SETTINGS
        people, cards, reviews, holds, news = gather()
        mails = messages(people, cards, reviews, holds, news, SETTINGS.notify.desk_url)
        sent = send(mails, dry_run=args.print_only)
        print(f"{len(mails)} of {len(people)} reviewer(s) had something to act on; {sent} email(s) sent.")
        return 0

    if args.logs:
        from src.export.logs import collect
        folder = args.out if args.out != "proposals.csv" else "data/evaluation"
        for name, n in collect(folder).items():
            print(f"Wrote {folder}/{name}: {n} row(s)")
        return 0

    if args.numbers:
        from src.export.numbers import build
        print(f"Wrote {build()}")
        return 0

    if args.weekly:
        import datetime as dt

        from src.export.weekly import SGT, build
        since = (dt.date.fromisoformat(args.since) if args.since
                 else dt.datetime.now(SGT).date() - dt.timedelta(days=7))
        out = Path(args.out) if args.out != "proposals.csv" else None
        path, n_existing, n_new = build(since, out)
        print(f"Wrote {path}: {n_existing} change(s) to existing records, {n_new} for new ones, "
              f"decided since {since:%d %b %Y}")
        return 0

    if args.publish:
        from src.export.deck import publish
        done = publish(backfill=args.backfill)
        print(f"Published {done['cards']} cards to the deck ({done['removed']} stale removed), "
              f"{done['noted']} noted, {done['index']:,} searchable records to the bucket")
        return 0

    if args.site:
        from src.export.site import build_site
        # The second desk, chosen by the reviewers in October 2026, is the one online.
        page = build_site(args.template or "prototype/desk.template.html", args.site)
        print(f"Wrote {page} ({page.stat().st_size / 1024:.0f} KB)")
        print(f"  python -m http.server -d {Path(args.site)} 8000   then open http://localhost:8000")
        return 0

    if args.proposal:
        import shutil
        from src.export.proposal import build as build_proposal
        target = Path(args.proposal)
        if target.exists():
            backup = target.with_name(target.stem + " (previous)" + target.suffix)
            shutil.copy2(target, backup)
            print(f"Kept the earlier draft at {backup}")
        out = build_proposal(target)
        print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
        return 0

    if args.slides:
        from src.export.slides import build
        out = build(Path(args.slides))
        print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
        print("  Speaker notes are on each slide. Screenshots go in data/slides/.")
        return 0

    if args.account:
        from src.export.accounts import create
        made = create(args.account[0], args.account[1], test=args.test)
        print(f"Created {made['email']} ({made['name']}{', test account' if made['test'] else ''})")
        print(f"  password: {made['password']}   (shown once and not stored; if it's lost, --reset-password)")
        return 0

    if args.mark_test:
        from src.export.accounts import mark_test
        try:
            mark_test(args.mark_test)
        except ValueError as e:
            print(e)
            return 1
        print(f"{args.mark_test} is now a test account: it can look at the desk, and nothing it does is saved.")
        return 0

    if args.holds:
        from src.export.accounts import holds
        rows = holds()
        if not rows:
            print("Nobody has a card on their desk.")
        for r in rows:
            print(f"{r['email']:32} {r['entity'][:40]:40} since {str(r['since'])[:16]}")
        return 0

    if args.release:
        from src.export.accounts import release
        try:
            n = release(args.release)
        except ValueError as e:
            print(e)
            return 1
        print(f"Released {n} card(s) held by {args.release}; they go to the next reviewer dealt them.")
        return 0

    if args.reset_password:
        from src.export.accounts import reset_password
        try:
            done = reset_password(args.reset_password)
        except ValueError as e:
            print(e)
            return 1
        print(f"New password for {done['email']}: {done['password']}   (shown once; the old one no longer works)")
        return 0

    if args.accounts:
        from src.export.accounts import listing
        rows = listing()
        if not rows:
            print("No accounts yet.")
            return 0
        for r in rows:
            print(f"{r['email']:40} {r['name']:24} {'test' if r['test'] else '':5} "
                  f"last sign-in {str(r['last_sign_in'])[:16] or 'never'}")
        return 0

    if args.requests:
        from src.shared.supabase_client import get_client
        rows = (get_client().from_("access_requests").select("id, name, email, message, asked_at, handled")
                .order("asked_at").execute().data or [])
        open_rows = [r for r in rows if not r["handled"]]
        if not open_rows:
            print(f"No open access requests ({len(rows)} handled).")
            return 0
        for r in open_rows:
            print(f"#{r['id']}  {r['asked_at'][:16]}  {r['name']} <{r['email']}>")
            if r.get("message"):
                print(f"      {r['message']}")
        print("Create the account under Authentication > Users, then mark the row handled:")
        print(f"  update access_requests set handled = true where id in ({', '.join(str(r['id']) for r in open_rows)});")
        return 0

    if args.package:
        import zipfile
        from src.export.cards import build_cards, build_index, npt_map
        from src.export.package import build, readme, standalone

        template = Path(args.template or "src/export/desk_template.html")
        if not template.exists():
            print(f"Need the review page at {template}. Pass --template to point elsewhere.")
            return 1

        index, variants = build_index(with_variants=True)
        cards, noted = build_cards(backfill=args.backfill, index=index, variants=variants)
        page = template.read_text(encoding="utf-8")
        marker = page.index("<script>window.__CARDS__=")
        end = page.index(";</script>", marker) + len(";</script>")
        dump = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
        data = ("<script>window.__CARDS__=" + dump(cards)
                + ";window.__INDEX__=" + dump(index)
                + ";window.__NPT__=" + dump(npt_map(variants, index))
                + ";window.__NOTED__=" + dump(noted) + ";</script>")
        page = page[:marker] + data + page[end:]

        out = Path(args.package)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("review.html", build(page))
            archive.writestr("README.txt", readme(len(cards)))
            # A reviewer who does not know what any of this is needs the
            # explainer in the same folder, not a link they will not follow.
            explainer = Path("docs/pipeline.html")
            if explainer.exists():
                archive.writestr("pipeline.html",
                                 standalone(explainer.read_text(encoding="utf-8")))
        size = out.stat().st_size / 1024 / 1024
        print(f"Wrote {out} ({size:.1f} MB)")
        print(f"  {len(cards)} cards to decide, {len(noted)} entities noted as up to date or "
              f"only mentioned, {len(index):,} searchable records")
        print("  review.html    the tool; pipeline.html  what it is; README.txt  how")
        print("  Reviewers open review.html, work through it, and send back the CSV.")
        return 0

    if args.reviews:
        from src.export.reviews import COLUMNS as RCOLS, collect, disagreements
        rows = collect(args.reviews)
        if not rows:
            print(f"No decisions found in {args.reviews}")
            return 0
        out = args.out if args.out != "proposals.csv" else "decisions.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=RCOLS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        reviewers = sorted({r["reviewer"] for r in rows if r["reviewer"]})
        verdicts = {}
        for r in rows:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        split = disagreements(rows)
        print(f"Wrote {len(rows)} decision(s) to {out}")
        print(f"  reviewers : {', '.join(reviewers) or 'unnamed'}")
        print(f"  verdicts  : {verdicts}")
        if split:
            print(f"  {len({r['proposal_id'] for r in split})} proposal(s) where "
                  f"reviewers disagreed -- worth reading first")
        return 0

    rows = build_rows(backfill=args.backfill)
    if args.action:
        rows = [r for r in rows if r["action"] == args.action]

    if not rows:
        print("No proposals to export.")
        return 0

    columns = REVIEW_COLUMNS if args.format == "review" else FULL_COLUMNS

    with open(args.out, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        if args.format == "review":
            writer.writerow({c: REVIEW_HEADERS.get(c, c) for c in columns})
        else:
            writer.writeheader()
        writer.writerows(rows)

    entities = len({(r["article_id"], r["entity"]) for r in rows})
    changes = sum(1 for r in rows if r["field"])
    flags = sum(1 for r in rows if r["action"] != "MATCH_AND_UPDATE")
    print(f"Wrote {len(rows)} row(s) to {args.out}  [{args.format}]")
    print(f"  {entities} entit(ies), {changes} proposed change(s)")
    if flags:
        print(f"  {flags} need a person's judgement -- sorted to the top")
    print("\nverdict: yes = apply it | no = wrong | edit = right record, fix the wording")
    return 0


if __name__ == "__main__":
    sys.exit(main())
