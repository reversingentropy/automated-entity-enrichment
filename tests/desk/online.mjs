// Drives the online desk headless against a stand-in for Supabase: sign in,
// the deck from the table, a card already held coming back first, cards
// another reviewer holds or decided never dealt, a claim that cannot reach
// the table, decisions written to the table, sign out and back in.
//   node online.mjs <page.js>
import { body, byId, store } from "./shim.mjs";
import fs from "node:fs";

// The stand-in. `deck` is filled once the page's practice cards exist, since
// the real cards are cloned from them.
const db = { deck: null, reviews: [{ pid: 903, card_key: "uid:r3", reviewer: "u2", decision: { verdict: "approve" } }],
             claims: { "uid:r2": "u2", "uid:r4": "u1" }, rpcs: [], access_requests: [], conflicts: [], failClaim: null,
             weekly_log: [], change_log: [], meta: null,
             // What was asked for, in order, and the gates a test can hold shut to
             // stand in for a slow connection.
             log: [], gate: null, deskGate: null };
const rowsOf = table => table === "claims"
  ? Object.entries(db.claims).map(([card_key, reviewer]) => ({ card_key, reviewer })) : db[table];
let user = null;
const fake = {
  auth: {
    getSession: async () => ({ data: { session: user ? { user } : null } }),
    signInWithPassword: async ({ email, password }) => {
      if (email.startsWith("test") && password === "tpw") {
        user = { id: "u9", email, user_metadata: { name: "Tester" }, app_metadata: { test: true } };
        return { data: { user }, error: null };
      }
      if (password !== "pw") return { data: null, error: { message: "bad" } };
      user = { id: "u1", email, user_metadata: { name: "Glenn" } };
      return { data: { user }, error: null };
    },
    updateUser: async ({ data }) => { db.meta = { ...(db.meta || {}), ...data }; return { data: { user }, error: null }; },
    signOut: async () => { user = null; return {}; },
  },
  from(table) {
    return {
      // Rows come back in no particular order, as from the real table.
      select: () => ({ order: () => ({ range: async (a, b) => {
        db.log.push("asked " + table);
        if (db.gate) await db.gate;
        return { data: rowsOf(table).slice().reverse().slice(a, b + 1), error: null };
      } }) }),
      insert: async row => { db[table].push(row); return { data: row, error: null }; },
      // As the table does: one decision per proposal, a second refused whole.
      upsert: async (rows, opts) => {
        if (table === "weekly_log") {
          const r = rows;
          const i = db.weekly_log.findIndex(x => x.reviewer === r.reviewer && x.week_start === r.week_start && x.method === r.method);
          if (i >= 0) db.weekly_log[i] = r; else db.weekly_log.push(r);
          return { data: r, error: null };
        }
        db.conflicts.push(opts && opts.onConflict);
        if (rows.some(r => db.reviews.some(x => x.pid === r.pid && x.reviewer !== r.reviewer)))
          return { data: null, error: { code: "23505", message: "duplicate key value violates unique constraint" } };
        rows.forEach(r => {
          const i = db.reviews.findIndex(x => x.pid === r.pid);
          if (i >= 0) db.reviews[i] = r; else db.reviews.push(r);
        });
        return { data: rows, error: null };
      },
    };
  },
  rpc: async (name, args) => {
    const key = args.key;
    db.rpcs.push(name + " " + (key || args.record_uid));
    if (name === "desk_record") return { data: [{ key: "Occupation", value: "Civil engineer" }, { key: "Description", value: "Designed the bridge." }], error: null };
    if (name === "claim_card") {
      if (db.failClaim === key) { db.failClaim = null; return { data: null, error: { message: "network" } }; }
      if (db.reviews.some(r => r.card_key === key && r.reviewer !== "u1")) return { data: false, error: null };
      const h = db.claims[key];
      if (h && h !== "u1") return { data: false, error: null };
      db.claims[key] = "u1"; return { data: true, error: null };
    }
    if (db.claims[key] === "u1") delete db.claims[key];
    return { data: null, error: null };
  },
  storage: { from: () => ({ download: async () => { db.log.push("asked desk.json"); if (db.deskGate) await db.deskGate; return ({ data: { text: async () =>
    JSON.stringify({ index: [["r-9", "Tan, Mei Ling", "PERSON", "Engineer", ""]], npt: { "r-9": ["陈美玲"] }, noted: [{ entity: "Noted One", new: false, article: "x", link: "https://x" }],
      status: { published: "2026-09-28T17:40:00Z", newest_news: "2026-09-27", tte_dump: "TTE-DELTA_20260901.zip (2026-09-01)",
                steps: { load: "success", relevance: "success", extraction: "failure", resolution: "success" } } }) } }); } }) },
};
globalThis.supabase = { createClient: () => fake };

