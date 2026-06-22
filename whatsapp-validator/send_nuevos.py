"""Manda el bloque de nuevos (frío) de a uno, espaciado largo, parando si hay error.
Frío = más espaciado que conversación abierta. Tope hoy: 5."""
import json, time, random, sys

OUTBOX = "outbox.json"
MSGS = [
    ("+525559256291", "ASF Prisma (seguros)", "Buen día, ¿les llegan fotos de siniestros, pólizas e identificaciones de clientes por WhatsApp y luego es un caos encontrarlas? Se ordenan por cliente solas. ¿Le muestro?"),
    ("+523311437246", "CI Asesores (seguros)", "Hola, ¿reciben pólizas, INE y comprobantes de cada cliente por WhatsApp y ordenarlos quita tiempo? Lo hacemos en automático por cliente. ¿Le interesa verlo?"),
    ("+525511011720", "Gutiérrez (seguros)", "Buen día, ¿las fotos de siniestros y documentos de clientes se les pierden en el WhatsApp? Los ordenamos por cliente sin talacha. ¿Le muestro?"),
    ("+524425054066", "Verde Olivo (inmob)", "Hola, ¿les llegan INE, comprobantes de ingresos y contratos de cada cliente por WhatsApp y armar el expediente es batalla? Se ordena solo. ¿Le interesa verlo?"),
    ("+523323397568", "Inmob GDL (inmob)", "Buen día, ¿reciben los papeles de cada inquilino por WhatsApp y luego cuesta encontrarlos? Los ordenamos por cliente en automático. ¿Le muestro?"),
]

for i, (phone, name, text) in enumerate(MSGS):
    json.dump([{"phone": phone, "text": text}], open(OUTBOX, "w"), ensure_ascii=False, indent=2)
    print(f"[{i+1}/5] encolado → {name}", flush=True)
    status = None
    for _ in range(20):
        time.sleep(2)
        try:
            status = json.load(open(OUTBOX))[0].get("status")
        except Exception:
            continue
        if status == "sent":
            print(f"   ENVIADO ✓ {name}", flush=True); break
        if status and status.startswith("error"):
            print(f"   ERROR en {name}: {status} — DETENIENDO TODO", flush=True); sys.exit(1)
        if status == "no_whatsapp":
            print(f"   SIN WhatsApp {name} — saltando", flush=True); break
    if status != "sent":
        print(f"   ⚠️ {name} no confirmó (status={status})", flush=True)
    if i < len(MSGS) - 1:
        d = random.randint(150, 240)
        print(f"   ...esperando {d}s antes del siguiente", flush=True)
        time.sleep(d)

print("LISTO — bloque de 5 nuevos procesado", flush=True)
