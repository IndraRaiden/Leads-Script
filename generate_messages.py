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


# Cada vertical: plantillas BREVES (1-2 líneas). {n} = nombre del negocio.
# Gancho de dolor + CTA suave. Sin links ni adjuntos. Ver [[feedback-brief-outreach]].
TEMPLATES = {
    "fletes": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Batallan para encontrar fotos de entregas o cotizaciones viejas en WhatsApp? Hicimos algo que las ordena solo. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Se les pierde la evidencia de una mudanza entre tantos chats? Tenemos algo que la acomoda por cliente. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Pierden tiempo buscando fotos de entregas en WhatsApp? Armamos algo que las ordena. ¿Le late?",
    ],
    "transporte": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Tardan en hallar el POD o la foto de una entrega entre los chats? Hicimos algo que las ordena por viaje. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Se les regan las evidencias de entrega en WhatsApp? Tenemos algo que las junta solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Pierden tiempo buscando fotos de entregas viejas? Armamos algo que las ordena. ¿Le late?",
    ],
    "contable": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cuánto tiempo se va juntando facturas y recibos que llegan en fotos por WhatsApp? Hicimos algo que los ordena por cliente. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Batallan en el cierre persiguiendo comprobantes regados en chats? Tenemos algo que los acomoda solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Pierden horas bajando tickets de WhatsApp? Armamos algo que los ordena por cliente y mes. ¿Le late?",
    ],
    "juridico": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Tardan armando un expediente con docs regados en WhatsApp y correo? Hicimos algo que los junta por caso. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Se les traspapela un documento entre tantos chats de un asunto? Tenemos algo que lo ordena solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Pierden tiempo reconstruyendo expedientes de varios chats? Armamos algo para eso. ¿Le late?",
    ],
    "condominios": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo juntan los comprobantes y reportes que mandan por foto en WhatsApp? Hicimos algo que los ordena por unidad. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Batallan a fin de mes con recibos de mantenimiento regados en chats? Tenemos algo que los acomoda solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿El expediente de una unidad está repartido en mil fotos? Armamos algo que lo ordena. ¿Le late?",
    ],
    "inmobiliaria": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo tienen las fotos y docs de cada propiedad cuando un cliente pregunta? Hicimos algo que los ordena por inmueble. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Tardan hallando el contrato o fotos de un inmueble entre chats? Tenemos algo que lo ordena solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Se pierde documentación de una propiedad en WhatsApp? Armamos algo para eso. ¿Le late?",
    ],
    "seguros": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo arman un reclamo con las fotos del siniestro que llegan por WhatsApp? Hicimos algo que las ordena por póliza. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Se va tiempo juntando evidencias de un siniestro regadas en chats? Tenemos algo que las junta solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Batallan rearmando expedientes de reclamos? Armamos algo que los ordena. ¿Le late?",
    ],
    "construccion": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo ordenan las fotos de avance de obra que llegan por WhatsApp? Hicimos algo que las junta por proyecto. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Batallan hallando la foto de un avance o un plano entre chats? Tenemos algo que lo ordena solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Se pierde evidencia de obra en los WhatsApp del equipo? Armamos algo para eso. ¿Le late?",
    ],
    "aduanal": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo arman pedimentos y facturas que llegan por WhatsApp y correo? Hicimos algo que los ordena por operación. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Se va tiempo juntando documentos de un despacho regados en chats? Tenemos algo que los junta solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Se traspapela un documento de un despacho en WhatsApp? Armamos algo para eso. ¿Le late?",
    ],
    "oficios": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo encuentran fotos y cotizaciones de trabajos viejos en WhatsApp? Hicimos algo que las ordena por cliente. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Tardan hallando la foto o el presupuesto de un trabajo entre chats? Tenemos algo que lo acomoda solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Se pierde la foto de un trabajo entre tanto WhatsApp? Armamos algo para eso. ¿Le late?",
    ],
    "viajes": [
        "Hola ¿{n}? 👋 Los vi en Google Maps. ¿Cómo ordenan vouchers y docs de cada reserva que llegan por WhatsApp? Hicimos algo que los junta por cliente. ¿Le interesa?",
        "Qué tal {n}, los vi en Maps. ¿Batallan juntando los papeles de una reserva regados en chats? Tenemos algo que los ordena solo. ¿Le cuento rápido?",
        "Hola {n} 👋 Soy Ricardo, de una empresa mexicana de software. ¿Se traspapela un voucher o pasaporte en WhatsApp? Armamos algo para eso. ¿Le late?",
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
