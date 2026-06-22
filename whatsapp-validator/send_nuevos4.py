"""Bloque de 15 VALIDADOS (WhatsApp confirmado). Anti-duplicado:
- 'sent' cuenta. error/Connection Closed → salta sin reintentar (no duplica).
- 3 fallos seguidos → para. Tope: 15."""
import json, time, random, subprocess

OUTBOX = "outbox.json"
POOLS = {
    "seguros": [
        "Buen día, ¿las fotos de siniestros y papeles de clientes se les pierden en el WhatsApp? Los ordenamos por cliente solos. ¿Le muestro?",
        "Hola, ¿reciben pólizas, INE y comprobantes de cada cliente por WhatsApp y ordenarlos quita tiempo? Lo hacemos en automático. ¿Le interesa verlo?",
    ],
    "inmobiliaria": [
        "Hola, ¿les llegan INE, comprobantes y contratos de cada cliente por WhatsApp y armar el expediente es batalla? Se ordena solo. ¿Le interesa verlo?",
        "Buen día, ¿reciben los papeles de cada inquilino por WhatsApp y luego cuesta encontrarlos? Los ordenamos por cliente solos. ¿Le muestro?",
    ],
    "financiera": [
        "Hola, ¿reciben comprobantes de pago e identificaciones de cada acreditado por WhatsApp y es talacha encontrarlos? Los ordenamos por cliente solos. ¿Le muestro?",
        "Buen día, ¿se les juntan comprobantes e INE de clientes en el WhatsApp? Los acomodamos por cliente en automático. ¿Le interesa verlo?",
    ],
}

def listener_alive():
    return subprocess.run(["pgrep", "-f", "node send_and_watch"], capture_output=True).returncode == 0

CANDS = json.load(open("/tmp/bloque4.json"))
counters = {"seguros": 0, "inmobiliaria": 0, "financiera": 0}
sent = 0
consec_err = 0
inciertos = []

for c in CANDS:
    if sent >= 15:
        break
    if not listener_alive():
        print("   ⛔ listener caído — POSIBLE BAN, deteniendo", flush=True); break
    v = c["v"]; text = POOLS[v][counters[v] % len(POOLS[v])]; counters[v] += 1
    json.dump([{"phone": c["phone"], "text": text}], open(OUTBOX, "w"), ensure_ascii=False, indent=2)
    status = None
    for _ in range(18):
        time.sleep(2)
        try:
            status = json.load(open(OUTBOX))[0].get("status")
        except Exception:
            continue
        if status:
            break
    if status == "sent":
        sent += 1; consec_err = 0
        print(f"ENVIADO ✓ {c['name']} ({v}) — reales: {sent}", flush=True)
    elif status == "no_whatsapp":
        print(f"sin WhatsApp {c['name']} (raro, estaba validado) — salta", flush=True)
    else:
        consec_err += 1; inciertos.append(c["name"])
        print(f"⚠️ {c['name']}: {status} — salto. seguidos: {consec_err}", flush=True)
        if consec_err >= 3:
            print("   ⛔ 3 fallos seguidos — inestable, DETENIENDO", flush=True); break
    if sent < 15:
        time.sleep(random.randint(150, 240))

if inciertos:
    print(f"INCIERTOS (revisar): {', '.join(inciertos)}", flush=True)
print(f"LISTO4 — {sent} enviados reales", flush=True)
