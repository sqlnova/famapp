# Revisión de Código y Fixes - FamApp

## Resumen Ejecutivo
Revisé el código de la app de organizador familiar y identifiqué un bug crítico en la lógica de creación de rutinas recurrentes. El fix implementado asegura que las rutinas se creen con la fecha de inicio correcta.

## Bug Principal Identificado y Arreglado

### 🐛 Fecha Incorrecta en Rutinas Recurrentes
**Archivo:** `server/web.py` (línea 803)  
**Severidad:** Alta

#### Problema
Cuando se creaba una rutina nueva (ej: "Psico Gaetano para jueves"), el sistema usaba **hoy** como fecha de inicio en lugar del próximo día que coincida con los días especificados.

**Ejemplo del bug:**
- Hoy: miércoles 15/04/2026
- Rutina creada: Psico Gaetano (jueves)
- **Comportamiento anterior:** Evento crearía para 15/04 (miércoles)
- **Comportamiento esperado:** Evento debería crear para 16/04 (jueves)

#### Causa Raíz
```python
# ANTES (incorrecto)
start_date = datetime.now(AR_TZ).strftime("%Y-%m-%d")  # Siempre hoy
```

Aunque la regla de recurrencia (RRULE) especificaba correctamente "BYDAY=TH" (jueves), la fecha de inicio estaba mal, lo que causaba inconsistencias.

#### Solución Implementada
Se creó la función `_get_next_occurrence_date()` que:
1. Toma los días seleccionados (ej: ["jueves"])
2. Convierte a códigos RRULE (ej: ["TH"])
3. Busca el próximo día coincidente a partir de hoy
4. Retorna la fecha correcta

```python
# DESPUÉS (correcto)
start_date = _get_next_occurrence_date(routine_obj["days"])

# Para jueves desde miércoles → retorna 2026-04-16
# Para miércoles desde miércoles → retorna 2026-04-15 (hoy)
# Para lunes desde miércoles → retorna 2026-04-20
```

## Validaciones Agregadas

### ✅ Validación de Días Seleccionados
**Archivo:** `server/web.py` (línea 756)

Se agregó validación para rechazar rutinas sin días seleccionados:
```python
if not days:
    raise HTTPException(status_code=400, detail="Debe seleccionar al menos un día de la semana")
```

### ✅ Validación de Horarios
Se agregó validación para asegurar que nueva rutina tenga al menos una hora (ida o vuelta):
```python
if is_new and not (payload.get("outbound_time") or payload.get("return_time")):
    raise HTTPException(status_code=400, detail="Debe especificar hora de ida o vuelta")
```

## Cambios Realizados

| Archivo | Cambios |
|---------|---------|
| `server/web.py` | ✅ Agregada función `_get_next_occurrence_date()` |
| `server/web.py` | ✅ Actualizado endpoint `POST /api/routines` con validaciones |
| `server/web.py` | ✅ Arreglado cálculo de `start_date` en creación de rutinas |

## Testing Manual

La lógica fue validada con casos de prueba:

```python
# Hoy: miércoles 15/04/2026

_get_next_occurrence_date(['jueves'])        # → 2026-04-16 ✓
_get_next_occurrence_date(['miercoles'])     # → 2026-04-15 ✓
_get_next_occurrence_date(['lun'])           # → 2026-04-20 ✓
_get_next_occurrence_date([])                # → 2026-04-15 (fallback) ✓
```

## Recomendaciones Adicionales

### 1. Sincronización de Rutinas Existentes
El fix aplica a nuevas rutinas. Las rutinas creadas antes del fix pueden tener eventos en fechas incorrectas. **Recomendación:** Eliminar y recrear las rutinas problemáticas, o agregar una migración para corregir las existentes.

### 2. Mejorar UI de Rutinas
Sugerencias para mejorar la interfaz:
- Mostrar claramente "Próxima ocurrencia: 16/04 (jueves)"
- Agregar vista de preview de primeros 4 eventos que se crearán
- Validación en tiempo real en el frontend

### 3. Logging Mejorado
Agregar logging cuando se crean rutinas:
```python
logger.info("routine_created_with_events", 
    routine_id=routine_obj["id"],
    title=routine_obj["title"],
    days=routine_obj["days"],
    first_event_date=start_date)
```

### 4. Considerar Tzinfo en Comparaciones
El código ya usa `AR_TZ = pytz.timezone("America/Argentina/Buenos_Aires")` correctamente, pero es importante mantener esto consistente en toda la app.

### 5. Cobertura de Tests
El archivo `tests/test_web_tasks_fallback.py` podría beneficiarse de:
- Tests unitarios para `_get_next_occurrence_date()`
- Tests de integración para la API POST /api/routines
- Tests de validación de errores HTTP 400

## Flujo de Trabajo Actual (post-fix)

```
Usuario crea rutina "Psico Gaetano"
    ↓
Selecciona: Días=[jueves], Hora ida=18:00, Responsable=Julieta
    ↓
POST /api/routines
    ↓
Validación: ✓ días, ✓ horarios
    ↓
Cálculo: next_occurrence("jueves") → 2026-04-16
    ↓
Crea 2 eventos recurrentes:
  • "Llevar a Gaetano al Psicopedagoga" - 18:00 (responsable: Julieta)
  • "Buscar a Gaetano del Psicopedagoga" - 18:50 (responsable: Mauro)
    ↓
RRULE: FREQ=WEEKLY;BYDAY=TH;UNTIL=2026-12-31
    ↓
Usuario ve en calendario a partir del 16/04 ✓
```

## Conclusión

El sistema está arquitecturalmente bien diseñado con agentes especializados y fallbacks robustos. El bug principal ha sido corregido y se han agregado validaciones defensivas. La app está lista para uso en producción para rutinas, aunque se recomienda testing adicional en la interfaz web antes de lanzamiento completo.

---
**Fecha de revisión:** 2026-04-15  
**Branch:** `claude/family-calendar-app-MA00R`  
**Commit:** ca67593 - "Fix: Correct routine start date calculation and add input validation"
