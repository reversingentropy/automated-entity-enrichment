// Drives the second desk online against the stand-in (app2_fake.js): sign in, home, the database dealing each
// record, deciding with the next record handed over, kept for review, a hold that lapsed and went to a colleague,
// a dropped connection, switching type and languages quickly, stopping, changing one's own decision, a decided
// record brought back by new news, each person's count, and a test account. Writes one line, RESULT {...} or
// ERROR ..., into #selftest.
(async () => {
  const F = window.__FAKE__, out = {};
  const tick = (ms = 20) => new Promise(r => setTimeout(r, ms));
  const until = async (f, n = 400) => { for (let i = 0; i < n; i++) { if (f()) return true; await tick(); } return false; };
  const say = t => { const pre = document.querySelector("#selftest"); pre.hidden = false; pre.textContent = t; };
  const stage = () => document.querySelector("#stage").innerHTML;
  const settled = () => until(() => !dealBusy && DEAL !== "asking" && DEAL !== "saving");
  const cOf = key => CARDS.find(c => c.key === key);
  const decideThrough = async () => {          // accept every change of the record on screen, or confirm it
    const k = card().key;
    if (stOf(card()).screen === "create") act("create"); else act("same");
    for (let g = 0; g < 30 && DEALT === k && DEAL === null; g++) act("accept");
    await settled();
    return k;
  };
  try {
    out.signInShown = await until(() => document.querySelector("#veil .signin"));
    document.querySelector("#em").value = "glenn@nlb.gov.sg"; document.querySelector("#pw").value = "pw";
    act("signin");
    out.loaded = await until(() => !loading && CARDS.length && NPT_READY);
    out.cards = CARDS.length;
    // home first: how many are waiting, one button to go on, and nothing taken yet
    out.homeFirst = PAGE === "home" && /records? waiting for you/.test(stage()) && !!document.querySelector('[data-act="start"]') && F.rpcs.length === 0;
    const t = new Date(), today = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
    STATUS = { line: { date: today, text: "A quiet Saturday for the catalogue." } }; draw();
    out.dayLineShown = stage().includes("A quiet Saturday for the catalogue.");
    STATUS.line.date = "2000-01-01"; draw();
    out.staleLineHidden = !stage().includes("A quiet Saturday");
    out.noAllSaved = !/all saved/i.test(stage());
    act("settings");
    out.allFourLanguagesOffered = [...document.querySelectorAll("#veil .lang input")].map(x => x.value).join() === "en,zh,ms,ta";
    act("savelangs");
    out.langsStayHome = PAGE === "home" && !document.querySelector("#veil") && F.rpcs.length === 0;
    // Feedback 3: a date's day, month and year are one change, TTE's parts kept in grey; accepted, each part that
    // changes is its own field on the sheet
    const dc = CARDS.find(x => !x.isNew && ordered(x).length && !reopened(x) && x.picked !== ordered(x)[0].uid) || CARDS.find(x => !x.isNew && ordered(x).length);
    const dOpt = ordered(dc)[0], keepExtra = dOpt.extra, keepDates = dOpt.dates, keepS = S[dc.key];
    dOpt.extra = [{ field: "Day Started (dd)", strategy: "REPLACE", adding: "16", existing: ["01"] }, { field: "Month Started (mm)", strategy: "APPEND", adding: "9", existing: ["07"] }];
    dOpt.dates = { "Day Started (dd)": "01", "Month Started (mm)": "07", "Year Started (yyyy)": "2026" };
    S[dc.key] = undefined;
    const dst = stOf(dc), drows = rowsFor(dc, dOpt), dk = drows.findIndex(r => r.date);
    out.dateIsOneChange = drows.filter(r => r.date).length === 1 && !drows.some(r => /\((dd|mm|yyyy)\)$/.test(r.field));
    Object.assign(dst, { screen: "change", chosen: 0, cand: 0, ch: dk });
    const dhtml = change(dc, dst);
    out.dateShownWhole = /Set date started to this\?/.test(dhtml) && /Date started in TTE now/.test(dhtml) && /<s>1 Jul 2026<\/s>/.test(dhtml)
      && /class="newv">16<\/span> <span class="newv">Sep<\/span> <span class="old" title="Kept from TTE[^"]*">2026<\/span>/.test(dhtml) && /leave date started as it is/.test(dhtml);
    const sheet = acceptedOf(dc, dst, drows[dk], dk).filter(a => a.proposed !== a.current).map(a => `${a.field}:${a.current}>${a.proposed}`).join();
    out.dateAcceptWritesParts = sheet === "Day Started (dd):01>16,Month Started (mm):07>09";
    dst.edit[dk] = true; out.dateEditBoxes = (change(dc, dst).match(/class="din"/g) || []).length === 3;
    dateOf(dst, dk, drows[dk]).Year = "2025";
    out.dateEditedYearWritten = acceptedOf(dc, dst, drows[dk], dk).some(a => a.field === "Year Started (yyyy)" && a.current === "2026" && a.proposed === "2025");
    const born = rowsFor(dc, Object.assign({}, dOpt, { extra: [{ field: "Birth Year (yyyy)", strategy: "REPLACE", adding: "1974", existing: ["1973"] }], dates: {} }));
    out.birthDateOneChange = born.length >= 1 && born[0].field === "Date of birth" && born[0].existing[0] === "1973";
    const ev = rowsFor(dc, Object.assign({}, dOpt, { extra: [{ field: "Day", strategy: "REPLACE", adding: "17", existing: [] }, { field: "Month", strategy: "APPEND", adding: "11", existing: ["10"] }], dates: { Year: "2026" } }));
    const evAt = ev.findIndex(r => r.date);
    Object.assign(dst, { ch: evAt }); dst.val = {}; dst.edit = {};
    out.eventDateOneChange = ev.filter(r => r.date).length === 1 && ev[evAt].field === "Event date" && ev[evAt].existing[0] === "Oct 2026"
      && acceptedOf(dc, dst, ev[evAt], evAt).filter(a => a.proposed !== a.current).map(a => `${a.field}:${a.current}>${a.proposed}`).join() === "Day:>17,Month:10>11";
    dOpt.extra = keepExtra; dOpt.dates = keepDates; S[dc.key] = keepS;
    out.fieldNamed = fieldLabel("Day Started (dd)") === "Day started" && fieldLabel("Description") === "Description" && fieldLabel("Affiliations(groupName)") === "Affiliations";
    out.sourceDateHasYear = /2026/.test(dayOf("2026-09-16"));
    out.outletNamed = outletOf("https://www.beritaharian.sg/singapura/x") === "Berita Harian" && outletOf("https://www.tamilmurasu.com.sg/singapore/x") === "Tamil Murasu";
    // a record to create: a field naming records says whether TTE has each one, and any value can be left out with ×,
    // which keeps it off the sheet and is saved with the decision
    const nc = CARDS.find(x => x.isNew && x.newsLinked && x.newsLinked.Awards), nst = fresh(nc);
    const nShown = nc.newsFields.filter(f => f.key !== "Description").slice(0, 5).reduce((n, f) => n + fieldVals(f).length, 0);
    out.newRecordValuesCanBeLeftOut = (create(nc, nst).match(/data-act="nout"/g) || []).length === nShown;
    out.newRecordSaysWhatTteHas = /not in TTE/.test(create(nc, nst));
    const award = nc.newsFields.findIndex(f => f.key === "Awards");
    nst.out["n" + award + ":0"] = true;
    const nx = { kind: "created", entity: nc.entity, entityEn: nc.entityEn, ctype: nc.type, newsFields: nc.newsFields, leftOut: leftOutOf(nc, nst), accepted: [], when: new Date() };
    out.newRecordLeftOutStruck = /class="nvi out"/.test(create(nc, nst));
    out.newRecordLeftOutOffSheet = nx.leftOut.length === 1 && nx.leftOut[0].field === "Awards"
      && !changesRows([nx]).some(r => r[2] === "Awards") && changesRows([nx]).some(r => r[2] === "Affiliations(groupName)");
    // a quote says which language it is in, so Chinese and Tamil get their own fonts and Tamil its wider lines
    const zc = CARDS.find(x => (x.sources[0].link || "").includes("zaobao") && x.sources[0].original);
    const zhtml = newsBlock(zc, { i: 0, pills: [0], act: "src", names: [zc.entity] });
    out.quoteSaysItsLanguage = /<blockquote lang="zh">/.test(zhtml) && /<p class="tr" lang="en">/.test(zhtml);
    // and any value can be edited: the sheet carries the edit, and the decision keeps what was changed
    const ast = fresh(nc), aff = nc.newsFields.findIndex(f => f.key === "Affiliations(groupName)");
    ast.nedit = true;
    out.newRecordEditBoxes = (create(nc, ast).match(/class="cin nin"/g) || []).length === nShown && /<textarea class="dta nin"/.test(create(nc, ast));
    ast.nval[aff + ":0"] = "KK Women's and Children's Hospital";
    const ex = { kind: "created", entity: nc.entity, newsFields: nc.newsFields, fields: finalFields(nc, ast), edited: editedOf(nc, ast), leftOut: [], accepted: [], when: new Date() };
    out.newRecordEditOnSheet = changesRows([ex]).some(r => r[2] === "Affiliations(groupName)" && r[4] === "KK Women's and Children's Hospital")
      && ex.edited.length === 1 && toDecision(ex, nc).fields.length === ex.fields.length && toDecision(ex, nc).edited.length === 1;
    out.newRecordLeftOutSaved = toDecision(nx, nc).leftOut.length === 1 && fromDecision(toDecision(nx, nc), nc).leftOut.length === 1;
    // the variant name: asked for a Chinese name TTE lacks, not for one it holds; and it can be corrected or replaced
    out.variantAsked = rowsFor(cOf(F.mineKey), ordered(cOf(F.mineKey))[0]).some(r => r.variant);
    out.variantNotAskedWhenHeld = !rowsFor(cOf(F.theirReview), ordered(cOf(F.theirReview))[0]).some(r => r.variant);
    const vc = cOf(F.mineKey), vrow = rowsFor(vc, ordered(vc)[0]).findIndex(r => r.variant);
    const vst = Object.assign(fresh(vc), { screen: "change", chosen: 0, ch: vrow }), vhtml = change(vc, vst);
    out.variantEditable = /data-act="edit"/.test(vhtml) && /data-m="replace"/.test(vhtml) && /Non-English names in TTE now/.test(vhtml);
    vst.val[vrow] = ["雪城 (edited)"]; vst.mode[vrow] = "replace";
    const vgot = acceptedOf(vc, vst, rowsFor(vc, ordered(vc)[0])[vrow], vrow);
    out.variantEditSaved = vgot.field === "Non-English name" && vgot.proposed === "雪城 (edited)";

    // Start: the record already on this reviewer's desk comes back first, taken again by name
    act("start"); await settled();
    const who = () => document.querySelector("#who");
    out.realAccountNamed = !who().hidden && !who().classList.contains("test") && /Signed in as/.test(who().textContent) && /saved/.test(who().textContent);
    out.firstIsMine = DEALT === F.mineKey && F.rpcs.includes("claim_card:" + F.mineKey) && !F.rpcs.some(r => r.startsWith("take_next"));
    // deciding it: saved through decide(), the record given back and the next handed over in the same call
    const k1 = await decideThrough();
    const mine = F.reviews.filter(r => r.card_key === k1);
    out.saved = mine.length === cOf(k1).pids.length && mine.every(r => r.reviewer === "u1" && r.verdict === "approve");
    out.savedVariant = mine.length && (mine[0].decision.rows || []).some(r => r.field === "Non-English name" && r.proposed.split(" | ").includes(cOf(k1).entity));
    out.oneCallPerRecord = F.rpcs.filter(r => r === "decide:" + k1).length === 1 && !F.rpcs.some(r => r.startsWith("release_card:" + k1));
    out.nextDealt = !!DEALT && DEALT !== k1 && F.mine().length === 1 && F.mine()[0] === DEALT;
    out.othersNeverDealt = DEALT !== F.theirs && DEALT !== F.theirReview && !F.direct;
    // switching the type and the languages quickly: one record held at most, and the page shows the one the database gave
    const sel = document.querySelector("#group"), groups = [...sel.options].map(o => o.value);
    for (let r = 0; r < 3; r++) for (const g of groups) { sel.value = g; sel.dispatchEvent(new Event("change")); await tick(2); }
    await settled();
    out.oneHoldAfterTypes = F.mine().length <= 1 && (F.mine()[0] || null) === DEALT;
    // updating and creating apart: a new person is under "Create new records", never "People"; the groups never move
    const newP = CARDS.find(c => c.isNew && c.type === "PERSON");
    out.newRecordsApart = !!newP && groupOf(newP) === "new records" && CARDS.filter(c => groupOf(c) === "people").every(c => !c.isNew)
      && groups.join() === "all,people,organisations,other changes,new records";
    for (const ls of [["zh"], ["en"], ["en", "zh"], ["zh"], ["en", "zh"]]) {
      act("settings"); document.querySelectorAll("#veil .lang input").forEach(x => { x.checked = ls.includes(x.value); }); act("savelangs"); await tick(2);
    }
    await settled();
    out.oneHoldAfterLanguages = F.mine().length <= 1 && (F.mine()[0] || null) === DEALT;
    sel.value = "all"; sel.dispatchEvent(new Event("change")); await settled();
    // kept for review: saved as unsure, and never dealt back to the one who kept it
    const k2 = DEALT;
    act("keep"); await settled();
    out.keptSavedUnsure = F.reviews.some(r => r.card_key === k2 && r.verdict === "unsure" && r.decision.kept_by.includes("u1"));
    // a colleague's record kept for review is offered, with who kept it
    const kc = cOf(F.keptByJo);
    out.keptByColleagueOffered = openFor(kc) && /Jo kept this for review/.test(cardNote(kc));
    // away an hour: the hold lapsed and a colleague took the record. The late decision is not kept, and they are told
    const k3 = DEALT; F.steal(k3);
    act("keep"); await settled(); await until(() => DEALT && DEALT !== k3);
    out.lateDecisionRefused = !F.reviews.some(r => r.card_key === k3 && r.reviewer === "u1") && /went to a colleague while you were away/.test(NOTICE) && !LOG.some(x => x.key === k3) && DEALT !== k3;
    // the same, found by the renewal rather than by a decision
    const k4 = DEALT; F.steal(k4);
    await renewNow(); await settled();
    out.renewalFindsItGone = /went back to the pile/.test(NOTICE) && DEALT !== k4 && F.mine().length <= 1;
    // a renewal keeps the record while the reviewer works
    const k4b = DEALT; F.shift = 50 * 60000; await renewNow(); F.shift = 0;
    out.renewalKeeps = DEALT === k4b && F.rpcs.includes("renew_card:" + k4b) && F.mine()[0] === k4b;
    // three hours away, and nobody took the record: the first mouse movement renews the hold, and it is still theirs
    const kb = DEALT; lastActive = Date.now() - 3 * 3600e3; F.shift = 3 * 3600e3;
    document.dispatchEvent(new PointerEvent("pointermove")); await tick(80); F.shift = 0;
    out.backAndStillMine = DEALT === kb && F.mine()[0] === kb && F.rpcs.filter(r => r === "renew_card:" + kb).length >= 2;
    // three hours away, and a colleague took it: coming back to the window moves the screen on, and says why, before any click
    const kt = DEALT; F.steal(kt); lastActive = Date.now() - 3 * 3600e3;
    window.dispatchEvent(new Event("focus")); await tick(80); await settled();
    out.backAndTakenToldFirst = DEALT !== kt && /went back to the pile while you were away/.test(NOTICE);
    // (the colleague's other records go back, so there is still work for the checks below)
    F.claims = F.claims.filter(h => h.reviewer !== "u2" || h.card_key === F.theirs);
    if (!DEALT) { act("start"); await settled(); }
    // a dropped connection: the decision is kept here and said to be unsaved; it goes up when the connection is back
    const k5 = DEALT; F.fail = true;
    act("keep"); await until(() => DEAL === "unsaved");
    out.unsavedKept = !!UNSENT[k5] && /Not saved yet/.test(stage()) && F.mine()[0] === k5;
    if (!out.unsavedKept) out.unsavedDetail = [k5, DEAL, DEALT, Object.keys(UNSENT), F.mine(), F.claims.map(h => h.card_key + ":" + h.reviewer)];
    F.fail = false; act("resend"); await settled();
    out.unsavedSent = !UNSENT[k5] && F.reviews.some(r => r.card_key === k5) && DEALT !== k5;
    // stop for now: the record is given back, and home says what is left (Jo has finished, so there is one to take)
    F.claims = F.claims.filter(h => h.reviewer !== "u2");
    act("start"); await settled();
    const ks = DEALT;
    out.dealtAfterColleagueLeft = !!ks;
    act("stopnow"); await until(() => F.mine().length === 0);
    out.stopReleases = F.rpcs.includes("release_card:" + ks) && F.mine().length === 0 && PAGE === "home" && /still waiting/.test(stage());
    if (!out.stopReleases) out.stopDetail = [ks, F.mine(), PAGE, HOMENOTE];
    // change one's own decision: taken back by name, decided again, and the sheet keeps one line for it
    const i1 = LOG.findIndex(x => x.key === k1);
    act("redo", { dataset: { i: String(i1) } }); await until(() => DEALT === k1 && DEAL === null);
    out.redoTaken = DEALT === k1 && /changing your decision/.test(stage());
    act("discard"); await settled();
    out.redoReplaced = F.reviews.filter(r => r.card_key === k1).every(r => r.verdict === "reject" && r.reviewer === "u1") && LOG.filter(x => x.key === k1).length === 1;
    act("stopnow");
    // new news about a record a colleague decided: it comes back for the new proposal only
    const rc = F.deck.find(d => d.key === F.theirReview).card;
    rc.pids.push(99999);
    rc.sources.push({ pid: 99999, link: "https://www.zaobao.com/news/singapore/story20261231-1", date: "2026-12-31", article: "new", says: "", quote: "", original: "", name: rc.entity });
    rc.changes.push({ ...F.newChange, from: "https://www.zaobao.com/news/singapore/story20261231-1", supporters: ["https://www.zaobao.com/news/singapore/story20261231-1"] });
    CARDS.find(c => c.key === F.theirReview).pids = rc.pids.slice();
    Object.assign(CARDS.find(c => c.key === F.theirReview), JSON.parse(JSON.stringify(rc)));
    act("start"); await settled();
    const back = card(), asked = back ? rowsFor(back, ordered(back)[0]) : [];
    out.reopenedDealt = DEALT === F.theirReview;
    out.onlyNewAsked = asked.length === 1 && asked[0].field === F.newChange.field;
    out.reopenedNote = /Decided before by Jo/.test(stage());
    out.reopenedShowsNewArticle = back && back.sources[stOf(back).src].pid === 99999;
    act("stopnow");
    // each person's count, for fairness
    PAGE = "results"; VIEW = "team"; draw();
    out.perPerson = /Who decided how many/.test(stage()) && /Glenn/.test(stage()) && /Jo/.test(stage());
    PAGE = "home"; draw();
    // the reader's language first: an English reader sees the English article of a mixed card
    langs = ["en"];
    out.englishFirst = fresh(cOf(F.mixed)).src === cOf(F.mixed).sources.findIndex(s => !/zaobao/.test(s.link));
    // Home's numbers add up to the total, and the big number plus the other languages is what is still to decide
    PAGE = "home"; draw();
    const hd = homeData(), still = hd.segs.find(s => s[0] === "wait")[1];
    out.homeAddsUp = hd.segs.reduce((a, s) => a + s[1], 0) === hd.total && hd.n + hd.other === still && hd.other > 0
      && new RegExp(`${hd.other} more (is|are) only in other languages`).test(stage()) && new RegExp(`${still} still to decide`).test(stage());
    langs = ["en", "zh"];
    // a record confirmed with nothing to change is not on the changes sheet
    out.noConfirmOnlyRows = changesRows([{ kind: "uptodate", uid: "1", entity: "X", accepted: [], when: new Date() }]).length === 1;
    // the sheet after a reload: earlier decisions come back from the table
    const before = LOG.length;
    F.setUser({ id: "u1", email: "glenn@nlb.gov.sg", user_metadata: { name: "Glenn" }, app_metadata: {} });
    await signedIn({ id: "u1", email: "glenn@nlb.gov.sg", user_metadata: { name: "Glenn" }, app_metadata: {} });
    out.resumed = LOG.length === before && LOG.every(x => DECIDED.has(x.key));
    if (!out.resumed) out.resumedDetail = [before, LOG.length, LOG.map(x => x.key + ":" + x.kind)];
    // the languages decide what is offered: a record held from before, in a language no longer chosen, is given back
    // rather than offered first; a type with nothing in those languages cannot be picked; and one picked anyway sends
    // the reviewer home saying so, where Continue deals any type rather than asking for that one again
    const u1 = { id: "u1", email: "glenn@nlb.gov.sg", user_metadata: { name: "Glenn" }, app_metadata: {} };
    const zhOnly = CARDS.find(c => cardLangs(c).join() === "zh" && openFor(c) && !HELD.has(c.key));
    out.zhOnlyOpen = !!zhOnly;
    if (zhOnly) {
      F.claims = F.claims.filter(h => h.reviewer !== "u1").concat([{ card_key: zhOnly.key, reviewer: "u1", claimed_at: new Date().toISOString() }]);
      await signedIn(u1);
      act("start"); await settled();
      const heldZh = DEALT === zhOnly.key;
      act("nav", { dataset: { nav: "home" } });
      act("settings"); document.querySelectorAll("#veil .lang input").forEach(x => { x.checked = x.value === "en"; }); act("savelangs"); await tick(20);
      out.otherLanguageGivenBack = heldZh && !F.mine().includes(zhOnly.key) && !DEALT && homeData().next !== zhOnly && !stage().includes(esc(gist(nameOf(zhOnly), 40)));
      act("start"); await settled();
      out.emptyTypeNotOffered = [...sel.options].find(o => o.value === "organisations").disabled && !CARDS.some(c => available(c) && groupOf(c) === "organisations");
      sel.value = "organisations"; sel.dispatchEvent(new Event("change")); await settled();
      out.emptyTypeSaysSo = PAGE === "home" && /Nothing under Organisations/.test(stage()) && group === "all";
      act("start"); await settled();
      out.continueAfterEmptyType = F.rpcs.filter(r => r.startsWith("take_next")).pop() === "take_next:all" && group === "all" && (!DEALT || readable(card()));
      act("stopnow"); langs = ["en", "zh"];
    }
    // a test account: looks, holds nothing, saves nothing
    // ...and a test account holds nothing: an old hold of its own, in a language not chosen, is not offered first
    const zk = CARDS.find(c => cardLangs(c).join() === "zh").key;
    F.claims.push({ card_key: zk, reviewer: "u9", claimed_at: new Date(Date.now() - 30 * 86400e3).toISOString() });
    langs = ["en"];
    const nRev = F.reviews.length, nRpc = F.rpcs.length;
    F.setUser({ id: "u9", email: "test@nlb.gov.sg", user_metadata: { name: "Tester" }, app_metadata: { test: true } });
    await signedIn({ id: "u9", email: "test@nlb.gov.sg", user_metadata: { name: "Tester" }, app_metadata: { test: true } });
    out.testHoldsNothing = MINE.size === 0 && !available(cOf(zk)) && !LIST.some(i => CARDS[i].key === zk);
    act("start"); act("keep"); await tick(100);
    out.testWritesNothing = F.reviews.length === nRev && F.rpcs.length === nRpc && /Test account/.test(stage());
    out.testAccountNamed = who().classList.contains("test") && /Test account/.test(who().textContent) && /test@nlb\.gov\.sg/.test(who().textContent);
    out.noDirectWrites = !F.direct;

    // An account made on the sign-in screen: it waits, the admin approves it on their home page, and it can start.
    const suVeil = () => (document.querySelector("#veil") || {}).textContent || "";
    const suType = (vals) => Object.entries(vals).forEach(([id, v]) => { document.querySelector("#" + id).value = v; });
    F.setUser(null); signInPage(); act("signup");
    out.signUpShown = !!document.querySelector("#veil #nm") && !!document.querySelector("#veil #pw2");
    suType({ nm: "New Colleague", em: "new@nlb.gov.sg", pw: "short", pw2: "short" });
    act("dosignup"); await tick();
    out.signUpChecksLength = /at least 8/.test(suVeil()) && document.querySelector("#nm").value === "New Colleague";
    suType({ pw: "long enough", pw2: "long enough" });
    act("dosignup");
    out.signUpWaits = await until(() => /waiting for Ashwin/.test(suVeil()));
    act("checkagain");
    out.stillWaiting = await until(() => /Not approved yet/.test(suVeil()));
    const suId = F.accounts[0].id;
    F.accounts.push({ id: "u99", email: "stranger@example.com", name: "Who", made: new Date().toISOString(), waiting: true });
    const suBoss = { id: "u1", email: "glenn@nlb.gov.sg", user_metadata: { name: "Glenn" }, app_metadata: { admin: true } };
    F.setUser(suBoss); await signedIn(suBoss);
    out.adminSeesWaiting = await until(() => /2 new accounts are waiting/.test(stage()) && /new@nlb\.gov\.sg/.test(stage()));
    document.querySelector(`[data-act="approve"][data-id="${suId}"]`).click();
    out.adminApproves = await until(() => !F.accounts[0].waiting && /is approved/.test(stage()) && /1 new account is waiting/.test(stage()));
    window.confirm = () => true;
    document.querySelector('[data-act="decline"][data-id="u99"]').click();
    out.adminDeclines = await until(() => F.accounts.length === 1 && !/new account/.test(stage()) && /was declined/.test(stage()));
    // the declined one, still holding a sign-in from before: it is told, and signed out
    const declined = { id: "u99", email: "stranger@example.com", user_metadata: { name: "Who" }, app_metadata: {} };
    F.setUser(declined); me = declined; waitingPage(); act("checkagain");
    out.declinedTold = await until(() => /was declined/.test(suVeil()) && !!document.querySelector("#veil #em"));
    const suFresh = { id: suId, email: "new@nlb.gov.sg", user_metadata: { name: "New Colleague" }, app_metadata: {} };
    F.setUser(suFresh); await signedIn(suFresh);
    out.approvedStarts = !document.querySelector("#veil") && PAGE === "home" && !/new account/.test(stage());
    act("changepw"); suType({ pw: "a new one!", pw2: "a new one!" }); act("dochangepw");
    out.passwordChanged = await until(() => F.passwordSetTo === "a new one!" && /Password changed/.test(stage()));
    say("RESULT " + JSON.stringify(out));
  } catch (e) { say("ERROR " + (e && e.stack || e) + "\n" + JSON.stringify(out)); }
})();
