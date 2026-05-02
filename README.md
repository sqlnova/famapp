# FamApp

Sistema multi-agente de logística familiar.  
Recibe mensajes de WhatsApp, entiende la intención y actúa: agenda eventos, calcula tiempos de viaje reales y gestiona la lista de compras.

## Arquitectura

```
WhatsApp → Twilio Webhook → FastAPI
                               │
                         Intake Agent (LangGraph)
                         ┌─────┴──────────────────────────┐
                    Schedule Agent   Logistics Agent   Shopping Agent
                    (Google Cal)     (Google Maps)     (Supabase)
                         └───────────────────────────────-┘
                               │
                         WhatsApp push (Twilio)
```

### Agentes

| Agente | Estado | Descripción |
|--------|--------|-------------|
| **Intake** | ✅ Implementado | Recibe mensajes, clasifica intención con LLM (GPT-4o-mini), extrae entidades y rutea |
| **Shopping** | ✅ Básico | Agrega y lista items en Supabase |
| **Schedule** | 🟡 En evolución | Crea, modifica y elimina eventos en Google Calendar (incluye soporte para eventos recurrentes) |
| **Logistics** | 🔜 Stub | Calcula tiempo de viaje real con Maps y manda alertas proactivas |

## Stack

- **Python 3.11+**
- **LangGraph** – orquestación de agentes
- **FastAPI + Uvicorn** – servidor webhook
- **Twilio** – WhatsApp in/out
- **OpenAI GPT-4o-mini** – LLM para el Intake Agent
- **Supabase (PostgreSQL)** – persistencia
- **Google Calendar API** – calendario familiar
- **Google Maps Directions API** – tiempos de viaje con tráfico real

## Setup rápido

### 1. Clonar y crear entorno

```bash
git clone https://github.com/sqlnova/famapp
cd famapp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Variables de entorno

```bash
cp .env.example .env
# Editar .env con tus keys
```

### 3. Base de datos (Supabase)

Ejecutar `db/migrations/001_initial.sql` en el SQL editor de tu proyecto Supabase.

### 4. Google APIs

1. Crear proyecto en Google Cloud Console
2. Habilitar Calendar API y Maps Directions API
3. Descargar `credentials.json` → `credentials/google_credentials.json`
4. Primera vez: correr el flujo OAuth2 para generar `credentials/google_token.json`

### 5. Twilio WhatsApp

1. Crear cuenta Twilio y activar WhatsApp Sandbox (o número dedicado)
2. Configurar el webhook apuntando a: `https://tu-dominio.com/webhook/whatsapp`
3. Para desarrollo local usar ngrok: `ngrok http 8000`

### 6. Correr

```bash
python main.py
```

## Tests

```bash
pytest tests/ -v
```

## Estructura del proyecto

```
famapp/
├── agents/
│   ├── intake/          # LangGraph graph – clasificación y ruteo
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   ├── state.py
│   │   └── tools.py
│   ├── schedule/        # Google Calendar (stub)
│   ├── logistics/       # Google Maps + alertas proactivas (stub)
│   └── shopping/        # Lista de compras Supabase
├── core/
│   ├── config.py        # Settings con pydantic-settings
│   ├── models.py        # Modelos Pydantic compartidos
│   ├── supabase_client.py
│   └── whatsapp.py      # Twilio wrapper
├── db/
│   └── migrations/
│       └── 001_initial.sql
├── server/
│   └── webhook.py       # FastAPI app
├── tests/
│   └── test_intake.py
├── main.py
├── requirements.txt
└── .env.example
```

## Próximos pasos

- [ ] Implementar Schedule Agent con Google Calendar API
- [ ] Implementar Logistics Agent con Google Maps + alertas cron
- [ ] APScheduler para polling proactivo de eventos
- [ ] Soporte multimedia (fotos de tickets, etc.)


## Web privada (MVP)

La app web autenticada está en `/app` y usa Supabase Auth para login.

```bash
python main.py
# abrir http://localhost:8000/app
```

Módulos incluidos:
- Inicio (resumen diario accionable)
- Agenda (Hoy/Semana/Mes)
- Compras (pendientes/comprados + alta rápida)
- Rutinas familiares (crear/editar)
- Más/Configuración (familia + lugares)

## Mobile-first captura inteligente

### Backend
1. Ejecutar migraciones nuevas (`db/migrations/014_mobile_capture.sql`).
2. Nuevos endpoints autenticados en `/app/api/captures`:
   - `POST /api/captures`
   - `GET /api/captures`
   - `GET /api/captures/:id`
   - `POST /api/captures/:id/process`
   - `POST /api/captures/:id/confirm`
   - `POST /api/captures/:id/discard`
3. Registro de push token: `POST /api/push/register`.

### Mobile (Expo)
```bash
cd mobile
npm install
EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start
```

### Variables de entorno nuevas
- `OPENAI_API_KEY`
- `APP_TIMEZONE=America/Argentina/Buenos_Aires`
- `EXPO_PUBLIC_API_URL`

### OpenAI Capture Agent
`core/capture_agent.py` implementa extracción estructurada (eventos/tareas/recordatorios) con `structured_output` de LangChain/OpenAI y fallback heurístico.

### Push notifications
Se deja preparado:
- storage de `push_tokens`
- tabla `capture_reminders`
- generación de reminders al confirmar capturas

### Twilio desacoplado
Twilio se mantiene para webhook de WhatsApp, pero captura inteligente corre por API web/mobile sin depender del canal WhatsApp.
