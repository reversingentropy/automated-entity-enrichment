"""
Build a standalone review file to send to reviewers.

One HTML file that opens from disk with no server, no login and no network.
Decisions are kept in the browser and downloaded as a CSV when finished, which
each reviewer sends back. The same template, served with `window.__ONLINE__`
set, is the online desk; see `src/export/site.py`.
"""


def standalone(fragment: str, head: str = "") -> str:
    """
    Wrap the page fragment as a complete document.

    Without the charset a local file renders every curly quote as mojibake,
    so a page shipped in the zip has to carry its own. `head` is anything
    else the document needs before the page, such as a script tag.
    """
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<style>html{color-scheme:light dark}body{margin:0}"
            "img{max-width:100%}[hidden]{display:none!important}</style>\n"
            + head +
            "</head>\n<body>\n" + fragment + "\n</body>\n</html>\n")


def build(source_html: str) -> str:
    """The page as a file that runs from disk."""
    return standalone(source_html)


def readme(card_count: int) -> str:
    return f"""TTE proposal review
===================

{card_count} proposed changes to the knowledge base, drawn from Singapore news
articles. We would like your judgement on whether each one is correct.

HOW TO USE IT

1. Open review.html in any browser. Double-clicking it is enough -- there is
   nothing to install and it does not need the internet.
2. Enter your name when asked, the languages you read, and which groups of
   records to work on (all of them, unless you are sharing the deck).
3. Answer one question per screen. Each screen offers two or three buttons,
   and the keyboard shortcut is printed on each. Three practice records come
   first; "How this works" at the top explains the screens at any time.

     - First: is this the same person, organisation or place? The news is on
       the left, the record we hold is on the right, described in the same
       fields in the same order.
     - Then one field at a time: should this go on the record? The proposal
       is on the left; the record on the right is never altered on screen.
       To take part of a proposal, "leave out" what you do not want and
       accept the rest.

   Nothing is pre-selected and nothing is applied until you say so. There
   is no skipping: a record you cannot settle is "Keep for review", for the
   team to discuss; "Back one step" undoes the last answer.

4. "Your sheet" at the top lists every decision you have made, lets you
   reopen one, and downloads two files at any time:

     approved-changes-<you>.csv   one row per attribute to apply in TTE
     review-decisions-<you>.csv   every decision, for the pipeline

   Send both back.

If you want to know what any of this is or where the proposals come from,
open pipeline.html first. It explains the whole thing in a few minutes and
follows one real article from publication to the edit it produced.

WHAT WE ARE ASKING

Not whether the writing is perfect -- whether the change is RIGHT. Chiefly:

  - Is this the same person, organisation or place as the record shown?
  - Does the proposed change say something true, and belong in that field?
  - Where a description is rewritten, does it keep what mattered? The screen
    lists what the rewrite adds and what it removes before showing the text,
    and warns you when a lot of the existing description would disappear.
    Those are the ones most worth your attention.

If you cannot tell, "Keep for review" is a real answer and more useful than
a guess. There is a notes box on every card if you want to say why.

WHAT HAPPENS TO YOUR ANSWERS

They stay in your browser until you download them. Nothing is sent anywhere.
Your CSV comes back to us and is used to measure how good the automated
proposals are -- nothing is applied to the knowledge base on your say-so.

If you close the browser part-way through, reopening the file picks up where
you left off, as long as you use the same browser.
"""
