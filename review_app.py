"""
review_app.py — Web-based review queue for the KOS Pipeline.

Usage:
    pip install streamlit
    streamlit run review_app.py
"""

import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

# ─── Paths ────────────────────────────────────────────────────────────────────

PROPOSALS_JSON = "outputs/proposals.json"
DECISIONS_JSON = "outputs/decisions.json"

# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="KB Population",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data
def load_proposals():
    if not os.path.exists(PROPOSALS_JSON):
        return []
    with open(PROPOSALS_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_decisions():
    if not os.path.exists(DECISIONS_JSON):
        return {}
    with open(DECISIONS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {str(d["proposal_id"]): d for d in data}


def save_decision(proposal_id: str, decision: str, reason: str = ""):
    existing = load_decisions()
    existing[proposal_id] = {
        "proposal_id": proposal_id,
        "decision":    decision,
        "reason":      reason,
        "reviewer":    st.session_state.get("reviewer", "librarian"),
        "timestamp":   datetime.now().isoformat(),
    }
    os.makedirs("outputs", exist_ok=True)
    with open(DECISIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, indent=2, ensure_ascii=False)
    st.session_state.decisions = existing


def undo_decision(proposal_id: str):
    existing = load_decisions()
    existing.pop(str(proposal_id), None)
    with open(DECISIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, indent=2, ensure_ascii=False)
    st.session_state.decisions = existing


# ─── Session state ────────────────────────────────────────────────────────────

if "decisions" not in st.session_state:
    st.session_state.decisions = load_decisions()
if "reviewer" not in st.session_state:
    st.session_state.reviewer = "librarian"

proposals = load_proposals()

if not proposals:
    st.error("No proposals found. Run `python 04_build_proposals.py` first.")
    st.stop()

decisions = st.session_state.decisions

# Split into the two review queues
event_updates = [
    p for p in proposals
    if p["entity"]["match_type"] in ("high_match", "low_match")
    and p["entity"]["tte_uid"]
]
new_entities = [
    p for p in proposals
    if p["entity"]["match_type"] == "no_match"
    and p["entity"]["name"].strip()
]

def is_decided(pid):
    return str(pid) in decisions

pending_updates = [p for p in event_updates if not is_decided(p["id"])]
pending_new     = [p for p in new_entities  if not is_decided(p["id"])]

# ─── Helpers ──────────────────────────────────────────────────────────────────

PRIORITY_ICON = {"HIGH": "🟢", "MEDIUM": "🟡", "FLAG": "🔴"}
DECISION_ICON = {
    "approved":    "✅",
    "rejected":    "❌",
    "flagged":     "🚩",
    "no_kb_update": "⏭️",
}
ENTITY_ICON = {
    "PERSON":       "👤",
    "ORGANISATION": "🏢",
    "FACILITY":     "🏗️",
    "LOCATION":     "📍",
    "EVENT":        "📅",
    "AWARD":        "🏆",
    "PROGRAMME":    "📋",
    "LEGAL_ACT":    "⚖️",
}


def score_label(score):
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "—"
    if s >= 15:
        return ":green[High]"
    if s >= 5:
        return ":orange[Medium]"
    return ":red[Low]"


def decision_badge(pid):
    d = decisions.get(str(pid))
    if not d:
        return ""
    icon = DECISION_ICON.get(d["decision"], "•")
    return f"{icon} {d['decision'].replace('_', ' ').upper()}"


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### KB Population")
    st.caption("Review & Approve")
    st.divider()

    page = st.radio(
        "nav",
        label_visibility="collapsed",
        options=["Dashboard", "New Entities", "Event Updates", "History & Backup"],
        format_func=lambda x: {
            "Dashboard":        "🏠  Dashboard",
            "New Entities":     f"👤  New Entities  ({len(pending_new)} pending)",
            "Event Updates":    f"🔄  Event Updates  ({len(pending_updates)} pending)",
            "History & Backup": "🕐  History & Backup",
        }[x],
    )

    st.divider()
    new_reviewer = st.text_input("Reviewer", value=st.session_state.reviewer)
    if new_reviewer != st.session_state.reviewer:
        st.session_state.reviewer = new_reviewer


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

if page == "Dashboard":
    st.title("Dashboard")
    st.caption("Review and approve changes to your knowledge base")

    today = datetime.now().date().isoformat()
    approved_today = sum(1 for d in decisions.values() if d["decision"] == "approved"    and d["timestamp"][:10] == today)
    rejected_today = sum(1 for d in decisions.values() if d["decision"] == "rejected"    and d["timestamp"][:10] == today)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("New Entities to Review",  len(pending_new),     help="Entities not yet in TTE")
    c2.metric("Event Updates to Review", len(pending_updates), help="Proposed changes to existing TTE records")
    c3.metric("Approved Today",          approved_today)
    c4.metric("Rejected Today",          rejected_today)

    st.divider()

    # Attention required
    flagged_pending  = [p for p in proposals if p.get("priority") == "FLAG"     and not is_decided(p["id"])]
    low_match_pending = [p for p in event_updates if p["entity"]["match_type"] == "low_match" and not is_decided(p["id"])]

    if flagged_pending or low_match_pending:
        st.subheader("Attention Required")
        if flagged_pending:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.warning(f"**{len(flagged_pending)}** proposals with no TTE match — potential new entity candidates")
                if c2.button("Review now", key="att_flag"):
                    st.session_state["nav_override"] = "New Entities"
        if low_match_pending:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.info(f"**{len(low_match_pending)}** low-confidence entity matches need disambiguation")
                if c2.button("Review now", key="att_low"):
                    st.session_state["nav_override"] = "Event Updates"

    st.divider()

    # Recent activity
    st.subheader("Recent Activity")
    proposals_map = {str(p["id"]): p for p in proposals}

    if not decisions:
        st.caption("No decisions yet")
    else:
        recent = sorted(decisions.values(), key=lambda d: d["timestamp"], reverse=True)[:8]
        for d in recent:
            proposal = proposals_map.get(d["proposal_id"], {})
            entity   = proposal.get("entity", {})
            name     = entity.get("authorised_name") or entity.get("name") or d["proposal_id"]
            icon     = DECISION_ICON.get(d["decision"], "•")
            st.write(f"{icon} **{name}** · {proposal.get('event_type', '')} · {d['timestamp'][:10]}")

    st.divider()

    # Event type breakdown
    st.subheader("Pending Event Updates by Type")
    if pending_updates:
        counts = {}
        for p in pending_updates:
            counts[p["event_type"]] = counts.get(p["event_type"], 0) + 1
        df = pd.DataFrame(
            sorted(counts.items(), key=lambda x: -x[1]),
            columns=["Event Type", "Pending"]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("All event updates reviewed.")


# ═══════════════════════════════════════════════════════════════════════════════
# NEW ENTITIES
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "New Entities":
    st.title("Review New Entities")
    st.caption("Approve or reject entities not currently in your knowledge base")

    # Filters
    col_search, col_type, col_show = st.columns([3, 2, 2])
    search_q     = col_search.text_input("Search", placeholder="Search entities...", label_visibility="collapsed")
    all_types    = sorted(set(p["entity"]["type"] for p in new_entities if p["entity"]["type"]))
    type_filter  = col_type.selectbox("Entity Type", ["All"] + all_types, label_visibility="collapsed")
    show_decided = col_show.checkbox("Show reviewed", value=False)

    filtered = new_entities if show_decided else pending_new
    if type_filter != "All":
        filtered = [p for p in filtered if p["entity"]["type"] == type_filter]
    if search_q:
        filtered = [p for p in filtered if search_q.lower() in p["entity"]["name"].lower()]

    total_label = "total" if show_decided else "pending"
    st.caption(f"**{len(filtered)}** {total_label}" + (" — showing first 30" if len(filtered) > 30 else ""))

    if not filtered:
        st.info("No entities to review with current filters.")

    for p in filtered[:30]:
        entity  = p["entity"]
        pid     = str(p["id"])
        decided = is_decided(pid)
        icon    = ENTITY_ICON.get(entity["type"], "•")
        candidates = p.get("top_candidates", [])

        with st.container(border=True):
            hc1, hc2 = st.columns([5, 1])

            with hc1:
                st.markdown(f"#### {icon} {entity['name']}")
                tc = st.columns(4)
                tc[0].caption(f"**{entity['type']}**")
                tc[1].caption(f"Linking: {score_label(entity.get('match_score', 0))}")
                tc[2].caption(f"{PRIORITY_ICON.get(p['priority'], '⚪')} {p['priority']}")
                if decided:
                    tc[3].caption(decision_badge(pid))

            with hc2:
                if p.get("article_url"):
                    st.link_button("↗ Article", p["article_url"], use_container_width=True)

            st.caption(f"📰 {p.get('article_title', '')}  ·  *{p.get('event_type', '')}*")

            # Duplicate candidates
            if candidates:
                with st.expander(f"⚠️ Possible duplicates in TTE ({len(candidates)} candidates found)"):
                    for c in candidates[:3]:
                        score = float(c.get("score", 0))
                        pct   = min(int(score / 20 * 100), 99)
                        st.write(
                            f"• **{c.get('authorised_name', '')}**  —  {pct}% match  "
                            f"(UID: `{c.get('uid', '')}`)"
                        )

            # Decision buttons
            if not decided:
                b1, b2, b3 = st.columns(3)
                if b1.button("✅ Approve",       key=f"a_{pid}", use_container_width=True, type="primary"):
                    save_decision(pid, "approved");  st.rerun()
                if b2.button("❌ Reject",         key=f"r_{pid}", use_container_width=True):
                    save_decision(pid, "rejected");  st.rerun()
                if b3.button("⏭️ No KB update",   key=f"n_{pid}", use_container_width=True):
                    save_decision(pid, "no_kb_update"); st.rerun()
            else:
                b1, _ = st.columns([2, 5])
                if b1.button("↩ Undo", key=f"u_{pid}", use_container_width=True):
                    undo_decision(pid); st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT UPDATES
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "Event Updates":
    st.title("Review Event Updates")
    st.caption("Approve or reject proposed changes to existing TTE entities")

    # Filters
    col_search, col_event, col_show = st.columns([3, 3, 2])
    search_q     = col_search.text_input("Search", placeholder="Search entities...", label_visibility="collapsed")
    all_events   = sorted(set(p["event_type"] for p in event_updates))
    event_filter = col_event.selectbox("Event Type", ["All"] + all_events, label_visibility="collapsed")
    show_decided = col_show.checkbox("Show reviewed", value=False)

    filtered = event_updates if show_decided else pending_updates
    if event_filter != "All":
        filtered = [p for p in filtered if p["event_type"] == event_filter]
    if search_q:
        q = search_q.lower()
        filtered = [
            p for p in filtered
            if q in p["entity"]["name"].lower()
            or q in p["entity"].get("authorised_name", "").lower()
        ]

    total_label = "total" if show_decided else "pending"
    st.caption(f"**{len(filtered)}** {total_label}" + (" — showing first 30" if len(filtered) > 30 else ""))

    if not filtered:
        st.info("No proposals to review with current filters.")

    for p in filtered[:30]:
        entity  = p["entity"]
        pid     = str(p["id"])
        decided = is_decided(pid)
        changes = p.get("proposed_changes", [])
        icon    = ENTITY_ICON.get(entity.get("vocabulary", ""), "•")

        with st.container(border=True):
            hc1, hc2 = st.columns([5, 1])

            with hc1:
                display_name = entity.get("authorised_name") or entity["name"]
                st.markdown(f"#### {icon} {display_name}")
                tc = st.columns(5)
                tc[0].caption(f"**{entity.get('vocabulary', '')}**")
                tc[1].caption(p["event_type"][:35])
                tc[2].caption(f"{PRIORITY_ICON.get(p['priority'], '⚪')} {p['priority']}")
                tc[3].caption(f"Score: {score_label(entity.get('match_score', 0))}")
                tc[4].caption(f"{entity.get('record_richness', 0)} TTE fields")
                if decided:
                    st.caption(decision_badge(pid))

            with hc2:
                if p.get("article_url"):
                    st.link_button("↗ Article", p["article_url"], use_container_width=True)

            st.caption(
                f"📰 {p.get('article_title', '')}  ·  "
                f"Extracted as: *{entity['name']}*  ·  "
                f"UID: `{entity.get('tte_uid', '')}`"
            )

            # Proposed field changes (only present if fact extraction was run)
            if changes:
                st.markdown("**Proposed changes:**")
                for change in changes:
                    cc1, cc2 = st.columns([2, 5])
                    cc1.code(change.get("field", ""), language=None)
                    cc2.write(change.get("new_value", ""))
                    if change.get("evidence"):
                        st.caption(f"> *\"{change['evidence'][:250]}\"*")
            else:
                note = p.get("note", "No field values extracted — review article directly")
                st.caption(f"ℹ️ {note}")

            # Low-match candidates
            candidates = p.get("top_candidates", [])
            if candidates and entity.get("match_type") == "low_match":
                with st.expander("🔍 Near-match candidates"):
                    for c in candidates[:3]:
                        score = float(c.get("score", 0))
                        st.write(f"• [{score:.2f}] **{c.get('authorised_name', '')}** (UID: `{c.get('uid', '')}`)")

            # Decision buttons
            if not decided:
                b1, b2, b3, b4 = st.columns(4)
                if b1.button("✅ Approve",      key=f"a_{pid}", use_container_width=True, type="primary"):
                    save_decision(pid, "approved");     st.rerun()
                if b2.button("❌ Reject",        key=f"r_{pid}", use_container_width=True):
                    save_decision(pid, "rejected");     st.rerun()
                if b3.button("⏭️ No KB update",  key=f"n_{pid}", use_container_width=True):
                    save_decision(pid, "no_kb_update"); st.rerun()
                if b4.button("🚩 Flag",           key=f"f_{pid}", use_container_width=True):
                    save_decision(pid, "flagged");      st.rerun()
            else:
                b1, _ = st.columns([2, 5])
                if b1.button("↩ Undo", key=f"u_{pid}", use_container_width=True):
                    undo_decision(pid); st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY & BACKUP
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "History & Backup":
    st.title("Decision History & Backup")
    st.caption("Review, undo, and export your review decisions")

    total    = len(decisions)
    approved = sum(1 for d in decisions.values() if d["decision"] == "approved")
    rejected = sum(1 for d in decisions.values() if d["decision"] == "rejected")
    flagged  = sum(1 for d in decisions.values() if d["decision"] == "flagged")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Decisions", total)
    c2.metric("Approved",        approved)
    c3.metric("Rejected",        rejected)
    c4.metric("Flagged",         flagged)

    st.divider()

    # Export CSV
    proposals_map = {str(p["id"]): p for p in proposals}

    rows = []
    for d in decisions.values():
        if d["decision"] != "approved":
            continue
        proposal = proposals_map.get(d["proposal_id"], {})
        entity   = proposal.get("entity", {})
        changes  = proposal.get("proposed_changes") or [{}]
        for change in changes:
            rows.append({
                "tte_uid":             entity.get("tte_uid", ""),
                "tte_authorised_name": entity.get("authorised_name", ""),
                "tte_vocabulary":      entity.get("vocabulary", ""),
                "event_type":          proposal.get("event_type", ""),
                "entity_name":         entity.get("name", ""),
                "field":               change.get("field", ""),
                "new_value":           change.get("new_value", ""),
                "evidence":            change.get("evidence", ""),
                "article_url":         proposal.get("article_url", ""),
                "reviewer":            d.get("reviewer", ""),
                "timestamp":           d.get("timestamp", ""),
            })

    csv_data = pd.DataFrame(rows).to_csv(index=False) if rows else "No approved changes yet.\n"
    st.download_button(
        "⬇️  Export approved_changes.csv",
        csv_data,
        file_name="approved_changes.csv",
        mime="text/csv",
        type="primary",
        disabled=not rows,
    )

    st.divider()

    # History table with filters
    col_type, col_action = st.columns(2)
    type_filter   = col_type.selectbox("Type",   ["All", "New Entities", "Updates"])
    action_filter = col_action.selectbox("Action", ["All", "approved", "rejected", "flagged", "no_kb_update"])

    history = []
    for d in sorted(decisions.values(), key=lambda x: x["timestamp"], reverse=True):
        proposal  = proposals_map.get(d["proposal_id"], {})
        entity    = proposal.get("entity", {})
        row_type  = "New Entity" if entity.get("match_type") == "no_match" else "Update"

        if type_filter == "New Entities" and row_type != "New Entity":
            continue
        if type_filter == "Updates" and row_type != "Update":
            continue
        if action_filter != "All" and d["decision"] != action_filter:
            continue

        history.append({
            "Decision": DECISION_ICON.get(d["decision"], "•") + " " + d["decision"].replace("_", " "),
            "Entity":   entity.get("authorised_name") or entity.get("name") or d["proposal_id"],
            "Type":     row_type,
            "Event":    proposal.get("event_type", "")[:45],
            "Reviewer": d.get("reviewer", ""),
            "Date":     d["timestamp"][:10],
            "_pid":     d["proposal_id"],
        })

    st.caption(f"**{len(history)}** decisions")

    if history:
        df_display = pd.DataFrame(history).drop(columns=["_pid"])
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Undo last decision
        st.divider()
        st.caption("Undo a decision by proposal ID")
        undo_id = st.text_input("Proposal ID to undo", placeholder="e.g. 42")
        if st.button("↩ Undo decision") and undo_id:
            if undo_id in decisions:
                undo_decision(undo_id)
                st.success(f"Decision for proposal {undo_id} removed.")
                st.rerun()
            else:
                st.error(f"No decision found for proposal ID {undo_id}.")
    else:
        st.caption("No decisions found.")
