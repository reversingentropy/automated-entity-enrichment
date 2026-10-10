// Drives the review desk headless through the three practice records, which
// need no database, then through two real records cloned from them, and
// prints one line per screen. Exit code is the verdict.
//   node drive.mjs <page.js>
import { body, byId, store } from "./shim.mjs";
import fs from "node:fs";
const api = new Function(fs.readFileSync(process.argv[2], "utf-8")
  + "\n;return {render, REAL, PRACTICE, NPT, get CARDS(){return CARDS}, get labels(){return labels}, csv, changesCsv, stateFor, get langs(){return langs}, get types(){return types}, INDEX};")();
const stage = byId.stage;
const buttons = () => stage.all().filter(n => n.tagName === "BUTTON");
const click = label => {
  const b = buttons().find(n => n.textContent.trim().startsWith(label));
  if (!b) throw new Error("no button " + label + " among " + JSON.stringify(buttons().map(x => x.textContent.trim())));
  b.click();
};
const ask = () => (stage.querySelector(".ask") || {}).textContent || "";
const must = (cond, what) => { if (!cond) throw new Error("expected " + what); console.log("ok  " + what); };

// Two real records, cloned from the practice ones so the deck has a person
// and an organisation to split by type and to tally.
const clone = (card, key, pid) => {
  const c = JSON.parse(JSON.stringify(card));
  c.key = key; c.pids = [pid]; delete c.practice; delete c.coach;
  return c;
};
// the third practice record's rewrite, also taken past the style guide's five sentences
Object.assign(api.PRACTICE[2].changes.find(c => c.field === "Description"), { overLimit: true, sentences: 6 });
api.REAL.push(clone(api.PRACTICE[0], "uid:r1", 901), clone(api.PRACTICE[2], "uid:r3", 903));
api.render();

// sign in, reading English and Chinese, working on people only
stage.all().find(n => n.tagName === "INPUT" && !n.type).value = "Drive";
const boxes = stage.all().filter(n => n.tagName === "INPUT" && n.type === "checkbox");
boxes[1].checked = true; boxes[1].onchange();
const work = stage.all().filter(n => n.classList.contains("types"))[0];
const groups = work.all().filter(n => n.tagName === "INPUT");
must(groups.length === 2 && /People \(1\)/.test(work.textContent) && /Organisations \(1\)/.test(work.textContent), "type picker lists the deck's groups with counts");
groups[1].checked = false; groups[1].onchange();
click("Start");
must(api.langs.includes("zh"), "languages saved at sign-in");
must(JSON.stringify(api.types) === '["people"]' && store["tte-types"] === '["people"]', "type choice saved at sign-in");
must(!!body.querySelector(".veil"), "tutorial shown on a first visit");
must(body.querySelector(".veil").all().filter(n => n.tagName === "LI").length === 5 && !body.querySelector(".veil").querySelector(".sheet-step"), "the tutorial is one sheet");
for (let k = 0; k < 8; k++) {
  const v = body.querySelector(".veil"); if (!v) break;
  v.all().find(n => n.tagName === "BUTTON" && /^(Next|Try it)/.test(n.textContent)).click();
}
must(/same person/.test(ask()) && byId.count.textContent.startsWith("practice 1"), "tutorial ends in practice record 1");
must(buttons().some(n => /Keep for review/.test(n.textContent)) && !buttons().some(n => /Not sure/.test(n.textContent)), "the third answer is Keep for review");
const tray = () => buttons().filter(n => n.classList.contains("tray-btn")).map(n => n.textContent.trim());
must(tray().length === 1 && /Back one step/.test(tray()[0]) && !tray().some(t => /Next|Previous/.test(t)), "the tray is undo and nothing else");
must(buttons().find(n => n.classList.contains("tray-btn")).disabled, "nothing to undo on the first screen of the first record");
const bar = stage.querySelector(".actions");
must(bar && bar.children[0].classList.contains("tray-btn") && !!bar.querySelector(".stamps"), "back and the stamps share the bar at the foot");
must(/Record 1 of 3/.test(stage.querySelector(".kicker").textContent) && /candidate 1 of 2/.test(stage.querySelector(".kicker").textContent), "the step line says the record and the candidate");
must(/1 more candidate/.test(buttons().find(n => /^Not this record/.test(n.textContent)).textContent), "the stamp says what comes next");
must(!/similarity/.test(stage.textContent), "no model score on the record");
must(byId.help.textContent === "How this works", "help lives in the masthead");
byId.help.onclick(); must(!!body.querySelector(".veil"), "and opens the tutorial");
body.querySelector(".veil").all().find(n => n.tagName === "BUTTON" && /close/.test(n.textContent)).click();
must(!body.querySelector(".veil"), "which closes again");
must(byId.outcomes.textContent === "", "no tally during practice");
must(!!stage.querySelector(".coach"), "coaching line on the screen");

