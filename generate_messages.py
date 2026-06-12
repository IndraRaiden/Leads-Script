"""Genera mensajes de primer contacto por WhatsApp, personalizados por lead.

Lee un CSV de leads (con columnas name, search_query, search_location, whatsapp)
y agrega una columna `wa_message` con un mensaje de apertura adaptado al vertical
del negocio y al nombre real. Rota entre 3-4 variantes por vertical (determinista
por índice de fila, sin aleatoriedad) para que el envío en abanico no mande texto
idéntico — clave anti-spam.

Reglas del mensaje (ver chat): sin links/imágenes, abre con el dolor del cliente,
posición de "construyendo algo, pidiendo opinión", cierra pidiendo permiso.

Uso:
    python generate_messages.py output/HOT_leads_MX_WHATSAPP.csv
    -> escribe output/HOT_leads_MX_WHATSAPP_msgs.csv
"""

import csv
import re
import sys
from pathlib import Path


def first_name(name: str) -> str:
    """Nombre corto presentable del negocio para el saludo."""
    n = re.sub(r'["“”]', "", name).strip()
    n = re.sub(r"\b(S\.?A\.?\s*de\s*C\.?V\.?|S\.?\s*C\.?|S\.?\s*de\s*R\.?L\.?)\b", "", n, flags=re.I)
    n = re.sub(r"\s+", " ", n).strip(" .,-")
    return n or "su negocio"


