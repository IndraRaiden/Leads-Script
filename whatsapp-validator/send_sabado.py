"""Manda las 9 inmobiliarias restantes (sábado), verificando ENTREGA REAL via ACK.
Reporta 'ENTREGADO' solo si aumenta el contador de ACK; si no, 'sin confirmar'."""
import json, time, random, subprocess

OUTBOX = "outbox.json"
LOG = "/tmp/wa_listener.log"
MSGS = [
    "Buen día, ¿reciben INE, comprobantes de ingresos y contratos de cada cliente por WhatsApp y armar el expediente es batalla? Se ordena solo. ¿Le interesa verlo?",
    "Hola, ¿les llegan los papeles de cada cliente (INE, comprobantes, contratos) por WhatsApp y luego cuesta encontrarlos? Los ordenamos por cliente solos. ¿Le muestro?",
]

def listener_alive():
    return subprocess.run(["pgrep", "-f", "node send_and_watch"], capture_output=True).returncode == 0

def ack_count():
    try:
        return open(LOG).read().count("ACK ENTREGADO")
    except Exception:
        return 0

cands = json.load(open("/tmp/sabado10.json"))[1:]  # saltar ACCI (ya enviada)
entregados = 0
inciertos = []

for i, c in enumerate(cands):
    if not listener_alive():
        print("⛔ listener caído — deteniendo", flush=True); break
    before = ack_count()
    text = MSGS[i % len(MSGS)]
    json.dump([{"phone": c["phone"], "text": text}], open(OUTBOX, "w"), ensure_ascii=False, indent=2)
    status = None
    for _ in range(15):
        time.sleep(2)
        try:
            status = json.load(open(OUTBOX))[0].get("status")
        except Exception:
            continue
        if status:
            break
    if status != "sent":
        print(f"⚠️ {c['name']}: status={status} — salta", flush=True)
        inciertos.append(c["name"])
    else:
        time.sleep(12)  # esperar el ACK de entrega
        if ack_count() > before:
            entregados += 1
            print(f"ENTREGADO ✓✓ {c['name']} (reales: {entregados})", flush=True)
        else:
            print(f"~ {c['name']}: enviado pero SIN confirmar entrega aún", flush=True)
            inciertos.append(c["name"])
    if i < len(cands) - 1:
        time.sleep(random.randint(90, 150))

print(f"INCIERTOS: {', '.join(inciertos) if inciertos else 'ninguno'}", flush=True)
print(f"LISTO SABADO — {entregados} entregados confirmados (+ ACCI = {entregados+1})", flush=True)
