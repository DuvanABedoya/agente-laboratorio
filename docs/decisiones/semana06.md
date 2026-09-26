# Decisiones de arquitectura: El agente del laboratorio de cómputo

**Equipo:** [Nombre del equipo] — Duvan Andrés Bedoya Rengifo  
**Ubicación del script:** `scripts/agente_laboratorio.py`  
**Proveedor y modelo usados en las pruebas:** Google Gemini, `gemini-3.5-flash-lite` (endpoint compatible con OpenAI)

---

## 1. Forma del sistema

- **Elección:** Agente autónomo con bucle ReAct.
- **Justificación técnica:**
  Las solicitudes que llegan al laboratorio no tienen un camino fijo. El siguiente paso depende de lo que el sistema vaya encontrando:
  - Para **cancelar**, el usuario da el código del estudiante (E-101), pero la herramienta de cancelación necesita el `id_reserva` (RES-402). El agente tiene que consultar primero, leer la observación y solo entonces decidir la cancelación. Si el estudiante no tuviera reserva, el camino termina ahí.
  - Una **consulta compuesta** ("puestos libres y hasta qué hora abre") mezcla un dato que exige herramienta (disponibilidad) con uno que ya está en las reglas (horario). El modelo decide qué parte consulta y qué parte responde de su contexto.
  - Una solicitud **fuera de horario** (22:00) no debe tocar ninguna herramienta: se responde directo.

  Un **workflow** determinista obligaría a escribir a mano cada ramificación de un lenguaje natural abierto. Un **chat** simple no tiene acceso al estado del laboratorio, así que inventaría puestos. El agente combina las dos cosas: decide el camino y trae el dato real con las herramientas.

---

## 2. El Contexto y las Instrucciones (System Prompt)

Texto exacto del `SYSTEM_PROMPT` implementado en el script (las franjas se insertan desde la constante `FRANJAS_VALIDAS`, para que prompt y código no se contradigan):

```text
Eres el agente de operaciones del laboratorio de cómputo de la universidad.
Atiendes consultas sobre los 20 puestos (P-01 a P-20) y sus reservas.

REGLAS DURAS DE NEGOCIO:
1. Horario estricto: el laboratorio abre a las 06:00 y cierra a las 20:00, en franjas fijas de 2 horas:
   06:00-08:00, 08:00-10:00, 10:00-12:00, 12:00-14:00, 14:00-16:00, 16:00-18:00, 18:00-20:00. Fuera de ese horario el laboratorio está cerrado.
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
Después de cada ACCION recibirás una OBSERVACION con el resultado. Responde en español.
```

**Explicación de reglas y restricciones:**

- **Rol:** la primera línea fija la identidad (agente de operaciones del laboratorio) y el alcance (20 puestos y sus reservas), para que no responda temas ajenos.
- **Horario 06:00 a 20:00:** se da la lista completa de franjas y no solo "de 6 a 8". Así el modelo puede rechazar las 22:00 sin consultar nada (Misión 3) y responder "hasta qué hora abre" desde su contexto (Misión 1).
- **1 puesto por estudiante:** queda como regla dura del negocio. Hoy no hay herramienta para crear reservas, pero la regla ya está escrita para cuando se agregue en la semana 7.
- **Cancelación:** la regla 3 amarra la autorización a la herramienta. El modelo no puede "dar por cancelada" una reserva por su cuenta, y si el operador rechaza debe decir que la reserva sigue activa (Misión 2A).
- **Herramientas cerradas:** se nombran las tres con un ejemplo de uso cada una, se explica el orden consulta → cancelación y se prohíbe explícitamente inventar herramientas.
- **Protocolo ReAct:** una sola línea por vuelta con `ACCION:` o `FINAL:`. Esto simplifica el parseo y evita que el modelo mezcle razonamiento con la acción.

---

## 3. Las herramientas y el mapa de autonomía

| Herramienta / Función | Parámetros y retorno | Nivel de autonomía (`sugiere` / `ejecuta con aprobación` / `ejecuta y reporta`) | Peor escenario si alucina sin supervisión |
|---|---|---|---|
| `consultar_disponibilidad` | `franja: str` -> puestos libres o aviso de cerrado | `ejecuta y reporta` | Entrega de datos desactualizados; bajo riesgo y totalmente reversible. |
| `consultar_reserva` | `codigo_estudiante: str` -> puesto, franja e id de reserva | `ejecuta y reporta` | Lectura de estado; riesgo bajo. |
| `cancelar_reserva` | `id_reserva: str` -> resultado de cancelación | `ejecuta con aprobación` (Human-in-the-loop) | Pérdida definitiva de la reserva de un estudiante, conflicto en mostrador presencial e interrupción del servicio. |

