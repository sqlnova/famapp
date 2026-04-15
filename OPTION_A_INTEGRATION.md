# Integración: Sugerencias de Tareas en Eventos (Opción A)

## 🎯 Qué se Implementó

Se integró completamente el sistema de sugerencias inteligentes de tareas directamente en el flujo de edición de eventos. Ahora, cuando un usuario edita un evento, aparece automáticamente un modal con tareas sugeridas que puede crear con un click.

## 📱 Cómo Funciona (Flujo del Usuario)

### Paso 1: Usuario edita un evento
```
Usuario hace click en "Editar evento" en la agenda
→ Se abre formulario de edición
```

### Paso 2: Usuario guarda cambios
```
Usuario modifica evento "Cumpleaños de Gaetano"
→ Hace click en "Guardar"
```

### Paso 3: Sistema sugiere tareas automáticamente
```
La app automáticamente:
1. Guarda el evento en el calendario
2. Analiza título, ubicación y fecha
3. Genera sugerencias inteligentes
4. Muestra un modal bonito con opciones
```

### Paso 4: Usuario selecciona tareas
```
Modal muestra:
  ☐ Comprar regalo (Regalo para Cumpleaños de Gaetano)
  ☐ Preparar decoración (Globos, guirnaldas, etc.)
  ☐ Organizar comida/bebidas (Torta, snacks, bebidas)

Usuario selecciona las que quiere:
  ☑ Comprar regalo
  ☑ Organizar comida/bebidas
```

### Paso 5: Crear tareas automáticamente
```
Usuario hace click en "Crear 2 tarea(s)"
→ Las tareas se crean automáticamente
→ Se agregan a la sección "Tareas por miembro"
→ Modal se cierra
```

## 🎨 UI del Modal

El modal aparece como una lámina deslizable desde la parte inferior (iOS-style):

```
┌─────────────────────────────────────┐
│ Tareas sugeridas para este evento  ✕│
├─────────────────────────────────────┤
│ Selecciona las tareas que quieres  │
│ crear:                              │
│                                     │
│ ☐ Comprar regalo                   │
│   Regalo para Cumpleaños de...     │
│                                     │
│ ☐ Preparar decoración               │
│   Globos, guirnaldas, etc.         │
│                                     │
│ ☑ Organizar comida/bebidas          │
│   Torta, snacks, bebidas           │
│                                     │
├─────────────────────────────────────┤
│ [Cancelar]  [Crear 1 tarea(s)]    │
└─────────────────────────────────────┘
```

**Características:**
- ✨ Botón X para cerrar
- ☑️ Checkboxes para seleccionar
- 📝 Descripción de cada tarea
- 🔢 Contador en vivo: "Crear X tarea(s)"
- 🚫 Botón de crear deshabilitado hasta seleccionar algo

## 🔧 Cambios Técnicos

### Estado Nueva (app.html)
```javascript
showTaskSuggestions: false,     // Controla visibilidad del modal
suggestedTasks: [],              // Lista de tareas sugeridas
selectedSuggestions: [],         // IDs de tareas seleccionadas (reservado)
```

### Funciones Nuevas

**1. `suggestTasksForEvent(eventPayload)`**
- Llama a `POST /api/tasks/suggestions`
- Recibe array de sugerencias del servidor
- Las mapea con propiedad `selected: false`
- Muestra el modal

**2. `toggleSuggestion(idx)`**
- Toggle checkbox de una sugerencia
- Actualiza `suggestedTasks[idx].selected`

**3. `createSuggestedTasks()`**
- Filtra solo las tareas seleccionadas
- Itera y crea cada una con `POST /api/tasks`
- Recarga los datos
- Cierra el modal

**4. `cancelSuggestions()`**
- Cierra el modal sin crear nada
- Limpia el estado

### Modificación a `saveEvent()`
```javascript
// Antes: solo guardaba el evento
await this.api(`/events/${id}`, { PUT })
this.showEventForm = false
await this.loadData()

// Ahora: también busca sugerencias
await this.api(`/events/${id}`, { PUT })
this.showEventForm = false
await this.suggestTasksForEvent(payload)  // ← NUEVO
// Si hay sugerencias, el modal se muestra
// Si no, recarga datos automáticamente
```

