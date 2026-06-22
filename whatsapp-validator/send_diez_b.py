"""Manda 10 leads CloudSH nuevos (inmo/escuela/condominio), mensaje por vertical,
verificando ENTREGA REAL via ACK. Espaciado 90-150s. Para si listener cae."""
import json, time, random, subprocess

OUTBOX = "outbox.json"
LOG = "/tmp/wa_listener.log"

MSGS = {
    "inmo": "Hola, ¿les llegan los papeles de cada cliente (INE, comprobantes, contratos) por WhatsApp y luego cuesta encontrarlos? Los ordenamos por cliente solos. ¿Le muestro?",
    "escuela": "Buen día, ¿reciben por WhatsApp los papeles de cada alumno (INE de papás, comprobante de domicilio, acta, pagos) y juntarlos por alumno es batalla? Se ordena solo. ¿Le interesa verlo?",
    "condominio": "Buen día, ¿les llegan por WhatsApp los comprobantes de pago de cada condómino y conciliar quién pagó es batalla? Los ordenamos por unidad solos. ¿Le muestro?",
}

def listener_alive():
    return subprocess.run(["pgrep", "-f", "node send_and_watch"], capture_output=True).returncode == 0

def ack_count():
    try:
        return open(LOG).read().count("ACK ENTREGADO")
    except Exception:
        return 0

cands = json.load(open("/tmp/cloudsh_send10b.json"))
entregados = 0
inciertos = []

for i, c in enumerate(cands):
    if not listener_alive():
        print("⛔ listener caído — deteniendo", flush=True); break
    before = ack_count()
    text = MSGS.get(c["vert"], MSGS["inmo"])
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
        time.sleep(12)  # esperar ACK de entrega
        if ack_count() > before:
            entregados += 1
            print(f"ENTREGADO ✓✓ {c['name']} [{c['vert']}] (reales: {entregados})", flush=True)
        else:
            print(f"~ {c['name']}: enviado pero SIN confirmar entrega aún", flush=True)
            inciertos.append(c["name"])
    if i < len(cands) - 1:
        time.sleep(random.randint(120, 200))

print(f"INCIERTOS: {', '.join(inciertos) if inciertos else 'ninguno'}", flush=True)
print(f"LISTO — {entregados}/10 entregados confirmados", flush=True)