**Detalles de implementación:**

- `consultar_disponibilidad` valida la franja contra `FRANJAS_VALIDAS` **en el código**, no solo en el prompt. Si el modelo pidiera `22:00-24:00`, la herramienta igual responde que el laboratorio está cerrado y detalla el horario. Es una doble barrera.
- Los parámetros se limpian antes de usarse: se quitan espacios, comillas y backticks, y los códigos se pasan a mayúsculas. Así un `e-101` o un `` `RES-402` `` del modelo no rompe la búsqueda.
- Si el modelo llama una herramienta que no existe, el despachador no falla: le devuelve como observación la lista de las tres herramientas válidas.

**Mecanismo de Human-in-the-loop:**

El despachador `ejecutar_herramienta` intercepta `cancelar_reserva` antes de tocar el estado:

1. Verifica que el `id_reserva` exista. Si no existe, responde "No existe una reserva activa con id …" y ni siquiera molesta al operador.
2. Pregunta por consola: `[CONTROL-HUMANO] ¿Autorizas cancelar la reserva RES-402? (s/n):`
3. Si el operador escribe **`s`**, borra la reserva de `RESERVAS`, devuelve el puesto a `DISPONIBILIDAD` en su franja y retorna `Reserva RES-402 cancelada exitosamente y puesto liberado.`
4. **Cualquier otra respuesta** (`n`, Enter vacío o fin de entrada) aborta la operación y retorna `Cancelación de reserva RES-402 rechazada por el operador humano.` El valor por defecto es no cancelar: el sistema falla hacia el lado seguro.

El modelo nunca ejecuta la cancelación. Solo la *solicita*, y la decisión la toma una persona.

---

## 4. Criterio de parada y seguridad

- **Límite máximo de vueltas (`MAX_VUELTAS`):** 5 vueltas, con `for vuelta in range(1, MAX_VUELTAS + 1)`.
- **Condición de éxito:** detección de `FINAL:`. El agente extrae la respuesta, la imprime como `[RESPUESTA FINAL]` y sale con `break`.
- **Manejo del tope de iteraciones:** si se agotan las 5 vueltas sin `FINAL:`, el `else` del `for` imprime `[PARADA] Tope alcanzado` y termina.
- **Respuestas fuera de protocolo:** si el modelo no responde con `ACCION:` ni `FINAL:`, se le recuerda el formato. Ese recordatorio **consume una vuelta**, así que un modelo que se sale del protocolo en todas las vueltas también termina en el tope y no queda en un ciclo infinito.
- **Consideraciones de timeout:** toda llamada HTTP usa `urlopen(..., timeout=TIMEOUT_SEGUNDOS)`. Sin ese límite, si la API se degrada, el hilo queda bloqueado esperando indefinidamente. En un servidor eso agota los hilos disponibles y tumba el servicio para todos los usuarios. El tope de vueltas protege contra un modelo que no termina; el timeout protege contra una red que no responde. Se necesitan los dos.
  - **Decisión basada en medición:** empezamos con 10 segundos, como sugiere la guía, y en las pruebas **se dispararon varios timeouts**: el agente respondió correctamente `FINAL: No pude comunicarme con el modelo (The read operation timed out)` en lugar de colgarse. Medimos la latencia real de `gemini-3.5-flash-lite` y dio **entre 14 y 17 segundos por petición**, incluso para respuestas de una palabra. Por eso el timeout quedó en **30 segundos, con 1 reintento** para errores de red o 5xx (en una de las mediciones otro modelo de Gemini respondió `503 Service Unavailable`). Los errores 4xx (key o modelo inválido) no se reintentan, porque repetirlos no los arregla.
- **TLS:** se usa `ssl.create_default_context()`, que **verifica** el certificado del proveedor. El taller usaba `ssl._create_unverified_context()`, que desactiva esa verificación y expone la API key a un ataque de intermediario. Por eso lo cambiamos.
- **API key:** se lee de la variable de entorno `API_KEY` (o `GEMINI_API_KEY` como respaldo). Nunca queda escrita en el código ni en el repositorio.

---

## 5. Evidencia de ejecución (Trazas reales de terminal)

Ejecutadas contra la API real de Gemini (`gemini-3.5-flash-lite`). Las mismas trazas quedan en `docs/trazas/`.

