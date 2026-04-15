# Sistema de Sugerencias de Tareas Inteligentes

## Descripción General

Se ha implementado un motor de sugerencias de tareas que **analiza automáticamente los eventos del calendario** y sugiere tareas relacionadas para ayudar a la familia a prepararse.

## Cómo Funciona

### 1. Análisis de Patrones
El motor examina el **título, ubicación y fecha** del evento para identificar patrones:

| Patrón | Ejemplos de Eventos | Tareas Sugeridas |
|--------|-------------------|------------------|
| **Cumpleaños** | Cumpleaños de Gaetano, Cumple Mamá | • Comprar regalo<br>• Preparar decoración<br>• Organizar comida/bebidas |
| **Viajes** | Viaje a Mendoza, Vuelo a Buenos Aires, Terminal bus | • Preparar maleta<br>• Confirmar vuelo/pasaje<br>• Revisar pasaportes |
| **Médico** | Dentista, Revisación pediatra, Consulta doctor | • Confirmar turno<br>• Preparar documentos médicos<br>• Preparar lista de preguntas |
| **Escuela/Actividades** | Colegio, Fútbol, Natación, Gym | • Preparar mochila |
| **Reuniones** | Reunión trabajo, Conferencia | • Preparar documentos |
| **Eventos Sociales** | Fiesta, Cena, Almuerzo | • Confirmar asistencia<br>• Preparar regalo |

### 2. Endpoint API

**POST `/api/tasks/suggestions`**

Recibe un objeto de evento y devuelve sugerencias inteligentes.

```bash
curl -X POST /app/api/tasks/suggestions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Cumpleaños de Gaetano",
    "start": "2026-05-15T18:00:00",
    "location": "Casa",
    "children": ["Gaetano"]
  }'
```

**Response:**
```json
{
  "suggestions": [
    {
      "title": "Comprar regalo",
      "description": "Regalo para Cumpleaños de Gaetano"
    },
    {
      "title": "Preparar decoración",
      "description": "Globos, guirnaldas, etc."
    },
    {
      "title": "Organizar comida/bebidas",
      "description": "Torta, snacks, bebidas"
    }
  ]
}
```

## Integración en el Frontend

### Opción 1: Al Crear Evento (Recomendado)

Cuando el usuario cree un evento nuevo, se pueden mostrar las tareas sugeridas:

```javascript
// En app.html, después de crear un evento:
async function suggestTasksForEvent(event) {
  const response = await fetch('/app/api/tasks/suggestions', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${this.token}` },
    body: JSON.stringify(event)
  })
  const data = await response.json()
  // Mostrar en un modal: "¿Deseas crear estas tareas?"
  return data.suggestions
}
```

### Opción 2: En la Vista de Evento

Mostrar un botón "Sugerir tareas relacionadas" en cada evento que, al hacer clic, genere y agregue tareas automáticamente.

### Opción 3: Tareas "de hoy" Inteligentes

En la sección de "Tareas por miembro", mostrar tanto tareas manuales como sugeridas (sin permitir marcar como hecha las sugeridas hasta que se conviertan en tareas reales).

## Estructura del Código

```
agents/tasks/
├── __init__.py
└── suggestions.py
    ├── generate_task_suggestions(event: CalendarEvent)
    └── filter_duplicate_suggestions(suggestions)

server/web.py
└── POST /api/tasks/suggestions (nuevo endpoint)
```

## Futuros Mejoras

1. **Aprendizaje de Patrones**: Registrar qué tareas el usuario crea normalmente y refinar las sugerencias basadas en comportamiento histórico

2. **Priorización Temporal**: Sugerir tareas con timing inteligente (ej: "Comprar regalo" aparece 1 semana antes del cumpleaños)

3. **Integración con WhatsApp**: Cuando se agende un evento por WhatsApp, enviar directamente las tareas sugeridas para que la familia confirme

4. **Tareas Recurrentes**: Para eventos recurrentes (como "Colegio todos los días"), ofrecer crear tareas recurrentes automáticas (ej: "Preparar mochila" diariamente)

5. **Contexto de Ubicación**: Usar Google Maps para sugerir tareas adicionales (ej: si es un viaje de más de 4 horas, sugerir "Preparar snacks para el viaje")

6. **Templates Personalizables**: Permitir a las familias crear sus propios patrones de tareas ("Cuando hay evento de [palabra], siempre me recuerda que haga X")

## Ejemplos de Uso

### Ejemplo 1: Cumpleaños
```
Evento: "Cumpleaños de Isabella - 22/06/2026"
Sugerencias:
✓ Comprar regalo
✓ Preparar decoración  
✓ Organizar comida/bebidas

Usuario puede clickear cada una para crearlas como tareas reales asignadas a alguien.
```

### Ejemplo 2: Viaje
```
Evento: "Viaje a Córdoba - Salida 10/07/2026"
Sugerencias:
✓ Preparar maleta
✓ Confirmar vuelo/pasaje
✓ Revisar pasaportes (aparece porque falta > 1 día)

Las tareas se pueden asignar a diferentes personas según quién viaja.
```

### Ejemplo 3: Médico
```
Evento: "Dentista - Gaetano"
Sugerencias:
✓ Confirmar turno
✓ Preparar documentos médicos
✓ Preparar lista de preguntas

Útil para no olvidar nada importante en la cita.
```

## Testing

Para probar el endpoint sin integración frontend:

```bash
# Test con cumpleaños
curl -X POST http://localhost:8000/app/api/tasks/suggestions \
  -H "Authorization: Bearer <tu_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Cumpleaños de Gaetano",
    "start": "2026-05-15T18:00:00Z",
    "end": "2026-05-15T19:00:00Z"
  }'

# Test con viaje
curl -X POST http://localhost:8000/app/api/tasks/suggestions \
  -H "Authorization: Bearer <tu_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Vuelo a Buenos Aires",
    "start": "2026-05-20T20:00:00Z",
    "end": "2026-05-20T21:00:00Z",
    "location": "Aeropuerto Internacional"
  }'
```

---
**Estado:** ✅ Motor implementado, listo para integración frontend  
**Branch:** `claude/family-calendar-app-MA00R`
