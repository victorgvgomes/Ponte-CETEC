"""Auditoria dos perfis vinculados: aponta trabalhos que destoam da área do docente.

NÃO altera o banco. Para cada perfil vinculado, busca no OpenAlex os trabalhos
com a área de conhecimento atribuída a cada um e sinaliza os que pertencem a um
domínio minoritário na produção do docente. Serve para achar perfis que misturam
trabalhos de homônimos.

O OpenAlex classifica cada trabalho em quatro domínios (Physical Sciences, Life
Sciences, Health Sciences, Social Sciences) e, dentro deles, em áreas.

Uso:  python coleta/openalex_auditoria.py
Saída: dados/openalex_auditoria.csv, uma linha por trabalho suspeito.
"""

import os
import sqlite3
import time
from collections import Counter
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
URL_TRABALHOS = "https://api.openalex.org/works"
ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"
ARQ_AUDITORIA = RAIZ / "dados" / "openalex_auditoria.csv"

# Um domínio é "minoritário" se reúne menos que esta fração dos trabalhos do docente
LIMITE_MINORITARIO = 0.30
# Com menos trabalhos classificados que isso, não há base para comparar
MINIMO_PARA_AUDITAR = 4

if not API_KEY:
    raise RuntimeError("OPENALEX_KEY não encontrada. Confira o arquivo .env na raiz do projeto.")


# ---------------------------------------------------------------------------
# Busca no OpenAlex
# ---------------------------------------------------------------------------
def buscar_trabalhos(openalex_id):
    """Trabalhos de um perfil, com o tópico principal (de onde vêm domínio e área)."""
    params = {
        "filter": f"authorships.author.id:{openalex_id}",
        "select": "id,title,publication_year,primary_topic",
        "per_page": 100,
        "cursor": "*",
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
        params["cursor"] = dados["meta"].get("next_cursor")
        time.sleep(0.2)
    return trabalhos


def dominio_e_area(trabalho):
    """Devolve (domínio, área) do trabalho, ou (None, None) se o OpenAlex não classificou."""
    topico = trabalho.get("primary_topic") or {}
    dominio = (topico.get("domain") or {}).get("display_name")
    area = (topico.get("field") or {}).get("display_name")
    return dominio, area


# ---------------------------------------------------------------------------
# Banco de dados (somente leitura)
# ---------------------------------------------------------------------------
def perfis_vinculados(conn):
    return conn.execute(
        """
        SELECT v.docente_id, d.nome, v.openalex_id
        FROM docente_openalex v
        JOIN docentes d ON d.id = v.docente_id
        WHERE v.status = 'vinculado'
        ORDER BY v.docente_id
        """
    ).fetchall()


def trabalhos_excluidos(conn):
    """Pares (docente, trabalho) já excluídos à mão; a tabela pode ainda não existir."""
    try:
        return set(conn.execute("SELECT docente_id, openalex_id FROM publicacoes_excluidas"))
    except sqlite3.OperationalError:
        return set()


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main():
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")

    with sqlite3.connect(ARQ_BANCO) as conn:
        perfis = perfis_vinculados(conn)
        excluidos = trabalhos_excluidos(conn)
    print(f"{len(perfis)} perfis vinculados para auditar.")

    # 1. Baixa os trabalhos de cada perfil e agrupa por docente
    por_docente = {}  # docente_id -> {"nome": ..., "trabalhos": {W: dados}}
    for docente_id, nome, perfil in perfis:
        docente = por_docente.setdefault(docente_id, {"nome": nome, "trabalhos": {}})
        for trabalho in buscar_trabalhos(perfil):
            trabalho_id = trabalho["id"].rsplit("/", 1)[-1]
            if (docente_id, trabalho_id) in excluidos or not trabalho.get("title"):
                continue
            dominio, area = dominio_e_area(trabalho)
            docente["trabalhos"].setdefault(trabalho_id, {
                "perfil": perfil,
                "ano": trabalho.get("publication_year"),
                "titulo": trabalho["title"],
                "dominio": dominio,
                "area": area,
            })
        print(f"  {perfil}  {nome}")

    # 2. Para cada docente, acha os domínios minoritários e lista os trabalhos neles
    suspeitos, sem_base = [], []
    for docente_id, docente in por_docente.items():
        classificados = [t for t in docente["trabalhos"].values() if t["dominio"]]
        if len(classificados) < MINIMO_PARA_AUDITAR:
            sem_base.append(docente["nome"])
            continue

        contagem = Counter(t["dominio"] for t in classificados)
        predominante = contagem.most_common(1)[0][0]
        for trabalho_id, t in docente["trabalhos"].items():
            if not t["dominio"] or t["dominio"] == predominante:
                continue
            fracao = contagem[t["dominio"]] / len(classificados)
            if fracao < LIMITE_MINORITARIO:
                suspeitos.append({
                    "docente_id": docente_id,
                    "nome": docente["nome"],
                    "dominio_predominante": predominante,
                    "perfil": t["perfil"],
                    "trabalho": trabalho_id,
                    "ano": t["ano"],
                    "dominio": t["dominio"],
                    "area": t["area"],
                    "fracao_do_dominio": round(fracao, 2),
                    "titulo": t["titulo"],
                })

    # 3. Relatório
    colunas = ["docente_id", "nome", "dominio_predominante", "perfil", "trabalho",
               "ano", "dominio", "area", "fracao_do_dominio", "titulo"]
    relatorio = pd.DataFrame(suspeitos, columns=colunas)
    relatorio.to_csv(ARQ_AUDITORIA, index=False, encoding="utf-8-sig")

    print()
    if relatorio.empty:
        print("Nenhum trabalho suspeito encontrado.")
    else:
        print(f"{len(relatorio)} trabalhos suspeitos, de {relatorio['docente_id'].nunique()} docentes:")
        resumo = relatorio.groupby(["docente_id", "nome"]).size().sort_values(ascending=False)
        for (docente_id, nome), quantidade in resumo.items():
            print(f"  {quantidade:>3}  docente {docente_id}  {nome}")
    print(f"\n{len(sem_base)} docentes com menos de {MINIMO_PARA_AUDITAR} trabalhos classificados não foram auditados.")
    print(f"Detalhes em {ARQ_AUDITORIA}")
    print("\nPara remover os que não forem do docente:")
    print("  python coleta/openalex_publicacoes.py --excluir ID_DO_DOCENTE W123 W456")


if __name__ == "__main__":
    main()