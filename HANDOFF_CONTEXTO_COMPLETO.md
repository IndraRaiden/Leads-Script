# HANDOFF — Contexto completo del outreach CloudSH (Leads-Script)

> Documento de traspaso. Léelo COMPLETO antes de tocar nada. Sirve para que un chat
> nuevo continúe exactamente donde vamos. Última actualización: 2026-06-12.
> Usuario: Ricardo (ricardo.mata@beluga.mx).

---

## 0. Qué estamos haciendo (resumen de 30 seg)

Conseguir clientes para **CloudSH** (SaaS de inteligencia de archivos: ordena fotos,
comprobantes y documentos que los negocios reciben por WhatsApp/email; está en
`/Users/ricardomata/Documents/GitHub/beco/stronghold-apps/cloudstronghold`).

Flujo: **scrapear leads de Google Maps → validar teléfono → validar que tengan WhatsApp →
mandar mensaje de apertura (corto) → capturar respuestas (texto y audio) → dar seguimiento.**

Todo el outreach se hace desde la carpeta `/Users/ricardomata/Documents/GitHub/beco/Leads-Script`
con el WhatsApp de Ricardo vinculado como "dispositivo vinculado" (Baileys).

---

## 1. REGLAS DE TRABAJO (no romper)

1. **Modo de envío: yo PROPONGO el mensaje → Ricardo APRUEBA → yo lo MANDO.** Nunca blastear
   automático sin OK. Uno por uno.
2. **Mensajes MUY cortos**, 1-2 líneas (~15-25 palabras). Largos = se ven "creepy / muy IA"
   y no responden. Gancho de dolor + CTA corto. NO decir "Soy Ricardo, software mexicano"
   (suena mal); mejor omitir auto-etiqueta o "de una empresa mexicana de software".
3. **Ricardo NO toca WhatsApp** — yo capturo, transcribo y respondo todo. Él solo decide rumbo.
4. **Contadores NO son el mercado** (ver §6). Enfocar fletes, condominios, transporte, jurídico,
   constructoras, seguros.
5. Antes de mandar cualquier cosa, releer y recortar el mensaje.

---

## 2. ESTRUCTURA DE ARCHIVOS

```
Leads-Script/
├── leads_scraper.py            # Scraper de Google Maps (Playwright). Valida tel (phonenumbers),
│                               #   genera wa.me, detecta negocios cerrados, columna whatsapp.
├── enrich_master.py            # Rellena columnas de validación en MASTER_leads.csv viejo.
├── generate_messages.py        # Agrega columna wa_message (mensaje corto por vertical+nombre).
├── transcribe.py               # Transcribe audios con Whisper/gpt-4o-transcribe (key de Core/.env).
├── seguimiento_interesados.csv # ⭐ Lista viva de leads interesados/bots con estado y próximo paso.
├── HANDOFF_CONTEXTO_COMPLETO.md # Este archivo.
├── .venv/                      # Python 3.13 (Homebrew). El python del sistema es 3.9 y NO sirve.
├── sweeps/                     # Definiciones de búsqueda "tipo | ciudad" por línea.
│   ├── sweep_cloudstronghold_mx.txt / _mx2.txt
│   └── sweep_mx500_a.txt / _b.txt / _c.txt   # Mega-run nacional (84 búsquedas).
├── output/
│   ├── MASTER_leads.csv        # TODOS los leads scrapeados, dedup, con validación.
│   ├── HOT_leads_MX.csv         # MX calientes (score>=5, tel válido, abiertos).
│   ├── HOT_leads_MX_WHATSAPP.csv # MX calientes con WhatsApp CONFIRMADO.
│   ├── SEND_today_10.csv        # Los primeros 10 enviados (plantilla larga vieja).
│   ├── SEND_pool.csv / POOL_payers* # Pool de candidatos del batch de 24.
│   ├── WATCH_ALL.csv            # ⭐ Universo de contactos que vigila el listener.
│   └── runs/                    # CSV timestamped por corrida.
└── whatsapp-validator/         # ⭐ TODA la infra de WhatsApp (Node/Baileys). Ver §4.
    ├── validate.js             # Valida en lote si números tienen WhatsApp (onWhatsApp). Genera QR.
    ├── send.js                 # Manda 1 mensaje a 1 número (uso puntual; OJO conflicto si listener vivo).
    ├── send_and_watch.js       # ⭐⭐ EL PRINCIPAL: listener único que vigila respuestas + manda por colita.
    ├── recover.js              # Intento de recuperar mensajes viejos vía history-sync (NO sirve si ya vinculado).
    ├── outbox.json             # ⭐ Cola de salida: aquí se escriben mensajes/archivados a ejecutar.
    ├── replies.json            # ⭐ Todas las respuestas capturadas de leads.
    ├── sent.json               # Teléfonos ya enviados (anti-duplicado).
    ├── listener.lock           # Candado de instancia única (PID del listener vivo).
    ├── media/                  # Audios descargados (.ogg) de los leads.
    ├── auth/                   # ⚠️ Sesión de WhatsApp. NO COMMITEAR. Borrarla = re-escanear QR.
    └── node_modules/           # @whiskeysockets/baileys, qrcode, pino.
```

