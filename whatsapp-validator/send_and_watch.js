/**
 * Envía los pendientes (already_sent != 'yes') de un CSV con ritmo humano y se
 * queda ESCUCHANDO respuestas entrantes de cualquiera de los contactos del CSV.
 * Una sola sesión: evita conflictos de dos conexiones sobre ./auth.
 *
 * Imprime una línea por evento (lo capta Monitor):
 *   ENVIADO ✓ | <nombre>
 *   RESPUESTA ⬅ <nombre> (<telefono>): <texto>
 * Persiste respuestas en replies.json.
 *
 * Uso: node send_and_watch.js <leads.csv> [minSeg] [maxSeg]
 */
const fs = require("fs");
const path = require("path");
const pino = require("pino");
const makeWASocket = require("@whiskeysockets/baileys").default;
const { useMultiFileAuthState, DisconnectReason, downloadMediaMessage } = require("@whiskeysockets/baileys");

const AUTH_DIR = path.join(__dirname, "auth");
const REPLIES_FILE = path.join(__dirname, "replies.json");
const SENT_FILE = path.join(__dirname, "sent.json");
const OUTBOX_FILE = path.join(__dirname, "outbox.json");
const MEDIA_DIR = path.join(__dirname, "media");
if (!fs.existsSync(MEDIA_DIR)) fs.mkdirSync(MEDIA_DIR);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function loadSent() {
  return fs.existsSync(SENT_FILE) ? new Set(JSON.parse(fs.readFileSync(SENT_FILE, "utf-8"))) : new Set();
}
function recordSent(set) {
  fs.writeFileSync(SENT_FILE, JSON.stringify([...set], null, 2));
}

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
  const maxSends = Number(process.argv[5] || Infinity); // tope de envíos nuevos
  if (!input) { console.error("Uso: node send_and_watch.js <leads.csv> [minSeg] [maxSeg] [maxSends]"); process.exit(1); }

  // Candado de instancia única: evita que dos procesos manden la misma colita
  // (causa de mensajes duplicados). Si hay uno vivo, este se niega a arrancar.
  const LOCK = path.join(__dirname, "listener.lock");
  if (fs.existsSync(LOCK)) {
    const oldPid = parseInt(fs.readFileSync(LOCK, "utf-8"), 10);
    let alive = false;
    try { process.kill(oldPid, 0); alive = true; } catch {}
    // Solo abortar si el lock es de OTRO proceso vivo. Si es de este mismo proceso
    // (reconexión interna tras caída/QR expirado que re-llama main()), continuar.
    if (alive && oldPid !== process.pid) { console.error(`Ya hay un listener vivo (PID ${oldPid}). Abortando para no duplicar.`); process.exit(1); }
  }
  fs.writeFileSync(LOCK, String(process.pid));
  const releaseLock = () => { try { if (fs.existsSync(LOCK) && parseInt(fs.readFileSync(LOCK, "utf-8"), 10) === process.pid) fs.unlinkSync(LOCK); } catch {} };
  process.on("exit", releaseLock);
  process.on("SIGTERM", () => { releaseLock(); process.exit(0); });
  process.on("SIGINT", () => { releaseLock(); process.exit(0); });

  const rows = parseCsv(fs.readFileSync(input, "utf-8"));
  const h = rows[0];
  const pi = h.indexOf("phone_e164"), mi = h.indexOf("wa_message"),
        ni = h.indexOf("name"), si = h.indexOf("already_sent");
  if (pi === -1 || mi === -1) { console.error("CSV sin phone_e164 / wa_message"); process.exit(1); }

  // Mapa telefono(normalizado) -> nombre, para etiquetar respuestas de los 10.
  const contacts = new Map();
  for (let i = 1; i < rows.length; i++) {
    const p = (rows[i][pi] || "").replace(/\D/g, "");
    if (p) contacts.set(p, ni >= 0 ? rows[i][ni] : p);
  }
  const replies = fs.existsSync(REPLIES_FILE) ? JSON.parse(fs.readFileSync(REPLIES_FILE, "utf-8")) : [];

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const sock = makeWASocket({
    auth: state, logger: pino({ level: "silent" }), browser: ["LeadsValidator", "Desktop", "1.0"],
    syncFullHistory: true,            // al vincular de cero, jala el historial reciente
    shouldSyncHistoryMessage: () => true,
  });
  sock.ev.on("creds.update", saveCreds);

  // Procesa un mensaje entrante (de tiempo real o del historial). Registra TODO
  // mensaje directo no propio: si empata con un lead usa su nombre, si no (p.ej.
  // JID oculto @lid) usa el pushName — así nunca se descarta nada en silencio.
  async function processMessage(m, src) {
    if (!m || m.key?.fromMe) return;
    const jid = m.key?.remoteJid || "";
    if (jid.endsWith("@g.us") || jid === "status@broadcast" || !jid) return;
    const num = jid.split("@")[0].replace(/\D/g, "");
    const alt = num.startsWith("521") ? "52" + num.slice(3) : num;
    const known = contacts.get(num) || contacts.get(alt);
    const name = known || (m.pushName ? `${m.pushName} (?)` : `desconocido ${jid}`);

    const audio = m.message?.audioMessage;
    let text, mediaPath = "";
    if (audio) {
      try {
        const buf = await downloadMediaMessage(m, "buffer", {}, { reuploadRequest: sock.updateMediaMessage });
        mediaPath = path.join(MEDIA_DIR, `${num}_${m.messageTimestamp}.ogg`);
        fs.writeFileSync(mediaPath, buf);
        text = `[audio ${Math.round((audio.seconds || 0))}s → ${path.basename(mediaPath)}]`;
      } catch (e) {
        text = `[audio: error al descargar: ${e.message}]`;
      }
    } else {
      text = m.message?.conversation || m.message?.extendedTextMessage?.text ||
             (m.message?.imageMessage ? "[imagen]" : m.message ? "[mensaje]" : "");
    }
    if (!text) return;
    if (replies.some((r) => r.id === m.key.id)) return; // anti-duplicado
    console.log(`RESPUESTA ⬅ ${name} (+${num}): ${text}`);
    replies.push({ id: m.key.id, name, phone: num, text, mediaPath, at: Number(m.messageTimestamp) || 0, src });
    fs.writeFileSync(REPLIES_FILE, JSON.stringify(replies, null, 2));
  }

  // Tiempo real (todos los tipos) + historial al vincular de cero.
  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const m of messages) await processMessage(m, "live");
  });
  sock.ev.on("messaging-history.set", async ({ messages }) => {
    for (const m of messages || []) await processMessage(m, "history");
  });

  // ACK real de entrega de NUESTROS mensajes: 2=llegó al servidor, 3=ENTREGADO al
  // destinatario, 4=LEÍDO. Si se queda en 2 y nunca pasa a 3, no se entregó.
  sock.ev.on("messages.update", (updates) => {
    for (const u of updates || []) {
      const s = u.update?.status;
      if (u.key?.fromMe && s) {
        const label = s >= 4 ? "LEÍDO ✓✓" : s === 3 ? "ENTREGADO ✓✓" : s === 2 ? "solo-servidor ✓ (NO entregado aún)" : `status ${s}`;
        console.log(`ACK ${label} → ${u.key.remoteJid}`);
      }
    }
  });

  let started = false;
  sock.ev.on("connection.update", async (u) => {
    const { connection, lastDisconnect, qr } = u;
    if (qr) {
      try {
        await require("qrcode").toFile(path.join(__dirname, "qr.png"), qr, { width: 480, margin: 2 });
        console.log("QR actualizado: qr.png — escanéalo con WhatsApp > Dispositivos vinculados");
      } catch (e) { console.log("Error generando QR:", e.message); }
    }
    if (connection === "open" && !started) {
      started = true;
      console.log("Conectado. Enviando pendientes y escuchando respuestas...\n");
      const sent = loadSent();
      const pending = [];
      for (let i = 1; i < rows.length; i++) {
        if (si >= 0 && (rows[i][si] || "").toLowerCase() === "yes") continue;
        const p = (rows[i][pi] || "").replace(/\D/g, "");
        if (sent.has(p)) continue; // ya enviado en una corrida previa (anti-duplicado)
        if (rows[i][pi] && rows[i][mi]) pending.push(i);
      }
      let sentCount = 0;
      for (let k = 0; k < pending.length && sentCount < maxSends; k++) {
        const i = pending[k];
        const phone = rows[i][pi].replace(/\D/g, "");
        const name = ni >= 0 ? rows[i][ni] : phone;
        let didSend = false;
        try {
          const res = await sock.onWhatsApp(`${phone}@s.whatsapp.net`);
          if (!Array.isArray(res) || !res[0]?.exists) { console.log(`SIN WhatsApp | ${name}`); continue; }
          await sock.sendMessage(res[0].jid, { text: rows[i][mi] });
          sent.add(phone); recordSent(sent);
          sentCount++; didSend = true;
          console.log(`ENVIADO ✓ (${sentCount}/${maxSends === Infinity ? "∞" : maxSends}) | ${name}`);
        } catch (e) {
          console.log(`ERROR | ${name}: ${e.message}`);
        }
        // pausa humana solo después de un envío real, si aún faltan
        if (didSend && sentCount < maxSends && k < pending.length - 1) {
          const wait = (minS + Math.random() * (maxS - minS)) * 1000;
          console.log(`   ...esperando ${Math.round(wait / 1000)}s\n`);
          await sleep(wait);
        }
      }
      console.log(`\nEnvíos terminados (${sentCount} enviados). Sigo ESCUCHANDO respuestas (TaskStop para terminar).`);

      // Colita de salida: revisa outbox.json cada 4s y manda lo pendiente SIN
      // reiniciar el proceso. Para responder a un lead, agrega un objeto
      // {phone, text} con status ausente; aquí se marca status:"sent".
      setInterval(async () => {
        let box;
        try { box = JSON.parse(fs.readFileSync(OUTBOX_FILE, "utf-8")); } catch { return; }
        if (!Array.isArray(box)) return;
        let changed = false;
        for (const item of box) {
          if (item.status) continue;
          // Acción de archivar un chat (objeciones / no interesados).
          if (item.action === "archive" && item.jid) {
            try {
              await sock.chatModify(
                { archive: true, lastMessages: [{ key: { remoteJid: item.jid, id: item.lastId || "", fromMe: false }, messageTimestamp: item.at || 0 }] },
                item.jid
              );
              item.status = "archived"; changed = true;
              console.log(`ARCHIVADO ✓ → ${item.jid}`);
            } catch (e) { item.status = "error:" + e.message; changed = true; }
            continue;
          }
          if ((!item.text && !item.mediaPath) || (!item.phone && !item.jid)) continue;
          try {
            let targetJid;
            if (item.jid) {
              // Responder directo a un chat por su JID (incluye @lid de ID oculto)
              targetJid = item.jid;
            } else {
              const phone = String(item.phone).replace(/\D/g, "");
              const res = await sock.onWhatsApp(`${phone}@s.whatsapp.net`);
              if (!Array.isArray(res) || !res[0]?.exists) { item.status = "no_whatsapp"; changed = true; continue; }
              targetJid = res[0].jid;
            }
            // mediaPath → manda un video (MP4) con caption opcional; si no, texto.
            if (item.mediaPath) {
              const buf = fs.readFileSync(item.mediaPath);
              await sock.sendMessage(targetJid, { video: buf, mimetype: "video/mp4", caption: item.text || "" });
              console.log(`OUTBOX ✓ (video) → ${targetJid}: ${path.basename(item.mediaPath)}`);
            } else {
              await sock.sendMessage(targetJid, { text: item.text });
              console.log(`OUTBOX ✓ → ${targetJid}: ${item.text.slice(0, 60)}...`);
            }
            item.status = "sent"; item.sentAt = Date.now(); changed = true;
          } catch (e) { item.status = "error:" + e.message; changed = true; }
        }
        if (changed) fs.writeFileSync(OUTBOX_FILE, JSON.stringify(box, null, 2));
      }, 4000);
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) { console.error("Sesión cerrada. Re-vincula."); process.exit(1); }
      else setTimeout(() => main(), 1500); // reconecta y sigue escuchando
    }
  });
}

main().catch((e) => { console.error("Error:", e.message); process.exit(1); });
