// Shared helpers. No framework, no build step.

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {}));
  const t = await r.text();
  let body;
  try { body = t ? JSON.parse(t) : {}; } catch { body = { error: t }; }
  if (!r.ok) body._httpError = r.status;
  return body;
}
const jpost = (p, obj) => api(p, { method: "POST", body: JSON.stringify(obj || {}) });
const el = (tag, attrs, ...kids) => {
  const n = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === "class") n.className = attrs[k];
    else if (k === "html") n.innerHTML = attrs[k];
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
    else n.setAttribute(k, attrs[k]);
  }
  for (const kid of kids) n.append(kid && kid.nodeType ? kid : document.createTextNode(kid == null ? "" : kid));
  return n;
};
const $ = (s, r = document) => r.querySelector(s);
const naira = (n) => "₦" + Number(n || 0).toLocaleString("en-NG");
const when = (ts) => new Date(ts * 1000).toLocaleString("en-GB", { hour12: false });

function outcomeChip(o) {
  if (o === true || o === "true") return el("span", { class: "chip yes" }, "YES");
  if (o === false || o === "false") return el("span", { class: "chip no" }, "NO");
  if (o === "withheld") return el("span", { class: "chip wait" }, "WITHHELD");
  if (o === "unverifiable") return el("span", { class: "chip hold" }, "NOT VERIFIED YET");
  if (o === "disclosed") return el("span", { class: "chip yes" }, "SHARED");
  if (o === "released") return el("span", { class: "chip yes" }, "RELEASED");
  if (o === "queued") return el("span", { class: "chip wait" }, "QUEUED");
  return el("span", { class: "chip wait" }, String(o).toUpperCase());
}

// canonical JSON matching Python json.dumps(sort_keys=True, separators=(",",":"))
function canonical(v) {
  if (v === null || typeof v === "number" || typeof v === "boolean") return JSON.stringify(v);
  if (typeof v === "string") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  const keys = Object.keys(v).sort();
  return "{" + keys.map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
}
function b64uToBytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// Independently verify a gateway attestation in the browser against the
// published public key, the way a partner's own server would.
async function verifyAttestation(att) {
  try {
    const jwks = await api("/.well-known/jwks.json");
    const raw = b64uToBytes(jwks.keys[0].x);
    const key = await crypto.subtle.importKey("raw", raw, { name: "Ed25519" }, false, ["verify"]);
    const data = new TextEncoder().encode(canonical(att.payload));
    const ok = await crypto.subtle.verify("Ed25519", key, b64uToBytes(att.sig), data);
    const expd = att.payload.exp * 1000 < Date.now();
    if (ok && !expd) return { ok: true, text: "Signature valid. Checked here in the browser against the gateway public key. Not expired." };
    if (ok && expd) return { ok: false, text: "Signature valid but the answer has expired." };
    return { ok: false, text: "Signature did not verify." };
  } catch (e) {
    return { ok: null, text: "This browser will not do Ed25519 in WebCrypto. The gateway reports the signature as valid; a partner server would confirm it independently." };
  }
}

function header(active) {
  const nav = [["/", "Home"], ["/citizen", "Citizen"], ["/partner", "Partner"], ["/auditor", "Auditor"], ["/ussd", "USSD"]];
  document.body.prepend(el("header", { class: "top" },
    el("span", { class: "brand" }, "SabiID"),
    el("span", { class: "tag" }, "Prove the fact. Not the file."),
    el("nav", {}, ...nav.map(([h, t]) => el("a", { href: h, style: h === active ? "opacity:1;text-decoration:underline" : "" }, t)))
  ));
}
