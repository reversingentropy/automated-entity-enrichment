// A stand-in for Supabase, for the second desk (prototype/desk.template.html) run online in a headless browser.
// The test fills window.__FAKE__ before this script: the deck, everyone's reviews and holds, and the search file.
// The queue functions follow sql/15_desk_queue.sql rule for rule (tests/test_desk_queue.py checks the SQL itself in
// a real Postgres): newest news first, one record held per person, a hold lapses after an hour unless renewed, a
// decision is kept only on a record its reviewer holds, a record kept for review goes to someone else, and only
// one's own decision can be changed. The evaluation functions follow sql/19_evaluation.sql the same way: the first 50
// rows (20 for extraction) go to every evaluator, the rest are dealt one at a time and held, and nobody reads anyone's labels.
(function () {
  const F = window.__FAKE__;
  F.rpcs = []; F.fail = false; F.direct = false; F.shift = 0;
  F.reviews = F.reviews || []; F.claims = F.claims || [];
  F.evalItems = F.evalItems || []; F.evalLabels = F.evalLabels || []; F.evalHolds = F.evalHolds || []; F.evalResults = F.evalResults || [];
  F.accounts = F.accounts || [];      // accounts made on the sign-in screen (sql/20_self_signup.sql)
  let user = null;
  const HOLD = 60 * 60000;
  const now = () => Date.now() + F.shift;
  const live = h => now() - new Date(h.claimed_at).getTime() < HOLD;
  const me = () => user && user.id;
  const isTest = () => !!(user && user.app_metadata && user.app_metadata.test);
  const isEval = () => !!(user && user.app_metadata && user.app_metadata.evaluator);
  const isAdmin = () => !!(user && user.app_metadata && user.app_metadata.admin);
  const SHARED = task => task === "extraction" ? 20 : 50;
  const evLive = h => now() - new Date(h.held_at).getTime() < HOLD;
  const evItem = (task, item) => F.evalItems.find(i => i.task === task && i.item === item);
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
      // changes to records TTE has before records to create, each newest first
      const order = (a, b) => (!!a.card.isNew - !!b.card.isNew) || (newest(b.card) > newest(a.card) ? 1 : newest(b.card) < newest(a.card) ? -1 : 0) || (a.card.i - b.card.i) || (a.key < b.key ? -1 : 1);
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
    eval_take({ task, langs }) {
      const who = me(); if (!who || !isEval() || isTest()) return null;
      const L = langs || ["en", "zh", "ms", "ta"], byOrd = (a, b) => a.ord - b.ord;
      const labelled = (i, by) => F.evalLabels.some(l => l.task === task && l.item === i.item && (!by || l.labeller === by));
      const shared = F.evalItems.filter(i => i.task === task && i.ord <= SHARED(i.task) && L.includes(i.lang) && !labelled(i, who)).sort(byOrd)[0];
      if (shared) return shared.item;
      F.evalHolds = F.evalHolds.filter(h => !(h.labeller === who && h.task === task));
      const next = F.evalItems.filter(i => i.task === task && i.ord > SHARED(i.task) && L.includes(i.lang) && !labelled(i)
        && !F.evalHolds.some(h => h.task === task && h.item === i.item && evLive(h))).sort(byOrd)[0];
      if (!next) return null;
      F.evalHolds = F.evalHolds.filter(h => !(h.task === task && h.item === next.item)).concat([{ task, item: next.item, labeller: who, held_at: stamp() }]);
      return next.item;
    },
    eval_save({ task, item, label, seconds }) {
      const who = me(); if (!who || !isEval() || isTest() || !label || typeof label !== "object" || Array.isArray(label)) return false;
      const i = evItem(task, item); if (!i) return false;
      if (i.ord > SHARED(i.task) && (F.evalLabels.some(l => l.task === task && l.item === item && l.labeller !== who)
          || F.evalHolds.some(h => h.task === task && h.item === item && h.labeller !== who && evLive(h)))) return false;
      F.evalLabels = F.evalLabels.filter(l => !(l.task === task && l.item === item && l.labeller === who))
        .concat([{ task, item, labeller: who, label, seconds: seconds ?? null, at: stamp() }]);
      F.evalHolds = F.evalHolds.filter(h => !(h.task === task && h.item === item && h.labeller === who));
      return true;
    },
    eval_release() { F.evalHolds = F.evalHolds.filter(h => h.labeller !== me()); return null; },
    eval_progress() {
      if (!isEval()) return [];
      const out = new Map();
      F.evalItems.forEach(i => {
        const k = i.task + "|" + i.lang, ls = F.evalLabels.filter(l => l.task === i.task && l.item === i.item), mine = ls.some(l => l.labeller === me());
        if (!out.has(k)) out.set(k, { task: i.task, lang: i.lang, total: 0, shared: 0, shared_mine: 0, mine: 0, labelled: 0, held: 0,
                                      labellers: new Set(F.evalLabels.filter(l => l.task === i.task).map(l => l.labeller)).size });
        const p = out.get(k);
        p.total++; if (i.ord <= SHARED(i.task)) { p.shared++; if (mine) p.shared_mine++; }
        if (mine) p.mine++;
        if (i.ord > SHARED(i.task) && ls.length) p.labelled++;
        if (F.evalHolds.some(h => h.task === i.task && h.item === i.item && h.labeller !== me() && evLive(h))) p.held++;
      });
      return [...out.values()];
    },
    approve_account({ account }) {
      const a = F.accounts.find(x => x.id === account && x.waiting); if (!isAdmin() || !a) return false;
      a.waiting = false; return true;
    },
    decline_account({ account }) {
      if (!isAdmin() || !F.accounts.some(x => x.id === account && x.waiting)) return false;
      F.accounts = F.accounts.filter(x => x.id !== account); F.declined = (F.declined || []).concat(account); return true;
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
  // What a signed-in reviewer may read: the evaluation's rows and report only as an evaluator, its labels and holds never.
  const rows = table => table === "deck" ? F.deck : table === "reviews" ? F.reviews : table === "claims" ? F.claims
    : table === "eval_items" ? (isEval() ? F.evalItems : []) : table === "eval_results" ? (isEval() ? F.evalResults : [])
    : table === "eval_labels" || table === "eval_holds" ? null : [];
  const client = {
    auth: {
      getSession: async () => ({ data: { session: user ? { user } : null } }),
      // asks the server, so an account declined since sign-in is found gone
      getUser: async () => (user && !(F.declined || []).includes(user.id) ? { data: { user }, error: null }
                                                                         : { data: { user: null }, error: { message: "User not found" } }),
      signInWithPassword: async ({ email, password }) => {
        if (password !== "pw") return { data: null, error: { message: "bad" } };
        user = email.startsWith("test")
          ? { id: "u9", email, user_metadata: { name: "Tester" }, app_metadata: { test: true } }
          : { id: "u1", email, user_metadata: { name: "Alex" }, app_metadata: {} };
        return { data: { user }, error: null };
      },
      signOut: async () => { user = null; return {}; },
      // Sign-up with "Confirm email" off: the account is made and signed in at once, and waits for approval.
      signUp: async ({ email, password, options }) => {
        if (F.accounts.some(a => a.email === email)) return { data: null, error: { message: "User already registered" } };
        const name = (options && options.data && options.data.name) || "";
        user = { id: "u" + (10 + F.accounts.length), email, user_metadata: { name }, app_metadata: {} };
        F.accounts.push({ id: user.id, email, name, made: new Date(now()).toISOString(), waiting: true });
        return { data: { user, session: { user } }, error: null };
      },
      updateUser: async ({ password }) => { F.passwordSetTo = password; return { data: { user }, error: null }; },
    },
    from(table) {
      return {
        select: () => {
          const q = { eq: [], by: null, desc: false };
          const chain = {
            eq: (col, v) => { q.eq.push([col, v]); return chain; },
            order: (col, o) => { if (!q.by) { q.by = col; q.desc = !!(o && o.ascending === false); } return chain; },
            range: async (a, b) => {
              let xs = rows(table);
              if (xs === null) { F.readLabels = true; return { data: null, error: { code: "42501" } }; }
              xs = xs.filter(r => q.eq.every(([col, v]) => r[col] === v));
              // the evaluation tables come back in the order asked for; the desk's own, as they always have
              if (table.startsWith("eval_") && q.by) xs = xs.slice().sort((x, y) => (x[q.by] > y[q.by] ? 1 : x[q.by] < y[q.by] ? -1 : 0) * (q.desc ? -1 : 1));
              return { data: JSON.parse(JSON.stringify(xs.slice(a, b + 1))), error: null };
            },
          };
          return chain;
        },
        // Reviewers may not write the tables directly (sql/15); the page must not try.
        upsert: async () => { F.direct = true; return { data: null, error: { code: "42501" } }; },
      };
    },
    rpc: async (name, args = {}) => {
      // asked at every sign-in and by the admin's pages; not part of the queue the driver counts calls to
      if (name === "is_waiting") return { data: !!(user && F.accounts.some(a => a.id === user.id && a.waiting)), error: null };
      if (name === "waiting_accounts")
        return { data: isAdmin() ? F.accounts.filter(a => a.waiting).map(({ id, email, name, made }) => ({ id, email, name, made })) : [], error: null };
      F.rpcs.push(name + ":" + (args.key || args.grp || args.task || ""));
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
