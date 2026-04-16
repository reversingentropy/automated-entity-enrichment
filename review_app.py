"""
review_app.py — Review queue for the KOS Pipeline.

Reads from:
  outputs/review_queue.csv          — one row per proposed field change
  outputs/new_entity_candidates.csv — entities with no TTE match

Usage:
    streamlit run review_app.py
"""

import hashlib
import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

# ─── Paths ────────────────────────────────────────────────────────────────────

REVIEW_QUEUE_CSV   = "outputs/review_queue.csv"
NEW_CANDIDATES_CSV = "outputs/new_entity_candidates.csv"
DECISIONS_JSON     = "outputs/decisions.json"

# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="KB Population",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Data loading ─────────────────────────────────────────────────────────────

@st.cache_data
def load_review_queue() -> pd.DataFrame:
    if not os.path.exists(REVIEW_QUEUE_CSV):
        return pd.DataFrame()
    return pd.read_csv(REVIEW_QUEUE_CSV, dtype=str).fillna("")


@st.cache_data
def load_new_candidates() -> pd.DataFrame:
    if not os.path.exists(NEW_CANDIDATES_CSV):
        return pd.DataFrame()
    return pd.read_csv(NEW_CANDIDATES_CSV, dtype=str).fillna("")


def load_decisions() -> dict:
    if not os.path.exists(DECISIONS_JSON):
        return {}
    with open(DECISIONS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    # Skip entries from the old decisions format (which used proposal_id instead of group_id)
    return {d["group_id"]: d for d in data if "group_id" in d}


def save_decision(group_id: str, decision: str, row_ids: list, edited_fields: dict = None):
    existing = load_decisions()
    entry = {
        "group_id":  group_id,
        "decision":  decision,
        "row_ids":   row_ids,
        "reviewer":  st.session_state.get("reviewer", "librarian"),
        "timestamp": datetime.now().isoformat(),
    }
    if edited_fields:
        entry["edited_fields"] = edited_fields
    existing[group_id] = entry
    os.makedirs("outputs", exist_ok=True)
    with open(DECISIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, indent=2, ensure_ascii=False)
    st.session_state.decisions = existing


def undo_decision(group_id: str):
    existing = load_decisions()
    existing.pop(group_id, None)
    with open(DECISIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, indent=2, ensure_ascii=False)
    st.session_state.decisions = existing


# ─── Group building ───────────────────────────────────────────────────────────

def make_group_id(article_url: str, event_type: str, entity_name: str) -> str:
    key = f"{article_url}|{event_type}|{entity_name}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def build_groups(df: pd.DataFrame) -> list[dict]:
    """
    Group review_queue rows by (article_url, event_type, entity_name).
    Returns a list of group dicts, each containing entity metadata and a
    list of field-change dicts.
    """
    groups: dict[str, dict] = {}
    for _, row in df.iterrows():
        gid = make_group_id(
            row.get("article_url", ""),
            row.get("event_type", ""),
            row.get("entity_name", ""),
        )
        if gid not in groups:
            groups[gid] = {
                "group_id":          gid,
                "article_url":       row.get("article_url", ""),
                "article_title":     row.get("article_title", ""),
                "event_type":        row.get("event_type", ""),
                "entity_name":       row.get("entity_name", ""),
                "entity_type":       row.get("entity_type", ""),
                "tte_uid":           row.get("tte_uid", ""),
                "tte_authorised_name": row.get("tte_authorised_name", ""),
                "tte_vocabulary":    row.get("tte_vocabulary", ""),
                "match_score":       row.get("match_score", ""),
                "match_type":        row.get("match_type", ""),
                "record_richness":   row.get("record_richness", ""),
                "llm_confidence":    row.get("llm_confidence", ""),
                "row_ids":           [],
                "fields":            [],
            }
        groups[gid]["row_ids"].append(row.get("row_id", ""))
        groups[gid]["fields"].append({
            "field":         row.get("field", ""),
            "current_value": row.get("current_value", ""),
            "new_value":     row.get("new_value", ""),
            "final_value":   row.get("final_value", row.get("new_value", "")),
            "merge_state":   row.get("merge_state", ""),
            "evidence":      row.get("evidence", ""),
        })
    return list(groups.values())


# ─── Session state ────────────────────────────────────────────────────────────

if "decisions" not in st.session_state:
    st.session_state.decisions = load_decisions()
if "reviewer" not in st.session_state:
    st.session_state.reviewer = "librarian"
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

PAGES = ["Dashboard", "Event Updates", "New Entities", "History & Backup"]

decisions   = st.session_state.decisions
queue_df    = load_review_queue()
cands_df    = load_new_candidates()

if queue_df.empty and cands_df.empty:
    st.error(
        "No data found. Run `python build_prompts.py` → fill `llm_response` "
        "column → run `python join_responses.py`, then reopen this app."
    )
    st.stop()

all_groups    = build_groups(queue_df) if not queue_df.empty else []
decided_ids   = set(decisions.keys())
pending_groups = [g for g in all_groups if g["group_id"] not in decided_ids]

pending_cands  = 0 if cands_df.empty else int(
    cands_df.apply(
        lambda r: make_group_id(r.get("article_url",""), r.get("event_type",""), r.get("entity_name",""))
        not in decided_ids,
        axis=1,
    ).sum()
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

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

DECISION_ICON = {
    "approved":           "✅",
    "rejected":           "❌",
    "flagged":            "🚩",
    "no_kb_update":       "⏭️",
    "flagged_research":   "🔬",
    "dismissed":          "✖️",
}

MERGE_BADGE = {
    "ADD":     ":green[● ADD]",
    "APPEND":  ":blue[● APPEND]",
    "REPLACE": ":orange[● REPLACE]",
}


def score_label(score: str) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "—"
    if s >= 15:
        return ":green[High]"
    if s >= 5:
        return ":orange[Medium]"
    return ":red[Low]"


def decision_badge(group_id: str) -> str:
    d = decisions.get(group_id)
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
        options=PAGES,
        index=PAGES.index(st.session_state.page),
        format_func=lambda x: {
            "Dashboard":       "🏠  Dashboard",
            "Event Updates":   f"🔄  Event Updates  ({len(pending_groups)} pending)",
            "New Entities":    f"👤  New Entities  ({pending_cands} pending)",
            "History & Backup":"🕐  History & Backup",
        }[x],
    )
    st.session_state.page = page

    st.divider()
    new_reviewer = st.text_input("Reviewer", value=st.session_state.reviewer)
    if new_reviewer != st.session_state.reviewer:
        st.session_state.reviewer = new_reviewer


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

if page == "Dashboard":
    st.title("Dashboard")
    st.caption("Review and approve proposed changes to your knowledge base")

    today = datetime.now().date().isoformat()
    approved_today = sum(
        1 for d in decisions.values()
        if d["decision"] == "approved" and d["timestamp"][:10] == today
    )
    rejected_today = sum(
        1 for d in decisions.values()
        if d["decision"] == "rejected" and d["timestamp"][:10] == today
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Event Updates Pending", len(pending_groups))
    c2.metric("New Entities Pending",  pending_cands)
    c3.metric("Approved Today",        approved_today)
    c4.metric("Rejected Today",        rejected_today)

    st.divider()

    # Event type breakdown of pending groups
    st.subheader("Pending by Event Type")
    if pending_groups:
        counts: dict[str, int] = {}
        for g in pending_groups:
            counts[g["event_type"]] = counts.get(g["event_type"], 0) + 1
        breakdown = pd.DataFrame(
            sorted(counts.items(), key=lambda x: -x[1]),
            columns=["Event Type", "Pending"],
        )
        st.dataframe(breakdown, use_container_width=True, hide_index=True)
    else:
        st.caption("All event updates reviewed.")

    st.divider()

    # Recent decisions
    st.subheader("Recent Activity")
    if not decisions:
        st.caption("No decisions yet.")
    else:
        recent = sorted(decisions.values(), key=lambda d: d["timestamp"], reverse=True)[:10]

        # Build a quick lookup from group_id → display name
        group_map = {g["group_id"]: g for g in all_groups}
        for d in recent:
            icon  = DECISION_ICON.get(d["decision"], "•")
            g     = group_map.get(d["group_id"], {})
            name  = g.get("tte_authorised_name") or g.get("entity_name") or d["group_id"]
            etype = g.get("event_type", "")
            st.write(f"{icon} **{name}** · {etype} · {d['timestamp'][:10]}")


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT UPDATES
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "Event Updates":
    st.title("Review Event Updates")
    st.caption("Approve or reject proposed changes to existing TTE records")

    if not all_groups:
        st.info("No review queue found. Run `python join_responses.py` first.")
        st.stop()

    # Filters
    col_search, col_event, col_show = st.columns([3, 3, 2])
    search_q     = col_search.text_input("Search", placeholder="Search entities...", label_visibility="collapsed")
    all_events   = sorted(set(g["event_type"] for g in all_groups))
    event_filter = col_event.selectbox("Event Type", ["All"] + all_events, label_visibility="collapsed")
    show_decided = col_show.checkbox("Show reviewed", value=False)

    display_groups = all_groups if show_decided else pending_groups
    if event_filter != "All":
        display_groups = [g for g in display_groups if g["event_type"] == event_filter]
    if search_q:
        q = search_q.lower()
        display_groups = [
            g for g in display_groups
            if q in g["entity_name"].lower() or q in g["tte_authorised_name"].lower()
        ]

    total_label = "total" if show_decided else "pending"
    st.caption(
        f"**{len(display_groups)}** {total_label}"
        + (" — showing first 30" if len(display_groups) > 30 else "")
    )

    if not display_groups:
        st.info("No proposals to review with current filters.")

    for g in display_groups[:30]:
        gid     = g["group_id"]
        decided = gid in decided_ids
        icon    = ENTITY_ICON.get(g["entity_type"], "•")
        name    = g["tte_authorised_name"] or g["entity_name"]

        with st.container(border=True):
            # Header row
            hc1, hc2 = st.columns([5, 1])
            with hc1:
                st.markdown(f"#### {icon} {name} *(extracted as: {g['entity_name']})*")
                mc = st.columns(5)
                mc[0].caption(f"**{g['tte_vocabulary'] or g['entity_type']}**")
                mc[1].caption(g["event_type"][:38])
                mc[2].caption(f"Score: {score_label(g['match_score'])}")
                mc[3].caption(f"{g['record_richness']} TTE fields")
                mc[4].caption(f"UID: `{g['tte_uid']}`")
                if decided:
                    st.caption(decision_badge(gid))
            with hc2:
                if g["article_url"]:
                    st.link_button("↗ Article", g["article_url"], use_container_width=True)

            st.caption(
                f"📰 {g['article_title']}  ·  ")

            st.divider()

            # Field changes
            ACTION_OPTIONS = ["Append to existing", "Replace existing", "Add new field"]
            ACTION_FROM_MERGE = {
                "APPEND":  "Append to existing",
                "REPLACE": "Replace existing",
                "ADD":     "Add new field",
            }

            for i, fc in enumerate(g["fields"]):
                merge_state     = fc["merge_state"]
                default_action  = ACTION_FROM_MERGE.get(merge_state, "Add new field")
                key_act         = f"act_{gid}_{i}"
                key_val         = f"nv_{gid}_{i}"

                # Row 1: field label + current value
                lc1, lc2 = st.columns([2, 5])
                lc1.markdown(f"**TTE Field:** {fc['field']}")
                lc2.markdown(f"**Current value:** {fc['current_value'] or '*empty*'}")

                # Row 2: action dropdown + editable new value
                ac1, ac2 = st.columns([2, 5])
                ac1.selectbox(
                    "Action",
                    options=ACTION_OPTIONS,
                    index=ACTION_OPTIONS.index(default_action),
                    key=key_act,
                    label_visibility="collapsed",
                    disabled=decided,
                )
                ac2.text_input(
                    "New value",
                    value=fc["new_value"],
                    key=key_val,
                    label_visibility="collapsed",
                    disabled=decided,
                )

                # Evidence
                if fc["evidence"]:
                    st.caption(f"> *\"Evidence: {fc['evidence'][:280]}\"*")

                # Collapsed live preview
                with st.expander("Preview final TTE value ▶", expanded=False):
                    edited_val     = st.session_state.get(key_val, fc["new_value"])
                    selected_action = st.session_state.get(key_act, default_action)
                    current        = fc["current_value"] or ""
                    if selected_action == "Append to existing" and current:
                        preview = current + " | " + edited_val
                    else:
                        preview = edited_val
                    st.code(preview, language=None)

                st.write("")

            # Decision buttons
            if not decided:
                b1, b2, b3, b4 = st.columns(4)
                if b1.button("✅ Approve All",   key=f"a_{gid}", use_container_width=True, type="primary"):
                    edited_fields = {
                        g["row_ids"][j]: {
                            "new_value": st.session_state.get(f"nv_{gid}_{j}", g["fields"][j]["new_value"]),
                            "action":    st.session_state.get(f"act_{gid}_{j}", ACTION_FROM_MERGE.get(g["fields"][j]["merge_state"], "Add new field")),
                        }
                        for j in range(len(g["fields"]))
                        if j < len(g["row_ids"])
                    }
                    save_decision(gid, "approved", g["row_ids"], edited_fields=edited_fields); st.rerun()
                if b2.button("❌ Reject",          key=f"r_{gid}", use_container_width=True):
                    save_decision(gid, "rejected",     g["row_ids"]); st.rerun()
                if b3.button("⏭️ No KB Update",    key=f"n_{gid}", use_container_width=True):
                    save_decision(gid, "no_kb_update", g["row_ids"]); st.rerun()
                if b4.button("🚩 Flag",             key=f"f_{gid}", use_container_width=True):
                    save_decision(gid, "flagged",      g["row_ids"]); st.rerun()
            else:
                b1, _ = st.columns([2, 5])
                if b1.button("↩ Undo", key=f"u_{gid}", use_container_width=True):
                    undo_decision(gid); st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# NEW ENTITIES
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "New Entities":
    st.title("Review New Entities")
    st.caption("Entities not found in TTE — flag for research or dismiss")

    if cands_df.empty:
        st.info("No new entity candidates found.")
        st.stop()

    # Attach group_id to candidates
    cands_df["_gid"] = cands_df.apply(
        lambda r: make_group_id(r.get("article_url",""), r.get("event_type",""), r.get("entity_name","")),
        axis=1,
    )
    cands_df["_decided"] = cands_df["_gid"].map(lambda gid: gid in decided_ids)

    col_search, col_type, col_show = st.columns([3, 2, 2])
    search_q     = col_search.text_input("Search", placeholder="Search entities...", label_visibility="collapsed")
    all_types    = sorted(cands_df["entity_type"].dropna().unique().tolist())
    type_filter  = col_type.selectbox("Entity Type", ["All"] + all_types, label_visibility="collapsed")
    show_decided = col_show.checkbox("Show reviewed", value=False)

    filtered = cands_df if show_decided else cands_df[~cands_df["_decided"]]
    if type_filter != "All":
        filtered = filtered[filtered["entity_type"] == type_filter]
    if search_q:
        q = search_q.lower()
        filtered = filtered[filtered["entity_name"].str.lower().str.contains(q, na=False)]

    filtered = filtered.reset_index(drop=True)
    total_label = "total" if show_decided else "pending"
    st.caption(
        f"**{len(filtered)}** {total_label}"
        + (" — showing first 50" if len(filtered) > 50 else "")
    )

    if filtered.empty:
        st.info("No entities to review with current filters.")

    for _, row in filtered.head(50).iterrows():
        gid     = row["_gid"]
        decided = row["_decided"]
        icon    = ENTITY_ICON.get(row.get("entity_type", ""), "•")

        with st.container(border=True):
            hc1, hc2 = st.columns([5, 1])
            with hc1:
                st.markdown(f"#### {icon} {row.get('entity_name', '')}")
                tc = st.columns(3)
                tc[0].caption(f"**{row.get('entity_type', '')}**")
                tc[1].caption(f"*{row.get('event_type', '')}*")
                tc[2].caption(f"Confidence: {row.get('confidence', '')}")
                if decided:
                    st.caption(decision_badge(gid))
            with hc2:
                if row.get("article_url"):
                    st.link_button("↗ Article", row["article_url"], use_container_width=True)

            st.caption(f"📰 {row.get('article_title', '')}")

            onesearch_url = (
                "https://catalogue.nlb.gov.sg/search/card?keywords="
                + row.get("entity_name", "").replace(" ", "+")
            )
            sc1, sc2 = st.columns([4, 2])
            sc1.caption("🔍 Verify significance: does this entity have 2+ resources in NLB collections?")
            sc2.link_button("Search OneSearch ↗", onesearch_url, use_container_width=True)

            if not decided:
                b1, b2 = st.columns(2)
                if b1.button("🔬 Flag for Research", key=f"fr_{gid}", use_container_width=True, type="primary"):
                    save_decision(gid, "flagged_research", [row.get("row_id", gid)]); st.rerun()
                if b2.button("✖️ Dismiss",             key=f"di_{gid}", use_container_width=True):
                    save_decision(gid, "dismissed",        [row.get("row_id", gid)]); st.rerun()
            else:
                b1, _ = st.columns([2, 5])
                if b1.button("↩ Undo", key=f"u_{gid}", use_container_width=True):
                    undo_decision(gid); st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORY & BACKUP
# ═══════════════════════════════════════════════════════════════════════════════

elif page == "History & Backup":
    st.title("History & Backup")
    st.caption("Review decisions and export approved changes for TTE import")

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

    # Export approved changes in TTE CSV format
    st.subheader("Export Approved Changes")

    # Build row_id → decision lookup (for reviewer, timestamp, and edited values)
    row_to_decision: dict[str, dict] = {}
    for d in decisions.values():
        if d["decision"] == "approved":
            for rid in d.get("row_ids", []):
                row_to_decision[rid] = d

    export_rows = []
    if not queue_df.empty and row_to_decision:
        approved_queue = queue_df[queue_df["row_id"].isin(row_to_decision.keys())]
        for _, row in approved_queue.iterrows():
            rid  = row["row_id"]
            d    = row_to_decision[rid]
            edit = d.get("edited_fields", {}).get(rid, {})

            # Use reviewer-edited value if present, otherwise original
            new_val = edit.get("new_value") or row.get("new_value", "")
            action  = edit.get("action", "")

            # Compute final value from action + current value
            current = row.get("current_value", "")
            if action == "Append to existing" and current:
                final = current + " | " + new_val
            elif action in ("Replace existing", "Add new field"):
                final = new_val
            else:
                # No edit recorded — fall back to join_responses.py final_value
                final = row.get("final_value") or row.get("new_value", "")

            export_rows.append({
                "Key UID":            row.get("tte_uid", ""),
                "Key Descriptor":     row.get("tte_authorised_name", ""),
                "Key Vocabulary":     row.get("tte_vocabulary", ""),
                "Relationship Type":  row.get("field", ""),
                "Related Descriptor": final,
                "Evidence":           row.get("evidence", ""),
                "Article URL":        row.get("article_url", ""),
                "Reviewer":           d.get("reviewer", ""),
                "Timestamp":          d.get("timestamp", ""),
            })

    if export_rows:
        export_df = pd.DataFrame(export_rows)
        csv_bytes = export_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            "⬇️  Export approved_changes.csv (TTE format)",
            csv_bytes,
            file_name="approved_changes.csv",
            mime="text/csv",
            type="primary",
        )
        st.dataframe(export_df, use_container_width=True, hide_index=True)
    else:
        st.info("No approved changes yet.")

    st.divider()

    # Decision history table
    st.subheader("All Decisions")

    action_filter = st.selectbox(
        "Filter by decision",
        ["All", "approved", "rejected", "flagged", "no_kb_update",
         "flagged_research", "dismissed"],
    )

    group_map = {g["group_id"]: g for g in all_groups}

    history = []
    for d in sorted(decisions.values(), key=lambda x: x["timestamp"], reverse=True):
        if action_filter != "All" and d["decision"] != action_filter:
            continue

        g     = group_map.get(d["group_id"], {})
        name  = g.get("tte_authorised_name") or g.get("entity_name") or d["group_id"]
        etype = g.get("event_type", "")
        dtype = "New Entity" if d["decision"] in ("flagged_research","dismissed") else "Update"

        history.append({
            "Decision":  DECISION_ICON.get(d["decision"],"•") + " " + d["decision"].replace("_"," "),
            "Entity":    name,
            "Type":      dtype,
            "Event":     etype[:45],
            "Fields":    len(d.get("row_ids", [])),
            "Reviewer":  d.get("reviewer", ""),
            "Date":      d["timestamp"][:10],
            "_gid":      d["group_id"],
        })

    st.caption(f"**{len(history)}** decisions")

    if history:
        st.dataframe(
            pd.DataFrame(history).drop(columns=["_gid"]),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.caption("Undo a decision by group ID")
        undo_id = st.text_input("Group ID", placeholder="e.g. a3f2b1c4d5e6")
        if st.button("↩ Undo decision") and undo_id:
            if undo_id in decisions:
                undo_decision(undo_id)
                st.success(f"Decision for group {undo_id} removed.")
                st.rerun()
            else:
                st.error(f"No decision found for group ID {undo_id}.")
    else:
        st.caption("No decisions match the current filter.")