# Cada vertical: lista de plantillas. {n} = nombre del negocio.
# El dolor de apertura es específico al giro. Sin links ni adjuntos.
TEMPLATES = {
    "fletes": [
        "Hola, ¿{n}? 👋 Los vi en Google Maps. Pregunta rápida: cuando un cliente les reclama una entrega, ¿qué tan rápido encuentran la foto de evidencia entre todos los chats? Soy Ricardo, de una empresa mexicana de software — estamos armando una herramienta que ordena justo eso y ando platicando con fleteros antes de lanzar. ¿Le late si le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Una duda de campo: ¿cuánto tardan en hallar la foto o el comprobante de una mudanza vieja cuando alguien lo pide? Estoy construyendo algo mexicano que junta todas esas fotos y las ordena por cliente solito. Me sirve mucho la opinión de gente que mueve carga de verdad — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. Pregunta honesta: ¿se les ha perdido la evidencia de una entrega entre tantos WhatsApp? Ando hablando con fleteros porque estamos por sacar una herramienta que resuelve eso. No les vendo nada hoy, busco que me digan si tiene sentido. ¿Les interesa?",
    ],
    "transporte": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: cuando piden el POD o la foto de una entrega vieja, ¿qué tan fácil es encontrarla entre los chats de los choferes? Soy Ricardo, empresa mexicana de software — estamos por lanzar algo que ordena justo eso y platico con transportistas antes. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda de colega: ¿cuánto tiempo se va el equipo juntando evidencias de entrega regadas en WhatsApp? Construimos algo que las agrupa por viaje y cliente. Me late mucho su opinión antes de salir — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Les ha pasado que un cliente reclama y la foto de la entrega está enterrada en mil chats? Ando hablando con líneas de carga porque sacamos una herramienta para eso. No vendo hoy, pido feedback real. ¿Les interesa verla?",
    ],
    "contable": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta de colega a colega: ¿cuántas horas se les van cada cierre persiguiendo las facturas y recibos que los clientes mandan en fotos por WhatsApp? Soy Ricardo, empresa mexicana de software — armamos algo que junta y ordena todo eso por cliente. ¿Les interesaría verlo antes de que salga?",
        "Qué tal {n}, los encontré en Maps. Duda honesta: en temporada, ¿cuánto tiempo pierden bajando comprobantes que llegan por foto y correo desordenados? Estamos construyendo una herramienta mexicana que los acomoda solos por cliente y mes. Su opinión me sirve mucho antes de lanzar — ¿se puede?",
        "Hola {n} 👋 Vi su despacho en Google. ¿Les toca rearmar el expediente de un cliente juntando fotos de tickets de varios chats? Ando platicando con contadores porque sacamos algo justo para eso. No les vendo hoy, busco feedback. ¿Les late?",
    ],
    "juridico": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: al armar un expediente, ¿cuánto tardan juntando los documentos y fotos que el cliente fue mandando por WhatsApp y correo? Soy Ricardo, empresa mexicana de software — construimos algo que ordena toda esa documentación por caso. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda de colega: ¿se les ha traspapelado un documento clave entre tantos chats de un asunto? Estamos por lanzar una herramienta que agrupa todo por expediente. Me sirve su opinión antes de salir — ¿se puede?",
        "Hola {n} 👋 Vi su despacho en Google. ¿Cuánto tiempo se va reconstruyendo un expediente con papeles regados en WhatsApp, correo y fotos? Ando hablando con abogados porque sacamos algo para eso. No vendo hoy, pido feedback. ¿Les interesa?",
    ],
    "condominios": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: los comprobantes de pago y reportes que los condóminos mandan por foto en WhatsApp, ¿cómo los ordenan a fin de mes? Soy Ricardo, empresa mexicana de software — armamos algo que junta todo eso por unidad y mes. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda honesta: ¿cuánto batallan juntando evidencias y recibos de mantenimiento que llegan sueltos por chat? Construimos una herramienta que los acomoda por condominio. Su opinión me sirve antes de lanzar — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Les pasa que el expediente de una unidad está repartido en mil fotos de WhatsApp? Ando platicando con administradores porque sacamos algo para eso. No les vendo hoy, busco feedback. ¿Les late?",
    ],
    "inmobiliaria": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: las fotos de propiedades y documentos de cada operación, ¿cómo las tienen ordenadas cuando un cliente pregunta? Soy Ricardo, empresa mexicana de software — armamos algo que junta todo por propiedad y cliente. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda de campo: ¿cuánto tardan hallando el contrato o las fotos de un inmueble entre tantos chats? Estamos por lanzar una herramienta que lo ordena solito. Me sirve su opinión antes de salir — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Se les ha perdido la documentación de una propiedad entre WhatsApp y correo? Ando hablando con inmobiliarias porque sacamos algo para eso. No vendo hoy, pido feedback. ¿Les interesa?",
    ],
    "seguros": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: las fotos de un siniestro y los documentos de la póliza que el cliente manda por WhatsApp, ¿cómo los arman para el reclamo? Soy Ricardo, empresa mexicana de software — construimos algo que ordena todo eso por caso. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda honesta: ¿cuánto tiempo se va juntando evidencias de un siniestro regadas en chats y correo? Armamos una herramienta que las agrupa por póliza y cliente. Su opinión me sirve antes de lanzar — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Les ha tocado rearmar un expediente de reclamo juntando fotos de varios lados? Ando platicando con agentes de seguros porque sacamos algo para eso. No les vendo hoy, busco feedback. ¿Les late?",
    ],
    "construccion": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: las fotos de avance de obra que mandan por WhatsApp, ¿cómo las ordenan por proyecto cuando el cliente pide reporte? Soy Ricardo, empresa mexicana de software — armamos algo que junta todo eso por obra. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda de campo: ¿cuánto batallan hallando la foto de un avance o un plano entre tantos chats de obra? Construimos una herramienta que lo ordena solo por proyecto. Me sirve su opinión antes de salir — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Se pierde evidencia de obra entre los WhatsApp del equipo? Ando hablando con constructoras porque sacamos algo para eso. No vendo hoy, pido feedback. ¿Les interesa?",
    ],
    "aduanal": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: pedimentos, facturas y fotos de carga que llegan por WhatsApp y correo, ¿cómo los arman por operación? Soy Ricardo, empresa mexicana de software — construimos algo que ordena toda esa documentación por embarque. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda de colega: ¿cuánto tiempo se va juntando los documentos de un despacho regados en mil chats? Armamos una herramienta que los agrupa por operación y cliente. Su opinión me sirve antes de lanzar — ¿se puede?",
        "Hola {n} 👋 Vi su agencia en Google. ¿Se les ha traspapelado un documento de un despacho entre WhatsApp y correo? Ando platicando con agentes aduanales porque sacamos algo para eso. No les vendo hoy, busco feedback. ¿Les late?",
    ],
    "oficios": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: las fotos de trabajos y cotizaciones que mandan por WhatsApp, ¿cómo las encuentran cuando un cliente vuelve meses después? Soy Ricardo, empresa mexicana de software — armamos algo que ordena todo eso por cliente y trabajo. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda honesta: ¿cuánto tardan hallando la foto o el presupuesto de un trabajo viejo entre tantos chats? Construimos una herramienta que lo acomoda solo. Me sirve su opinión antes de salir — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Se pierde la foto de un trabajo entre tanto WhatsApp? Ando hablando con talleres y negocios como el suyo porque sacamos algo para eso. No vendo hoy, pido feedback. ¿Les interesa?",
    ],
    "viajes": [
        "Hola, ¿{n}? Los vi en Google Maps. Pregunta rápida: comprobantes, vouchers y documentos de cada reserva que llegan por WhatsApp, ¿cómo los ordenan por cliente y viaje? Soy Ricardo, empresa mexicana de software — armamos algo que junta todo eso solo. ¿Le cuento en 2 mensajes?",
        "Qué tal {n}, los encontré en Maps. Duda de campo: ¿cuánto batallan juntando los papeles de una reserva regados en chats? Construimos una herramienta que los agrupa por cliente. Su opinión me sirve antes de lanzar — ¿se puede?",
        "Hola {n} 👋 Vi su perfil en Google. ¿Se traspapela un voucher o un pasaporte entre tantos WhatsApp? Ando platicando con agencias de viajes porque sacamos algo para eso. No les vendo hoy, busco feedback. ¿Les late?",
    ],
}

