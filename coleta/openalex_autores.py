"""Vincula cada docente do banco aos seus perfis de autor no OpenAlex.

O OpenAlex às vezes divide a mesma pessoa em vários perfis, então um docente
pode ter mais de um ID. Por isso os vínculos ficam na tabela docente_openalex,
com uma linha por perfil.

Status de cada vínculo:
    vinculado  nome inteiro, primeiro nome por extenso e perfil com afiliação UFRB
    conferir   nome compatível, mas fora da UFRB ou abreviado/parcial: revisar à mão
    rejeitado  marcado à mão na revisão; o script nunca altera um status já gravado

Uso:
    python coleta/openalex_autores.py            # só docentes ainda não buscados
    python coleta/openalex_autores.py --refazer  # busca todos de novo
"""

import os
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")

API_KEY = os.getenv("OPENALEX_KEY")
UFRB_ID = "I129192303"
URL_AUTORES = "https://api.openalex.org/authors"

ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"
ARQ_REVISAO = RAIZ / "dados" / "openalex_vinculos.csv"

# Palavras ignoradas na comparação de nomes
SUFIXOS = {"filho", "junior", "jr", "neto", "sobrinho"}
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}

if not API_KEY:
    raise RuntimeError("OPENALEX_KEY não encontrada. Confira o arquivo .env na raiz do projeto.")


# ---------------------------------------------------------------------------
# Comparação de nomes
# ---------------------------------------------------------------------------
def palavras(texto):
    """Lista de palavras em minúsculas, sem acento e sem pontuação."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", " ", sem_acento.lower()).split()


def significativas(nome):
    """Palavras do nome, sem partículas (de, da...) e sem sufixos (Filho, Junior...)."""
    return [p for p in palavras(nome) if p not in PARTICULAS and p not in SUFIXOS]


def casa(p, d):
    """A palavra do candidato casa com a do docente se for igual ou a inicial dela."""
    return p == d or (len(p) == 1 and d.startswith(p))


def compativel(nome_candidato, nome_docente):
    """As palavras do candidato aparecem, na mesma ordem, no nome do docente."""
    do_docente = significativas(nome_docente)
    do_candidato = significativas(nome_candidato)
    if len(do_candidato) < 2 or do_candidato[-1] != do_docente[-1]:
        return False                      # sobrenome final tem que bater
    pos = 0
    for p in do_candidato:
        while pos < len(do_docente) and not casa(p, do_docente[pos]):
            pos += 1
        if pos == len(do_docente):
            return False                  # sobrou palavra sem correspondência
        pos += 1
    return True


def nome_inteiro(nome_candidato, nome_docente):
    """Verdadeiro se o candidato traz todas as palavras do docente (por extenso ou inicial)."""
    return len(significativas(nome_candidato)) >= len(significativas(nome_docente))


def nome_curto(nome):
    """Primeiro nome e último sobrenome: "Denis Rinaldi Petrucci" -> "denis petrucci"."""
    partes = significativas(nome)
    return f"{partes[0]} {partes[-1]}"


# ---------------------------------------------------------------------------
# Busca no OpenAlex
# ---------------------------------------------------------------------------
def buscar_autores(texto, na_ufrb):
    """Procura autores pelo texto; com na_ufrb=True, só quem já teve vínculo com a UFRB."""
    params = {
        "search": texto,
        "select": "id,display_name,orcid,works_count,last_known_institutions",
        "per_page": 25,
        "api_key": API_KEY,
    }
    if na_ufrb:
        params["filter"] = f"affiliations.institution.id:{UFRB_ID}"

    resp = requests.get(URL_AUTORES, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(0.2)  # pausa curta entre as chamadas
    return resp.json()["results"]


def candidatos_do_docente(nome):
    """Devolve {id: (candidato, na_ufrb)} com os perfis de nome compatível com o docente."""
    buscas = [
        (nome, True),               # nome completo, na UFRB
        (nome_curto(nome), True),   # nome curto, na UFRB
        (nome, False),              # nome completo, sem filtro
    ]
    achados = {}
    for texto, na_ufrb in buscas:
        for c in buscar_autores(texto, na_ufrb):
            if c["id"] in achados:
                continue  # já apareceu antes (as buscas da UFRB vêm primeiro)
            if compativel(c.get("display_name") or "", nome):
                achados[c["id"]] = (c, na_ufrb)
    return achados


def classificar(candidato, nome, na_ufrb):
    """Decide com que segurança o perfil corresponde ao docente."""
    nome_openalex = candidato["display_name"]
    inteiro = nome_inteiro(nome_openalex, nome)
    primeiro_por_extenso = significativas(nome_openalex)[0] == significativas(nome)[0]
    if na_ufrb and inteiro and primeiro_por_extenso:
        return "vinculado"
    return "conferir"


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
def criar_tabelas(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS docente_openalex (
            docente_id    INTEGER NOT NULL REFERENCES docentes(id),
            openalex_id   TEXT    NOT NULL,
            status        TEXT    NOT NULL,   -- vinculado | conferir | rejeitado
            nome_openalex TEXT,
            na_ufrb       INTEGER NOT NULL,   -- 1 = perfil com afiliação UFRB
            nome_inteiro  INTEGER NOT NULL,   -- 1 = traz todas as palavras do nome
            publicacoes   INTEGER,
            instituicao   TEXT,
            PRIMARY KEY (docente_id, openalex_id)
        );
        CREATE TABLE IF NOT EXISTS openalex_busca (
            docente_id INTEGER PRIMARY KEY REFERENCES docentes(id),
            buscado_em TEXT NOT NULL
        );
    """)


