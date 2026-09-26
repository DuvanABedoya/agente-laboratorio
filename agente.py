import os
import json
import urllib.request
import ssl

# 1. Configuración de API y Proveedores
PROVEEDOR = os.environ.get("PROVEEDOR", "gemini").strip().lower()
API_KEY = os.environ.get("API_KEY", "").strip()

if PROVEEDOR == "groq" or API_KEY.startswith("gsk_"):
    URL = "https://api.groq.com/openai/v1/chat/completions"
    MODELO = "qwen/qwen3.8-27b"
else:
    URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    MODELO = "gemini-3.5-flash-lite"

# 2. Herramientas locales (código Python normal)
def consultar_stock(producto):
    stock = {"zapatillas": 14, "camisetas": 5, "gorras": 0}
    return f"Hay {stock.get(producto.lower().strip(), 0)} unidades de '{producto}'."

def consultar_precio(producto):
    precios = {"zapatillas": 85, "camisetas": 25, "gorras": 15}
    precio = precios.get(producto.lower().strip())
    return f"El precio de '{producto}' es ${precio} USD." if precio else f"'{producto}' no encontrado."

def cancelar_pedido(id_pedido):
    return f"Pedido {id_pedido} cancelado exitosamente en el sistema."

def ejecutar_herramienta(nombre, param):
    nombre = nombre.lower().strip()
    if nombre == "cancelar_pedido":
        # Gradiente de autonomía: confirmación humana (Human-in-the-loop)
        try:
            if input(f"[CONTROL-HUMANO] ¿Autorizas cancelar pedido {param}? (s/n): ").strip().lower() != "s":
                return "Cancelación rechazada por el usuario humano."
        except EOFError:
            return "Cancelación rechazada por el usuario humano."
        return cancelar_pedido(param)
    if nombre == "consultar_stock": return consultar_stock(param)
    if nombre == "consultar_precio": return consultar_precio(param)
    return f"Herramienta '{nombre}' no reconocida."

# 3. Llamada al modelo con fallback simulado
def llamar_modelo(mensajes):
    if not API_KEY:
        q = mensajes[1]["content"].lower() if len(mensajes) > 1 else ""
        h = " ".join(m["content"].lower() for m in mensajes[1:])
        if any(w in q for w in ["zapatilla", "stock", "precio"]):
            if "unidades de" not in h: return "ACCION: consultar_stock:zapatillas"
            if "el precio de" not in h: return "ACCION: consultar_precio:zapatillas"
            return "FINAL: Hay 14 unidades de zapatillas en stock y su precio es de $85 USD."
        if any(w in q for w in ["cancela", "402"]):
            if "cancelado" not in h and "rechazada" not in h: return "ACCION: cancelar_pedido:402"
            return "FINAL: El trámite sobre el pedido 402 ha concluido."
        return "ACCION: consultar_stock:buscando_mas_informacion"

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    req = urllib.request.Request(
        URL,
        data=json.dumps({"model": MODELO, "messages": mensajes, "temperature": 0}).encode("utf-8"),
        headers=headers
    )
    ctx = ssl._create_unverified_context() if hasattr(ssl, "_create_unverified_context") else None
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()

# 4. Protocolo ReAct y bucle agéntico
SYSTEM_PROMPT = """Eres un agente servicial con acceso a tres herramientas:
- consultar_stock:producto
- consultar_precio:producto
- cancelar_pedido:id_pedido

Formato de respuesta:
- Para usar una herramienta responde: ACCION: HERRAMIENTA:parametro
- Para dar la respuesta final responde: FINAL: respuesta"""

MAX_VUELTAS, vuelta = 5, 0
modo = f"API ({MODELO})" if API_KEY else "MODO SIMULADO"
print(f"=== Agente iniciado en {modo} ===")
pregunta = input("\n¿Qué deseas consultar?: ").strip() or "Revisa si hay zapatillas y cuánto cuestan"
historial = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": pregunta}]

while True:
    vuelta += 1
    if vuelta >= MAX_VUELTAS:
        print("[PARADA] Tope alcanzado")
        break

    print(f"\n--- Vuelta {vuelta} ---")
    resp = llamar_modelo(historial)
    print(f"[Modelo]: {resp}")

    if resp.startswith("FINAL:"):
        print(f"\n[RESPUESTA FINAL]: {resp[6:].strip()}")
        break
    elif resp.startswith("ACCION:"):
        _, accion = resp.split("ACCION:", 1)
        partes = [p.strip() for p in accion.strip().split(":", 1)]
        nom, param = partes[0], partes[1] if len(partes) > 1 else ""
        obs = ejecutar_herramienta(nom, param)
        print(f"[Herramienta -> {nom}]: {obs}")
        historial.extend([{"role": "assistant", "content": resp}, {"role": "user", "content": f"OBSERVACION: {obs}"}])
    else:
        print(f"\n[RESPUESTA FINAL]: {resp}")
        break
