/**
 * Envía un mensaje de WhatsApp usando la sesión ya vinculada (./auth).
 * Uso: node send.js <numero_e164_sin_mas> "<texto>"
 *   node send.js 526242392710 "Hola Ernesto, un saludo!"
 * Resuelve el JID con onWhatsApp antes de enviar; aborta si el número no existe.
 */
const path = require("path");
const pino = require("pino");
const makeWASocket = require("@whiskeysockets/baileys").default;
const { useMultiFileAuthState, DisconnectReason } = require("@whiskeysockets/baileys");

const AUTH_DIR = path.join(__dirname, "auth");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const phone = (process.argv[2] || "").replace(/\D/g, "");
  const text = process.argv[3];
  if (!phone || !text) {
    console.error('Uso: node send.js <numero> "<texto>"');
    process.exit(1);
  }

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const sock = makeWASocket({
    auth: state,
    logger: pino({ level: "silent" }),
    browser: ["LeadsValidator", "Desktop", "1.0"],
  });
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (u) => {
    const { connection, lastDisconnect } = u;
    if (connection === "open") {
      try {
        const res = await sock.onWhatsApp(`${phone}@s.whatsapp.net`);
        if (!Array.isArray(res) || !res[0]?.exists) {
          console.error(`+${phone} no tiene WhatsApp. No se envió nada.`);
          process.exit(2);
        }
        const jid = res[0].jid;
        await sock.sendMessage(jid, { text });
        console.log(`Enviado a ${jid}: ${text}`);
        await sleep(2000);
        process.exit(0);
      } catch (e) {
        console.error("Error al enviar:", e.message);
        process.exit(1);
      }
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code !== DisconnectReason.loggedOut) {
        // reintento simple de reconexión
        setTimeout(() => main(), 1500);
      } else {
        console.error("Sesión cerrada (logged out). Re-vincula con validate.js.");
        process.exit(1);
      }
    }
  });
}

main().catch((e) => {
  console.error("Error:", e.message);
  process.exit(1);
});
