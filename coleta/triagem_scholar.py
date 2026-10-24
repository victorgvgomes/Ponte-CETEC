"""Triagem das publicações novas vindas do Google Acadêmico.

NÃO altera o banco. Lê dados/scholar_publicacoes_novas.csv (gerado pelo
`python coleta/scholar.py validar`) e aponta, para cada publicação, os motivos
para não incluí-la. Usa as mesmas regras já usadas nas publicações do banco:

  1. ja_excluido     -> o título é de um trabalho que você já excluiu antes
                        como homônimo daquele docente (tabela publicacoes_excluidas).
                        Uma decisão anterior nunca é desfeita.
  2. sem_conteudo    -> o título não diz do que o trabalho trata: nome de revista,
                        "Apresentação", o próprio nome do docente (regras da seção 3.11).
  3. ja_no_banco     -> parece o mesmo trabalho de uma publicação do banco, com o
                        título em outro idioma ou com pequenas diferenças (embeddings).
  4. repetido        -> parece o mesmo trabalho de outra publicação nova do mesmo
                        docente (por exemplo, versão em português e em inglês).
  5. destoa          -> o assunto fica isolado do resto da produção do docente:
                        possível homônimo (embeddings, mesma medida da seção 3.12).
  6. autoria         -> o nome do docente não aparece na lista de autores.

Gera dados/triagem_scholar.csv, uma linha por publicação, com a sugestão:
  incluir   -> nenhum apontamento
  conferir  -> destoa ou autoria (você decide)
  ignorar   -> ja_excluido, sem_conteudo, ja_no_banco ou cópia repetida

A coluna "decisao" é sua: escreva incluir, ignorar ou orientacao (trabalho de
aluno orientado pelo docente: não entra como publicação, fica guardado à parte).
Ela é mantida quando o script roda de novo. Nada entra no banco por este script.

Uso:
  python coleta/triagem_scholar.py
      Analisa tudo. Precisa do Ollama aberto com o nomic-embed-text e de
      internet para buscar na OpenAlex os títulos dos trabalhos já excluídos
      (só na primeira vez; depois ficam em dados/excluidas_titulos.csv).

  python coleta/triagem_scholar.py --sem-embeddings
      Roda só as regras 1, 2 e 6, sem o Ollama. Útil para um teste rápido.

  python coleta/triagem_scholar.py --aprovar-sem-apontamento
      Escreve "incluir" na coluna decisao das linhas com sugestão "incluir"
      que ainda estão em branco. É a aprovação em bloco: só rode depois de
      olhar o CSV.

  python coleta/triagem_scholar.py --aplicar
      ÚNICO modo que grava no banco. Antes, copia o banco para
      dados/ponte_cetec_antes_scholar.db. Depois:
      - decisao = incluir    -> entra em publicacoes, com fonte = 'scholar'.
        O Google não tem código de obra; o campo openalex_id recebe um código
        próprio "GS-..." (fixo para o mesmo docente e título), para que as
        outras triagens e o --excluir do openalex_publicacoes.py funcionem.
      - decisao = orientacao -> entra na tabela orientacoes (criada se não
        existir), separada das publicações.
      - publicação do Google que já tinha entrado e agora está com outra
        decisão -> sai do banco.
      Pode rodar mais de uma vez sem duplicar nada.
"""

import csv
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import numpy as np
import requests

# Reaproveita o que já existe na pasta coleta/
sys.path.insert(0, str(Path(__file__).parent))
from triagem_conteudo import TITULOS_GENERICOS, PALAVRAS_TITULO_CURTO, normalizar
from scholar import normalizar_titulo, titulos_iguais

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).parent.parent
ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"
ARQ_NOVAS = RAIZ / "dados" / "scholar_publicacoes_novas.csv"
ARQ_TRIAGEM = RAIZ / "dados" / "triagem_scholar.csv"
ARQ_EXCLUIDAS = RAIZ / "dados" / "excluidas_titulos.csv"

URL_OPENALEX = "https://api.openalex.org/works"

# Mesmos limites da triagem por semelhança (seção 3.12). Aqui a comparação é só
# entre títulos, porque o Google Acadêmico não traz resumo: os limites podem
# precisar de nova calibração depois da primeira rodada.
MINIMO_PUBLICACOES = 4
VIZINHOS = 3
LIMITE_ISOLADO = -3.0
LIMITE_SIMILAR_MESMO_IDIOMA = 0.97
LIMITE_SIMILAR_TRADUCAO = 0.88
DIFERENCA_ANOS_TRADUCAO = 1