## 📊 Patrones Reconocidos

| Tipo de Evento | Sugerencias |
|---|---|
| **Cumpleaños** | Comprar regalo, Preparar decoración, Organizar comida/bebidas |
| **Viaje** | Preparar maleta, Confirmar vuelo/pasaje, Revisar pasaportes* |
| **Médico** | Confirmar turno, Preparar documentos médicos, Preparar lista de preguntas |
| **Escuela/Actividad** | Preparar mochila |
| **Reunión** | Preparar documentos |
| **Evento Social** | Confirmar asistencia, Preparar regalo/detalles |

*\*Solo aparece si falta más de 1 día para el viaje*

## 🚀 Cómo Probar

### 1. Editar un evento existente
```
1. Ir a "Agenda" → "Hoy"
2. Hacer click en un evento
3. Cambiar algo (ej: el título)
4. Click "Guardar"
5. → Debería aparecer el modal con sugerencias
```

### 2. Crear un evento con patrón obvio
```
1. (Si hay función de crear evento) Crear evento "Cumpleaños de alguien"
2. Guardar
3. → Modal sugiere: Comprar regalo, Decoración, Comida
```

### 3. Sin sugerencias
```
1. Editar evento "Ir al trabajo"
2. Guardar
3. → Modal NO aparece (no hay sugerencias)
4. → Se recarga la agenda normalmente
```

## 🔌 Endpoints Relacionados

### POST /api/tasks/suggestions
**Solicitud:**
```json
{
  "title": "Cumpleaños de Gaetano",
  "start": "2026-05-15T18:00:00Z",
  "end": "2026-05-15T19:00:00Z",
  "location": "Casa",
  "responsible_nickname": null,
  "children": ["Gaetano"]
}
```

**Respuesta:**
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

### POST /api/tasks (para crear tareas)
**Solicitud:**
```json
{
  "title": "Comprar regalo",
  "assignee": "",
  "due_date": "",
  "notes": "Regalo para Cumpleaños de Gaetano"
}
```

## ✨ Mejoras Futuras

1. **Precargar responsable** - Si el evento tiene `responsible_nickname`, asignar automáticamente la tarea a esa persona

2. **Due date automático** - Calcular fecha de vencimiento inteligente:
   - Para "Comprar regalo" en cumpleaños: 1 día antes
   - Para "Preparar maleta" en viaje: 2 días antes

3. **Confirmar antes de crear** - Mostrar un resumen de tareas que se van a crear:
   ```
   "¿Crear estas 2 tareas para el 15/05?"
   - Comprar regalo
   - Organizar comida/bebidas
   ```

4. **Historial de sugerencias** - Recordar qué tareas el usuario crea normalmente y priorizarlas

5. **Categorización** - Permitir elegir categoría o etiqueta para las tareas (urgente, normal, baja)

## 📋 Checklist de Funcionalidad

- ✅ Modal aparece al guardar evento
- ✅ Checkboxes funcionan correctamente
- ✅ Contador de tareas en vivo
- ✅ Botón crear deshabilitado hasta seleccionar
- ✅ Tareas se crean correctamente
- ✅ Modal se cierra después de crear
- ✅ Datos se recargan automáticamente
- ✅ Botón Cancelar funciona
- ✅ Si no hay sugerencias, no aparece modal

## 🐛 Posibles Mejoras

Si encuentras problemas:
1. **Las sugerencias no aparecen**: Verificar que el endpoint `/api/tasks/suggestions` esté funcionando
2. **Modal no se cierra**: Revisar que `createSuggestedTasks()` se ejecute completa
3. **Tareas no se crean**: Verificar permiso de usuario y token de autenticación

---

**Estado:** ✅ Completamente integrado y funcional  
**Branch:** `claude/family-calendar-app-MA00R`  
**Última actualización:** 2026-04-15