def gravar_vinculo(conn, docente_id, nome, candidato, na_ufrb):
    """Grava o perfil. Se ele já existe, atualiza os dados mas preserva o status."""
    status = classificar(candidato, nome, na_ufrb)
    instituicoes = candidato.get("last_known_institutions") or []
    conn.execute(
        """
        INSERT INTO docente_openalex
            (docente_id, openalex_id, status, nome_openalex, na_ufrb, nome_inteiro, publicacoes, instituicao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(docente_id, openalex_id) DO UPDATE SET
            nome_openalex = excluded.nome_openalex,
            publicacoes   = excluded.publicacoes,
            instituicao   = excluded.instituicao
        """,
        (
            docente_id,
            candidato["id"].rsplit("/", 1)[-1],  # fica só o A123...
            status,
            candidato["display_name"],
            int(na_ufrb),
            int(nome_inteiro(candidato["display_name"], nome)),
            candidato["works_count"],
            instituicoes[0]["display_name"] if instituicoes else None,
        ),
    )

    # ORCID só é aproveitado de perfil confiável, e sem sobrescrever um já existente
    orcid = (candidato.get("orcid") or "").rsplit("/", 1)[-1] or None
    if status == "vinculado" and orcid:
        conn.execute("UPDATE docentes SET orcid = COALESCE(orcid, ?) WHERE id = ?", (orcid, docente_id))


SQL_PENDENTES = """
    SELECT d.id, d.nome
    FROM docentes d
    LEFT JOIN openalex_busca b ON b.docente_id = d.id
    WHERE b.docente_id IS NULL
"""

SQL_REVISAO = """
    SELECT d.id AS docente_id, d.nome,
           COALESCE(v.status, 'não encontrado') AS status,
           v.nome_openalex, v.openalex_id, v.na_ufrb, v.nome_inteiro, v.publicacoes, v.instituicao
    FROM docentes d
    LEFT JOIN docente_openalex v ON v.docente_id = d.id
    ORDER BY d.id, v.status DESC, v.publicacoes DESC
"""

# Situação de cada docente: a melhor entre os perfis dele
SQL_RESUMO = """
    SELECT CASE
               WHEN SUM(v.status = 'vinculado') > 0 THEN 'vinculado'
               WHEN SUM(v.status = 'conferir') > 0 THEN 'conferir'
               ELSE 'não encontrado'
           END AS situacao
    FROM docentes d
    LEFT JOIN docente_openalex v ON v.docente_id = d.id
    GROUP BY d.id
"""


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main():
    refazer = "--refazer" in sys.argv

    # sqlite3.connect cria um banco vazio se o arquivo não existir; melhor parar antes
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(
            f"Banco não encontrado ou vazio: {ARQ_BANCO}\n"
            "Rode antes: python dados/criar_banco.py  e  python coleta/coleta_docentes.py"
        )

    with sqlite3.connect(ARQ_BANCO) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'docentes'"
        ).fetchone()[0]
        if not total or not conn.execute("SELECT COUNT(*) FROM docentes").fetchone()[0]:
            raise SystemExit("A tabela docentes não existe ou está vazia. Rode a coleta de docentes antes.")

        criar_tabelas(conn)

        if refazer:
            docentes = conn.execute("SELECT id, nome FROM docentes").fetchall()
        else:
            docentes = conn.execute(SQL_PENDENTES).fetchall()
        print(f"{len(docentes)} docentes para buscar no OpenAlex.")

        for docente_id, nome in docentes:
            achados = candidatos_do_docente(nome)
            for candidato, na_ufrb in achados.values():
                gravar_vinculo(conn, docente_id, nome, candidato, na_ufrb)

            conn.execute(
                "INSERT OR REPLACE INTO openalex_busca (docente_id, buscado_em) VALUES (?, date('now'))",
                (docente_id,),
            )
            conn.commit()  # salva a cada docente: se a API cair, o que já foi feito fica
            n = len(achados)
            print(f"  {n} {'perfil' if n == 1 else 'perfis'}  {nome}")

        revisao = pd.read_sql_query(SQL_REVISAO, conn)
        resumo = pd.read_sql_query(SQL_RESUMO, conn)

    revisao.to_csv(ARQ_REVISAO, index=False, encoding="utf-8-sig")

    print()
    print(resumo["situacao"].value_counts().to_string())
    print(f"\nRevisão salva em {ARQ_REVISAO.name}")


if __name__ == "__main__":
    main()