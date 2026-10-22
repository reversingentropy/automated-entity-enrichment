// Drives the desk's Evaluation page against the stand-in (app2_fake.js): hidden from a reviewer; for an evaluator,
// the three sheets in the pipeline's order, the scored report and the desk's acceptance; each sheet's own rules,
// accepted before its rows every time it is chosen and a click away on every row; relevance by key and by click, Back, the shared rows
// then the dealt ones, a row a colleague labelled first or holds, a lapsed hold, Stop for now; matching's three
// answers; extraction's marks, wrong details, a missed name selected in the article or typed in; and a test account
// that saves nothing. Writes one line, RESULT {...} or ERROR ..., into #selftest.
(async () => {
  const F = window.__FAKE__, out = {};
  const tick = (ms = 20) => new Promise(r => setTimeout(r, ms));
  const until = async (f, n = 400) => { for (let i = 0; i < n; i++) { if (f()) return true; await tick(); } return false; };
  const say = t => { const pre = document.querySelector("#selftest"); pre.hidden = false; pre.textContent = t; };
  const stage = () => document.querySelector("#stage").innerHTML;
  const q = s => document.querySelector(s);
  const key = k => document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
  const idle = () => until(() => !EV.busy);
  const labelOf = (task, item, who = "u1") => (F.evalLabels.find(l => l.task === task && l.item === item && l.labeller === who) || {}).label;
  const as = async (id, meta) => {
    const u = { id, email: id + "@nlb.gov.sg", user_metadata: { name: id === "u9" ? "Tester" : "Glenn" }, app_metadata: meta };
    F.setUser(u); await signedIn(u); await until(() => !loading && CARDS.length);
  };
  const rel = F.evalItems.filter(i => i.task === "relevance").sort((a, b) => a.ord - b.ord).map(i => i.item);
  try {
    // a reviewer: no Evaluation in the sidebar, and the page itself asks nothing of the database
    await until(() => document.querySelector("#veil .signin"));
    q("#em").value = "glenn@nlb.gov.sg"; q("#pw").value = "pw";
    act("signin");
    out.loaded = await until(() => !loading && CARDS.length);
    out.reviewerNoNav = q("#evalnav").hidden === true;
    act("nav", { dataset: { nav: "evaluation" } }); await tick(40);
    out.reviewerRefused = /for evaluators/.test(stage()) && !F.rpcs.some(r => r.startsWith("eval_")) && !F.readLabels;

    // an evaluator: the three sheets, how far along each is, the report, and the desk's acceptance
    langs = ["en"];
    await as("u1", { evaluator: true });
    out.evaluatorNav = q("#evalnav").hidden === false;
    act("nav", { dataset: { nav: "evaluation" } });
    out.overviewLoaded = await until(() => EV.progress && EV.report !== undefined && /Start/.test(stage()));
    out.overview = /Label the sheets/.test(stage()) && /Relevance/.test(stage()) && /Matching/.test(stage()) && /Extraction/.test(stage())
      && /you have done 0 of the 49 in your languages/.test(stage())
      && /Relevance<\/h3>[\s\S]*Extraction<\/h3>[\s\S]*Matching<\/h3>/.test(stage()) && !/data-act="ev-guide"/.test(stage()) && /2 are only in languages you do not read/.test(stage());
    out.reportShown = stage().includes("precision 0.91 &lt;weighted&gt;") && !F.readLabels;
    // Glenn accepted the date started and the description, and left out the founder: one change per date, by language
    const acc = stage().slice(stage().indexOf("Changes accepted on the desk"));
    out.acceptanceShown = /<table class="evacc">/.test(acc) && /Date started<\/td><td>100%/.test(acc) && /Founder<\/td><td>0%/.test(acc)
      && /Description<\/td><td>100%/.test(acc) && /<th>Chinese<\/th>/.test(acc) && !/Month started/.test(acc);

    // relevance: the shared rows first, in sheet order, in the labeller's languages; the AI's answer nowhere
    // the rules first, written from the prompt, with its version; the keys answer nothing under them
    act("ev-start", { dataset: { t: "relevance" } }); await tick(40);
    out.guideFirst = EV.guide && !EV.item && /Not relevant:/.test(stage()) && /Make your best call/.test(stage()) && /Accept and start/.test(stage())
      && !/Same:|Nothing missed/.test(stage()) && /<code>prompts\/relevance.txt<\/code> \(version [0-9a-f]{8}\)/.test(stage())
      && !F.rpcs.some(r => r.startsWith("eval_take"));
    key("y"); await tick(40);
    out.guideKeysDoNothing = !F.evalLabels.length && EV.guide;
    act("ev-guide-done"); await until(() => EV.item);
    out.relFirst = EV.item.ord === 1 && stage().includes("Headline 1<") && stage().includes("Summary 1<") && /Yes, relevant/.test(stage())
      && /one of everyone\u2019s 50/.test(stage()) && !/app_said|AI said/.test(stage()) && !/Open article/.test(stage());
    // the row alone, and its rules a click away
    out.rowIsShort = !/class="evguide"/.test(stage()) && /data-act="ev-guide">Rules</.test(stage());
    act("ev-guide");
    out.fullGuideOpens = !!q("#veil .evguide") && /Not relevant:/.test(q("#veil").innerHTML);
    key("y"); await tick(40);
    out.keysWaitForGuide = !F.evalLabels.length && EV.item.ord === 1;
    act("ev-guide-close");
    out.guideCloses = !q("#veil");
    key("y"); await until(() => EV.item && EV.item.ord === 2);
    out.relKeySaved = labelOf("relevance", rel[0]).relevant === true && F.evalLabels[0].seconds >= 0;
    act("ev-rel", { dataset: { v: "n" } }); await until(() => EV.item && EV.item.ord !== 2);
    out.relOtherLanguageSkipped = EV.item.ord === 4 && labelOf("relevance", rel[1]).relevant === false;
    // Back: the last row again, its answer shown; answered again, the label is replaced, not added
    act("ev-back");
    out.backShowsAnswer = EV.item.ord === 2 && /stamp red was/.test(stage()) && !/stamp go was/.test(stage());
    act("ev-rel", { dataset: { v: "y" } }); await until(() => EV.item && EV.item.ord === 4);
    out.backReplaces = F.evalLabels.filter(l => l.item === rel[1]).length === 1 && labelOf("relevance", rel[1]).relevant === true;
    for (let g = 0; g < 60 && EV.item && EV.item.ord <= 50; g++) { act("ev-rel", { dataset: { v: "y" } }); await idle(); }
    out.sharedDone = F.evalLabels.filter(l => l.task === "relevance" && l.labeller === "u1").length === 49 && !labelOf("relevance", rel[2]);
    // past the shared rows: dealt, and held, one at a time
    const r51 = EV.item && EV.item.item;
    out.dealtHeld = EV.item && EV.item.ord === 51 && F.evalHolds.some(h => h.item === r51 && h.labeller === "u1") && /given to you alone/.test(stage());
    // a colleague labelled it first: this label is not kept, and the labeller is told
    F.evalLabels.push({ task: "relevance", item: r51, labeller: "u3", label: { relevant: false }, seconds: 4, at: new Date().toISOString() });
    act("ev-rel", { dataset: { v: "y" } }); await idle();
    out.colleagueFirstRefused = !labelOf("relevance", r51) && /A colleague labelled that row first/.test(stage()) && EV.item && EV.item.ord === 52;
    // a row a colleague holds is not dealt
    F.evalHolds.push({ task: "relevance", item: rel[52], labeller: "u3", held_at: new Date().toISOString() });
    act("ev-rel", { dataset: { v: "n" } }); await idle();
    out.heldRowSkipped = EV.item && EV.item.ord === 54 && !/A colleague labelled/.test(stage());
    act("ev-rel", { dataset: { v: "n" } }); await idle();
    out.sheetDone = !EV.item && /Nothing left for you on this sheet/.test(stage());
    // the colleague's hold lapses: the row comes back
    F.shift = 61 * 60000; act("ev-retry"); await until(() => EV.item); F.shift = 0;
    out.lapsedHoldDealt = EV.item && EV.item.ord === 53 && F.evalHolds.some(h => h.item === rel[52] && h.labeller === "u1");
    // stop for now: the hold is given back, and the overview counts what is done
    act("ev-stop"); await until(() => !F.evalHolds.some(h => h.labeller === "u1") && EV.progress && /done 49 of the 49/.test(stage()));
    out.stopReleases = F.rpcs.includes("eval_release:") && !EV.task && /Label the sheets/.test(stage()) && /Continue/.test(stage());

    // matching: the news beside the record; same, different, or can't tell, by key
    act("ev-start", { dataset: { t: "matching" } }); await tick(40);
    out.matchGuide = EV.guide && /A matching name alone is not enough/.test(stage()) && /prompts\/resolution.txt/.test(stage()) && !/Not relevant/.test(stage());
    act("ev-guide-done"); await until(() => EV.item);
    out.matchShown = /same\?/.test(stage()) && /Lee, Theng Kiat/.test(stage()) && /<mark>Lee Theng Kiat<\/mark>/.test(stage()) && /Can\u2019t tell/.test(stage()) && /Open article/.test(stage());
    const m = F.evalItems.filter(i => i.task === "matching").sort((a, b) => a.ord - b.ord).map(i => i.item);
    key("?"); await until(() => EV.item && EV.item.ord === 2);
    key("n"); await until(() => EV.item && EV.item.ord === 3);
    key("y"); await until(() => !EV.item && !EV.busy);
    out.matchKeys = [0, 1, 2].map(i => (labelOf("matching", m[i]) || {}).same).join() === "?,N,Y";
    act("ev-stop"); await until(() => !EV.task);

    // extraction: each name marked, any wrong detail tapped, and who it missed
    act("ev-start", { dataset: { t: "extraction" } }); await tick(40);
    out.extGuide = EV.guide && /Not worth a record:/.test(stage()) && /prompts\/extraction.txt/.test(stage()) && /prompts\/tte\/notability.txt/.test(stage());
    act("ev-guide-done"); await until(() => EV.item);
    const x1 = EV.item, [n0, n1] = x1.body.names.map(n => n.entity);
    out.extHighlights = /<mark>Acme Robotics<\/mark>/.test(stage()) && /<mark>Chng Siew Hern<\/mark>/.test(stage()) && !/<mark>Lim Bee Hoon/.test(stage());
    out.extWaits = q('[data-act="ev-save"]').disabled && /2 names still to mark/.test(stage()) && !q('[data-act="ev-field"]');
    act("ev-verdict", { dataset: { i: "0", v: "ok" } });
    out.chipsForOk = document.querySelectorAll('[data-act="ev-field"][data-i="0"]').length === 2;
    act("ev-field", { dataset: { i: "0", j: "1" } }); act("ev-field", { dataset: { i: "0", j: "0" } }); act("ev-field", { dataset: { i: "0", j: "0" } });
    out.chipMarkedWrong = EV.label.names[n0].wrong_fields.join() === "Founder" && document.querySelectorAll(".evchip.bad").length === 1;
    act("ev-verdict", { dataset: { i: "1", v: "not_worth" } });
    out.waitsForMissed = q('[data-act="ev-save"]').disabled && /Say who it missed/.test(stage());
    // a name selected in the article can be added as missed
    const walker = document.createTreeWalker(q("#evtext"), NodeFilter.SHOW_TEXT);
    let node; while ((node = walker.nextNode()) && !node.data.includes("Lim Bee Hoon"));
    const at = node.data.indexOf("Lim Bee Hoon"), range = document.createRange();
    range.setStart(node, at); range.setEnd(node, at + "Lim Bee Hoon".length);
    getSelection().removeAllRanges(); getSelection().addRange(range);
    out.selectOffersAdd = await until(() => !q("#evadd").disabled && /Add “Lim Bee Hoon” as missed/.test(q("#evadd").textContent));
    act("ev-addmiss");
    out.missedAdded = EV.label.missed.join() === "Lim Bee Hoon" && /evchip miss/.test(stage()) && q('[data-act="ev-none"]').disabled && !q('[data-act="ev-save"]').disabled;
    act("ev-save"); await until(() => EV.item && EV.item !== x1);
    const l1 = labelOf("extraction", x1.item) || { names: {} };
    out.extSaved = (l1.names[n0] || {}).verdict === "ok" && l1.names[n0].wrong_fields.join() === "Founder" && (l1.names[n1] || {}).verdict === "not_worth"
      && (l1.missed || []).join() === "Lim Bee Hoon" && !("none" in l1);
    // an article whose text could not be fetched: a link to it, and the missed names typed in instead
    const x2 = EV.item;
    out.noTextFallback = !!q("#evmisstxt") && /Open the article/.test(stage()) && !q("#evadd");
    act("ev-verdict", { dataset: { i: "0", v: "wrong" } });
    out.wrongHasNoChips = !q('[data-act="ev-field"]');
    const ta = q("#evmisstxt"); ta.value = "Tan Ah Kow\n\n"; ta.dispatchEvent(new Event("input", { bubbles: true }));
    out.typedMissedReady = !q('[data-act="ev-save"]').disabled && q('[data-act="ev-none"]').disabled;
    ta.value = ""; ta.dispatchEvent(new Event("input", { bubbles: true }));
    out.clearedNotReady = q('[data-act="ev-save"]').disabled;
    act("ev-none");
    out.nothingMissedReady = !q('[data-act="ev-save"]').disabled && /class="ok on"/.test(stage());
    act("ev-save"); await until(() => !EV.item && !EV.busy);
    const l2 = labelOf("extraction", x2.item) || { names: {} };
    out.extSecondSaved = Object.values(l2.names).map(n => n.verdict).join() === "wrong" && (l2.missed || [1]).length === 0;
    act("ev-stop"); await until(() => !EV.task);

    // a test account marked as an evaluator: walks the rows here, and the database keeps nothing
    const nL = F.evalLabels.length, nH = F.evalHolds.length;
    await as("u9", { test: true, evaluator: true });
    out.signInResets = !EV.task && !EV.item;
    act("nav", { dataset: { nav: "evaluation" } }); await until(() => EV.progress);
    const nR = F.rpcs.length;
    act("ev-start", { dataset: { t: "relevance" } }); await tick(40);
    out.rulesEveryTime = EV.guide && !EV.item;      // the rules again, though accepted before in this browser
    act("ev-guide-done"); await until(() => EV.item);
    const t1 = EV.item.ord;
    key("y"); await until(() => EV.item && EV.item.ord !== t1);
    out.testWalks = t1 === 1 && EV.item.ord === 2 && /nothing you label is saved/.test(stage());
    out.testSavesNothing = F.evalLabels.length === nL && F.evalHolds.length === nH && !F.rpcs.slice(nR).some(r => /^eval_(take|save)/.test(r));
    out.noDirectWrites = !F.direct && !F.readLabels;
    say("RESULT " + JSON.stringify(out));
  } catch (e) { say("ERROR " + (e && e.stack || e) + "\n" + JSON.stringify(out)); }
})();
