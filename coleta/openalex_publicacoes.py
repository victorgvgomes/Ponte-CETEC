"""Baixa do OpenAlex as publicações de cada perfil vinculado a um docente.

Lê os perfis com status "vinculado" na tabela docente_openalex e grava os
trabalhos na tabela publicacoes. Se um docente tem vários perfis, ou se o
script roda mais de uma vez, o mesmo trabalho não é duplicado.

Uso:
    python coleta/openalex_publicacoes.py            # só perfis ainda não baixados
    python coleta/openalex_publicacoes.py --refazer  # baixa todos de novo
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")

API_KEY = os.getenv("OPENALEX_KEY")
URL_TRABALHOS = "https://api.openalex.org/works"
ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"

CAMPOS = "id,doi,title,publication_year,type,language,abstract_inverted_index,topics,keywords"

if not API_KEY:
    raise RuntimeError("OPENALEX_KEY não encontrada. Confira o arquivo .env na raiz do projeto.")


# ---------------------------------------------------------------------------
# Busca no OpenAlex
# ---------------------------------------------------------------------------
def buscar_trabalhos(openalex_id):
    """Devolve todos os trabalhos de um perfil de autor, percorrendo as páginas."""
    params = {
        "filter": f"authorships.author.id:{openalex_id}",
        "select": CAMPOS,
        "per_page": 100,
        "cursor": "*",  # início da paginação
        "api_key": API_KEY,
    }
    trabalhos = []
    while params["cursor"]:
        resp = requests.get(URL_TRABALHOS, params=params, timeout=60)
        resp.raise_for_status()
        dados = resp.json()
        if not dados["results"]:
            break
        trabalhos.extend(dados["results"])
        params["cursor"] = dados["meta"].get("next_cursor")  # None na última página
        time.sleep(0.2)  # pausa curta entre as chamadas
    return trabalhos


def montar_resumo(indice):
    """Reconstrói o texto do resumo.

    O OpenAlex entrega o resumo como {palavra: [posições]}, por exemplo
    {"Este": [0], "estudo": [1, 5]}. Aqui as palavras voltam para a ordem original.
    """
    if not indice:
        return None
    posicoes = []
    for palavra, lista in indice.items():
        for pos in lista:
            posicoes.append((pos, palavra))
    return " ".join(palavra for _, palavra in sorted(posicoes))


def nomes(itens):
    """Lista de nomes (tópicos ou palavras-chave) em JSON, ou None se vazia."""
    lista = [i["display_name"] for i in itens or [] if i.get("display_name")]
    return json.dumps(lista, ensure_ascii=False) if lista else None


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
NOVAS_COLUNAS = {
    "publicacoes": {
        "openalex_id": "TEXT",  # W123..., identifica o trabalho
        "doi": "TEXT",
        "tipo": "TEXT",         # article, book-chapter, dissertation...
        "idioma": "TEXT",
        "topicos": "TEXT",      # lista em JSON
    },
    "docente_openalex": {
        "publicacoes_em": "TEXT",  # data em que os trabalhos do perfil foram baixados
    },
}


def preparar_banco(conn):
    """Acrescenta as colunas que faltam, sem apagar nada."""
    for tabela, colunas in NOVAS_COLUNAS.items():
        existentes = {linha[1] for linha in conn.execute(f"PRAGMA table_info({tabela})")}
        if not existentes:
            raise SystemExit(f"Tabela {tabela} não existe. Rode antes criar_banco.py e openalex_autores.py.")
        for coluna, tipo in colunas.items():
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")

    # impede que o mesmo trabalho seja gravado duas vezes para o mesmo docente
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_publicacoes_obra ON publicacoes(docente_id, openalex_id)"
    )


def gravar_trabalho(conn, docente_id, trabalho):
    """Grava o trabalho; se ele já existe para o docente, atualiza os dados."""
    conn.execute(
        """
        INSERT INTO publicacoes
            (docente_id, openalex_id, titulo, resumo, ano, doi, tipo, idioma, topicos, palavras_chave, fonte)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'openalex')
        ON CONFLICT(docente_id, openalex_id) DO UPDATE SET
            titulo = excluded.titulo,
            resumo = excluded.resumo,
            ano = excluded.ano,
            doi = excluded.doi,
            tipo = excluded.tipo,
            idioma = excluded.idioma,
            topicos = excluded.topicos,
            palavras_chave = excluded.palavras_chave
        """,
        (
            docente_id,
            trabalho["id"].rsplit("/", 1)[-1],  # fica só o W123...
            trabalho["title"],
            montar_resumo(trabalho.get("abstract_inverted_index")),
            trabalho.get("publication_year"),
            trabalho.get("doi"),
            trabalho.get("type"),
            trabalho.get("language"),
            nomes(trabalho.get("topics")),
            nomes(trabalho.get("keywords")),
        ),
    )


SQL_RESUMO = """
    SELECT COUNT(*)                         AS publicacoes,
           COUNT(resumo)                    AS com_resumo,
           COUNT(*) - COUNT(resumo)         AS sem_resumo,
           COUNT(DISTINCT docente_id)       AS docentes
    FROM publicacoes
    WHERE fonte = 'openalex'
"""


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main():
    refazer = "--refazer" in sys.argv

    # sqlite3.connect cria um banco vazio se o arquivo não existir; melhor parar antes
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")

    with sqlite3.connect(ARQ_BANCO) as conn:
        preparar_banco(conn)

        filtro = "" if refazer else "AND v.publicacoes_em IS NULL"
        perfis = conn.execute(
            f"""
            SELECT v.docente_id, v.openalex_id, d.nome
            FROM docente_openalex v
            JOIN docentes d ON d.id = v.docente_id
            WHERE v.status = 'vinculado' {filtro}
            ORDER BY v.docente_id
            """
        ).fetchall()
        print(f"{len(perfis)} perfis para baixar do OpenAlex.")

        for docente_id, openalex_id, nome in perfis:
            trabalhos = buscar_trabalhos(openalex_id)
            gravados = 0
            for trabalho in trabalhos:
                if not trabalho.get("title"):
                    continue  # sem título não há o que aproveitar
                gravar_trabalho(conn, docente_id, trabalho)
                gravados += 1

            conn.execute(
                "UPDATE docente_openalex SET publicacoes_em = date('now') WHERE docente_id = ? AND openalex_id = ?",
                (docente_id, openalex_id),
            )
            conn.commit()  # salva a cada perfil: se a API cair, o que já foi feito fica
            print(f"  {gravados:>4} {'trabalho ' if gravados == 1 else 'trabalhos'}  {openalex_id}  {nome}")

        total, com_resumo, sem_resumo, docentes = conn.execute(SQL_RESUMO).fetchone()

    print()
    print(f"Publicações no banco: {total}")
    print(f"  com resumo: {com_resumo}")
    print(f"  sem resumo: {sem_resumo}")
    print(f"Docentes com ao menos uma publicação: {docentes}")


if __name__ == "__main__":
    main()