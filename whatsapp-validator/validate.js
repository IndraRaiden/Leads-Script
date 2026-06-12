/**
 * WhatsApp registration validator.
 *
 * Connects to WhatsApp via Baileys (linked device). On first run it writes
 * qr.png — scan it from WhatsApp > Linked devices. The session persists in
 * ./auth/, so later runs skip the QR.
 *
 * Usage:
 *   node validate.js <input.csv>
 *
 * Reads the `phone_e164` column, checks each number with onWhatsApp() (no
 * messages are sent), and writes <input>_verified.csv adding:
 *   whatsapp_verified  yes | no
 *   whatsapp_jid       canonical WhatsApp id when registered
 * Numbers are checked one by one with a randomized 1.5–3s delay to stay
 * far from anti-abuse thresholds.
 */

const fs = require("fs");
const path = require("path");
const pino = require("pino");
const QRCode = require("qrcode");
const makeWASocket = require("@whiskeysockets/baileys").default;
const { useMultiFileAuthState, DisconnectReason } = require("@whiskeysockets/baileys");

const AUTH_DIR = path.join(__dirname, "auth");
const QR_FILE = path.join(__dirname, "qr.png");
const READY_FILE = path.join(__dirname, "connected.flag");

function parseCsv(text) {
  // Minimal CSV parser handling quoted fields.
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') inQuotes = false;
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function toCsvLine(values) {
  return values
    .map((v) => {
      v = String(v ?? "");
      return /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    })
    .join(",");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const sock = makeWASocket({
    auth: state,
    logger: pino({ level: "silent" }),
    browser: ["LeadsValidator", "Desktop", "1.0"],
  });
  sock.ev.on("creds.update", saveCreds);

  return new Promise((resolve, reject) => {
    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;
      if (qr) {
        await QRCode.toFile(QR_FILE, qr, { width: 480, margin: 2 });
        console.log(`QR actualizado: ${QR_FILE} — escanéalo con WhatsApp > Dispositivos vinculados`);
      }
      if (connection === "open") {
        fs.writeFileSync(READY_FILE, new Date().toISOString());
        if (fs.existsSync(QR_FILE)) fs.unlinkSync(QR_FILE);
        console.log("Conectado a WhatsApp.");
        resolve(sock);
      }
      if (connection === "close") {
        const code = lastDisconnect?.error?.output?.statusCode;
        if (code === DisconnectReason.restartRequired) {
          // Normal right after pairing — reconnect with saved creds.
          console.log("Reinicio requerido tras vincular, reconectando...");
          resolve(await connect());
        } else {
          reject(new Error(`Conexión cerrada (status ${code}). Borra ./auth y reintenta si persiste.`));
        }
      }
    });
  });
}

async function main() {
  const input = process.argv[2];
  if (!input) {
    console.error("Uso: node validate.js <input.csv>");
    process.exit(1);
  }

  const rows = parseCsv(fs.readFileSync(input, "utf-8"));
  const header = rows[0];
  const phoneIdx = header.indexOf("phone_e164");
  if (phoneIdx === -1) {
    console.error("El CSV no tiene columna phone_e164.");
    process.exit(1);
  }

  const sock = await connect();
  await sleep(2000);

  const outHeader = [...header, "whatsapp_verified", "whatsapp_jid"];
  const outRows = [outHeader];
  const cache = new Map();
  let yes = 0, no = 0;

  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    const phone = (row[phoneIdx] || "").replace(/\D/g, "");
    let verified = "", jid = "";
    if (phone) {
      if (cache.has(phone)) {
        ({ verified, jid } = cache.get(phone));
      } else {
        try {
          const res = await sock.onWhatsApp(`${phone}@s.whatsapp.net`);
          const hit = Array.isArray(res) && res[0]?.exists;
          verified = hit ? "yes" : "no";
          jid = hit ? res[0].jid : "";
        } catch (e) {
          verified = `error:${e.message}`.slice(0, 60);
        }
        cache.set(phone, { verified, jid });
        await sleep(1500 + Math.random() * 1500);
        // Long rest every 40 fresh lookups — keeps big batches far from
        // anti-abuse thresholds.
        if (cache.size % 40 === 0) {
          console.log("Descanso de lote (60-120s)...");
          await sleep(60000 + Math.random() * 60000);
        }
      }
      if (verified === "yes") yes++; else if (verified === "no") no++;
      console.log(`[${i}/${rows.length - 1}] +${phone} → ${verified}`);
    }
    outRows.push([...row, verified, jid]);
  }

  const outFile = input.replace(/\.csv$/i, "_verified.csv");
  fs.writeFileSync(outFile, outRows.map(toCsvLine).join("\n") + "\n", "utf-8");
  console.log(`\nListo: ${outFile} — con WhatsApp: ${yes}, sin WhatsApp: ${no}`);
  process.exit(0);
}

main().catch((e) => {
  console.error("Error:", e.message);
  process.exit(1);
});
