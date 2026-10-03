"""Vincula cada docente do banco ao seu cadastro de autor no OpenAlex."""

import os
import sqlite3
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

if not API_KEY:
    raise RuntimeError("OPENALEX_KEY não encontrada. Confira o arquivo .env na raiz do projeto.")


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------
def normalizar(nome):
    """Tira acentos, deixa minúsculo e remove espaços extras, para comparar nomes."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def buscar_autores(nome):
    """Procura autores com esse nome que já tiveram vínculo com a UFRB."""
    params = {
        "search": nome,
        "filter": f"affiliations.institution.id:{UFRB_ID}",
        "select": "id,display_name,orcid,works_count",
        "per_page": 5,
        "api_key": API_KEY,
    }
    resp = requests.get(URL_AUTORES, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["results"]


def escolher(nome, candidatos):
    """Decide qual candidato corresponde ao docente e com que segurança."""
    if not candidatos:
        return None, "não encontrado"

    iguais = [c for c in candidatos if normalizar(c["display_name"]) == normalizar(nome)]
    if len(iguais) == 1:
        return iguais[0], "vinculado"
    if len(candidatos) == 1:
        return candidatos[0], "vinculado - conferir nome"
    return None, "ambíguo"


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main():
    with sqlite3.connect(ARQ_BANCO) as conn:
        docentes = conn.execute(
            "SELECT id, nome FROM docentes WHERE openalex_id IS NULL"
        ).fetchall()
        print(f"{len(docentes)} docentes sem vínculo com o OpenAlex.")

        registros = []
        for docente_id, nome in docentes:
            candidatos = buscar_autores(nome)
            escolhido, status = escolher(nome, candidatos)

            if escolhido:
                openalex_id = escolhido["id"].rsplit("/", 1)[-1]  # fica só o A123...
                orcid = (escolhido.get("orcid") or "").rsplit("/", 1)[-1] or None
                conn.execute(
                    "UPDATE docentes SET openalex_id = ?, orcid = COALESCE(orcid, ?) WHERE id = ?",
                    (openalex_id, orcid, docente_id),
                )

            registros.append({
                "docente_id": docente_id,
                "nome": nome,
                "status": status,
                "openalex_nome": escolhido["display_name"] if escolhido else "",
                "openalex_id": escolhido["id"] if escolhido else "",
                "publicacoes": escolhido["works_count"] if escolhido else "",
                "candidatos": " | ".join(
                    f'{c["display_name"]} ({c["id"].rsplit("/", 1)[-1]}, {c["works_count"]} pub.)'
                    for c in candidatos
                ),
            })
            print(f"  {status:<26} {nome}")
            time.sleep(0.2)  # pausa curta entre as chamadas

    revisao = pd.DataFrame(registros)
    revisao.to_csv(ARQ_REVISAO, index=False, encoding="utf-8-sig")

    print()
    print(revisao["status"].value_counts().to_string())
    print(f"\nRevisão salva em {ARQ_REVISAO.name}")


if __name__ == "__main__":
    main()