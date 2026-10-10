// Drives the second desk online against the stand-in: sign in, who is dealt what, holding a record, saving each
// decision, the variant-name change, the reader's language first, a refused hold, a clash, a dropped connection,
// and a test account. Writes one line, RESULT {...} or ERROR ..., into #selftest.
(async () => {
  const F = window.__FAKE__, out = {};
  const tick = (ms = 20) => new Promise(r => setTimeout(r, ms));
  const until = async (f, n = 300) => { for (let i = 0; i < n; i++) { if (f()) return true; await tick(); } return false; };
  const say = t => { const pre = document.querySelector("#selftest"); pre.hidden = false; pre.textContent = t; };
  const decideThrough = async () => {          // accept every change of the record on screen, or confirm it
    const k = card().key;
    if (stOf(card()).screen === "create") act("create"); else act("same");
    for (let g = 0; g < 30 && !DECIDED.has(k); g++) act("accept");
    await until(() => !UNSENT[k]);
    return k;
  };
  try {
    out.signInShown = await until(() => document.querySelector("#veil .signin"));
    document.querySelector("#em").value = "glenn@nlb.gov.sg"; document.querySelector("#pw").value = "pw";
    act("signin");
    out.loaded = await until(() => !loading && CARDS.length && NPT_READY);
    out.cards = CARDS.length;
    // home first: how many are waiting, and one button to go on
    out.homeFirst = PAGE === "home" && /records? waiting for you/.test(document.querySelector("#stage").innerHTML)
                    && !!document.querySelector('[data-act="start"]') && !F.rpcs.some(r => r.startsWith("claim_card"));
    // the line of the day: shown on the day it was written, never a stale one
    const t = new Date(), today = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
    STATUS = { line: { date: today, text: "A quiet Saturday for the catalogue." } }; draw();
    out.dayLineShown = document.querySelector("#stage").innerHTML.includes("A quiet Saturday for the catalogue.");
    STATUS.line.date = "2000-01-01"; draw();
    out.staleLineHidden = !document.querySelector("#stage").innerHTML.includes("A quiet Saturday");
    out.noAllSaved = !/all saved/i.test(document.querySelector("#stage").innerHTML);
    // choosing languages from home stays on home, claiming nothing
    act("settings"); act("savelangs");
    out.langsStayHome = PAGE === "home" && !document.querySelector("#veil") && !F.rpcs.some(r => r.startsWith("claim_card"));
    act("start");
    out.dealt = LIST.map(i => CARDS[i].key);
    out.firstIsMine = card().key === F.mine;
    out.othersNotDealt = !out.dealt.includes(F.theirs) && !out.dealt.includes(F.theirReview);
    out.noClaimForHeld = !F.rpcs.some(r => r === "claim_card:" + F.mine);
    // the variant name: asked for a Chinese name TTE lacks, not for one it holds
    const cOf = key => CARDS.find(c => c.key === key);
    out.variantAsked = rowsFor(cOf(F.mine), ordered(cOf(F.mine))[0]).some(r => r.variant);
    out.variantNotAskedWhenHeld = !rowsFor(cOf(F.theirReview), ordered(cOf(F.theirReview))[0]).some(r => r.variant);
    // and it can be corrected, or put in place of the names TTE has, like any list
    const vc = cOf(F.mine), vrow = rowsFor(vc, ordered(vc)[0]).findIndex(r => r.variant);
    const vst = Object.assign(fresh(vc), { screen: "change", chosen: 0, ch: vrow }), vhtml = change(vc, vst);
    out.variantEditable = /data-act="edit"/.test(vhtml) && /data-m="replace"/.test(vhtml) && /Other names in TTE now/.test(vhtml);
    vst.val[vrow] = ["雪城 (edited)"]; vst.mode[vrow] = "replace";
    const vgot = acceptedOf(vc, vst, rowsFor(vc, ordered(vc)[0])[vrow], vrow);
    out.variantEditSaved = vgot.field === "Variant name" && vgot.proposed === "雪城 (edited)";
    // decide the held record: saved with the variant row, then let go
    const k1 = await decideThrough();
    const mine = F.upserts.filter(r => r.card_key === k1);
    out.saved = mine.length === cOf(k1).pids.length && mine.every(r => r.reviewer === "u1" && r.verdict === "approve");
    out.savedVariant = mine.length && (mine[0].decision.rows || []).some(r => r.field === "Variant name" && r.proposed.split(" | ").includes(cOf(k1).entity));
    out.released = F.rpcs.includes("release_card:" + k1);
    // the next record is shown only once it is held
    await until(() => claimed(card()) === true);
    out.claimedNext = F.rpcs.includes("claim_card:" + card().key);
    // the record after it is refused: the desk moves on and says so
    const k2 = card().key, k3 = CARDS[LIST[1]].key;
    F.refuse.add(k3);
    act("keep");
    await until(() => !UNSENT[k2]);
    out.keptSavedUnsure = F.upserts.some(r => r.card_key === k2 && r.verdict === "unsure");
    await until(() => TAKEN.has(k3));
    out.refusedSkipped = TAKEN.has(k3) && !LIST.map(i => CARDS[i].key).includes(k3) && /someone else/.test(NOTICE);
    // a dropped connection keeps the decision and says it is not saved yet; it goes up on the next try
    await until(() => claimed(card()) === true);
    F.fail = true;
    const k4 = card().key;
    act("keep");
    await tick(100);
    out.unsentKept = !!UNSENT[k4] && /not saved yet/.test(document.querySelector("#count").textContent);
    F.fail = false; await flushUnsent();
    out.unsentSent = !UNSENT[k4] && F.upserts.some(r => r.card_key === k4);
    // stop for now: the record on screen is let go, and home says what is left
    await until(() => claimed(card()) === true);
    const ks = card().key;
    act("stopnow");
    out.stopReleases = F.rpcs.includes("release_card:" + ks) && PAGE === "home" && /still waiting/.test(document.querySelector("#stage").innerHTML);
    act("start");
    // someone else's decision already in the table: yours is not kept, and you are told
    await until(() => claimed(card()) === true);
    const k5 = card().key; F.conflict.add(k5);
    act("keep");
    await until(() => !UNSENT[k5]);
    out.clashTold = !DECIDED.has(k5) && /already decided/.test(NOTICE) && !LOG.some(x => x.key === k5);
    // the reader's language first: an English reader sees the English article of a mixed card
    langs = ["en"];
    out.englishFirst = fresh(cOf(F.mixed)).src === cOf(F.mixed).sources.findIndex(s => !/zaobao/.test(s.link));
    langs = ["en", "zh"];
    // the sheet after a reload: earlier decisions come back from the table
    F.reviews.push(...F.upserts);
    const before = LOG.length;
    await signedIn({ id: "u1", email: "glenn@nlb.gov.sg", user_metadata: { name: "Glenn" }, app_metadata: {} });
    out.resumed = LOG.length === before && LOG.every(x => DECIDED.has(x.key));
    // a test account: looks, holds nothing, saves nothing
    const nUp = F.upserts.length, nRpc = F.rpcs.length;
    await signedIn({ id: "u9", email: "test@nlb.gov.sg", user_metadata: { name: "Tester" }, app_metadata: { test: true } });
    act("start"); act("keep"); await tick(100);
    out.testWritesNothing = F.upserts.length === nUp && F.rpcs.length === nRpc && /Test account/.test(document.querySelector("#stage").innerHTML);
    say("RESULT " + JSON.stringify(out));
  } catch (e) { say("ERROR " + (e && e.stack || e) + "\n" + JSON.stringify(out)); }
})();