### Misión 1: Consulta compuesta
```text
=== Agente del laboratorio iniciado en API (gemini-3.5-flash-lite) ===

¿Qué deseas consultar?: ¿Qué puestos hay libres para la franja de 10:00 a 12:00 y hasta qué hora abre el laboratorio?

--- Vuelta 1 ---
[Modelo]: ACCION: consultar_disponibilidad:10:00-12:00
[Herramienta -> consultar_disponibilidad]: Puestos libres en 10:00-12:00: P-01, P-02, P-03, P-05, P-06

--- Vuelta 2 ---
[Modelo]: FINAL: Los puestos libres para la franja de 10:00 a 12:00 son: P-01, P-02, P-03, P-05 y P-06. El laboratorio abre de 06:00 a 20:00 en horario estricto, por lo que su hora de cierre es a las 20:00.

[RESPUESTA FINAL]: Los puestos libres para la franja de 10:00 a 12:00 son: P-01, P-02, P-03, P-05 y P-06. El laboratorio abre de 06:00 a 20:00 en horario estricto, por lo que su hora de cierre es a las 20:00.
```

### Misión 2A: Cancelación con rechazo humano ('n')
```text
=== Agente del laboratorio iniciado en API (gemini-3.5-flash-lite) ===

¿Qué deseas consultar?: El estudiante E-101 necesita cancelar su reserva activa.

--- Vuelta 1 ---
[Modelo]: ACCION: consultar_reserva:E-101
[Herramienta -> consultar_reserva]: Estudiante E-101 tiene reservado el puesto P-04, franja 10:00-12:00, id de reserva RES-402

--- Vuelta 2 ---
[Modelo]: ACCION: cancelar_reserva:RES-402
[CONTROL-HUMANO] ¿Autorizas cancelar la reserva RES-402? (s/n): n
[Herramienta -> cancelar_reserva]: Cancelación de reserva RES-402 rechazada por el operador humano.

--- Vuelta 3 ---
[Modelo]: FINAL: La cancelación de tu reserva RES-402 fue rechazada por el operador humano, por lo que la reserva sigue activa.

[RESPUESTA FINAL]: La cancelación de tu reserva RES-402 fue rechazada por el operador humano, por lo que la reserva sigue activa.
```

### Misión 2B: Cancelación con aprobación humana ('s')
```text
=== Agente del laboratorio iniciado en API (gemini-3.5-flash-lite) ===

¿Qué deseas consultar?: El estudiante E-101 necesita cancelar su reserva activa.

--- Vuelta 1 ---
[Modelo]: ACCION: consultar_reserva:E-101
[Herramienta -> consultar_reserva]: Estudiante E-101 tiene reservado el puesto P-04, franja 10:00-12:00, id de reserva RES-402

--- Vuelta 2 ---
[Modelo]: ACCION: cancelar_reserva:RES-402
[CONTROL-HUMANO] ¿Autorizas cancelar la reserva RES-402? (s/n): s
[Herramienta -> cancelar_reserva]: Reserva RES-402 cancelada exitosamente y puesto liberado.

--- Vuelta 3 ---
[Modelo]: FINAL: La reserva RES-402 del estudiante E-101 ha sido cancelada exitosamente y el puesto P-04 ha sido liberado.

[RESPUESTA FINAL]: La reserva RES-402 del estudiante E-101 ha sido cancelada exitosamente y el puesto P-04 ha sido liberado.
```

### Misión 3: Regla de negocio y solicitud fuera de horario (22:00)
```text
=== Agente del laboratorio iniciado en API (gemini-3.5-flash-lite) ===

¿Qué deseas consultar?: Quiero reservar un puesto para hoy a las 10 de la noche (22:00).

--- Vuelta 1 ---
[Modelo]: FINAL: El laboratorio está cerrado a las 22:00. Nuestro horario de atención es de 06:00 a 20:00.

[RESPUESTA FINAL]: El laboratorio está cerrado a las 22:00. Nuestro horario de atención es de 06:00 a 20:00.
```

Resuelta en la Vuelta 1, sin llamar ninguna herramienta.

### Cómo reproducir

```powershell
$env:API_KEY = $env:GEMINI_API_KEY   # o la key de Groq (gsk_...)
python scripts/agente_laboratorio.py
```

Sin `API_KEY`, el script arranca en **MODO SIMULADO**: un modelo de reglas fijas que resuelve las mismas tres misiones sin conexión, útil para probar el bucle y el Human-in-the-loop sin gastar cuota.
