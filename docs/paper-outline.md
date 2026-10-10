# Paper argument map

Working companion to `docs/paper.md`. Plain language, one line per point.
No section-number shorthand (§) — just says what section it's in.

Title (unchanged): Designing for the Reviewer: A Human-in-the-Loop AI
Pipeline for News-Driven Knowledge Base Maintenance at the National Library
Board Singapore

Thesis: the system doesn't decide. It cuts the steps and information a
person needs to decide — find the record, gather the evidence, draft the
change — so the decision stays fast enough to actually happen, without
ever leaving that person's hands. The decision has to stay with a person
because a person can be held accountable for it. The system can't be
fired. The person can.

---

## Section 1 — The problem

- Authority file = controlled names + variant forms + structured fields;
  lets a catalogue search expand across every name a person is known by
- TTE feeds NLB discovery, Archives Online, other agencies, VIAF
- **52,628** is the name-authority subset this pipeline covers (persons,
  orgs, facilities, locations, events, awards, programmes, legal acts).
  Glenn's 1.8 million is all of TTE, including subject headings and other
  vocabularies this pipeline never touches — confirmed, write it that way
- Records are updated as part of routine practice; the volume of news
  makes comprehensive manual coverage hard to sustain — not "goes stale
  silently"
- Humans reading also get tired — real constraint, not decoration
- Question the paper answers: can AI help simplify this workflow
- *Engel et al. (2025)*: literature review, almost nothing written on
  what AI-assisted cataloguing oversight should look like — this is the
  gap the paper fills, keep

## Section 2 — The constraint (streamlit lesson)

- First version: flat list of 9,000+ candidates, no source sentence, no
  identity check — a person couldn't decide anything from it
- The lesson, plainly: a bad UI that isn't pleasant and usable won't get
  used, no matter how good the backend is
- Stands on its own, no citation needed — it's your own finding
- Saccucci & Potter **moved out of here** — their finding is "model
  output quality wasn't good enough for full automation," a different
  claim from "the interface was ugly and nobody used it." Goes near
  "why a human needs to be in the loop at all" instead, if anywhere

## Section 3 — Design principles

- Never write to TTE directly — every change ends at a named person. Not
  caution for its own sake: the system can't be held accountable if a
  wrong fact reaches a national archive. A person can, so the decision
  has to stay with a person.
- Recall early, precision late — a missed article is gone for good; a
  bad match is rejected in seconds
- We tell the AI the field names, in a short cheat-sheet. We don't trust
  it to get them right. After it answers, code checks every field name
  and value against the real list — if it invented a name or used a
  disallowed value, code fixes or drops it. Prompt asks, code checks.
- One question per screen, identity then one field at a time — current,
  verified in the code (`renderWho()` → `renderPencil()`)

## Section 4 — The pipeline

- Four stages nightly, free tiers only
- Trigram retrieval, not embeddings — cost, and it didn't help (see
  findings)
- No changes needed
- Real next step, not a paper matter: Vercel deployment

## Section 5 — Findings

- **Identity lives in facts, not names.** AI's own translation of a name
  is a guess and can be confidently wrong: a Chinese name's AI-guessed
  English spelling matched a real TTE record — for the wrong person, a
  banker dead since 1966. Answer: don't trust AI's translation for
  identity decisions alone. Use it to search, never as the final proof —
  confirm with real facts (job, age, dates) before matching. Fixed by
  searching the original-language name first and treating any AI-guessed
  spelling as a weaker lead. References cut, a plain sentence covers it.
- **Editing is not writing.** Asked to add one new fact to a biography,
  the AI deleted a Navy career and ten years as Deputy PM and called the
  result a "merge." Nobody would catch that without comparing old and new
  side by side. The danger isn't a loud error — it's silently losing real
  history, which is exactly what a library can't tolerate. Fixed: every
  rewrite now shows a before/after, flagged when too much vanishes.
- **A match with nothing to change wastes attention.** A third of matches
  proposed nothing; the first reviewer called every one a waste and the
  deck was rebuilt on that verdict.
