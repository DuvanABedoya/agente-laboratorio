# Agente del laboratorio de cómputo

Ingeniería de Aplicaciones con IA · Universidad Cooperativa de Colombia · Semana 6

Agente autónomo en Python 3 puro (solo biblioteca estándar) que atiende las operaciones del laboratorio de cómputo: consulta puestos libres por franja, consulta reservas de estudiantes y cancela reservas con confirmación humana obligatoria.

## Contenido

| Ruta | Qué es |
|---|---|
| `scripts/agente_laboratorio.py` | El agente del reto: bucle ReAct, 3 herramientas, Human-in-the-loop, tope de 5 vueltas y timeout. |
| `docs/decisiones/semana06.md` | Documento de arquitectura: forma del sistema, System Prompt, mapa de autonomía, parada y trazas. |
| `docs/trazas/` | Salidas reales de consola de las misiones 1, 2A, 2B y 3. |
| `agente.py` | Agente del taller guiado (tienda deportiva), punto de partida del reto. |

## Cómo correrlo

```powershell
$env:API_KEY = "<tu key de Gemini o de Groq>"
python scripts/agente_laboratorio.py
```

- `PROVEEDOR=gemini` (por defecto) o `PROVEEDOR=groq`. Una key que empieza por `gsk_` usa Groq automáticamente.
- Sin `API_KEY` corre en **modo simulado**, sin conexión.
- No requiere `pip install`.
