"""Reanuda el envío de los nuevos pendientes con salvaguarda mejorada:
- error transitorio (Connection Closed/Terminated) → reintenta tras pausa, no para.
- listener caído (posible ban/loggedOut) → DETIENE todo.
Tope: 14 enviados reales aquí (con CI Asesores ya van 15)."""
import json, time, random, sys, subprocess

OUTBOX = "outbox.json"
POOLS = {
    "seguros": [
        "Buen día, ¿las fotos de siniestros y papeles de clientes se les pierden en el WhatsApp? Los ordenamos por cliente solos. ¿Le muestro?",
        "Hola, ¿reciben pólizas, INE y comprobantes de cada cliente por WhatsApp y ordenarlos quita tiempo? Lo hacemos en automático. ¿Le interesa verlo?",
        "Buen día, ¿se les acumulan fotos de siniestros y documentos de clientes en el WhatsApp? Los acomodamos por cliente sin talacha. ¿Le muestro?",
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

# pendientes: las 2 inmobiliarias del bloque 1 que faltaron + el bloque 2
PEND = [
    {"phone": "+524425054066", "name": "Verde Olivo", "v": "inmobiliaria"},
    {"phone": "+523323397568", "name": "Inmob GDL", "v": "inmobiliaria"},
] + json.load(open("/tmp/bloque2.json"))

counters = {"seguros": 0, "inmobiliaria": 0, "financiera": 0}
sent = 0

def send_one(phone, text, name):
    for attempt in range(3):
        if not listener_alive():
            print(f"   ⛔ LISTENER CAÍDO antes de {name} — POSIBLE BAN, DETENIENDO TODO", flush=True)
            sys.exit(2)
        json.dump([{"phone": phone, "text": text}], open(OUTBOX, "w"), ensure_ascii=False, indent=2)
        status = None
        for _ in range(20):
            time.sleep(2)
            try:
                status = json.load(open(OUTBOX))[0].get("status")
            except Exception:
                continue
            if status:
                break
        if status == "sent":
            return "sent"
        if status == "no_whatsapp":
            return "no_whatsapp"
        # error transitorio → reintentar
        print(f"   ⚠️ {name}: {status} — reintento {attempt+1}/3 en 30s", flush=True)
        time.sleep(30)
    return "failed"

for c in PEND:
    if sent >= 14:
        print("   tope de 15 reales alcanzado — fin", flush=True)
        break
    v = c["v"]; text = POOLS[v][counters[v] % len(POOLS[v])]; counters[v] += 1
    print(f"→ {c['name']} ({v})", flush=True)
    r = send_one(c["phone"], text, c["name"])
    if r == "sent":
        sent += 1
        print(f"   ENVIADO ✓ {c['name']} (reales en este bloque: {sent})", flush=True)
    elif r == "no_whatsapp":
        print(f"   SIN WhatsApp {c['name']} — saltando", flush=True)
    else:
        print(f"   ✗ {c['name']} falló tras reintentos — saltando", flush=True)
    if sent < 14:
        d = random.randint(150, 240)
        print(f"   ...esperando {d}s", flush=True)
        time.sleep(d)

print(f"LISTO RESTO — {sent} enviados reales (más CI Asesores = {sent+1} fríos nuevos hoy)", flush=True)
