/**
 * Recuperador: pide a WhatsApp el history-sync y vuelca TODO mensaje entrante
 * (no propio) de los contactos del CSV, incluso los recibidos antes. Escucha
 * tanto messaging-history.set (sync) como messages.upsert (todos los tipos).
 * Descarga audios. Corre ~90s y termina.
 *
 * Uso: node recover.js <leads.csv>
 */
const fs = require("fs");
const path = require("path");
const pino = require("pino");
const makeWASocket = require("@whiskeysockets/baileys").default;
const { useMultiFileAuthState, downloadMediaMessage } = require("@whiskeysockets/baileys");

const AUTH_DIR = path.join(__dirname, "auth");
const MEDIA_DIR = path.join(__dirname, "media");
const OUT = path.join(__dirname, "recovered.json");
if (!fs.existsSync(MEDIA_DIR)) fs.mkdirSync(MEDIA_DIR);

function parseCsv(text) {
  const rows = []; let row = [], f = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { f += '"'; i++; } else if (c === '"') q = false; else f += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(f); f = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(f); f = ""; if (row.length > 1 || row[0] !== "") rows.push(row); row = []; }
    else f += c;
  }
  if (f !== "" || row.length) { row.push(f); rows.push(row); }
  return rows;
}

async function main() {
  const input = process.argv[2];
  const rows = parseCsv(fs.readFileSync(input, "utf-8"));
  const h = rows[0], pi = h.indexOf("phone_e164"), ni = h.indexOf("name");
  const contacts = new Map();
  for (let i = 1; i < rows.length; i++) {
    const p = (rows[i][pi] || "").replace(/\D/g, "");
    if (p) { contacts.set(p, rows[i][ni] || p); if (p.startsWith("52")) contacts.set("521" + p.slice(2), rows[i][ni] || p); }
  }

  const found = [];
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const sock = makeWASocket({
    auth: state, logger: pino({ level: "silent" }), browser: ["LeadsValidator", "Desktop", "1.0"],
    syncFullHistory: true,
    shouldSyncHistoryMessage: () => true,
  });
  sock.ev.on("creds.update", saveCreds);

  async function handle(m, src) {
    if (!m || m.key?.fromMe) return;
    const jid = m.key?.remoteJid || "";
    if (jid.endsWith("@g.us") || jid === "status@broadcast") return;
    const num = jid.split("@")[0].replace(/\D/g, "");
    const alt = num.startsWith("521") ? "52" + num.slice(3) : num;
    const name = contacts.get(num) || contacts.get(alt);
    if (!name) return;
    const audio = m.message?.audioMessage;
    let text = "", mediaPath = "";
    if (audio) {
      try {
        const buf = await downloadMediaMessage(m, "buffer", {}, { reuploadRequest: sock.updateMediaMessage });
        mediaPath = path.join(MEDIA_DIR, `${num}_${m.messageTimestamp}.ogg`);
        fs.writeFileSync(mediaPath, buf);
        text = `[audio ${Math.round(audio.seconds || 0)}s]`;
      } catch (e) { text = `[audio: ${e.message}]`; }
    } else {
      text = m.message?.conversation || m.message?.extendedTextMessage?.text ||
             (m.message?.imageMessage ? "[imagen]" : m.message ? "[otro]" : "");
    }
    if (!text) return;
    if (found.some((r) => r.id === m.key.id)) return;
    found.push({ id: m.key.id, name, phone: num, text, mediaPath, at: Number(m.messageTimestamp) || 0, src });
    fs.writeFileSync(OUT, JSON.stringify(found, null, 2));
    console.log(`RECUPERADO [${src}] ⬅ ${name} (+${num}): ${text}`);
  }

  sock.ev.on("messaging-history.set", async ({ messages }) => {
    for (const m of messages || []) await handle(m, "history");
  });
  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const m of messages || []) await handle(m, "upsert");
  });

  sock.ev.on("connection.update", (u) => {
    if (u.connection === "open") console.log("Conectado. Pidiendo history sync (90s)...");
  });

  setTimeout(() => {
    console.log(`\nFin. Recuperados: ${found.length}. Archivo: recovered.json`);
    process.exit(0);
  }, 90000);
}

main().catch((e) => { console.error("Error:", e.message); process.exit(1); });
