"""Diagnóstico dos docentes com status "não encontrado" na OpenAlex (versão 2).

NÃO altera o banco. Lê dados/openalex_vinculos.csv, refaz as buscas para cada
docente não encontrado e grava dados/openalex_diagnostico.csv.

Mudança da versão 2: o candidato só é aceito se o nome dele for COMPATÍVEL com
o nome do docente (função compativel), em vez de apenas conter o primeiro nome
e o sobrenome.

Uso:  python coleta/openalex_diagnostico.py
"""
import os
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")

API_KEY = os.getenv("OPENALEX_KEY")
UFRB_ID = "I129192303"
URL_AUTORES = "https://api.openalex.org/authors"

ARQ_REVISAO = RAIZ / "dados" / "openalex_vinculos.csv"
ARQ_DIAGNOSTICO = RAIZ / "dados" / "openalex_diagnostico.csv"

# Palavras ignoradas na comparação de nomes
SUFIXOS = {"filho", "junior", "jr", "neto", "sobrinho"}
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}


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
    """Verdadeiro se o candidato traz todas as palavras do docente (por extenso ou inicial).

    "Denis R. Petrucci" é inteiro para "Denis Rinaldi Petrucci".
    "Anderson Cruz" é parcial para "Anderson Reis da Cruz".
    """
    return len(significativas(nome_candidato)) >= len(significativas(nome_docente))


def buscar(texto, na_ufrb):
    params = {
        "search": texto,
        "select": "id,display_name,works_count,last_known_institutions",
        "per_page": 10,
        "api_key": API_KEY,
    }
    if na_ufrb:
        params["filter"] = f"affiliations.institution.id:{UFRB_ID}"

    resp = requests.get(URL_AUTORES, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(0.2)
    return resp.json()["results"]


def buscar_compativeis(nome, texto, na_ufrb):
    """Faz a busca e fica só com os candidatos de nome compatível com o docente."""
    return [c for c in buscar(texto, na_ufrb) if compativel(c.get("display_name") or "", nome)]


def descrever(candidato, nome):
    instituicoes = candidato.get("last_known_institutions") or []
    instituicao = instituicoes[0]["display_name"] if instituicoes else "sem instituição"
    codigo = candidato["id"].rsplit("/", 1)[-1]
    tipo = "nome inteiro" if nome_inteiro(candidato["display_name"], nome) else "nome parcial"
    return f'{candidato["display_name"]} ({codigo}, {candidato["works_count"]} pub., {instituicao}, {tipo})'


def diagnosticar(nome):
    partes = [p for p in palavras(nome) if p not in SUFIXOS]
    curto = f"{partes[0]} {partes[-1]}"

    # Duas buscas sempre: nome curto dentro da UFRB e nome completo sem filtro
    na_ufrb = buscar_compativeis(nome, curto, True)
    fora = buscar_compativeis(nome, nome, False)

    # Última tentativa, só se as duas falharem: nome curto sem filtro
    if not na_ufrb and not fora:
        fora = buscar_compativeis(nome, curto, False)

    # Quem já apareceu na busca da UFRB não precisa repetir em "fora"
    ids_ufrb = {c["id"] for c in na_ufrb}
    fora = [c for c in fora if c["id"] not in ids_ufrb]

    if any(nome_inteiro(c["display_name"], nome) for c in na_ufrb):
        rotulo = "1 nome inteiro na UFRB"
    elif any(nome_inteiro(c["display_name"], nome) for c in fora):
        rotulo = "2 nome inteiro fora da UFRB"
    elif na_ufrb or fora:
        rotulo = "3 só nome parcial"
    else:
        rotulo = "4 sem candidato compatível"

    return rotulo, curto, na_ufrb, fora


def main():
    if not API_KEY:
        raise SystemExit("OPENALEX_KEY não encontrada no .env")

    revisao = pd.read_csv(ARQ_REVISAO, encoding="utf-8-sig")
    status = revisao["status"].map(lambda s: " ".join(palavras(s)))
    pendentes = revisao[status == "nao encontrado"]

    if pendentes.empty:
        raise SystemExit('Nenhum docente com status "não encontrado" no CSV.')

    registros = []
    for linha in pendentes.itertuples():
        rotulo, curto, na_ufrb, fora = diagnosticar(linha.nome)
        registros.append({
            "docente_id": linha.docente_id,
            "nome": linha.nome,
            "nome_curto": curto,
            "diagnostico": rotulo,
            "candidatos_ufrb": " | ".join(descrever(c, linha.nome) for c in na_ufrb),
            "candidatos_fora": " | ".join(descrever(c, linha.nome) for c in fora),
        })
        print(f"  {rotulo:<30} {linha.nome}")

    resultado = pd.DataFrame(registros)
    resultado.to_csv(ARQ_DIAGNOSTICO, index=False, encoding="utf-8-sig")

    print()
    print(resultado["diagnostico"].value_counts().sort_index().to_string())
    print(f"\nDetalhes em {ARQ_DIAGNOSTICO}")


if __name__ == "__main__":
    main()