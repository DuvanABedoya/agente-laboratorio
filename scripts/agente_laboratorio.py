"""Agente de operaciones del laboratorio de cómputo (Reto semana 6).

Python 3 puro: solo biblioteca estándar, sin pip install.
Uso:
    PROVEEDOR=gemini|groq  API_KEY=<key>  python agente_laboratorio.py
Sin API_KEY corre en MODO SIMULADO (reglas fijas, para probar sin conexión).
"""
import os
import re
import sys
import json
import ssl
import urllib.request
import urllib.error

# 1. Configuración de API y proveedores
PROVEEDOR = os.environ.get("PROVEEDOR", "gemini").strip().lower()
API_KEY = (os.environ.get("API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
TIMEOUT_SEGUNDOS = 30  # tiempo límite por petición HTTP (medido: Gemini tarda 14-17 s)
REINTENTOS = 1         # un reintento si hay timeout o error 5xx

if PROVEEDOR == "groq" or API_KEY.startswith("gsk_"):
    URL = "https://api.groq.com/openai/v1/chat/completions"
    MODELO = "qwen/qwen3.8-27b"
else:
    URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    MODELO = "gemini-3.5-flash-lite"

# 2. Estado del laboratorio en memoria
FRANJAS_VALIDAS = [
    "06:00-08:00", "08:00-10:00", "10:00-12:00",
    "12:00-14:00", "14:00-16:00", "16:00-18:00", "18:00-20:00"
]

DISPONIBILIDAD = {
    "10:00-12:00": ["P-01", "P-02", "P-03", "P-05", "P-06"],
    "14:00-16:00": ["P-07", "P-08", "P-09"]
}

RESERVAS = {
    "E-101": {"puesto": "P-04", "franja": "10:00-12:00", "id_reserva": "RES-402"},
    "E-102": {"puesto": "P-10", "franja": "14:00-16:00", "id_reserva": "RES-503"}
}

HORARIO = "de 06:00 a 20:00 en bloques de 2 horas (" + ", ".join(FRANJAS_VALIDAS) + ")"


def leer(prompt):
    """input() que deja eco de lo digitado cuando la entrada no es un teclado (trazas)."""
    texto = input(prompt)
    if not sys.stdin.isatty():
        print(texto)
    return texto


# 3. Herramientas locales
def consultar_disponibilidad(franja):
    franja = franja.replace(" ", "")
    if franja not in FRANJAS_VALIDAS:
        return f"La franja '{franja}' está fuera del horario: el laboratorio está cerrado. Horario de atención {HORARIO}."
    libres = DISPONIBILIDAD.get(franja, [])
    if not libres:
        return f"No hay puestos libres en {franja}."
    return f"Puestos libres en {franja}: {', '.join(libres)}"


def consultar_reserva(codigo_estudiante):
    codigo = codigo_estudiante.strip().upper()
    r = RESERVAS.get(codigo)
    if not r:
        return f"El estudiante {codigo} no tiene reservas activas."
    return (f"Estudiante {codigo} tiene reservado el puesto {r['puesto']}, "
            f"franja {r['franja']}, id de reserva {r['id_reserva']}")


def buscar_reserva(id_reserva):
    for codigo, r in RESERVAS.items():
        if r["id_reserva"] == id_reserva:
            return codigo, r
    return None, None


def cancelar_reserva(id_reserva):
    codigo, r = buscar_reserva(id_reserva)
    del RESERVAS[codigo]
    DISPONIBILIDAD.setdefault(r["franja"], []).append(r["puesto"])
    DISPONIBILIDAD[r["franja"]].sort()
    return f"Reserva {id_reserva} cancelada exitosamente y puesto liberado."


def ejecutar_herramienta(nombre, param):
    nombre = nombre.lower().strip()
    param = param.strip().strip("`'\"").strip()
    if nombre == "consultar_disponibilidad":
        return consultar_disponibilidad(param)
    if nombre == "consultar_reserva":
        return consultar_reserva(param)
    if nombre == "cancelar_reserva":
        id_reserva = param.upper()
        if buscar_reserva(id_reserva)[0] is None:
            return f"No existe una reserva activa con id {id_reserva}."
        # Acción destructiva: Human-in-the-loop obligatorio
        try:
            confirmacion = leer(f"[CONTROL-HUMANO] ¿Autorizas cancelar la reserva {id_reserva}? (s/n): ").strip().lower()
        except EOFError:
            confirmacion = ""
        if confirmacion != "s":
            return f"Cancelación de reserva {id_reserva} rechazada por el operador humano."
        return cancelar_reserva(id_reserva)
    return f"Herramienta '{nombre}' no existe. Solo hay: consultar_disponibilidad, consultar_reserva, cancelar_reserva."


# 4. System Prompt
SYSTEM_PROMPT = f"""Eres el agente de operaciones del laboratorio de cómputo de la universidad.
Atiendes consultas sobre los 20 puestos (P-01 a P-20) y sus reservas.

REGLAS DURAS DE NEGOCIO:
1. Horario estricto: el laboratorio abre a las 06:00 y cierra a las 20:00, en franjas fijas de 2 horas:
   {", ".join(FRANJAS_VALIDAS)}. Fuera de ese horario el laboratorio está cerrado.
2. Máximo 1 reserva activa por estudiante.
3. Nunca confirmes la cancelación de una reserva sin la autorización previa del operador humano,
   que se pide únicamente a través de la herramienta cancelar_reserva. Si la observación dice que fue
   rechazada, informa que la reserva sigue activa.

HERRAMIENTAS (solo existen estas tres):
- consultar_disponibilidad:franja       (ej. consultar_disponibilidad:10:00-12:00)
- consultar_reserva:codigo_estudiante   (ej. consultar_reserva:E-101)
- cancelar_reserva:id_reserva           (ej. cancelar_reserva:RES-402)
Para cancelar necesitas el id de reserva: si no lo tienes, consúltalo primero con consultar_reserva.
No existe herramienta para crear reservas ni ninguna otra. Nunca inventes herramientas.
Si el usuario pide algo fuera de horario o no permitido, recházalo de inmediato con FINAL, sin usar herramientas.

PROTOCOLO ReAct (responde con UNA sola línea por vuelta, sin texto adicional):
- Para usar una herramienta: ACCION: herramienta:parametro
- Para dar la respuesta final al usuario: FINAL: respuesta
Después de cada ACCION recibirás una OBSERVACION con el resultado. Responde en español."""


# 5. Llamada al modelo (con modo simulado de respaldo)
def modelo_simulado(mensajes):
    q = mensajes[1]["content"]
    h = " ".join(m["content"] for m in mensajes[2:])
    horas = [int(x) for x in re.findall(r"\b(\d{1,2}):\d{2}", q)]
    if "noche" in q.lower() or any(x < 6 or x >= 20 for x in horas):
        return f"FINAL: No es posible. El laboratorio opera exclusivamente {HORARIO}; fuera de ese horario está cerrado."
    if "cancel" in q.lower():
        est = re.search(r"E-\d+", q, re.I)
        res = re.search(r"RES-\d+", h)
        if "cancelada exitosamente" in h:
            return f"FINAL: La reserva {res.group()} fue cancelada y el puesto quedó liberado."
        if "rechazada" in h:
            return f"FINAL: El operador no autorizó la cancelación; la reserva {res.group()} sigue activa."
        if res:
            return f"ACCION: cancelar_reserva:{res.group()}"
        if est and "no tiene reservas" not in h:
            return f"ACCION: consultar_reserva:{est.group().upper()}"
        return "FINAL: No encontré una reserva activa para cancelar."
    if len(horas) >= 2:
        if "Puestos libres" not in h and "No hay puestos" not in h:
            m = re.findall(r"\b\d{1,2}:\d{2}", q)
            return f"ACCION: consultar_disponibilidad:{m[0].zfill(5)}-{m[1].zfill(5)}"
        return f"FINAL: {h.split('OBSERVACION: ')[-1]}. El laboratorio abre hasta las 20:00."
    return "FINAL: Puedo consultar puestos libres por franja, consultar la reserva de un estudiante o cancelar una reserva."


def llamar_modelo(mensajes):
    if not API_KEY:
        return modelo_simulado(mensajes)
    req = urllib.request.Request(
        URL,
        data=json.dumps({"model": MODELO, "messages": mensajes, "temperature": 0}).encode("utf-8"),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"}
    )
    ctx = ssl.create_default_context()  # verifica el certificado TLS del proveedor
    for intento in range(REINTENTOS + 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT_SEGUNDOS) as resp:
                return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code < 500 or intento == REINTENTOS:
                return f"FINAL: El proveedor rechazó la petición (HTTP {e.code}). Revisa API_KEY y MODELO."
        except (urllib.error.URLError, TimeoutError) as e:
            if intento == REINTENTOS:
                return f"FINAL: No pude comunicarme con el modelo ({e}). Intenta de nuevo en un momento."
        print(f"[RED] Falla con el proveedor, reintento {intento + 1} de {REINTENTOS}...")


def interpretar(resp):
    """Devuelve ('FINAL', texto), ('ACCION', (nombre, param)) o (None, resp)."""
    for i, linea in enumerate(resp.replace("```", "").splitlines()):
        linea = linea.strip()
        if linea.startswith("FINAL:"):
            return "FINAL", "\n".join([linea[6:]] + resp.splitlines()[i + 1:]).strip()
        if linea.startswith("ACCION:"):
            nom, _, param = linea[7:].strip().partition(":")
            return "ACCION", (nom, param)
    return None, resp


# 6. Bucle agéntico con parada obligatoria
MAX_VUELTAS = 5
modo = f"API ({MODELO})" if API_KEY else "MODO SIMULADO"
print(f"=== Agente del laboratorio iniciado en {modo} ===")
pregunta = leer("\n¿Qué deseas consultar?: ").strip() or "¿Qué puestos hay libres de 10:00 a 12:00?"
historial = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": pregunta}]

for vuelta in range(1, MAX_VUELTAS + 1):
    print(f"\n--- Vuelta {vuelta} ---")
    resp = llamar_modelo(historial)
    print(f"[Modelo]: {resp}")
    tipo, contenido = interpretar(resp)

    if tipo == "FINAL":
        print(f"\n[RESPUESTA FINAL]: {contenido}")
        break
    if tipo == "ACCION":
        nom, param = contenido
        obs = ejecutar_herramienta(nom, param)
        print(f"[Herramienta -> {nom.strip()}]: {obs}")
        historial.extend([{"role": "assistant", "content": resp},
                          {"role": "user", "content": f"OBSERVACION: {obs}"}])
    else:
        # Fuera de protocolo: se le recuerda el formato y la vuelta cuenta para el tope
        historial.extend([{"role": "assistant", "content": resp},
                          {"role": "user", "content": "Responde solo con 'ACCION: herramienta:parametro' o 'FINAL: respuesta'."}])
else:
    print("\n[PARADA] Tope alcanzado")
