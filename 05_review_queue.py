"""
05_review_queue.py — Human review queue (terminal interface).

What this does:
  - Loads proposals.json (output of step 4)
  - Displays each proposal clearly in the terminal
  - Accepts reviewer decisions: approve / reject / skip / flag / quit
  - Saves decisions to decisions.json

Shows HIGH priority proposals first, then MEDIUM, then FLAG.

Usage:
    python 05_review_queue.py

Controls:
    a — Approve
    r — Reject (will ask for a reason)
    n — No KB update needed (entity is real but not significant enough)
    f — Flag for discussion
    s — Skip (come back later)
    q — Quit and save progress
"""

import json
import os
from datetime import datetime

import config
import utils

utils.print_header("Step 5: Human Review Queue")

# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

with open(config.PROPOSALS_JSON, "r", encoding="utf-8") as f:
    proposals = json.load(f)

# Load existing decisions if any (allows resuming)
decisions = {}
if os.path.exists(config.DECISIONS_JSON):
    with open(config.DECISIONS_JSON, "r", encoding="utf-8") as f:
        existing = json.load(f)
    decisions = {d["proposal_id"]: d for d in existing}
    print(f"  Resuming — {len(decisions)} decisions already recorded.")

# Sort by priority: HIGH first, then MEDIUM, then FLAG
priority_order = {"HIGH": 0, "MEDIUM": 1, "FLAG": 2}
pending = [
    p for p in proposals
    if str(p["id"]) not in decisions
    and p["status"] == "pending"
]
pending.sort(key=lambda p: priority_order.get(p.get("priority", "FLAG"), 3))

print(f"  Total proposals    : {len(proposals):,}")
print(f"  Already reviewed   : {len(decisions):,}")
print(f"  Pending review     : {len(pending):,}")


# ─────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def display_proposal(proposal: dict, current: int, total: int):
    """Display a single proposal in the terminal."""
    clear_screen()

    entity = proposal.get("entity", {})
    changes = proposal.get("proposed_changes", [])
    candidates = proposal.get("top_candidates", [])
    priority = proposal.get("priority", "")

    priority_colour = {"HIGH": "🟢", "MEDIUM": "🟡", "FLAG": "🔴"}.get(priority, "⚪")

    print("=" * 70)
    print(f"  PROPOSAL {current}/{total}   {priority_colour} {priority} PRIORITY")
    print("=" * 70)

    # Article
    print(f"\n📰 ARTICLE")
    print(f"   {proposal.get('article_title', 'No title')}")
    print(f"   {proposal.get('article_url', '')}")

    # Event
    print(f"\n📌 EVENT TYPE")
    print(f"   {proposal.get('event_type', '')}")

    # Entity match
    print(f"\n🔗 ENTITY MATCH")
    print(f"   Extracted name   : {entity.get('name', '')}")
    print(f"   Authorised form  : {entity.get('authorised_name', 'No match')}")
    print(f"   TTE UID          : {entity.get('tte_uid', 'None')}")
    print(f"   Vocabulary       : {entity.get('vocabulary', '')}")
    print(f"   Match score      : {entity.get('match_score', 0):.3f}  ({entity.get('match_type', '')})")
    print(f"   Record richness  : {entity.get('record_richness', 0)} TTE fields")

    # Proposed changes
    if changes:
        print(f"\n✏️  PROPOSED CHANGES")
        for change in changes:
            print(f"   Field    : {change.get('field', '')}")
            print(f"   New value: {change.get('new_value', '')}")
            print(f"   Evidence : \"{change.get('evidence', '')}\"")
            print()
    else:
        note = proposal.get("note", "No proposed changes extracted.")
        print(f"\n⚠️  NO CHANGES EXTRACTED")
        print(f"   {note}")

    # Near-match candidates (for disambiguation)
    if candidates and entity.get("match_type") in ("low_match", "no_match"):
        print(f"\n🔍 NEAR-MATCH CANDIDATES")
        for c in candidates[:3]:
            print(f"   [{c.get('score', 0):.3f}] {c.get('authorised_name', '')}  "
                  f"(UID: {c.get('uid', '')})")

    # LLM confidence
    llm_conf = proposal.get("llm_confidence", "")
    if llm_conf:
        print(f"\n   LLM confidence: {llm_conf}")
        confirmed = proposal.get("entity_confirmed", True)
        if not confirmed:
            print(f"   ⚠️  LLM did not confirm this article is about the matched entity")

    print("\n" + "─" * 70)
    print("  [a] Approve    [r] Reject    [n] No KB update    [f] Flag    [s] Skip    [q] Quit")
    print("─" * 70)


