// A stand-in for Supabase, for the second desk (prototype/desk.template.html) run online in a headless browser.
// The test fills window.__FAKE__ before this script: the deck, everyone's reviews and holds, and the search file.
// The queue functions follow sql/15_desk_queue.sql rule for rule (tests/test_desk_queue.py checks the SQL itself in
// a real Postgres): newest news first, one record held per person, a hold lapses after an hour unless renewed, a
// decision is kept only on a record its reviewer holds, a record kept for review goes to someone else, and only
// one's own decision can be changed.
(function () {
  const F = window.__FAKE__;
  F.rpcs = []; F.fail = false; F.direct = false; F.shift = 0;
  F.reviews = F.reviews || []; F.claims = F.claims || [];
  let user = null;
  const HOLD = 60 * 60000;
  const now = () => Date.now() + F.shift;
  const live = h => now() - new Date(h.claimed_at).getTime() < HOLD;
  const me = () => user && user.id;
  const isTest = () => !!(user && user.app_metadata && user.app_metadata.test);
  const langOf = link => /zaobao/.test(link) ? "zh" : /beritaharian/.test(link) ? "ms" : /tamilmurasu/.test(link) ? "ta" : "en";
  // card_group() in sql/16_desk_groups.sql
  const groupOf = c => c.isNew ? "new records" : c.type === "PERSON" ? "people" : c.type === "ORGANISATION" ? "organisations" : "other changes";
  const rev = pid => F.reviews.find(r => r.pid === pid);
  const keptBy = r => (r && r.decision && r.decision.kept_by) || [];
  const openFor = (c, who) => (c.pids || []).some(pid => { const r = rev(pid); return !r || (r.verdict === "unsure" && r.reviewer !== who && !keptBy(r).includes(who)); });
  const newest = c => (c.sources || []).map(s => s.date || "").sort().pop() || "";
  const holdOf = key => F.claims.find(h => h.card_key === key);
  const stamp = () => new Date(now()).toISOString();
  const take = (key, who) => {
    const h = holdOf(key);
    if (h && live(h) && h.reviewer !== who) return false;
    F.claims = F.claims.filter(x => x.card_key !== key);
    F.claims.push({ card_key: key, reviewer: who, claimed_at: stamp() });
    return true;
  };
  const fns = {
    take_next({ langs, grp }) {
      const who = me(); if (!who || isTest()) return null;
      F.claims = F.claims.filter(h => h.reviewer !== who);
      const ok = d => (!grp || grp === "all" || groupOf(d.card) === grp)
        && (d.card.sources || []).some(s => (langs || ["en", "zh", "ms", "ta"]).includes(langOf(s.link || "")))
        && openFor(d.card, who) && !(holdOf(d.key) && live(holdOf(d.key)));
      const order = (a, b) => (newest(b.card) > newest(a.card) ? 1 : newest(b.card) < newest(a.card) ? -1 : 0) || (a.card.i - b.card.i) || (a.key < b.key ? -1 : 1);
      for (const d of F.deck.filter(ok).sort(order)) if (take(d.key, who)) return d.key;
      return null;
    },
    claim_card({ key }) {
      const who = me(); if (!who || isTest()) return false;
      const d = F.deck.find(x => x.key === key); if (!d) return false;
      if (!openFor(d.card, who) && !F.reviews.some(r => r.card_key === key && r.reviewer === who)) return false;
      F.claims = F.claims.filter(h => h.reviewer !== who || h.card_key === key);
      return take(key, who);
    },
    renew_card({ key }) {
      const h = holdOf(key);
      if (!h || h.reviewer !== me()) return false;
      h.claimed_at = stamp(); return true;
    },
    release_card({ key }) { F.claims = F.claims.filter(h => !(h.card_key === key && h.reviewer === me())); return null; },
    decide({ key, rows, langs, grp }) {
      const who = me(); if (!who || isTest()) return { saved: 0, reason: "not allowed" };
      const h = holdOf(key); if (!h || h.reviewer !== who) return { saved: 0, reason: "not held" };
      const card = (F.deck.find(x => x.key === key) || {}).card;
      let saved = 0; const refused = [];
      for (const r of rows || []) {
        if (!card || !card.pids.includes(r.pid) || !["approve", "reject", "unsure"].includes(r.verdict)) { refused.push(r.pid); continue; }
        const old = rev(r.pid);
        if (old && !((old.reviewer === who && !(old.decision || {}).done) || (old.verdict === "unsure" && !keptBy(old).includes(who)))) { refused.push(r.pid); continue; }
        const kept = keptBy(old).concat(r.verdict === "unsure" && !keptBy(old).includes(who) ? [who] : []);
        const row = { pid: r.pid, card_key: key, reviewer: who, verdict: r.verdict, decision: { ...(r.decision || {}), kept_by: kept }, at: stamp() };
        F.reviews = F.reviews.filter(x => x.pid !== r.pid).concat([row]);
        saved++;
      }
      F.claims = F.claims.filter(x => !(x.card_key === key && x.reviewer === who));
      return { saved, refused, next: langs ? fns.take_next({ langs, grp }) : null };
    },
    mark_done({ pids, done }) {
      let n = 0;
      F.reviews.forEach(r => { if (pids.includes(r.pid) && r.reviewer === me()) { r.decision = { ...r.decision, done }; n++; } });
      return n;
    },
  };
  // For the driver: a colleague takes a record, as when this reviewer's hold has lapsed.
  F.steal = (key, who = "u2") => { F.claims = F.claims.filter(h => h.card_key !== key); F.claims.push({ card_key: key, reviewer: who, claimed_at: stamp() }); };
  F.mine = () => F.claims.filter(h => h.reviewer === me()).map(h => h.card_key);
  const rows = table => table === "deck" ? F.deck : table === "reviews" ? F.reviews : table === "claims" ? F.claims : [];
  const client = {
    auth: {
      getSession: async () => ({ data: { session: user ? { user } : null } }),
      signInWithPassword: async ({ email, password }) => {
        if (password !== "pw") return { data: null, error: { message: "bad" } };
        user = email.startsWith("test")
          ? { id: "u9", email, user_metadata: { name: "Tester" }, app_metadata: { test: true } }
          : { id: "u1", email, user_metadata: { name: "Glenn" }, app_metadata: {} };
        return { data: { user }, error: null };
      },
      signOut: async () => { user = null; return {}; },
    },
    from(table) {
      return {
        select: () => ({ order: () => ({ range: async (a, b) => ({ data: JSON.parse(JSON.stringify(rows(table).slice(a, b + 1))), error: null }) }) }),
        // Reviewers may not write the tables directly (sql/15); the page must not try.
        upsert: async () => { F.direct = true; return { data: null, error: { code: "42501" } }; },
      };
    },
    rpc: async (name, args) => {
      F.rpcs.push(name + ":" + (args.key || args.grp || ""));
      await new Promise(r => setTimeout(r, 5));
      if (F.fail) throw new Error("offline");
      if (!fns[name]) return { data: null, error: { message: "no such function" } };
      return { data: JSON.parse(JSON.stringify(fns[name](args) ?? null)), error: null };
    },
    storage: { from: () => ({ download: async () => ({ data: { text: async () => JSON.stringify(F.desk) } }) }) },
  };
  window.supabase = { createClient: () => client };
  // signedIn() in the driver signs in again directly; keep the fake's user in step with it
  F.setUser = u => { user = u; };
})();