`seguimiento_interesados.csv` y `output/*.csv` SÍ se versionan; `auth/`, `node_modules/`,
`.venv/`, `.DS_Store` están en `.gitignore`. El repo es su propio git
(`https://github.com/IndraRaiden/Leads-Script`, rama `main`). Para `git status` hay que
estar DENTRO de `Leads-Script` (la carpeta padre `beco` no es repo).

---

## 3. SETUP / INSTALACIÓN (ya hecho, por si hay que rehacer)

```bash
cd /Users/ricardomata/Documents/GitHub/beco/Leads-Script
# Python (usar 3.13 de Homebrew; el 3.9 del sistema NO sirve por sintaxis)
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install playwright pandas rich python-dotenv phonenumbers openai
.venv/bin/playwright install chromium
# Node (validator)
cd whatsapp-validator && npm install   # @whiskeysockets/baileys qrcode pino
```

---

## 4. INFRAESTRUCTURA DE WHATSAPP (lo más importante)

### 4.1 El listener principal: `send_and_watch.js`
Es UN solo proceso que: (a) opcionalmente manda los pendientes de un CSV, (b) **vigila TODAS
las respuestas entrantes** (texto e imagen, y **descarga audios** a `media/`), (c) procesa la
**cola `outbox.json`** cada 4s para mandar respuestas/archivar SIN reiniciarse.

Arrancarlo en modo "solo vigilar" (no manda nada nuevo, tope 0):
```bash
cd /Users/ricardomata/Documents/GitHub/beco/Leads-Script/whatsapp-validator
node send_and_watch.js ../output/WATCH_ALL.csv 75 200 0
#   args: <csv> <minSeg> <maxSeg> <maxSends>
```
- Tiene **candado de instancia única** (`listener.lock`). Si ya hay uno vivo, otro proceso
  se niega a arrancar (esto resolvió un bug donde 2 procesos mandaban DOBLE).
- Reconecta solo si se cae. Reusa `auth/` → **no pide QR** salvo que borres `auth/`.
- Verificar que está vivo: `pgrep -fl "node send_and_watch"`. Debe haber **uno solo**.

### 4.2 Mandar una respuesta (vía colita, sin reiniciar)
Escribir en `outbox.json` un array. El listener lo manda en ~4s y marca `status:"sent"`.
```json
[
  { "phone": "525554635554", "text": "mensaje corto" },
  { "jid": "125941510602912@lid", "text": "responder a un ID oculto" }
]
```
- Usar `phone` (10 dígitos MX o E164) cuando se conoce el número.
- Usar `jid` cuando la respuesta vino con **@lid** (ID oculto, ver §5).