// record 1: look at the other candidate, put it back, then every attribute
const tabs = () => stage.all().filter(n => n.classList.contains("tab") && !n.classList.contains("find"));
tabs()[1].click(); must(/Mei Lin/.test(stage.querySelector(".acard-name").textContent), "second candidate on view");
tabs().find(t => t.classList.contains("up")).click(); must(/Mei Ling/.test(stage.querySelector(".acard-name").textContent), "raised tab puts it back");
// a change may carry its own sentence from the article: her awards sentence cannot back her new post
const link1 = api.PRACTICE[0].sources[0].link, idQuote = (stage.querySelector(".clip-body") || {}).textContent || "";
api.PRACTICE[0].changes.forEach(ch => { ch.quotes = { [link1]: { quote: "A sentence that backs this change.", original: "" } }; });
const cardBefore = stage.querySelector(".acard");
click("Same");
must(cardBefore.querySelector(".impression") && /SAME/.test(cardBefore.querySelector(".impression").textContent), "the stamp lands on the record card");
must(/A sentence that backs this change/.test(stage.querySelector(".clip-body").textContent) && idQuote && !/A sentence that backs/.test(idQuote),
     "a change shows its own sentence from the article; the identity screen keeps the person's");
must(/Affiliations/.test(ask()) && /in TTE/.test(stage.querySelector(".badge").textContent), "affiliation badged");
must(/change 1 of 4/.test(stage.querySelector(".kicker").textContent), "the step line counts the changes");
must(!buttons().find(n => n.classList.contains("tray-btn")).disabled, "there is something to undo now");
must(/the article wrote/.test(stage.querySelector(".proposal").textContent), "article's wording kept beside TTE's name");
must(!buttons().some(n => n.classList.contains("leave")), "a single value offers nothing to leave out");
click("Accept");
must(/Awards/.test(ask()) && stage.all().filter(n => n.classList.contains("vline")).length === 2, "two award values offered");
const leaves = () => buttons().filter(n => n.classList.contains("leave"));
must(leaves().length === 2 && leaves().every(b => !b.disabled), "each award can be left out");
stage.all().find(n => n.classList.contains("vline") && /Long Service/.test(n.textContent)).all().find(n => n.classList.contains("leave")).click();
must(stage.all().filter(n => n.classList.contains("vline") && n.classList.contains("out")).length === 1, "the left-out value is struck");
must(/1 of 2 values will be added; 1 left out/.test(stage.querySelector(".proposal").textContent), "the count says what is kept");
must(!stage.all().some(n => n.tagName === "TEXTAREA" && n.classList.contains("editor")), "leaving out does not open the editor");
must(leaves().find(b => b.textContent === "put back") && leaves().find(b => b.textContent === "leave out").disabled, "the last value left cannot go too");
click("Accept the rest");
must(/birth year/.test(ask()) && /disagree/.test(stage.querySelector(".corrob").textContent), "sources disagree on the year");
stage.all().filter(n => n.classList.contains("chip"))[1].click();
must(stage.all().some(n => n.tagName === "TEXTAREA" && n.classList.contains("editor")), "choosing a wording opens the editor on it");
click("Accept my wording");
must(/description/.test(ask()) && stage.all().some(n => n.classList.contains("gline")), "description addition as a + line");
click("Edit the wording");
const ed = stage.all().find(n => n.tagName === "TEXTAREA" && n.classList.contains("editor"));
must(!!ed && !/Deputy chief/.test(ed.value), "editor holds the addition only");
ed.value = "She became chief executive in 2026."; ed.oninput();
must(/She became chief executive in 2026/.test(stage.querySelector(".result").textContent), "would-read shows the composed description");
click("+ leave a note"); stage.all().find(n => n.tagName === "TEXTAREA" && !n.classList.contains("editor")).value = "checked";
click("Accept my wording");
const l1 = api.labels["practice-1"];
must(l1 && l1.edits["Awards"] === "Public Service Medal (2015) | Public Administration Medal (Gold) (2026)", "the accepted awards are the ones not left out");
must(l1.rows.find(r => r.field === "Awards").proposed === "Public Service Medal (2015) | Public Administration Medal (Gold) (2026)", "the sheet row carries the kept value");

must(l1.seconds != null && l1.seconds >= 0, "the time the decision took is on the label");

