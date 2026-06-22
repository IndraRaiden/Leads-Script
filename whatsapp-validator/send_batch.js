/**
 * Envío por lotes con ritmo humano. Conecta UNA vez la sesión vinculada,
 * lee un CSV con columnas phone_e164 y wa_message, y envía cada mensaje con
 * una pausa aleatoria (default 60-180s) entre uno y otro. Verifica onWhatsApp
 * antes de cada envío y escribe un log de resultados.
 *
 * Uso: node send_batch.js <leads.csv> [minSeg] [maxSeg]
 *   node send_batch.js ../output/SEND_today_10.csv 60 180
 */
const fs = require("fs");
const path = require("path");
const pino = require("pino");
const makeWASocket = require("@whiskeysockets/baileys").default;
const { useMultiFileAuthState, DisconnectReason } = require("@whiskeysockets/baileys");

const AUTH_DIR = path.join(__dirname, "auth");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') q = false;
      else field += c;
    } else if (c === '"') q = true;
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

async function main() {
  const input = process.argv[2];
  const minS = Number(process.argv[3] || 60);
  const maxS = Number(process.argv[4] || 180);
  if (!input) { console.error("Uso: node send_batch.js <leads.csv> [minSeg] [maxSeg]"); process.exit(1); }

  const rows = parseCsv(fs.readFileSync(input, "utf-8"));
  const header = rows[0];
  const pi = header.indexOf("phone_e164");
  const mi = header.indexOf("wa_message");
  const ni = header.indexOf("name");
  if (pi === -1 || mi === -1) { console.error("CSV sin columnas phone_e164 / wa_message"); process.exit(1); }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const sock = makeWASocket({ auth: state, logger: pino({ level: "silent" }), browser: ["LeadsValidator", "Desktop", "1.0"] });
  sock.ev.on("creds.update", saveCreds);

  let started = false;
  sock.ev.on("connection.update", async (u) => {
    const { connection, lastDisconnect } = u;
    if (connection === "open" && !started) {
      started = true;
      console.log("Conectado. Iniciando envíos...\n");
      const results = [];
      for (let i = 1; i < rows.length; i++) {
        const phone = (rows[i][pi] || "").replace(/\D/g, "");
        const text = rows[i][mi];
        const name = ni >= 0 ? rows[i][ni] : phone;
        if (!phone || !text) continue;
        try {
          const res = await sock.onWhatsApp(`${phone}@s.whatsapp.net`);
          if (!Array.isArray(res) || !res[0]?.exists) {
            console.log(`[${i}] ${name} → SIN WhatsApp, saltado`);
            results.push({ name, phone, status: "no_whatsapp" });
            continue;
          }
          await sock.sendMessage(res[0].jid, { text });
          console.log(`[${i}] ${name} → ENVIADO ✓`);
          results.push({ name, phone, status: "sent" });
        } catch (e) {
          console.log(`[${i}] ${name} → ERROR: ${e.message}`);
          results.push({ name, phone, status: "error:" + e.message });
        }
        // pausa humana antes del siguiente (no tras el último)
        const remaining = rows.slice(i + 1).some((r) => r[pi] && r[mi]);
        if (remaining) {
          const wait = (minS + Math.random() * (maxS - minS)) * 1000;
          console.log(`    ...esperando ${Math.round(wait / 1000)}s\n`);
          await sleep(wait);
        }
      }
      const sent = results.filter((r) => r.status === "sent").length;
      fs.writeFileSync(path.join(__dirname, "send_log.json"), JSON.stringify(results, null, 2));
      console.log(`\nListo. Enviados: ${sent}/${results.length}. Log: send_log.json`);
      await sleep(3000);
      process.exit(0);
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code !== DisconnectReason.loggedOut && !started) setTimeout(() => main(), 1500);
      else if (code === DisconnectReason.loggedOut) { console.error("Sesión cerrada. Re-vincula."); process.exit(1); }
    }
  });
}

main().catch((e) => { console.error("Error:", e.message); process.exit(1); });