const api = new Function(fs.readFileSync(process.argv[2], "utf-8")
  + "\n;return {render, REAL, PRACTICE, NPT, INDEX, get CARDS(){return CARDS}, get labels(){return labels}, csv};")();
db.deck = ["uid:r1", "uid:r2", "uid:r3", "uid:r4", "uid:r5"].map((key, i) => {
  const c = JSON.parse(JSON.stringify(api.PRACTICE[i === 2 ? 2 : 0]));
  c.key = key; c.pids = [901 + i]; c.i = i; delete c.practice; delete c.coach;
  return { key, card: c };
});

const stage = byId.stage;
const buttons = () => stage.all().filter(n => n.tagName === "BUTTON");
const click = label => {
  const b = buttons().find(n => n.textContent.trim().startsWith(label));
  if (!b) throw new Error("no button " + label + " among " + JSON.stringify(buttons().map(x => x.textContent.trim())));
  b.click();
};
const ask = () => (stage.querySelector(".ask") || {}).textContent || "";
const must = (cond, what) => { if (!cond) throw new Error("expected " + what); console.log("ok  " + what); };
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise(r => setImmediate(r)); };
const inputs = () => stage.all().filter(n => n.tagName === "INPUT");

(async () => {
  store["tte-desk-tutorial-v1"] = "1"; store["tte-desk-practice-v1"] = "1";
  await settle();
  must(inputs().some(n => n.type === "email") && inputs().some(n => n.type === "password"), "an account sign-in, not a name box");
  must(stage.all().some(n => n.tagName === "A" && n.href === "pipeline.html"), "the explainer is a link away");
  click("No account?");
  const req = stage.querySelector(".request");
  must(!!req, "someone without an account can ask for one");
  req.all().find(n => n.tagName === "INPUT" && !n.type).value = "New Person";
  req.all().find(n => n.tagName === "INPUT" && n.type === "email").value = "new@nlb.gov.sg";
  req.all().find(n => n.tagName === "TEXTAREA").value = "Cataloguing, organisations";
  click("Send the request"); await settle();
  must(db.access_requests.length === 1 && db.access_requests[0].email === "new@nlb.gov.sg" && /Sent/.test(stage.querySelector(".request").textContent), "the request reaches the table and the screen says so");
  inputs().find(n => n.type === "email").value = "glenn@nlb.gov.sg";
  inputs().find(n => n.type === "password").value = "wrong";
  click("Sign in"); await settle();
  must(/not accepted/.test(stage.textContent), "a wrong password is refused");
  inputs().find(n => n.type === "password").value = "pw";
  // A slow connection: nothing answers until the gates open.
  let open, openDesk;
  db.gate = new Promise(r => { open = r; }); db.deskGate = new Promise(r => { openDesk = r; });
  click("Sign in"); await settle();
  must(["asked deck", "asked reviews", "asked claims", "asked desk.json"].every(x => db.log.includes(x)),
       "the deck, the decisions, the holds and the search index are all asked for before any answers");
  must(/Fetching the deck/.test(stage.textContent), "the screen says it is fetching while it waits");
  open(); await settle();
  must(!/Fetching the deck/.test(stage.textContent) && api.INDEX.length === 0,
       "the deck is on the screen while the search index is still on its way");
  openDesk(); await settle();
  db.gate = null; db.deskGate = null;
  must(/Before you start/.test(ask()) && !inputs().some(n => !n.type), "the account is the name; languages and groups are asked once");
  must(/People \(4\)/.test(stage.textContent) && /Organisations \(1\)/.test(stage.textContent), "the groups are counted over the fetched deck");
  db.failClaim = "uid:r1";   // the claim for the card after the held one will not reach the table
  click("Start"); await settle();
  must(api.CARDS.length === 3 && !api.CARDS.some(c => c.key === "uid:r3" || c.key === "uid:r2"),
       "cards another reviewer decided or holds are never dealt");
  must(/0 of 3 records reviewed · 1 decided by others/.test(byId.count.textContent), "the count says what others did");
  must(api.CARDS[0].key === "uid:r4" && /same person/.test(ask()) && db.claims["uid:r4"] === "u1",
       "a card held from an earlier sitting comes back first, though newer news waits");
  must(api.INDEX.length === 1 && api.NPT["r-9"][0] === "陈美玲", "the search index came from the bucket");
  const stamp = () => {
    click("Same"); click("Accept"); click("Accept"); stage.all().filter(n => n.classList.contains("chip"))[0].click();
    click("Accept my wording"); click("Accept");
  };
  must(!db.claims["uid:r1"] && !db.rpcs.includes("claim_card uid:r5") && /same person/.test(ask()),
       "a card asked for ahead that cannot reach the table changes nothing on the screen");
  stamp(); await settle();
  must(db.reviews.some(r => r.pid === 904 && r.reviewer === "u1") && !db.claims["uid:r4"], "the decision is in the table and the card let go");
  must(/Can't reach the desk/.test(stage.textContent) && !/same person/.test(ask()) && !db.claims["uid:r1"],
       "a claim that cannot reach the table shows no card, and says so");
  click("Try again"); await settle();
  must(/same person/.test(ask()) && db.claims["uid:r1"] === "u1", "trying again checks the card out, then shows it");
  must(db.claims["uid:r5"] === "u1", "the next card is already checked out while this one is worked on");
  stamp(); await settle();
  must(/same person/.test(ask()) && db.claims["uid:r5"] === "u1", "the next free card is checked out");
  // Past every hold, the table itself keeps one decision per proposal.
  db.reviews.push({ pid: 905, card_key: "uid:r5", reviewer: "u2", decision: { verdict: "reject" } });
  stamp(); await settle();
  must(!db.reviews.some(r => r.pid === 905 && r.reviewer === "u1") && !api.labels[905] && /already holds a decision/.test(stage.textContent),
       "a second decision on one record is refused by the table");
  const mine = db.reviews.filter(r => r.reviewer === "u1").map(r => r.pid).sort();
  must(mine.join() === "901,904" && db.reviews.find(r => r.pid === 904).decision.verdict === "approve", "both decisions are in the table");
  must(db.conflicts.every(x => x === "pid"), "decisions are written one per proposal");
  must(!Object.values(db.claims).includes("u1") && !db.rpcs.includes("claim_card uid:r2") && /All done/.test(ask()),
       "every card is let go once decided; the held card was never asked for");
  must(/Noted One/.test(stage.textContent), "the noted list came from the bucket");
  must(store["tte-review-v5:u1"] && JSON.parse(store["tte-review-v5:u1"])[904] && !JSON.parse(store["tte-review-v5:u1"])[905], "the browser keeps a copy under the account");

  must(db.meta && db.meta.langs && db.meta.langs.includes("en"), "the reviewer's languages and groups are kept on the account");

  // Your sheet: an approved change marked done in TTE, and the evaluation's two logs.
  byId.sheet.click(); await settle();
  const doneBtn = stage.all().find(n => n.tagName === "BUTTON" && /mark done in TTE/.test(n.textContent));
  must(!!doneBtn, "an approved record can be marked done in TTE");
  doneBtn.click(); await settle();
  must(db.reviews.some(r => r.reviewer === "u1" && r.decision.done) && /done in TTE/.test(stage.textContent),
       "done in TTE is saved with the decision");
  const forms = stage.all().filter(n => n.tagName === "FORM");
  must(forms.length === 2, "the sheet carries the evaluation's two logs");
  const inputsOf = f => f.all().filter(n => n.tagName === "INPUT");
  const [, weekMinutes, weekChanges] = inputsOf(forms[0]);
  weekMinutes.value = "140"; weekChanges.value = "6";
  await forms[0].onsubmit({ preventDefault() {} }); await settle();
  must(db.weekly_log.length === 1 && db.weekly_log[0].minutes === 140 && db.weekly_log[0].method === "manual"
       && db.weekly_log[0].reviewer === "u1", "this week's minutes and changes are saved");
  const log = inputsOf(forms[1]);   // date, article, record, uid, attribute, current, new
  log[1].value = "https://x/khaw"; log[2].value = "Khaw Boon Wan"; log[4].value = "Affiliations(groupName)"; log[6].value = "SPH Media Trust";
  await forms[1].onsubmit({ preventDefault() {} }); await settle();
  must(db.change_log.length === 1 && db.change_log[0].tte_entity === "Khaw Boon Wan" && db.change_log[0].method === "manual"
       && db.change_log[0].kind === "amend", "a change found by hand is logged");
  byId.sheet.click(); await settle();

  // The team page: everyone's progress and the pipeline's, no one's own numbers.
  byId.team.click(); await settle();
  const team = stage.textContent;
  must(/The team's desk/.test(team) && /decided/.test(team) && /kept for review/.test(team), "the team page counts the whole deck");
  must(/TTE-DELTA_20260901/.test(team) && /extraction \u2717 failed/.test(team) && /2026-09-27/.test(team),
       "the team page says how the pipeline's last run went");
  must(/This week: 2 records approved, 1 of them done in TTE/.test(team), "this week's approvals and what is done in TTE");
  stage.all().find(n => n.tagName === "BUTTON" && /team's decisions/.test(n.textContent)).click();
  must(globalThis.__lastDownload.split("\n").length === db.reviews.length + 1 && /done_in_tte/.test(globalThis.__lastDownload),
       "the team's decisions download, every reviewer's, with done in TTE");
  byId.team.click(); await settle();

  // out and back in: the decision comes back from the table
  stage.replaceChildren();
  byId.me.all().find(n => n.tagName === "BUTTON" && n.textContent === "Sign out").click(); await settle();
  must(inputs().some(n => n.type === "email") && api.REAL.length === 0, "sign out clears the desk");
  inputs().find(n => n.type === "email").value = "glenn@nlb.gov.sg";
  inputs().find(n => n.type === "password").value = "pw";
  click("Sign in"); await settle();
  must(!/Before you start/.test(ask()) && api.labels[904] && /2 of 2 records reviewed/.test(byId.count.textContent), "signed in again, the decision is back and the questions are not asked twice");
  must(api.csv().split("\n").length === 3, "the sheet carries the decision from the table");

  // A test account looks at the real deck and writes nothing.
  delete db.claims["uid:r2"];   // one card free for it to look at
  stage.replaceChildren();
  byId.me.all().find(n => n.tagName === "BUTTON" && n.textContent === "Sign out").click(); await settle();
  inputs().find(n => n.type === "email").value = "test@nlb.gov.sg";
  inputs().find(n => n.type === "password").value = "tpw";
  const before = { reviews: db.reviews.length, rpcs: db.rpcs.length };
  click("Sign in"); await settle();
  if (/Before you start/.test(ask())) { click("Start"); await settle(); }
  must(/Test account/.test(stage.textContent) && /same person/.test(ask()), "a test account sees the deck, and is told nothing is saved");
  // A record picked through search is drawn from the whole record, fetched when
  // it is chosen: the index holds a name and an identity line only.
  click("search for other matches");
  const sbox = stage.all().find(n => n.tagName === "INPUT");
  sbox.value = "mei ling"; sbox.oninput();
  stage.all().find(n => n.classList.contains("hit") && /Tan, Mei Ling/.test(n.textContent)).click(); await settle();
  must(db.rpcs.includes("desk_record r-9") && /Civil engineer/.test(stage.textContent) && /Designed the bridge/.test(stage.textContent)
       && !/Loading the record/.test(stage.textContent), "a record found by search shows its properties, fetched when it is chosen");
  stage.all().find(n => n.classList.contains("tab") && /Tan, Mei Ling/.test(n.textContent)).click();
  stamp(); await settle();
  must(db.reviews.length === before.reviews && !db.reviews.some(r => r.reviewer === "u9")
       && !db.rpcs.slice(before.rpcs).some(x => x.startsWith("claim_card")), "a test account holds no card and saves no decision");
  // Nothing kept in the browser, and nothing to download.
  must(!Object.keys(store).some(k => k.endsWith(":u9")), "a test account keeps no copy of its decisions in the browser");
  byId.sheet.click(); await settle();
  must(/nothing to download/.test(stage.textContent) && !stage.all().some(n => n.tagName === "BUTTON" && /download/i.test(n.textContent)),
       "a test account's sheet has no download");
  byId.sheet.click(); await settle();
  byId.team.click(); await settle();
  must(/The team's desk/.test(stage.textContent) && !stage.all().some(n => n.tagName === "BUTTON" && /download/i.test(n.textContent)),
       "a test account's team page has no download");
  byId.team.click(); await settle();
  console.log("PASS");
})().catch(e => { console.error(e); process.exit(1); });
