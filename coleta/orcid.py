"""Segunda via de validação: o registro do docente no ORCID.

Roda DEPOIS dos scripts do OpenAlex. O ORCID confirma e acrescenta, mas nunca
exclui nada, e respeita a lista de bloqueio da auditoria.

Passos, nesta ordem:
    python coleta/orcid.py --recuperar   1. lê o ORCID dos perfis vinculados no OpenAlex e
                                            grava onde o docente ainda não tem
    python coleta/orcid.py               2. valida cada ORCID e grava a situação no banco
    python coleta/orcid.py --aplicar     3. marca as publicações confirmadas e inclui as
                                            obras com DOI que faltam (só ORCIDs confirmados)

Decisões manuais, depois de olhar a lista dados/orcid_a_conferir.csv:
    python coleta/orcid.py --confirmar 91 104    o ORCID é do docente
    python coleta/orcid.py --rejeitar 128        o ORCID não é do docente (é apagado e não volta)
    python coleta/orcid.py --rejeitar 128 0000-0002-5658-6448   idem, informando o número

Situação de um ORCID:
    confirmado               nome compatível e (emprego na UFRB no registro OU ao menos um
                             trabalho-âncora no registro)
    confirmado manualmente   você conferiu e confirmou; o script não muda mais
    a conferir               nome compatível, sem emprego na UFRB e sem trabalho-âncora
    suspeito                 nome não reconhecido, ou registro com obras e nenhuma bate com o banco
    não encontrado           o ORCID não existe ou o registro não é público

Trabalho-âncora: publicação do docente em coautoria com outro docente da base.
Um homônimo de outra área não publica com colegas do CETEC.
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

import openalex_publicacoes as pub  # reaproveita a gravação de publicações

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).parent.parent
load_dotenv(RAIZ / ".env")

API_KEY = os.getenv("OPENALEX_KEY")
URL_OPENALEX = "https://api.openalex.org"
URL_ORCID = "https://pub.orcid.org/v3.0"   # API pública: não exige chave para dados públicos
CABECALHOS = {"Accept": "application/json", "User-Agent": "Ponte-CETEC (projeto academico UFRB)"}

ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"
ARQ_VALIDACAO = RAIZ / "dados" / "orcid_validacao.csv"
ARQ_A_CONFERIR = RAIZ / "dados" / "orcid_a_conferir.csv"
ARQ_FALTANTES = RAIZ / "dados" / "orcid_obras_faltantes.csv"

SUFIXOS = {"filho", "junior", "jr", "neto", "sobrinho"}
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}
CONFIRMADOS = ("confirmado", "confirmado manualmente")


# ---------------------------------------------------------------------------
# Comparação de nomes, DOIs e títulos
# ---------------------------------------------------------------------------
def palavras(texto):
    """Lista de palavras em minúsculas, sem acento e sem pontuação."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", " ", sem_acento.lower()).split()


def significativas(nome):
    """Palavras do nome, sem partículas e sufixos. A primeira palavra nunca é partícula."""
    lista = palavras(nome)
    return [p for i, p in enumerate(lista) if (i == 0 or p not in PARTICULAS) and p not in SUFIXOS]


def casa(p, d):
    return p == d or (len(p) == 1 and d.startswith(p))


def compativel(nome_candidato, nome_docente):
    """As palavras do candidato aparecem, na mesma ordem, no nome do docente."""
    do_docente = significativas(nome_docente)
    do_candidato = significativas(nome_candidato)
    if len(do_candidato) < 2 or not do_docente or do_candidato[-1] != do_docente[-1]:
        return False
    pos = 0
    for p in do_candidato:
        while pos < len(do_docente) and not casa(p, do_docente[pos]):
            pos += 1
        if pos == len(do_docente):
            return False
        pos += 1
    return True


def nome_colado(forma, nome_docente):
    """Reconhece nomes gravados sem espaço, como "edwinhobi" para Edwin Hobi Júnior."""
    colado = "".join(palavras(forma))
    do_docente = significativas(nome_docente)
    if len(do_docente) < 2:
        return False
    return colado in {"".join(do_docente), do_docente[0] + do_docente[-1]}


def normalizar_doi(doi):
    """Deixa só o identificador, em minúsculas; None se o texto não contiver um DOI."""
    achado = re.search(r"10\.\d{4,9}/\S+", (doi or "").strip().lower())
    return achado.group(0).rstrip(".,;") if achado else None