# Mapea la search_query a un grupo de plantillas.
QUERY_MAP = [
    ("fletes", "fletes"),
    ("mudanzas", "fletes"),
    ("transporte de carga", "transporte"),
    ("mensajeria", "transporte"),
    ("contable", "contable"),
    ("juridico", "juridico"),
    ("juridica", "juridico"),
    ("abogad", "juridico"),
    ("notaria", "juridico"),
    ("condominios", "condominios"),
    ("inmobiliaria", "inmobiliaria"),
    ("bienes raices", "inmobiliaria"),
    ("seguros", "seguros"),
    ("ajustador", "seguros"),
    ("constructora", "construccion"),
    ("construccion", "construccion"),
    ("contratista", "construccion"),
    ("maquinaria", "construccion"),
    ("aduanal", "aduanal"),
    ("herreria", "oficios"),
    ("carpinteria", "oficios"),
    ("plomeria", "oficios"),
    ("aire acondicionado", "oficios"),
    ("taller", "oficios"),
    ("hojalateria", "oficios"),
    ("transmisiones", "oficios"),
    ("purificadora", "oficios"),
    ("viajes", "viajes"),
    ("tour", "viajes"),
]


def vertical_for(query: str) -> str:
    q = query.lower()
    for needle, group in QUERY_MAP:
        if needle in q:
            return group
    return "oficios"  # fallback genérico seguro


def main():
    if len(sys.argv) < 2:
        print("Uso: python generate_messages.py <leads.csv>")
        sys.exit(1)
    src = Path(sys.argv[1])
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    if not rows:
        print("CSV vacío.")
        return

    fields = list(rows[0].keys())
    if "wa_message" not in fields:
        fields.append("wa_message")

    for i, r in enumerate(rows):
        group = vertical_for(r.get("search_query", ""))
        variants = TEMPLATES[group]
        tpl = variants[i % len(variants)]  # rotación determinista anti-duplicado
        r["wa_message"] = tpl.format(n=first_name(r.get("name", "")))

    out = src.with_name(src.stem + "_msgs.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} mensajes generados -> {out}")


if __name__ == "__main__":
    main()