- **Dead candidates, promoted to its own finding.** A person dead since
  1966 was offered as the match for a 2026 award, at a "perfect" name
  score — obviously wrong to a human, invisible to a system that only
  checks names. Fixed by comparing article date to death date.
  *Kreyche, Lisius & Park (2010)*: library systems hit exactly this, same
  fix — a real precedent, keep.
- **Cut from findings entirely**: the re-resolution optimization
  (188→7) — pure infrastructure cost-saving, not something this audience
  needs to hear about.
- **Coverage ceiling.** We compared TTE's own edit history — what
  librarians actually changed over two years — against what our three
  news sources could have told them about. About 1 in 8 of those real
  changes (up to 1 in 5 once we account for only seeing headlines, not
  full articles) came from news we monitor. The rest comes from sources
  we don't track, or routine cataloguing with no news trigger at all.
  **Default: keep it, framed as "here's what full coverage would take,"
  not "here's what we missed."** Override if you want it cut instead.

## Section 6 — Limits

- **Copyright.** Text fetched only to analyse, discarded, never stored
  (0 of 15,712 articles hold text today). Falls within Singapore's
  computational data analysis exception; no paywall circumvention.
- **Personal data.** System asserts facts about living people into a
  file other agencies and VIAF draw on. Control is procedural — nothing
  reaches TTE without a named cataloguer's decision.
- **Evaluation is pre-registered, not run.** Sampling and weights fixed
  in advance, crossover design (two on the app, two manual, swap at six
  weeks), agreement reported as Cohen's kappa.
- Everything else already cut (96%-unread paragraph, "guards only catch
  what was noticed," relational changes, acceptance-rate-is-ambiguous,
  throughput-pressure/Buçinca, timer-cuts-both-ways/Suchman)

## Section 7 — What transfers

Short checklist:
- Authority file export with field structure
- Cataloguing rules as schema, not guidance
- A news source with a feed
- A reviewer willing to spend an hour on the first fifty proposals
- A legal check on text-and-data-mining rules, done before any code
- Build the review interface before you trust the pipeline — the diff
  view caught a hidden deletion bug the pipeline had produced for weeks

Academic positioning (KBP/Mix'n'match, LLM-as-judge) — cut, as agreed.

## Section 8 — Conclusion

Not a technical recap. Your framing, close to verbatim:

> The point isn't to hand decisions to AI, even where AI could plausibly
> do it. It's to cut the steps and the information a person needs to
> actually decide — find the record, gather the evidence, draft the
> change — so the decision stays fast enough to happen at all, without
> ever leaving that person's hands. That's not caution for its own sake:
> a system can't be held accountable for a wrong fact in a national
> archive. A person can, and does.
>
> Keeping a person in that loop only works if the tool is one they'd
> actually want to use: accurate, but also fast to move through and not
> cognitively exhausting. The desk has small things built for exactly
> that — a stamp that lands the instant you decide, an optional sound, a
> line marking progress every ten records — with nothing that rewards
> speed over judgment: no timer, no score. Two cataloguers used it, told
> us the first version was wrong, and the version they helped redesign
> is the one this paper describes.

Grounded in the actual "game feel that serves the work" decision made
earlier in this project, not borrowed from a citation.

---

## Resolved this round
- Thesis sharpened around accountability: AI's job is reducing the steps
  and information a decision needs, not making the decision. The person
  stays in the loop because the person can be held accountable and the
  system can't — worked into the thesis, principle 1's rationale, and the
  conclusion's close

- TTE count — confirmed, 52,628 is the covered subset
- Coverage ceiling framing — defaulted to "keep, framed as a knob,"
  overridable
- Section 3 — rewritten in plain language
- Findings — dead candidates promoted, re-resolution cut, "so what"
  stated for identity and editing findings
- Conclusion — rewritten around your framing, grounded in real code

## Next step
Full prose pass once you confirm or override the coverage-ceiling default.
Tight prose for the argument sections (1, 2, 8), bullets for the list
sections (5, 6, 7).
