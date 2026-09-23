import sqlite3
from pathlib import Path

CAMINHO = Path(__file__).parent / "ponte_cetec.db"

SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS areas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL UNIQUE,
    sigla     TEXT,
    curso     TEXT,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS docentes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    area_id     INTEGER REFERENCES areas(id),
    email       TEXT,
    foto_url    TEXT,
    lattes_url  TEXT,
    orcid       TEXT,
    openalex_id TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS publicacoes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    docente_id     INTEGER NOT NULL REFERENCES docentes(id) ON DELETE CASCADE,
    titulo         TEXT NOT NULL,
    resumo         TEXT,
    ano            INTEGER,
    palavras_chave TEXT,  -- lista em JSON
    fonte          TEXT   -- ex.: openalex, scholar
);

CREATE TABLE IF NOT EXISTS perfis (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    docente_id   INTEGER REFERENCES docentes(id) ON DELETE CASCADE,
    area_id      INTEGER REFERENCES areas(id) ON DELETE CASCADE,
    resumo       TEXT,
    competencias TEXT,  -- lista em JSON
    eixos        TEXT,  -- lista em JSON
    tipos_dor    TEXT,  -- lista em JSON
    data_geracao TEXT DEFAULT CURRENT_TIMESTAMP,
    CHECK (docente_id IS NOT NULL OR area_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_docentes_area ON docentes(area_id);
CREATE INDEX IF NOT EXISTS idx_publicacoes_docente ON publicacoes(docente_id);
"""

with sqlite3.connect(CAMINHO) as conn:
    conn.executescript(SQL)

print(f"Banco criado em {CAMINHO}")