def normalizar_titulo(titulo):
    """Título sem marcações HTML, acentos e pontuação, para comparação."""
    return " ".join(palavras(re.sub(r"<[^>]+>", " ", titulo or "")))


def titulo_em(titulo, titulos):
    """Verdadeiro se o título coincide com algum do conjunto (aceita títulos em duas línguas juntas)."""
    t = normalizar_titulo(titulo)
    if len(t) < 15:
        return False
    return any(t == outro or (len(outro) >= 25 and (outro in t or t in outro)) for outro in titulos)


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
FALHA_DE_REDE = requests.exceptions.RequestException


def requisitar(url, **kwargs):
    """GET com até três tentativas, para falhas passageiras de rede (demora, queda de conexão)."""
    for tentativa in range(3):
        try:
            return requests.get(url, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if tentativa == 2:
                raise
            time.sleep(3 * (tentativa + 1))  # espera 3s, depois 6s


# ---------------------------------------------------------------------------
# Leitura do registro do ORCID
# ---------------------------------------------------------------------------
def pega(dado, *chaves):
    """Desce por um JSON aninhado; devolve None se algum nível faltar."""
    for chave in chaves:
        if not isinstance(dado, dict):
            return None
        dado = dado.get(chave)
    return dado


def buscar_registro(orcid):
    """Registro público do ORCID, ou None se não existir ou não for público."""
    resp = requisitar(f"{URL_ORCID}/{orcid}/record", headers=CABECALHOS, timeout=60)
    time.sleep(0.3)
    if resp.status_code in (404, 409, 410):
        return None
    resp.raise_for_status()
    return resp.json()


def nomes_do_registro(registro):
    formas = []
    dados = pega(registro, "person", "name") or {}
    completo = " ".join(filter(None, [pega(dados, "given-names", "value"), pega(dados, "family-name", "value")]))
    if completo:
        formas.append(completo)
    if pega(dados, "credit-name", "value"):
        formas.append(pega(dados, "credit-name", "value"))
    for outro in pega(registro, "person", "other-names", "other-name") or []:
        if outro.get("content"):
            formas.append(outro["content"])
    return formas


def afiliacoes(registro, tipo):
    """Lista de (organização, departamento) de um tipo: employments ou educations."""
    chave = tipo[:-1] + "-summary"
    achadas = []
    for grupo in pega(registro, "activities-summary", tipo, "affiliation-group") or []:
        for item in grupo.get("summaries") or []:
            resumo = item.get(chave) or {}
            achadas.append((pega(resumo, "organization", "name") or "", resumo.get("department-name") or ""))
    return achadas


def e_ufrb(organizacao):
    texto = " ".join(palavras(organizacao))
    return "reconcavo" in texto or "ufrb" in texto


def obras(registro):
    """Lista de {doi, ano, titulo} das obras do registro (o doi pode ser None)."""
    lista = []
    for grupo in pega(registro, "activities-summary", "works", "group") or []:
        doi = None
        for ident in pega(grupo, "external-ids", "external-id") or []:
            if ident.get("external-id-type") == "doi":
                doi = normalizar_doi(ident.get("external-id-value"))
                if doi:
                    break
        resumo = (grupo.get("work-summary") or [{}])[0]
        lista.append({
            "doi": doi,
            "ano": pega(resumo, "publication-date", "year", "value"),
            "titulo": pega(resumo, "title", "title", "value") or "",
        })
    return lista


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
NOVAS_COLUNAS = {
    "docentes": {"orcid_situacao": "TEXT", "orcid_evidencia": "TEXT"},
    "publicacoes": {"confirmado_orcid": "INTEGER"},  # 1 = a obra consta no ORCID confirmado do docente
}


def preparar_banco(conn):
    pub.preparar_banco(conn)  # colunas e tabelas do script de publicações
    for tabela, colunas in NOVAS_COLUNAS.items():
        existentes = {linha[1] for linha in conn.execute(f"PRAGMA table_info({tabela})")}
        for coluna, tipo in colunas.items():
            if coluna not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orcid_rejeitados (
            docente_id   INTEGER NOT NULL REFERENCES docentes(id),
            orcid        TEXT    NOT NULL,
            rejeitado_em TEXT    NOT NULL,
            PRIMARY KEY (docente_id, orcid)
        )
        """
    )


def publicacoes_por_docente(conn):
    """Para cada docente: DOIs e títulos no banco, e os DOIs e títulos dos trabalhos-âncora."""
    compartilhados = {
        linha[0] for linha in conn.execute(
            "SELECT openalex_id FROM publicacoes WHERE openalex_id IS NOT NULL "
            "GROUP BY openalex_id HAVING COUNT(DISTINCT docente_id) > 1"
        )
    }
    dados = {}
    for docente_id, trabalho_id, doi, titulo in conn.execute(
        "SELECT docente_id, openalex_id, doi, titulo FROM publicacoes"
    ):
        d = dados.setdefault(docente_id, {"dois": set(), "titulos": set(), "ancora_dois": set(), "ancora_titulos": set()})
        doi, titulo = normalizar_doi(doi), normalizar_titulo(titulo)
        if doi:
            d["dois"].add(doi)
        d["titulos"].add(titulo)
        if trabalho_id in compartilhados:
            if doi:
                d["ancora_dois"].add(doi)
            d["ancora_titulos"].add(titulo)
    return dados


# ---------------------------------------------------------------------------
# Passo 1: recuperar ORCIDs dos perfis vinculados
# ---------------------------------------------------------------------------
def orcid_do_perfil(perfil):
    """ORCID que o OpenAlex associa a um perfil de autor, ou None."""
    resp = requisitar(
        f"{URL_OPENALEX}/authors/{perfil}",
        params={"select": "id,display_name,orcid", "api_key": API_KEY},
        timeout=30,
    )
    time.sleep(0.2)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return (resp.json().get("orcid") or "").rsplit("/", 1)[-1] or None


def recuperar(conn):
    if not API_KEY:
        raise SystemExit("OPENALEX_KEY não encontrada no .env")

    perfis = conn.execute(
        """
        SELECT d.id, d.nome, d.orcid, v.openalex_id
        FROM docente_openalex v JOIN docentes d ON d.id = v.docente_id
        WHERE v.status = 'vinculado'
        ORDER BY d.id
        """
    ).fetchall()
    rejeitados = set(conn.execute("SELECT docente_id, orcid FROM orcid_rejeitados"))
    print(f"{len(perfis)} perfis vinculados para consultar.")

    achados = {}  # docente_id -> {"nome", "atual", "orcids": {orcid: [perfis]}}
    for docente_id, nome, atual, perfil in perfis:
        d = achados.setdefault(docente_id, {"nome": nome, "atual": atual, "orcids": {}})
        try:
            orcid = orcid_do_perfil(perfil)
        except FALHA_DE_REDE:
            print(f"  falha de rede no perfil {perfil} ({nome}); pulado")
            continue
        if orcid and (docente_id, orcid) not in rejeitados:
            d["orcids"].setdefault(orcid, []).append(perfil)

    gravados, conflitos, divergentes = 0, [], []
    for docente_id, d in achados.items():
        encontrados = list(d["orcids"])
        if d["atual"]:
            outros = [o for o in encontrados if o != d["atual"]]
            if outros:
                divergentes.append((d["nome"], d["atual"], outros))
        elif len(encontrados) == 1:
            conn.execute(
                "UPDATE docentes SET orcid = ?, orcid_situacao = NULL, orcid_evidencia = NULL WHERE id = ?",
                (encontrados[0], docente_id),
            )
            gravados += 1
            print(f"  gravado  {encontrados[0]}  {d['nome']}")
        elif len(encontrados) > 1:
            conflitos.append((d["nome"], encontrados))
    conn.commit()

    print(f"\n{gravados} ORCIDs gravados (ainda sem validação: rode o passo 2).")
    if conflitos:
        print("\nDocentes com mais de um ORCID nos perfis (nada gravado; decida e grave à mão):")
        for nome, lista in conflitos:
            print(f"  {nome}: {', '.join(lista)}")
    if divergentes:
        print("\nDocentes cujo ORCID no banco difere do que algum perfil traz (mantido o do banco):")
        for nome, atual, outros in divergentes:
            print(f"  {nome}: banco {atual}; perfis {', '.join(outros)}")
    total = conn.execute("SELECT COUNT(orcid) FROM docentes").fetchone()[0]
    print(f"\nDocentes com ORCID no banco agora: {total}")


# ---------------------------------------------------------------------------
# Passo 2: validar
# ---------------------------------------------------------------------------
def avaliar(nome, registro, banco):
    """Compara o registro do ORCID com o docente. Devolve (dados, obras_faltantes)."""
    formas = nomes_do_registro(registro)
    nome_ok = any(compativel(f, nome) or nome_colado(f, nome) for f in formas)

    empregos = afiliacoes(registro, "employments")
    emprego_ufrb = [dep for org, dep in empregos if e_ufrb(org)]
    formacoes = afiliacoes(registro, "educations")

    lista = obras(registro)
    coincidem, ancoras, faltam = 0, 0, []
    for obra in lista:
        por_doi = bool(obra["doi"]) and obra["doi"] in banco["dois"]
        if por_doi or titulo_em(obra["titulo"], banco["titulos"]):
            coincidem += 1
            if (obra["doi"] in banco["ancora_dois"]) or titulo_em(obra["titulo"], banco["ancora_titulos"]):
                ancoras += 1
        else:
            faltam.append(obra)

    if not formas:
        situacao, evidencia = "a conferir", "nome oculto no registro"
    elif not nome_ok:
        situacao, evidencia = "suspeito", "nome não reconhecido"
    elif emprego_ufrb:
        situacao, evidencia = "confirmado", "emprego na UFRB"
    elif ancoras:
        situacao, evidencia = "confirmado", "trabalho-âncora"
    elif lista and not coincidem:
        situacao, evidencia = "suspeito", "obras não batem com o banco"
    elif lista:
        situacao, evidencia = "a conferir", "obras batem, mas sem emprego na UFRB e sem âncora"
    else:
        situacao, evidencia = "a conferir", "registro vazio"

    dados = {
        "situacao": situacao,
        "evidencia": evidencia,
        "nome_orcid": formas[0] if formas else "(oculto)",
        "emprego_ufrb": "sim" if emprego_ufrb else "não",
        "unidade": "; ".join(sorted({d for d in emprego_ufrb if d})),
        "outros_empregos": "; ".join(sorted({org for org, _ in empregos if org and not e_ufrb(org)})),
        "formacao": "; ".join(sorted({org for org, _ in formacoes if org})),
        "obras": len(lista),
        "coincidem_com_banco": coincidem,
        "ancoras_no_registro": ancoras,
        "faltam_com_doi": sum(1 for o in faltam if o["doi"]),
        "faltam_sem_doi": sum(1 for o in faltam if not o["doi"]),
    }
    return dados, faltam


def validar(conn):
    docentes = conn.execute(
        "SELECT id, nome, orcid, orcid_situacao FROM docentes WHERE orcid IS NOT NULL AND orcid != '' ORDER BY id"
    ).fetchall()
    por_docente = publicacoes_por_docente(conn)
    vazio = {"dois": set(), "titulos": set(), "ancora_dois": set(), "ancora_titulos": set()}
    print(f"{len(docentes)} docentes com ORCID para validar.")

    linhas, faltantes = [], []
    for docente_id, nome, orcid, anterior in docentes:
        try:
            registro = buscar_registro(orcid)
        except FALHA_DE_REDE:
            linhas.append({"docente_id": docente_id, "nome": nome, "orcid": orcid,
                           "situacao": "não consultado", "evidencia": "falha de rede; rode de novo"})
            print(f"  {'não consultado':<23}            {nome}  (falha de rede)")
            continue  # a situação gravada no banco fica como estava

        if registro is None:
            dados, faltam = {"situacao": "não encontrado", "evidencia": "registro inexistente ou não público"}, []
        else:
            dados, faltam = avaliar(nome, registro, por_docente.get(docente_id, vazio))

        if anterior == "confirmado manualmente":
            dados["situacao"], dados["evidencia"] = anterior, "conferência manual"  # sua decisão prevalece
        else:
            conn.execute(
                "UPDATE docentes SET orcid_situacao = ?, orcid_evidencia = ? WHERE id = ?",
                (dados["situacao"], dados["evidencia"], docente_id),
            )
        linhas.append({"docente_id": docente_id, "nome": nome, "orcid": orcid, **dados})
        for obra in faltam:
            faltantes.append({"docente_id": docente_id, "nome": nome, "orcid": orcid,
                              "situacao": dados["situacao"], **obra})
        print(f"  {dados['situacao']:<23} {dados.get('obras', 0):>3} obras  {nome}")
    conn.commit()

    colunas = ["docente_id", "nome", "orcid", "situacao", "evidencia", "nome_orcid", "emprego_ufrb", "unidade",
               "outros_empregos", "formacao", "obras", "coincidem_com_banco", "ancoras_no_registro",
               "faltam_com_doi", "faltam_sem_doi"]
    validacao = pd.DataFrame(linhas, columns=colunas)
    validacao.to_csv(ARQ_VALIDACAO, index=False, encoding="utf-8-sig")
    a_conferir = validacao[~validacao["situacao"].isin(CONFIRMADOS + ("não consultado",))]
    a_conferir.to_csv(ARQ_A_CONFERIR, index=False, encoding="utf-8-sig")
    pd.DataFrame(faltantes, columns=["docente_id", "nome", "orcid", "situacao", "doi", "ano", "titulo"]).to_csv(
        ARQ_FALTANTES, index=False, encoding="utf-8-sig"
    )

    print()
    print(validacao["situacao"].value_counts().to_string())
    print()
    print(validacao[validacao["situacao"] == "confirmado"]["evidencia"].value_counts().to_string())
    falhas = int((validacao["situacao"] == "não consultado").sum())
    if falhas:
        print(f"\n{falhas} docentes não puderam ser consultados por falha de rede. Rode de novo para completá-los.")
    print(f"\n{len(a_conferir)} ORCIDs para você estudar em {ARQ_A_CONFERIR.name}")
    print("Depois de olhar cada um:  python coleta/orcid.py --confirmar ID   ou   --rejeitar ID")


# ---------------------------------------------------------------------------
# Decisões manuais
# ---------------------------------------------------------------------------
def confirmar(conn, argumentos):
    if not argumentos or not all(a.isdigit() for a in argumentos):
        raise SystemExit("Uso: --confirmar ID_DO_DOCENTE [outros ids]")
    for docente_id in map(int, argumentos):
        linha = conn.execute("SELECT nome, orcid FROM docentes WHERE id = ?", (docente_id,)).fetchone()
        if not linha or not linha[1]:
            print(f"  docente {docente_id}: sem ORCID no banco; nada feito")
            continue
        conn.execute(
            "UPDATE docentes SET orcid_situacao = 'confirmado manualmente', orcid_evidencia = 'conferência manual' WHERE id = ?",
            (docente_id,),
        )
        print(f"  confirmado manualmente  {linha[1]}  {linha[0]}")
    conn.commit()


def rejeitar(conn, argumentos):
    if not argumentos or not argumentos[0].isdigit():
        raise SystemExit("Uso: --rejeitar ID_DO_DOCENTE [ORCID]")
    docente_id = int(argumentos[0])
    linha = conn.execute("SELECT nome, orcid FROM docentes WHERE id = ?", (docente_id,)).fetchone()
    if not linha:
        raise SystemExit(f"Não existe docente com id {docente_id}.")
    orcid = argumentos[1] if len(argumentos) > 1 else linha[1]
    if not orcid:
        raise SystemExit("O docente não tem ORCID no banco. Informe o número: --rejeitar ID ORCID")

    conn.execute(
        "INSERT OR IGNORE INTO orcid_rejeitados (docente_id, orcid, rejeitado_em) VALUES (?, ?, date('now'))",
        (docente_id, orcid),
    )
    if linha[1] == orcid:
        conn.execute(
            "UPDATE docentes SET orcid = NULL, orcid_situacao = NULL, orcid_evidencia = NULL WHERE id = ?",
            (docente_id,),
        )
    conn.commit()
    print(f"  rejeitado  {orcid}  {linha[0]}  (não será gravado de novo pelo passo 1)")


# ---------------------------------------------------------------------------
# Passo 3: aplicar
# ---------------------------------------------------------------------------
def trabalho_por_doi(doi):
    """Trabalho no OpenAlex a partir do DOI, ou None se o OpenAlex não o tiver."""
    resp = requisitar(f"{URL_OPENALEX}/works/doi:{doi}", params={"api_key": API_KEY}, timeout=60)
    time.sleep(0.2)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def aplicar(conn):
    if not API_KEY:
        raise SystemExit("OPENALEX_KEY não encontrada no .env")

    docentes = conn.execute(
        f"SELECT id, nome, orcid FROM docentes WHERE orcid_situacao IN {CONFIRMADOS} ORDER BY id"
    ).fetchall()
    if not docentes:
        raise SystemExit("Nenhum ORCID confirmado. Rode antes o passo 2: python coleta/orcid.py")
    print(f"{len(docentes)} docentes com ORCID confirmado.")

    marcadas = incluidas = 0
    bloqueadas, sem_openalex, sem_doi = [], [], 0
    for docente_id, nome, orcid in docentes:
        try:
            registro = buscar_registro(orcid)
        except FALHA_DE_REDE:
            print(f"  falha de rede ao consultar o ORCID de {nome}; pulado (rode de novo depois)")
            continue
        if registro is None:
            continue
        no_banco = conn.execute(
            "SELECT openalex_id, doi, titulo FROM publicacoes WHERE docente_id = ?", (docente_id,)
        ).fetchall()
        excluidos = pub.excluidos_do_docente(conn, docente_id)
        novas = 0

        for obra in obras(registro):
            # a obra já está no banco? marca como confirmada
            iguais = [
                trabalho_id for trabalho_id, doi, titulo in no_banco
                if (obra["doi"] and normalizar_doi(doi) == obra["doi"])
                or titulo_em(obra["titulo"], {normalizar_titulo(titulo)})
            ]
            if iguais:
                for trabalho_id in iguais:
                    marcadas += conn.execute(
                        "UPDATE publicacoes SET confirmado_orcid = 1 "
                        "WHERE docente_id = ? AND openalex_id = ? AND confirmado_orcid IS NOT 1",
                        (docente_id, trabalho_id),
                    ).rowcount
                continue

            # não está: só entra se tiver DOI e o OpenAlex conhecer o trabalho
            if not obra["doi"]:
                sem_doi += 1
                continue
            try:
                trabalho = trabalho_por_doi(obra["doi"])
            except FALHA_DE_REDE:
                sem_openalex.append((nome, obra["doi"], "(falha de rede; rode de novo)"))
                continue
            if trabalho is None or not trabalho.get("title"):
                sem_openalex.append((nome, obra["doi"], obra["titulo"]))
                continue
            trabalho_id = trabalho["id"].rsplit("/", 1)[-1]
            if trabalho_id in excluidos:
                bloqueadas.append((docente_id, nome, trabalho_id, trabalho["title"]))
                continue
            if pub.gravar_trabalho(conn, docente_id, trabalho, "orcid"):
                novas += 1
            conn.execute(
                "UPDATE publicacoes SET confirmado_orcid = 1 WHERE docente_id = ? AND openalex_id = ?",
                (docente_id, trabalho_id),
            )

        conn.commit()
        incluidas += novas
        if novas:
            print(f"  {novas:>3} incluídas  {nome}")

    print(f"\nPublicações marcadas como confirmadas pelo ORCID: {marcadas}")
    print(f"Obras incluídas a partir do ORCID: {incluidas}")
    print(f"Obras sem DOI, não incluídas: {sem_doi}")
    if sem_openalex:
        print(f"\nObras com DOI que o OpenAlex não tem ({len(sem_openalex)}), não incluídas:")
        for nome, doi, titulo in sem_openalex:
            print(f"  {nome}: {doi}  {titulo[:70]}")
    if bloqueadas:
        print("\nATENÇÃO: obras do ORCID que estão na lista de bloqueio. Não foram incluídas.")
        print("Um ORCID confirmado listar um trabalho excluído sugere exclusão indevida; confira:")
        for docente_id, nome, trabalho_id, titulo in bloqueadas:
            print(f"  docente {docente_id}  {nome}: {trabalho_id}  {titulo[:70]}")
    total = conn.execute("SELECT COUNT(*) FROM publicacoes WHERE confirmado_orcid = 1").fetchone()[0]
    print(f"\nTotal de publicações confirmadas pelo ORCID no banco: {total}")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")

    with sqlite3.connect(ARQ_BANCO) as conn:
        preparar_banco(conn)
        if "--recuperar" in args:
            recuperar(conn)
        elif "--confirmar" in args:
            confirmar(conn, args[args.index("--confirmar") + 1:])
        elif "--rejeitar" in args:
            rejeitar(conn, args[args.index("--rejeitar") + 1:])
        elif "--aplicar" in args:
            aplicar(conn)
        else:
            validar(conn)


if __name__ == "__main__":
    main()