### 4.3 Archivar un chat (objeciones / muertos)
```json
[ { "action": "archive", "jid": "62565359030272@lid", "lastId": "<id del último msg>", "at": <timestamp> } ]
```
El `lastId` y `at` se sacan de `replies.json` (campo `id` y `at` del último mensaje de ese phone).

### 4.4 Ver respuestas capturadas
```bash
cat whatsapp-validator/replies.json   # cada msg: {id, name, phone, text, mediaPath, at}
```
Para monitorear en vivo, usar un Monitor sobre el output del proceso del listener buscando
`RESPUESTA|OUTBOX|ARCHIVADO|Sesión cerrada`.

### 4.5 Transcribir un audio
Los audios llegan a `media/<num>_<ts>.ogg`. La API rechaza extensión `.opus`, copiar a `.ogg`:
```bash
cp "whatsapp-validator/media/XXXX.ogg" /tmp/a.ogg
.venv/bin/python transcribe.py /tmp/a.ogg
```
(El usuario también puede reenviar el archivo de audio desde el teléfono si se perdió.)

### 4.6 Vincular WhatsApp (solo si se borró auth/)
`send_and_watch.js` genera `qr.png` al arrancar sin sesión. Abrir con:
`open -a Preview qr.png` y escanear desde WhatsApp > Dispositivos vinculados.
**Vincular DE CERO trae el history-sync** (mensajes recientes); reconectar con sesión ya
vinculada NO retrae mensajes viejos.

---

## 5. GOTCHAS TÉCNICOS (aprendidos a la mala)

1. **@lid (ID oculto):** WhatsApp ya no siempre manda el teléfono; manda un ID tipo
   `125941510602912@lid`. No se puede mapear a número directo. Para responder, mandar al `jid`.
   El listener etiqueta esas respuestas con el `pushName` (nombre de perfil) para no perderlas.
2. **No se pueden recuperar mensajes viejos** que llegaron mientras el listener no escuchaba o
   con la lista equivocada. Baileys NO re-entrega a un dispositivo ya vinculado. El history-sync
   solo llega al VINCULAR de cero. Si se perdió uno, pedir screenshot al usuario.
3. **Un solo proceso listener.** Dos = mensajes DOBLES. El candado lo previene; igual verificar
   con `pgrep` y matar extras con `pkill -9 -f send_and_watch` antes de relanzar.
4. **`send.js` vs listener:** no correr `send.js` mientras el listener está vivo (dos conexiones
   a la misma `auth/` se pelean). Mejor usar la colita `outbox.json` del listener.
5. **Python 3.13**, no el 3.9 del sistema. Siempre `.venv/bin/python`.
6. **Riesgo de ban:** número nuevo + muchos mensajes/día = riesgo. Ir lento, espaciar, calentar.
   Hoy ya se mandaron ~35; mañana ir suave.

---

## 6. APRENDIZAJE DE MERCADO (real, de las respuestas de hoy)

- **CONTADORES = NO.** No tienen el dolor: bajan XML directo del SAT y usan Contalink.
  Respuestas reales: "usamos CONTALINK", "todo se descarga del SAT, ya nadie hace eso".
  4 contadores reaccionaron mal/descartados. NO incluirlos en próximos batches.
- **SÍ enganchan** los que reciben fotos/documentos de verdad: **condominios, transporte de
  carga, fletes/mudanzas, jurídico, constructoras, seguros.** Cargar el outreach ahí.
- Mensaje que confundió (largo): la gente preguntó "¿a qué se refiere?". Refuerza regla de cortos.

---

## 7. ESTADO ACTUAL DE LEADS (al 2026-06-12)

Fuente viva: `seguimiento_interesados.csv`. Resumen:

**🟢 INTERESADOS (esperan el DEMO, dar seguimiento el lunes):**
| Negocio | Contacto | Vertical | Ciudad | Estado |
|---|---|---|---|---|
| LLBM Administración de Edificios | Laura | condominios | CDMX | Aceptó demo. Escribirle el LUNES con el ejemplo. wa.me/525554635554 |
| Expo Proveedores del Transporte | Jorge Curiel | transporte | Monterrey | Pidió presentación (audio). Ya se le presentó; mandar ejemplo. wa.me/528122570974 |
| Fletes Expres GP | (perfil GP) | fletes | GDL | "Sí, doy mi punto de vista". jid 125941510602912@lid |
| ABOGADO & ASOCIADOS Desp. Jurídico | Lic. Daniel | jurídico | GDL | Dijo "Sí". jid 234930416152740@lid. (Recibió 1 doble por error, ya disculpado.) |

**🤖 BOTS (auto-saludo, sin humano todavía) → REENGANCHAR EL LUNES:**
- Lic. Mayra Aguirre (179658599456909@lid)
- Despacho Jurídico Ornelas (122054397399220@lid)
- 2 despachos sin nombre (255941496852483@lid, 228561080344748@lid)

**🗄️ ARCHIVADOS (no volver a tocar):** 3 contadores con objeción + Despacho Gaytán/Laura
(contador, detectó bot) + 1 troll.

---

## 8. PENDIENTE CLAVE → EL DEMO

Todos los interesados esperan "un ejemplo en unos días". **No existe demo todavía** (CloudSH es
idea + scaffold en `stronghold-apps/cloudstronghold`). Sin algo visual que mandar, los leads se
enfrían. Siguiente paso propuesto: armar un **mockup de 3-4 pantallas** de cómo CloudSH recibe
las fotos/documentos de WhatsApp y los ordena por cliente, para mandarlo el lunes.

---

## 8.5 ⚠️ INCIDENTE 12-JUN NOCHE — CUENTA RESTRINGIDA 24 H

Tras ~46 envíos en frío en el día, WhatsApp desvinculó el dispositivo (`loggedOut`) a media
corrida del "batch 15" y **restringió la cuenta de Ricardo por 24 h** (se levanta ~13-jun tarde).
- `auth/` fue **borrada** → al volver hay que re-vincular con QR (§4.6). Vincular de cero trae
  history-sync → se recuperan las respuestas que lleguen mientras estamos caídos.
- **Batch 15** (mensajes nuevos cortos/directos aprobados por Ricardo, CSV `output/WATCH_BATCH15.csv`):
  **11/15 enviados** (5 fletes GDL, 3 transporte carga CDMX, Cobague Construcciones, Despacho
  Velasco, Corp. Magallón — ya en sent.json). **4 pendientes** que salen solos al relanzar con ese
  CSV: IntegraLex, ABC Admón. de Condominios, Sky Cancun Residences, Seguros M. Luengo.
- **NO relanzar sobre WATCH_ALL.csv**: tiene 45 pendientes con la plantilla larga VIEJA.
  Usar siempre `WATCH_BATCH15.csv` (viejos forzados a already_sent=yes).
- **Nueva regla de volumen:** máx ~15-20 envíos en frío/día. Evaluar número secundario para frío.
- El demo/mockup lo hará **Ricardo aparte** (quedó base en `demo/mockup.html`, no continuar).

## 9. PLAN DEL LUNES
1. (Sábado tarde, si la restricción ya se levantó) Re-vincular QR en modo solo-escucha y revisar
   respuestas de los 11 del batch vía history-sync.
2. Mandar el DEMO/ejemplo (lo hace Ricardo) a: Laura/LLBM, Jorge/Expo, Fletes GP, Lic. Daniel.
3. Reenganchar a los 4 bots.
4. Mandar los 4 restantes del batch 15 (WATCH_BATCH15.csv, maxSends 4).

---

## 10. MEMORIA (persistente entre sesiones)
En `~/.claude/projects/-Users-ricardomata-Documents-GitHub-beco/memory/`:
- `project_leads_script.md` — estado y reglas (resumen de este handoff).
- `feedback_brief_outreach.md` — regla de mensajes cortos.
- `MEMORY.md` — índice.
```
