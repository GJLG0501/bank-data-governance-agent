-- Se ejecuta en POSTGRES_DB al inicializar un volumen vacio.
-- Esta etapa solo habilita pgvector; no crea tablas ni carga datos.
CREATE EXTENSION IF NOT EXISTS vector;
