"""Segundo bloque de nuevos (frío). Espera a que el primer bloque termine,
luego manda los 14 candidatos con mensajes variados por vertical, espaciado largo,
parando si hay error o si la cuenta se cae."""
import json, time, random, sys

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

# Guard: esperar a que el primer bloque termine (evita pelear por el outbox).
print("esperando a que termine el primer bloque…", flush=True)
for _ in range(300):
    try:
        if "LISTO" in open("/tmp/send_nuevos.log").read():
            break
    except Exception:
        pass
    time.sleep(5)

cands = json.load(open("/tmp/bloque2.json"))
counters = {"seguros": 0, "inmobiliaria": 0, "financiera": 0}
sent_count = 0

for i, c in enumerate(cands):
    v = c["v"]
    pool = POOLS[v]
    text = pool[counters[v] % len(pool)]
    counters[v] += 1
    json.dump([{"phone": c["phone"], "text": text}], open(OUTBOX, "w"), ensure_ascii=False, indent=2)
    print(f"[{i+1}/{len(cands)}] encolado → {c['name']} ({v})", flush=True)
    status = None
    for _ in range(20):
        time.sleep(2)
        try:
            status = json.load(open(OUTBOX))[0].get("status")
        except Exception:
            continue
        if status == "sent":
            sent_count += 1
            print(f"   ENVIADO ✓ {c['name']} (reales: {sent_count})", flush=True); break
        if status and status.startswith("error"):
            print(f"   ERROR en {c['name']}: {status} — DETENIENDO TODO", flush=True); sys.exit(1)
        if status == "no_whatsapp":
            print(f"   SIN WhatsApp {c['name']} — saltando", flush=True); break
    # parar al llegar a ~15 reales (junto con los ~4 del primer bloque)
    if sent_count >= 11:
        print(f"   tope alcanzado (~15 reales con el primer bloque) — fin", flush=True); break
    d = random.randint(150, 240)
    print(f"   ...esperando {d}s", flush=True)
    time.sleep(d)

print(f"LISTO BLOQUE 2 — {sent_count} enviados reales en este bloque", flush=True)
