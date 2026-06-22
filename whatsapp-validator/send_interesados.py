"""Manda los 4 interesados de reactivación, de a uno, espaciado, parando si hay error.
Usa la colita outbox.json del listener vivo."""
import json, time, random, sys

OUTBOX = "outbox.json"
MSGS = [
    ("190395933810838@lid", "Hola Laura, buen día 🙌 Ya le tengo el ejemplo que le prometí de cómo se ordenan solos los comprobantes de su condominio. ¿Se lo paso por aquí?"),
    ("234930416152740@lid", "Buen día Lic., le preparé el ejemplo de cómo se arman los expedientes con los documentos que mandan sus clientes. ¿Se lo comparto?"),
    ("84305946620135@lid", "Hola Jorge, ¿cómo le va? Ya tengo el ejemplo que me pidió de cómo se ordenan las evidencias. ¿Se lo mando?"),
    ("125941510602912@lid", "Hola, le tengo el ejemplo de cómo se ordenan solas las fotos y evidencias de cada flete. ¿Se lo paso?"),
]
NAMES = ["Laura/LLBM", "Lic. Daniel", "Jorge/Expo", "Fletes GP"]

for i, (jid, text) in enumerate(MSGS):
    json.dump([{"jid": jid, "text": text}], open(OUTBOX, "w"), ensure_ascii=False, indent=2)
    print(f"[{i+1}/4] encolado → {NAMES[i]}", flush=True)
    status = None
    for _ in range(20):
        time.sleep(2)
        try:
            status = json.load(open(OUTBOX))[0].get("status")
        except Exception:
            continue
        if status == "sent":
            print(f"   ENVIADO ✓ {NAMES[i]}", flush=True); break
        if status and status.startswith("error"):
            print(f"   ERROR en {NAMES[i]}: {status} — DETENIENDO TODO", flush=True); sys.exit(1)
        if status == "no_whatsapp":
            print(f"   SIN WhatsApp {NAMES[i]} — saltando", flush=True); break
    if status != "sent":
        print(f"   ⚠️ {NAMES[i]} no confirmó (status={status})", flush=True)
    if i < len(MSGS) - 1:
        d = random.randint(110, 165)
        print(f"   ...esperando {d}s antes del siguiente", flush=True)
        time.sleep(d)

print("LISTO — 4 interesados procesados", flush=True)