def save_decisions():
    """Save current decisions to disk."""
    utils.ensure_outputs_dir()
    decision_list = list(decisions.values())
    with open(config.DECISIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(decision_list, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────
# REVIEW LOOP
# ─────────────────────────────────────────────

if not pending:
    print("\n✅ All proposals have been reviewed. Run python 06_export.py to export approved changes.")
    exit(0)

print(f"\nStarting review. Press 'q' at any time to save and quit.\n")
input("Press Enter to begin...")

reviewed_this_session = 0
reviewer_id = input("\nEnter your name/initials for the log: ").strip() or "reviewer"

for i, proposal in enumerate(pending):
    display_proposal(proposal, i + 1, len(pending))

    while True:
        choice = input("\n  Your decision: ").strip().lower()

        if choice == "a":
            decisions[str(proposal["id"])] = {
                "proposal_id":    str(proposal["id"]),
                "decision":       "approved",
                "reason":         "",
                "reviewer":       reviewer_id,
                "timestamp":      utils.now_str(),
                "article_url":    proposal.get("article_url", ""),
                "entity_name":    proposal.get("entity", {}).get("name", ""),
                "tte_uid":        proposal.get("entity", {}).get("tte_uid", ""),
                "event_type":     proposal.get("event_type", ""),
            }
            save_decisions()
            reviewed_this_session += 1
            print("  ✅ Approved.")
            break

        elif choice == "r":
            reason = input("  Reason for rejection (optional): ").strip()
            decisions[str(proposal["id"])] = {
                "proposal_id":    str(proposal["id"]),
                "decision":       "rejected",
                "reason":         reason,
                "reviewer":       reviewer_id,
                "timestamp":      utils.now_str(),
                "article_url":    proposal.get("article_url", ""),
                "entity_name":    proposal.get("entity", {}).get("name", ""),
                "tte_uid":        proposal.get("entity", {}).get("tte_uid", ""),
                "event_type":     proposal.get("event_type", ""),
            }
            save_decisions()
            reviewed_this_session += 1
            print("  ❌ Rejected.")
            break

        elif choice == "n":
            decisions[str(proposal["id"])] = {
                "proposal_id":    str(proposal["id"]),
                "decision":       "no_kb_update",
                "reason":         "Entity real but not significant enough for KB update",
                "reviewer":       reviewer_id,
                "timestamp":      utils.now_str(),
                "article_url":    proposal.get("article_url", ""),
                "entity_name":    proposal.get("entity", {}).get("name", ""),
                "tte_uid":        proposal.get("entity", {}).get("tte_uid", ""),
                "event_type":     proposal.get("event_type", ""),
            }
            save_decisions()
            reviewed_this_session += 1
            print("  ⏭️  Marked as no KB update needed.")
            break

        elif choice == "f":
            note = input("  Note for discussion (optional): ").strip()
            decisions[str(proposal["id"])] = {
                "proposal_id":    str(proposal["id"]),
                "decision":       "flagged",
                "reason":         note,
                "reviewer":       reviewer_id,
                "timestamp":      utils.now_str(),
                "article_url":    proposal.get("article_url", ""),
                "entity_name":    proposal.get("entity", {}).get("name", ""),
                "tte_uid":        proposal.get("entity", {}).get("tte_uid", ""),
                "event_type":     proposal.get("event_type", ""),
            }
            save_decisions()
            reviewed_this_session += 1
            print("  🚩 Flagged for discussion.")
            break

        elif choice == "s":
            print("  ⏭️  Skipped.")
            break

        elif choice == "q":
            save_decisions()
            print(f"\n  Saved. Reviewed {reviewed_this_session} proposals this session.")
            print("  Run python 05_review_queue.py again to continue.")
            exit(0)

        else:
            print("  Invalid input. Use: a / r / n / f / s / q")

# All done
save_decisions()
print("\n" + "=" * 70)
print(f"  Review complete! Reviewed {reviewed_this_session} proposals this session.")
total_approved = sum(1 for d in decisions.values() if d["decision"] == "approved")
print(f"  Total approved decisions: {total_approved}")
print("\nNext step: python 06_export.py")
