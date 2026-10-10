class Node {
  constructor(tag){ this.tagName=(tag||"").toUpperCase(); this.children=[]; this.attrs={}; this._text=""; this.style={}; this.classList={ _s:new Set(),
    add:(...c)=>c.forEach(x=>this.classList._s.add(x)), remove:(...c)=>c.forEach(x=>this.classList._s.delete(x)),
    toggle:(c)=>this.classList._s.has(c)?this.classList._s.delete(c):this.classList._s.add(c), contains:(c)=>this.classList._s.has(c)}; }
  get className(){ return [...this.classList._s].join(" "); } set className(v){ this.classList._s=new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent(){ return this.children.length ? this.children.map(c=>typeof c==="string"?c:c.textContent).join("") : this._text; }
  set textContent(v){ this.children=[]; this._text=String(v); }
  append(...xs){ xs.forEach(x=>{ if(x==null) return; if(typeof x==="string"){ this.children.push(x); } else { x.parentNode=this; this.children.push(x);} }); }
  appendChild(x){ this.append(x); return x; }
  prepend(...xs){ const rest=this.children; this.children=[]; this.append(...xs); this.children.push(...rest); }
  replaceChildren(...xs){ this.children=[]; this.append(...xs); }
  remove(){ if(this.parentNode){ this.parentNode.children=this.parentNode.children.filter(c=>c!==this);} }
  setAttribute(k,v){ this.attrs[k]=v; } focus(){} click(){ if(this.onclick) this.onclick({target:this}); }
  querySelector(sel){ return this.all().find(n=>matches(n,sel))||null; } querySelectorAll(sel){ return this.all().filter(n=>matches(n,sel)); }
  all(){ const out=[]; const walk=n=>{ n.children.forEach(c=>{ if(typeof c!=="string"){ out.push(c); walk(c);} }); }; walk(this); return out; }
  get isContentEditable(){ return false; }
}
function matches(n, sel){ if(sel.startsWith(".")) return n.classList.contains(sel.slice(1)); return n.tagName===sel.toUpperCase(); }
const byId = {}; const body = new Node("body");
globalThis.document = { createElement:(t)=>new Node(t), createTextNode:(t)=>String(t), body,
  getElementById:(id)=>byId[id]||null, addEventListener(){}, querySelector:(s)=>body.querySelector(s) };
for (const id of ["stage","count","me","sound","theme","sheet","team","help","bar","outcomes"]) { byId[id]=new Node(["sound","theme","sheet","team","help"].includes(id)?"button":"div"); body.append(byId[id]); }
const store = {};
globalThis.localStorage = { getItem:k=>(store[k]!==undefined?store[k]:null), setItem:(k,v)=>{store[k]=String(v);}, removeItem:k=>{delete store[k];} };
globalThis.window = globalThis; globalThis.matchMedia = ()=>({matches:false});
globalThis.alert = (m)=>{ throw new Error("alert: "+m); }; globalThis.confirm = ()=>true;
globalThis.setTimeout = (fn)=>{ fn(); return 0; };
globalThis.Blob = class { constructor(parts){ this.text=parts.join(""); } };
globalThis.URL = { createObjectURL:(b)=>{ globalThis.__lastDownload=b.text; return "blob:x"; }, revokeObjectURL(){} };
globalThis.AudioContext = undefined;
export { body, byId, store };
