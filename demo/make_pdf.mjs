/**
 * Render docs/TECHNICAL_WRITEUP.md to docs/TECHNICAL_WRITEUP.pdf, sized to stay
 * within four A4 pages. Uses the Chromium that Playwright already installed.
 *
 *   node docs/make_pdf.mjs
 */
import { chromium } from "playwright";
import { readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import path from "path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const md = readFileSync(path.join(HERE, "..", "docs", "TECHNICAL_WRITEUP.md"), "utf8");

// tiny markdown -> html, only the features this document uses
function mdToHtml(src) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) =>
    esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
  const lines = src.split("\n");
  let html = "", i = 0, inList = false, inCode = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  while (i < lines.length) {
    const l = lines[i];
    if (l.startsWith("```")) {
      if (!inCode) { closeList(); html += "<pre><code>"; inCode = true; }
      else { html += "</code></pre>"; inCode = false; }
      i++; continue;
    }
    if (inCode) { html += esc(l) + "\n"; i++; continue; }
    if (/^#\s+/.test(l)) { closeList(); html += `<h1>${inline(l.replace(/^#\s+/, ""))}</h1>`; }
    else if (/^##\s+/.test(l)) { closeList(); html += `<h2>${inline(l.replace(/^##\s+/, ""))}</h2>`; }
    else if (/^###\s+/.test(l)) { closeList(); html += `<h3>${inline(l.replace(/^###\s+/, ""))}</h3>`; }
    else if (/^\s*[-*]\s+/.test(l)) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${inline(l.replace(/^\s*[-*]\s+/, ""))}</li>`;
    } else if (l.trim() === "") { closeList(); }
    else { closeList(); html += `<p>${inline(l)}</p>`; }
    i++;
  }
  closeList();
  return html;
}

const page_html = `<!doctype html><meta charset="utf-8"><style>
  @page { size: A4; margin: 15mm 16mm; }
  body { font: 9.6pt/1.4 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; color: #1b1d1c; }
  h1 { font-size: 15pt; margin: 0 0 2pt; }
  h2 { font-size: 11pt; margin: 10pt 0 3pt; color: #0b5c2c; }
  h3 { font-size: 9.8pt; margin: 7pt 0 2pt; }
  p { margin: 3pt 0; }
  ul { margin: 3pt 0 3pt 0; padding-left: 16pt; }
  li { margin: 1.5pt 0; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 8.6pt; background: #f2f4f2; padding: 0 2px; }
  pre { background: #f6f8f6; border: 1px solid #e2e6e3; border-radius: 4px; padding: 6pt 8pt; margin: 4pt 0; }
  pre code { background: none; font-size: 8.4pt; }
  strong { font-weight: 650; }
  a { color: #0b5c2c; }
</style>${mdToHtml(md)}`;

const tmp = path.join(HERE, "_writeup.tmp.html");
writeFileSync(tmp, page_html);

const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto("file://" + tmp);
await page.pdf({
  path: path.join(HERE, "..", "docs", "TECHNICAL_WRITEUP.pdf"),
  format: "A4",
  printBackground: true,
  margin: { top: "15mm", bottom: "15mm", left: "16mm", right: "16mm" },
});
await browser.close();
console.log("wrote docs/TECHNICAL_WRITEUP.pdf");