// record 2: the guessed spelling, the NPT, the search
must(/not in TTE. Create a record/.test(ask()), "record 2 starts at create");
must(/new record/.test((stage.querySelector(".draft") || {}).textContent || "") && /Occupation/.test(stage.querySelector(".draft").textContent), "the record a create would make is drawn from the article");
must(/none matched by the model/.test(stage.querySelector(".drawer-label").textContent), "the nearest names are labelled as ruled out");
must(!buttons().find(n => n.classList.contains("tray-btn")).disabled, "back is live with a record behind");
must(stage.all().some(n => n.classList.contains("hint") && /own spelling/.test(n.textContent)), "guessed-spelling warning");
must(/NPT 陈美玲/.test(tabs()[0].textContent), "the candidate chip shows the NPT it was reached through");
const box = stage.all().find(n => n.tagName === "INPUT"); box.value = "陈美"; box.oninput();
const hit = stage.all().find(n => n.classList.contains("hit") && /Mei Ling/.test(n.textContent));
must(hit && /NPT 陈美玲/.test(hit.textContent), "search by an NPT finds the record it names, labelled");
api.INDEX.unshift(["x-1", "Jubilee, Ann (test)", "PERSON", "", ""], ["x-2", "Lee, Ann (test)", "PERSON", "", ""]);
box.value = "lee"; box.oninput();
must(/Lee, Ann/.test(stage.all().find(n => n.classList.contains("hit")).textContent), "a name starting with the search comes before one containing it");
api.INDEX.splice(0, 2);
box.value = "Housing"; box.oninput();
stage.all().find(n => n.classList.contains("hit") && /Mei Ling/.test(n.textContent)).click();
must(/same person/.test(ask()), "search leads to the identity question");
click("Same");

// record 3: the rewrite that deletes text
must(/same organisation/.test(ask()), "record 3");
click("Same");
must(/Rewrite/.test(ask()) && !!stage.querySelector(".warnbox"), "over-edit warning on a destructive rewrite");
must(stage.all().some(n => n.classList.contains("warnbox") && /6 sentences\. The style guide allows 3 to 5/.test(n.textContent)), "a held-for-a-person warning when a change takes the description past five sentences");
must(!buttons().some(n => n.classList.contains("leave")), "a rewrite that removes text has nothing to leave out");
click("No change");
must(/Practice over/.test(ask()) && Object.keys(api.labels).length === 3, "practice over with three practice decisions");
click("To the real records");
must(Object.keys(api.labels).length === 0 && !api.INDEX.some(r => String(r[0]).startsWith("practice-")) && !api.NPT["practice-101"], "nothing from practice survives");

// the real deck: people only, the tally, the sheet, the downloads
must(api.CARDS.length === 1 && api.CARDS[0].type === "PERSON", "the deck holds the chosen group only");
must(/0 of 1 records reviewed/.test(byId.count.textContent) && byId.outcomes.textContent === "", "count and an empty tally");
must(byId.sheet.textContent === "Your sheet", "the sheet is a click away");
byId.sheet.onclick();
must(/Your sheet/.test(ask()) && /Nothing decided yet/.test(stage.textContent), "the sheet before any decision");
byId.sheet.onclick();
click("Same"); click("Accept"); click("Accept"); stage.all().filter(n => n.classList.contains("chip"))[0].click(); click("Accept my wording"); click("Accept");
must(/1 of 1 records reviewed/.test(byId.count.textContent) && byId.outcomes.textContent === "1 amended", "tally by outcome in the masthead");
must(/All done/.test(ask()) && /records to amend/.test(stage.textContent), "the end sheet counts in the same words");
byId.sheet.onclick();
const rows = () => stage.all().filter(n => n.classList.contains("ledger-row"));
must(rows().length === 1 && /Tan Mei Ling/.test(rows()[0].textContent) && /amended/.test(rows()[0].textContent), "the sheet lists the decision");
const selects = stage.all().filter(n => n.tagName === "SELECT");
selects[0].value = "to create"; selects[0].onchange();
must(rows().length === 0 && /Nothing matches/.test(stage.textContent), "the outcome filter narrows the sheet");
selects[0].value = ""; selects[0].onchange();
click("Download approved changes");
must(/Awards/.test(globalThis.__lastDownload) && /Drive/.test(globalThis.__lastDownload), "the approved-changes sheet downloads from the sheet page");
rows()[0].click();
must(!/Your sheet/.test(ask()) && /reviewed · Drive/.test(stage.querySelector(".reviewed-mark").textContent), "a row reopens the decided record with the reviewer's mark");
must(/Decided: amended · stamp again to change it/.test((stage.querySelector(".decided-line") || {}).textContent || ""), "a decided record says so and how to change it");
must(/seconds/.test(api.csv().split("\n")[0]), "the decisions sheet carries the seconds");

must(byId.sound && byId.sound.textContent === "Sound: off" && store["tte-desk-sound"] == null, "sound is off by default");
byId.sound.onclick(); must(store["tte-desk-sound"] === "1" && byId.sound.textContent === "Sound: on", "sound toggle persists");
must(byId.theme.textContent === "Light desk" && store["tte-desk-theme"] == null, "the brown desk by default");
byId.theme.onclick(); must(store["tte-desk-theme"] === "light" && byId.theme.textContent === "Brown desk", "the light desk persists");
must(api.csv().split("\n").length === 2 && api.changesCsv().split("\n").length > 2, "both sheets carry the real decision");
console.log("PASS");
