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
| **Schedule** | 🔜 Stub | Crea/modifica eventos en Google Calendar |
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