# Partes de nome que muitos autores têm e que não identificam ninguém sozinhas
PARTES_COMUNS = {"da", "de", "do", "das", "dos", "e", "filho", "junior", "neto", "sobrinho"}

# Começos de título que são metadado, não trabalho
TITULO_METADADO = re.compile(r"^(year of publication|dossie|coordenacao|sumario|anais)", re.IGNORECASE)
# Nome de evento ou revista no lugar do título (ex.: "14º Congresso Brasileiro de...",
# "Revista de Engenharia Civil", "Encontro de Outono da SBF 2018/ID: 550-1").
# Aplicado ao título já normalizado (sem acentos e sem pontuação).
TITULO_EVENTO = re.compile(
    r"^(\d+[oa]? )?(congresso|simposio|encontro|seminario|workshop|conference|symposium|revista|journal)\b"
    r"|\bid \d+"
)

COLUNAS = [
    "id_docente", "nome_docente", "titulo", "ano", "veiculo", "autores", "citacoes",
    "apontamentos", "detalhe", "escore", "sugestao", "decisao", "observacao",
]


# ---------------------------------------------------------------------------
# Arquivos
# ---------------------------------------------------------------------------
def ler_csv(caminho):
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def gravar_csv(caminho, colunas, linhas):
    temporario = caminho.with_suffix(".tmp")
    with open(temporario, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows(linhas)
    temporario.replace(caminho)


def abrir_banco():
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")
    conn = sqlite3.connect(f"file:{ARQ_BANCO}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def ano_inteiro(valor):
    """'2021' -> 2021; vazio ou absurdo (ex.: '1') -> None."""
    try:
        ano = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return ano if 1950 <= ano <= 2100 else None


# ---------------------------------------------------------------------------
# 1. Trabalhos já excluídos como homônimos
# ---------------------------------------------------------------------------
def titulos_excluidos(conn):
    """{id_docente: [títulos normalizados]} dos trabalhos já excluídos.

    O banco guarda só o código OpenAlex de cada trabalho excluído. Os títulos
    são buscados na OpenAlex uma vez e guardados em dados/excluidas_titulos.csv.
    """
    excluidas = conn.execute("SELECT docente_id, openalex_id FROM publicacoes_excluidas").fetchall()
    guardados = {(l["docente_id"], l["openalex_id"]): l["titulo"] for l in ler_csv(ARQ_EXCLUIDAS)}

    faltam = [(str(d), oid) for d, oid in excluidas if (str(d), oid) not in guardados]
    if faltam:
        print(f"Buscando na OpenAlex o título de {len(faltam)} trabalhos já excluídos...")
        from dotenv import load_dotenv
        load_dotenv(RAIZ / ".env")
        chave_api = os.getenv("OPENALEX_KEY")
        nao_encontrados = []
        for docente_id, openalex_id in faltam:
            try:
                resp = requests.get(f"{URL_OPENALEX}/{openalex_id}",
                                    params={"api_key": chave_api, "select": "id,title"}, timeout=60)
            except requests.RequestException:
                # A mensagem do erro não é mostrada porque traz a chave da API
                raise SystemExit(f"Não consegui falar com a OpenAlex ao buscar {openalex_id}. "
                                 "Confira a internet e rode de novo.")
            if resp.status_code == 404:
                # O trabalho foi apagado ou fundido na OpenAlex: fica anotado sem título
                nao_encontrados.append(openalex_id)
                titulo = ""
            elif resp.status_code != 200:
                raise SystemExit(f"A OpenAlex respondeu {resp.status_code} ao buscar {openalex_id}. "
                                 "Rode de novo mais tarde.")
            else:
                titulo = resp.json().get("title") or ""
            guardados[(docente_id, openalex_id)] = titulo
        if nao_encontrados:
            print(f"  {len(nao_encontrados)} não existem mais na OpenAlex e ficam sem título "
                  f"(não podem ser comparados): {', '.join(nao_encontrados)}")
        linhas = [{"docente_id": d, "openalex_id": o, "titulo": t} for (d, o), t in guardados.items()]
        gravar_csv(ARQ_EXCLUIDAS, ["docente_id", "openalex_id", "titulo"], linhas)

    por_docente = {}
    for (docente_id, _), titulo in guardados.items():
        normalizado = normalizar_titulo(titulo)
        if normalizado:
            por_docente.setdefault(docente_id, []).append(normalizado)
    return por_docente


# ---------------------------------------------------------------------------
# 2. Título sem conteúdo (regras da triagem de conteúdo, seção 3.11)
# ---------------------------------------------------------------------------
def titulo_sem_conteudo(titulo, nome_docente):
    """Devolve o motivo, ou "" se o título descreve um trabalho."""
    t = normalizar(titulo)
    if not t:
        return "título vazio"
    if t in TITULOS_GENERICOS:
        return "título genérico"
    if t == normalizar(nome_docente):
        return "o título é o nome do docente"
    if TITULO_METADADO.match(t):
        return "título é metadado"
    if TITULO_EVENTO.search(t):
        return "título parece nome de evento ou revista"
    # O Google Acadêmico não traz DOI nem resumo: todo título curto é suspeito
    if len(t.split()) <= PALAVRAS_TITULO_CURTO:
        return "título curto (pode ser nome de revista)"
    return ""


# ---------------------------------------------------------------------------
# 6. Autoria
# ---------------------------------------------------------------------------
def checar_autoria(autores, nome_docente):
    """'ok', 'nao_visivel' (lista cortada sem o nome) ou 'ausente'.

    O Google escreve os autores como "TP Pagano, RB Loureiro". Conta como o
    docente quem tem como último nome uma parte do nome dele. Partes comuns
    ("Filho", "Neto") só contam se a primeira inicial também bater.
    """
    partes = [p for p in normalizar(nome_docente).split() if p]
    if not partes or not autores.strip():
        return "nao_visivel"
    proprias = {p for p in partes if p not in PARTES_COMUNS and len(p) > 2}
    comuns = {p for p in partes if p in PARTES_COMUNS}
    inicial = partes[0][0]

    for autor in re.split(r",|;", autores):
        palavras = normalizar(autor).split()
        if not palavras:
            continue
        sobrenome = palavras[-1]
        if sobrenome in proprias:
            return "ok"
        if sobrenome in comuns and palavras[0].startswith(inicial):
            return "ok"
        # Nome escrito por extenso ou invertido ("Pagano, Tiago")
        if any(p in proprias for p in palavras):
            return "ok"
    cortada = "..." in autores or "…" in autores
    return "nao_visivel" if cortada else "ausente"


# ---------------------------------------------------------------------------
# 3, 4 e 5. Embeddings
# ---------------------------------------------------------------------------
def vetores_dos_titulos(titulos_banco, titulos_novos):
    """Vetores dos títulos, pelo mesmo Ollama e mesmo cache de triagem_embeddings.py.

    O cache guarda só os vetores pedidos na chamada. Por isso também se pedem
    os textos que a triagem_embeddings.py usa: assim o cache dela não encolhe.
    """
    import triagem_embeddings as te
    with abrir_banco() as conn:
        textos_da_outra_triagem = [te.montar_texto(p) for p in te.ler_publicacoes(conn)]
    todos = textos_da_outra_triagem + titulos_banco + titulos_novos
    matriz = te.vetores_das_publicacoes(todos)
    inicio = len(textos_da_outra_triagem)
    meio = inicio + len(titulos_banco)
    return matriz[inicio:meio], matriz[meio:]


def idioma(titulo):
    import triagem_embeddings as te
    return te.idioma_titulo(titulo, None)


def mesmo_trabalho(titulo_a, ano_a, titulo_b, ano_b, valor):
    """Por que dois títulos podem ser o mesmo trabalho, ou "" (regra da seção 3.12)."""
    if valor >= LIMITE_SIMILAR_MESMO_IDIOMA:
        return "quase idênticos"
    a, b = idioma(titulo_a), idioma(titulo_b)
    idiomas_diferentes = "?" not in (a, b) and a != b
    # Sem ano em um dos dois, não dá para descartar: o par vai para conferência
    anos_proximos = ano_a is None or ano_b is None or abs(ano_a - ano_b) <= DIFERENCA_ANOS_TRADUCAO
    if idiomas_diferentes and anos_proximos and valor >= LIMITE_SIMILAR_TRADUCAO:
        return "possível tradução"
    return ""


def escore_robusto(valores):
    mediana = np.median(valores)
    desvio = 1.4826 * np.median(np.abs(valores - mediana))
    if desvio == 0:
        return np.zeros_like(valores)
    return (valores - mediana) / desvio


def analisar_embeddings(linhas, banco_por_docente, vetores_banco, vetores_novos):
    """Preenche os apontamentos ja_no_banco, repetido e destoa em cada linha."""
    for id_docente in sorted({l["id_docente"] for l in linhas}):
        idx_novos = [i for i, l in enumerate(linhas) if l["id_docente"] == id_docente]
        idx_banco = banco_por_docente.get(id_docente, [])
        vn = vetores_novos[idx_novos]
        vb = vetores_banco[[i for i, _ in idx_banco]] if idx_banco else np.zeros((0, vn.shape[1]))

        # 3. Mesmo trabalho que uma publicação do banco
        if len(idx_banco):
            sim_banco = vn @ vb.T
            for a, i in enumerate(idx_novos):
                l = linhas[i]
                j = int(np.argmax(sim_banco[a]))
                _, pub = idx_banco[j]
                motivo = mesmo_trabalho(l["titulo"], ano_inteiro(l["ano"]),
                                        pub["titulo"], pub["ano"], float(sim_banco[a, j]))
                if motivo:
                    l["_apont"].append("ja_no_banco")
                    l["_det"].append(f"{motivo} ({sim_banco[a, j]:.2f}) com o banco: {pub['titulo'][:90]}")

        # 4. Repetido entre as novas: fica a primeira com ano e veículo, as outras saem
        sim_novos = vn @ vn.T
        ordem = sorted(range(len(idx_novos)),
                       key=lambda a: (not linhas[idx_novos[a]]["ano"], not linhas[idx_novos[a]]["veiculo"], a))
        mantidas = []
        for a in ordem:
            l = linhas[idx_novos[a]]
            for b in mantidas:
                outra = linhas[idx_novos[b]]
                motivo = mesmo_trabalho(l["titulo"], ano_inteiro(l["ano"]),
                                        outra["titulo"], ano_inteiro(outra["ano"]), float(sim_novos[a, b]))
                if motivo:
                    l["_apont"].append("repetido")
                    l["_det"].append(f"{motivo} ({sim_novos[a, b]:.2f}) com outra nova: {outra['titulo'][:90]}")
                    break
            else:
                mantidas.append(a)

        # 5. Destoa: isolamento dentro de toda a produção do docente (banco + novas)
        pool = np.vstack([vb, vn])
        n = len(pool)
        if n < MINIMO_PUBLICACOES:
            for i in idx_novos:
                linhas[i]["_det"].append("poucas publicações para medir se destoa")
            continue
        sem = pool @ pool.T
        np.fill_diagonal(sem, -np.inf)
        k = min(VIZINHOS, n - 1)
        vizinhos = np.sort(sem, axis=1)[:, -k:].mean(axis=1)
        escores = escore_robusto(vizinhos)
        for a, i in enumerate(idx_novos):
            escore = float(escores[len(vb) + a])
            linhas[i]["escore"] = f"{escore:.2f}"
            if escore <= LIMITE_ISOLADO:
                linhas[i]["_apont"].append("destoa")


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------
def sugestao(apontamentos):
    if {"ja_excluido", "sem_conteudo", "ja_no_banco", "repetido"} & set(apontamentos):
        return "ignorar"
    if {"destoa", "autoria"} & set(apontamentos):
        return "conferir"
    return "incluir"


def chave(linha):
    return (linha["id_docente"], normalizar_titulo(linha["titulo"]))


def main(usar_embeddings=True):
    novas = ler_csv(ARQ_NOVAS)
    if not novas:
        raise SystemExit(f"{ARQ_NOVAS} não existe ou está vazio. Rode antes: python coleta/scholar.py validar")

    with abrir_banco() as conn:
        excluidos = titulos_excluidos(conn)
        import triagem_embeddings as te
        banco = te.ler_publicacoes(conn)  # o que entra nos perfis, com títulos corrigidos

    linhas = []
    for pub in novas:
        l = {c: pub.get(c, "") for c in COLUNAS}
        l["_apont"], l["_det"] = [], []

        # 1. Já excluído como homônimo
        t = normalizar_titulo(l["titulo"])
        if any(titulos_iguais(t, e) for e in excluidos.get(l["id_docente"], [])):
            l["_apont"].append("ja_excluido")
            l["_det"].append("trabalho já excluído antes como homônimo deste docente")

        # 2. Título sem conteúdo
        motivo = titulo_sem_conteudo(l["titulo"], l["nome_docente"])
        if motivo:
            l["_apont"].append("sem_conteudo")
            l["_det"].append(motivo)

        # 6. Autoria
        autoria = checar_autoria(l["autores"], l["nome_docente"])
        if autoria == "ausente":
            l["_apont"].append("autoria")
            l["_det"].append("nome do docente não aparece entre os autores")
        elif autoria == "nao_visivel":
            l["_det"].append("lista de autores cortada; nome não visível")

        if l["ano"] and ano_inteiro(l["ano"]) is None:
            l["_det"].append(f"ano inválido ({l['ano']})")
        linhas.append(l)

    # 3, 4 e 5: só com título com conteúdo e não excluído
    if usar_embeddings:
        validas = [l for l in linhas if not {"ja_excluido", "sem_conteudo"} & set(l["_apont"])]
        banco_por_docente, titulos_banco = {}, []
        for pub in banco:
            titulo = pub["titulo_corrigido"] or pub["titulo"]
            banco_por_docente.setdefault(str(pub["docente_id"]), []).append(
                (len(titulos_banco), {"titulo": titulo, "ano": pub["ano"]}))
            titulos_banco.append(titulo)
        vetores_banco, vetores_novos = vetores_dos_titulos(titulos_banco, [l["titulo"] for l in validas])
        analisar_embeddings(validas, banco_por_docente, vetores_banco, vetores_novos)

    # Monta as colunas finais e preserva o que você já decidiu
    antigas = {chave(l): l for l in ler_csv(ARQ_TRIAGEM)}
    for l in linhas:
        l["apontamentos"] = "; ".join(l["_apont"])
        l["detalhe"] = " | ".join(l["_det"])
        l["sugestao"] = sugestao(l["_apont"])
        antiga = antigas.get(chave(l), {})
        l["decisao"], l["observacao"] = antiga.get("decisao", ""), antiga.get("observacao", "")

    ordem = {"conferir": 0, "ignorar": 1, "incluir": 2}
    linhas.sort(key=lambda l: (ordem[l["sugestao"]], l["nome_docente"], l["titulo"]))
    gravar_csv(ARQ_TRIAGEM, COLUNAS, [{c: l.get(c, "") for c in COLUNAS} for l in linhas])

    # Resumo
    print("\nNada foi gravado no banco.")
    print(f"Publicações analisadas: {len(linhas)}")
    for s in ("incluir", "conferir", "ignorar"):
        print(f"  sugestão {s}: {sum(1 for l in linhas if l['sugestao'] == s)}")
    print("Apontamentos (uma publicação pode ter mais de um):")
    for a in ("ja_excluido", "sem_conteudo", "ja_no_banco", "repetido", "destoa", "autoria"):
        print(f"  {a}: {sum(1 for l in linhas if a in l['_apont'])}")
    if not usar_embeddings:
        print("  (ja_no_banco, repetido e destoa não foram analisados: rodou com --sem-embeddings)")
    else:
        escores = np.array([float(l["escore"]) for l in linhas if l["escore"]])
        if len(escores):
            print("Escore de isolamento das novas (para calibrar o limite de -3,0):")
            for p in (1, 5, 25, 50):
                print(f"  {p:>2}% abaixo de {np.percentile(escores, p):.2f}")
    print(f"\nPara conferir: {ARQ_TRIAGEM.relative_to(RAIZ)} (coluna decisao: incluir ou ignorar)")


def aprovar_sem_apontamento():
    linhas = ler_csv(ARQ_TRIAGEM)
    if not linhas:
        raise SystemExit(f"Rode antes a análise: {ARQ_TRIAGEM} não existe.")
    aprovadas = 0
    for l in linhas:
        if l["sugestao"] == "incluir" and not l["decisao"].strip():
            l["decisao"] = "incluir"
            l["observacao"] = l["observacao"] or "aprovada em bloco (sem apontamento)"
            aprovadas += 1
    gravar_csv(ARQ_TRIAGEM, COLUNAS, linhas)
    faltam = sum(1 for l in linhas if not l["decisao"].strip())
    print(f"{aprovadas} publicações aprovadas em bloco. Ainda sem decisão: {faltam}")


def codigo_obra(linha):
    """Código fixo da obra do Google Acadêmico: o mesmo docente e título geram o mesmo código."""
    import hashlib
    base = f"{linha['id_docente']}|{normalizar_titulo(linha['titulo'])}"
    return "GS-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def aplicar():
    import shutil
    linhas = ler_csv(ARQ_TRIAGEM)
    if not linhas:
        raise SystemExit(f"Rode antes a análise: {ARQ_TRIAGEM} não existe.")
    sem_decisao = [l for l in linhas if not l["decisao"].strip()]
    if sem_decisao:
        raise SystemExit(f"{len(sem_decisao)} linhas ainda sem decisão. Decida todas antes de gravar.")
    invalidas = {l["decisao"].strip().lower() for l in linhas} - {"incluir", "ignorar", "orientacao"}
    if invalidas:
        raise SystemExit(f"Decisões que não reconheço: {', '.join(sorted(invalidas))}. "
                         "Use incluir, ignorar ou orientacao.")
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")

    # Cópia de segurança do banco como estava antes do Google Acadêmico.
    # Só é feita na primeira vez: rodar de novo não pode apagar a cópia boa.
    copia = RAIZ / "dados" / "ponte_cetec_antes_scholar.db"
    if copia.exists():
        print(f"Cópia de segurança já existe (mantida): {copia.relative_to(RAIZ)}")
    else:
        shutil.copy2(ARQ_BANCO, copia)
        print(f"Cópia de segurança: {copia.relative_to(RAIZ)}")

    conn = sqlite3.connect(ARQ_BANCO)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orientacoes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            docente_id  INTEGER NOT NULL REFERENCES docentes(id),
            codigo      TEXT NOT NULL,
            titulo      TEXT NOT NULL,
            ano         INTEGER,
            autores     TEXT,
            veiculo     TEXT,
            fonte       TEXT,
            observacao  TEXT,
            incluido_em TEXT,
            UNIQUE (docente_id, codigo)
        )
        """
    )
    excluidas = {(str(d), o) for d, o in conn.execute("SELECT docente_id, openalex_id FROM publicacoes_excluidas")}

    novas = ja_estavam = barradas = orientacoes = removidas = 0
    for l in linhas:
        decisao = l["decisao"].strip().lower()
        codigo = codigo_obra(l)
        docente_id = int(l["id_docente"])

        if decisao == "incluir":
            if (l["id_docente"], codigo) in excluidas:
                barradas += 1  # você já excluiu esta obra antes: não volta
                continue
            cursor = conn.execute(
                """
                INSERT INTO publicacoes
                    (docente_id, openalex_id, titulo, ano, fonte, incluido_em)
                VALUES (?, ?, ?, ?, 'scholar', date('now'))
                ON CONFLICT(docente_id, openalex_id) DO NOTHING
                """,
                (docente_id, codigo, l["titulo"], ano_inteiro(l["ano"])),
            )
            if cursor.rowcount:
                novas += 1
            else:
                ja_estavam += 1
        else:
            # Se a obra tinha entrado antes e a decisão mudou, ela sai
            removidas += conn.execute(
                "DELETE FROM publicacoes WHERE docente_id = ? AND openalex_id = ? AND fonte = 'scholar'",
                (docente_id, codigo),
            ).rowcount

        if decisao == "orientacao":
            orientacoes += conn.execute(
                """
                INSERT INTO orientacoes
                    (docente_id, codigo, titulo, ano, autores, veiculo, fonte, observacao, incluido_em)
                VALUES (?, ?, ?, ?, ?, ?, 'scholar', ?, date('now'))
                ON CONFLICT(docente_id, codigo) DO NOTHING
                """,
                (docente_id, codigo, l["titulo"], ano_inteiro(l["ano"]), l["autores"], l["veiculo"], l["observacao"]),
            ).rowcount
        else:
            conn.execute("DELETE FROM orientacoes WHERE docente_id = ? AND codigo = ?", (docente_id, codigo))

    conn.commit()
    total = conn.execute("SELECT fonte, COUNT(*) FROM publicacoes GROUP BY fonte").fetchall()
    total_orient = conn.execute("SELECT COUNT(*) FROM orientacoes").fetchone()[0]
    conn.close()

    print(f"Publicações do Google Acadêmico gravadas agora: {novas}")
    print(f"  já estavam no banco: {ja_estavam} | barradas por exclusão anterior: {barradas} "
          f"| removidas por mudança de decisão: {removidas}")
    print(f"Orientações gravadas agora: {orientacoes} (total na tabela: {total_orient})")
    print("Publicações no banco por fonte: " + ", ".join(f"{f}: {n}" for f, n in total))


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    if "--aplicar" in argumentos:
        aplicar()
    elif "--aprovar-sem-apontamento" in argumentos:
        aprovar_sem_apontamento()
    else:
        main(usar_embeddings="--sem-embeddings" not in argumentos)
