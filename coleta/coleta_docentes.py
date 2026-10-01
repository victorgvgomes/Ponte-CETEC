
"""Coleta os docentes do CETEC/UFRB por área e gera CSV e Excel em dados/."""

from pathlib import Path

import pandas as pd
import sqlite3
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
URL = "https://ufrb.edu.br/cetec/estrutura-administrativa/areas-de-conhecimento"

PASTA_DADOS = Path(__file__).parent.parent / "dados"
PASTA_DADOS.mkdir(exist_ok=True)
ARQ_AREAS = PASTA_DADOS / "areas_conhecidas.txt"
ARQ_CSV = PASTA_DADOS / "docentes_cetec.csv"
ARQ_EXCEL = PASTA_DADOS / "docentes_cetec.xlsx"
ARQ_BANCO = PASTA_DADOS / "ponte_cetec.db"

MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "em"}


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def coletar():
    resp = requests.get(URL, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    registros = []
    area = None
    for elem in soup.find_all(["h2", "a"]):  # títulos e links, na ordem da página
        texto = elem.get_text(" ", strip=True)
        if elem.name == "h2":
            if texto.startswith(("Área", "Docentes")):
                area = texto  # mudou de área
            continue
        href = elem.get("href") or ""
        if area and ("siape=" in href or "lattes.cnpq.br" in href):
            prox = elem.next_sibling  # texto logo após o link
            funcao = prox.strip() if isinstance(prox, str) and "(" in prox else None
            registros.append({"area": area, "nome": texto, "funcao": funcao, "link": href})

    if not registros:
        raise RuntimeError("Nenhum docente encontrado. A estrutura da página pode ter mudado.")
    return registros


# ---------------------------------------------------------------------------
# Limpeza
# ---------------------------------------------------------------------------
def formatar_funcao(texto):
    palavras = texto.lower().split()
    return " ".join(
        p if p in MINUSCULAS and i > 0 else p.capitalize()
        for i, p in enumerate(palavras)
    )


def limpar(df):
    df = df.copy()
    df["nome"] = df["nome"].str.strip()
    df["siape"] = df["link"].str.extract(r"siape=(\d+)")[0]
    df["sigla"] = df["area"].str.extract(r"-\s*([A-Z]+)\s*$")[0].fillna("SUBST")
    df["coordenador"] = df["funcao"].str.contains(r"\(coordenador", case=False, na=False)
    df["funcao"] = df["funcao"].fillna("").str.strip("() ").apply(formatar_funcao)
    df = df.rename(columns={"link": "url_perfil"})

    # remove repetidos pelo SIAPE, sem descartar quem está sem SIAPE
    tem_siape = df["siape"].notna()
    duplicado = df.duplicated(subset="siape")
    return df[~(tem_siape & duplicado)].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def resumir(df):
    df = df.assign(
        tem_funcao=df["funcao"] != "",
        id_docente=df["siape"].fillna(df["nome"]),  # SIAPE ou, se faltar, o nome
    )
    resumo = (
        df.groupby("sigla")
        .agg(
            docentes=("id_docente", "nunique"),
            com_siape=("siape", "nunique"),
            com_funcao=("tem_funcao", "sum"),
            coordenadores=("coordenador", "sum"),
        )
        .reset_index()
        .sort_values("sigla")
    )
    total = pd.DataFrame([{
        "sigla": "TOTAL (sem repetição)",
        "docentes": df["id_docente"].nunique(),
        "com_siape": df["siape"].nunique(),
        "com_funcao": df.loc[df["tem_funcao"], "id_docente"].nunique(),
        "coordenadores": df.loc[df["coordenador"], "id_docente"].nunique(),
    }])
    return pd.concat([resumo, total], ignore_index=True)


def motivos_excecao(linha):
    motivos = []
    if pd.isna(linha["siape"]):
        motivos.append("Sem SIAPE")
    if "lattes" in linha["url_perfil"]:
        motivos.append("Link do Lattes")
    if linha["sigla"] == "SUBST":
        motivos.append("Substituto")
    return "; ".join(motivos)


def listar_excecoes(df):
    df = df.assign(excecao=df.apply(motivos_excecao, axis=1))
    excecoes = df[df["excecao"] != ""]
    return excecoes[["siape", "nome", "sigla", "url_perfil", "excecao"]]


# ---------------------------------------------------------------------------
# Verificação de mudanças no site
# ---------------------------------------------------------------------------
def verificar_mudancas(df):
    atuais = set(df["area"].unique())
    if not ARQ_AREAS.exists():
        ARQ_AREAS.write_text("\n".join(sorted(atuais)), encoding="utf-8")
        print("Lista de áreas salva pela primeira vez.")
        return

    conhecidas = set(ARQ_AREAS.read_text(encoding="utf-8").splitlines())
    novas, removidas = atuais - conhecidas, conhecidas - atuais
    if novas or removidas:
        print("⚠️ Os títulos de área mudaram no site.")
        if novas:
            print("  Novos:", novas)
        if removidas:
            print("  Removidos:", removidas)
        print("  Revise a regra da sigla e apague o arquivo para aceitar a nova lista.")


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
def salvar(df, resumo):
    df.to_csv(ARQ_CSV, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(ARQ_EXCEL) as writer:
        df.to_excel(writer, sheet_name="Docentes", index=False)
        resumo.to_excel(writer, sheet_name="Resumo por área", index=False)
        listar_excecoes(df).to_excel(writer, sheet_name="Exceções", index=False)

def salvar_banco(df):
    """Insere ou atualiza áreas e docentes no SQLite, sem duplicar a cada execução."""
    with sqlite3.connect(ARQ_BANCO) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
 
        # áreas: insere novas e atualiza a sigla das existentes
        for _, a in df[["area", "sigla"]].drop_duplicates().iterrows():
            conn.execute(
                """INSERT INTO areas (nome, sigla) VALUES (?, ?)
                   ON CONFLICT(nome) DO UPDATE SET sigla = excluded.sigla""",
                (a["area"], a["sigla"]),
            )
        ids_area = dict(conn.execute("SELECT nome, id FROM areas"))
 
        # docentes: identifica pelo SIAPE ou, se faltar, pelo nome
        for _, d in df.iterrows():
            dados = (d["nome"], ids_area[d["area"]], d["funcao"],
                     int(d["coordenador"]), d["url_perfil"])
            if pd.notna(d["siape"]):
                conn.execute(
                    """INSERT INTO docentes (siape, nome, area_id, funcao, coordenador, url_perfil)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(siape) DO UPDATE SET
                           nome = excluded.nome, area_id = excluded.area_id,
                           funcao = excluded.funcao, coordenador = excluded.coordenador,
                           url_perfil = excluded.url_perfil""",
                    (d["siape"], *dados),
                )
            else:
                existe = conn.execute(
                    "SELECT id FROM docentes WHERE siape IS NULL AND nome = ?", (d["nome"],)
                ).fetchone()
                if existe:
                    conn.execute(
                        """UPDATE docentes SET nome = ?, area_id = ?, funcao = ?,
                           coordenador = ?, url_perfil = ? WHERE id = ?""",
                        (*dados, existe[0]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO docentes (nome, area_id, funcao, coordenador, url_perfil)
                           VALUES (?, ?, ?, ?, ?)""",
                        dados,
                    )
 
        total = conn.execute("SELECT COUNT(*) FROM docentes").fetchone()[0]
    print(f"Banco atualizado: {total} docentes em {ARQ_BANCO.name}")
 
# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main():
    df = pd.DataFrame(coletar())
    df = limpar(df)
    verificar_mudancas(df)
    resumo = resumir(df)
    salvar(df, resumo)
    salvar_banco(df)

    print(f"{len(df)} docentes em {df['sigla'].nunique()} áreas")


if __name__ == "__main__":
    main()