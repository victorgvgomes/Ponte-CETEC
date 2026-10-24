"""Busca na OpenAlex o resumo das publicações que vieram do Google Acadêmico.

O Google Acadêmico só deu o título dessas publicações. Muitas existem na
OpenAlex, mas não estavam ligadas ao perfil do docente (perfis fragmentados).
Este script procura cada título na OpenAlex e, quando acha o MESMO trabalho,
propõe completar a publicação com resumo, DOI, tipo, idioma, tópicos e
palavras-chave.

Um resultado só conta como o mesmo trabalho quando:
  - o título é igual, ignorando acentos, maiúsculas e pontuação (ou um contém
    o outro, para títulos longos), pela mesma regra do scholar.py validar; e
  - o ano é compatível (até 1 ano de diferença), quando os dois têm ano.

Situações (coluna "situacao"):
  ENCONTRADO      -> mesmo trabalho, com o docente entre os autores. Sugestão: usar
  SEM_O_DOCENTE   -> mesmo título, mas o docente não aparece entre os autores
                     na OpenAlex. Sugestão: conferir (pode ser de outra pessoa)
  EXCLUIDO_ANTES  -> o trabalho achado é um que você já excluiu como homônimo
                     deste docente. Sugestão: nao_usar (e rever a publicação)
  JA_NO_BANCO     -> o trabalho achado já está no banco para este docente, vindo
                     da OpenAlex: a publicação do Google é repetida. Sugestão: nao_usar
  NAO_ENCONTRADO  -> nenhum resultado com o mesmo título
  ERRO_BUSCA      -> a OpenAlex recusou a busca deste título (ver observacao_busca)
  PENDENTE        -> a busca parou no limite de uso da OpenAlex; rode de novo depois

Cada título é buscado primeiro só no campo título; se nada voltar, é buscado de
novo de forma ampla (título, resumo e texto), que acha pequenas diferenças de
grafia. Nos dois casos o resultado ainda passa pela comparação de título e ano.

Uso:
  python coleta/scholar_openalex.py
      Só busca e analisa; não grava no banco. Gera dados/scholar_openalex.csv.
      As respostas da OpenAlex ficam em dados/scholar_openalex_cache.json:
      se parar no meio, rodar de novo continua de onde parou.

  python coleta/scholar_openalex.py --aprovar-encontrados
      Escreve "usar" na coluna decisao das linhas ENCONTRADO ainda em branco.

  python coleta/scholar_openalex.py --aplicar
      ÚNICO modo que grava no banco. Copia antes o banco para
      dados/ponte_cetec_antes_resumos.db (só na primeira vez). Para decisao = usar,
      completa a publicação; para decisao = nao_usar, desfaz um preenchimento
      feito antes por este script. O título e a origem (fonte = 'scholar') não
      mudam. Pode rodar mais de uma vez.
"""

import csv
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from openalex_publicacoes import API_KEY, URL_TRABALHOS, montar_resumo, nomes
from scholar import normalizar_titulo, titulos_iguais
from triagem_conteudo import normalizar

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).parent.parent
ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"
ARQ_SAIDA = RAIZ / "dados" / "scholar_openalex.csv"
ARQ_CACHE = RAIZ / "dados" / "scholar_openalex_cache.json"
ARQ_COPIA = RAIZ / "dados" / "ponte_cetec_antes_resumos.db"

CAMPOS = ("id,doi,title,publication_year,type,language,abstract_inverted_index,"
          "topics,keywords,authorships")
RESULTADOS_POR_BUSCA = 5
DIFERENCA_ANOS = 1
PAUSA = 0.2  # segundos entre as chamadas

# Partes de nome que não identificam ninguém sozinhas
PARTES_COMUNS = {"da", "de", "do", "das", "dos", "e", "filho", "junior", "neto", "sobrinho"}

COLUNAS = [
    "id_docente", "nome_docente", "codigo", "titulo_scholar", "ano_scholar",
    "situacao", "obra_openalex", "titulo_openalex", "ano_openalex", "autores_openalex",
    "tem_resumo", "doi", "sugestao", "decisao", "observacao", "observacao_busca",
]
SUGESTAO = {
    "ENCONTRADO": "usar",
    "SEM_O_DOCENTE": "conferir",
    "EXCLUIDO_ANTES": "nao_usar",
    "JA_NO_BANCO": "nao_usar",
    "NAO_ENCONTRADO": "",
    "ERRO_BUSCA": "",
    "PENDENTE": "",
}


# ---------------------------------------------------------------------------
# Arquivos
# ---------------------------------------------------------------------------
def ler_csv(caminho):
    if not caminho.exists():
        return []
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def gravar_csv(caminho, linhas):
    temporario = caminho.with_suffix(".tmp")
    with open(temporario, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS)
        escritor.writeheader()
        escritor.writerows(linhas)
    temporario.replace(caminho)


def ler_cache():
    if not ARQ_CACHE.exists():
        return {}
    return json.loads(ARQ_CACHE.read_text(encoding="utf-8"))


def gravar_cache(cache):
    temporario = ARQ_CACHE.with_suffix(".tmp")
    temporario.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    temporario.replace(ARQ_CACHE)


# ---------------------------------------------------------------------------
# Busca na OpenAlex
# ---------------------------------------------------------------------------
def texto_de_busca(titulo):
    """Título sem os caracteres que a OpenAlex usa como separador no filtro."""
    limpo = re.sub(r"[,:|()\"'“”\[\]{}!?;]", " ", titulo)
    return re.sub(r"\s+", " ", limpo).strip()[:250]


class LimiteOpenAlex(Exception):
    """A OpenAlex pediu para esperar várias vezes seguidas (limite de uso)."""


def chamar_openalex(params):
    """Uma chamada à OpenAlex. Devolve (resultados, erro); erro é "" quando deu certo."""
    params = dict(params, select=CAMPOS, per_page=RESULTADOS_POR_BUSCA, api_key=API_KEY)
    for tentativa in range(4):
        try:
            resp = requests.get(URL_TRABALHOS, params=params, timeout=60)
        except requests.RequestException:
            # A mensagem do erro não é mostrada porque traz a chave da API
            raise SystemExit("Não consegui falar com a OpenAlex. Confira a internet e rode de novo "
                             "(o que já foi buscado está guardado).")
        if resp.status_code == 429:  # muitas chamadas: espera e tenta de novo
            espera = resp.headers.get("Retry-After", "")
            time.sleep(min(int(espera), 60) if espera.isdigit() else 5 * (tentativa + 1))
            continue
        if resp.status_code == 200:
            return resp.json().get("results", []), ""
        if resp.status_code in (400, 403, 404):  # a busca não aceitou este texto
            return [], f"erro {resp.status_code}"
        raise SystemExit(f"A OpenAlex respondeu {resp.status_code}. Rode de novo mais tarde "
                         "(o que já foi buscado está guardado).")
    raise LimiteOpenAlex()


def buscar(pub, guardado):
    """Duas buscas, guardadas por publicação:
    1. "titulo": procura as palavras só no título (filtro title.search);
    2. "ampla": só se a primeira não trouxe nada, procura no título, no resumo e
       no texto (parâmetro search). Ela acha títulos com pequenas diferenças;
       o resultado continua tendo de passar pela comparação de título e ano.
    """
    guardado = dict(guardado or {})
    texto = texto_de_busca(pub["titulo"])
    if "titulo" not in guardado:
        guardado["titulo"], guardado["erro_titulo"] = chamar_openalex({"filter": f"title.search:{texto}"})
        time.sleep(PAUSA)
    if not guardado["titulo"] and "ampla" not in guardado:
        guardado["ampla"], guardado["erro_ampla"] = chamar_openalex({"search": texto})
        time.sleep(PAUSA)
    return guardado


def resultados(guardado):
    return (guardado or {}).get("titulo", []) + (guardado or {}).get("ampla", [])


# ---------------------------------------------------------------------------
# Comparação
# ---------------------------------------------------------------------------
def ano_inteiro(valor):
    try:
        ano = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return ano if 1950 <= ano <= 2100 else None


def nomes_dos_autores(trabalho):
    nomes_autores = []
    for autoria in trabalho.get("authorships") or []:
        nome = (autoria.get("author") or {}).get("display_name") or autoria.get("raw_author_name")
        if nome:
            nomes_autores.append(nome)
    return nomes_autores


def docente_entre_autores(nomes_autores, nome_docente):
    """True se algum autor tem um sobrenome do docente e o primeiro nome (ou a inicial) dele.

    Aceita as formas que a OpenAlex usa: "André Dias de Azevedo Neto",
    "A. D. Azevedo Neto", "Dias de Azevedo Neto André", "Azevedo Neto Ad".
    Exigir sobrenome e primeiro nome evita aceitar qualquer "Silva" ou "Santos".
    """
    partes = normalizar(nome_docente).split()
    if not partes:
        return False
    primeiro = partes[0]
    sobrenomes = {p for p in partes[1:] if p not in PARTES_COMUNS and len(p) > 2}
    for nome in nomes_autores:
        palavras = normalizar(nome).split()
        if len(palavras) < 2 or not any(p in sobrenomes for p in palavras):
            continue
        if primeiro in palavras:  # primeiro nome por extenso, em qualquer posição
            return True
        # Iniciais (palavras de até 3 letras que não são sobrenome nem "de", "da"...):
        # a primeira delas tem de começar pela inicial do docente
        iniciais = [p for p in palavras if len(p) <= 3 and p not in PARTES_COMUNS and p not in sobrenomes]
        if iniciais and iniciais[0][0] == primeiro[0]:
            return True
    return False


def mesmo_trabalho(titulo, ano, trabalho):
    if not titulos_iguais(normalizar_titulo(titulo), normalizar_titulo(trabalho.get("title") or "")):
        return False
    ano_oa = trabalho.get("publication_year")
    return ano is None or ano_oa is None or abs(ano - ano_oa) <= DIFERENCA_ANOS


def escolher(pub, resultados):
    """O resultado que é o mesmo trabalho: com o docente primeiro; depois com resumo."""
    iguais = [t for t in resultados if mesmo_trabalho(pub["titulo"], pub["ano"], t)]
    if not iguais:
        return None
    return max(iguais, key=lambda t: (docente_entre_autores(nomes_dos_autores(t), pub["docente"]),
                                      bool(t.get("abstract_inverted_index"))))


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def ler_publicacoes_scholar(conn):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT p.docente_id, d.nome AS docente, p.openalex_id AS codigo, p.titulo, p.ano
        FROM publicacoes p JOIN docentes d ON d.id = p.docente_id
        WHERE p.fonte = 'scholar'
        ORDER BY d.nome, p.titulo
        """
    ).fetchall()


def main():
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")
    conn = sqlite3.connect(f"file:{ARQ_BANCO}?mode=ro", uri=True)
    pubs = ler_publicacoes_scholar(conn)
    if not pubs:
        raise SystemExit("Nenhuma publicação com fonte = 'scholar' no banco. Rode antes o "
                         "python coleta/triagem_scholar.py --aplicar")
    excluidas = {(str(d), o) for d, o in conn.execute("SELECT docente_id, openalex_id FROM publicacoes_excluidas")}
    no_banco = {(str(d), o) for d, o in conn.execute(
        "SELECT docente_id, openalex_id FROM publicacoes WHERE fonte = 'openalex'")}
    conn.close()

    # 1. Busca (com cache)
    cache = ler_cache()
    # Execuções antigas guardavam só a lista da busca por título
    cache = {k: ({"titulo": v, "erro_titulo": ""} if isinstance(v, list) else v) for k, v in cache.items()}

    def completo(g):
        return g and "titulo" in g and (g["titulo"] or "ampla" in g)

    faltam = [p for p in pubs if not completo(cache.get(p["codigo"]))]
    print(f"{len(pubs)} publicações do Google Acadêmico; {len(pubs) - len(faltam)} já buscadas, "
          f"{len(faltam)} a buscar.")
    parou = False
    try:
        for i, pub in enumerate(faltam, start=1):
            cache[pub["codigo"]] = buscar(pub, cache.get(pub["codigo"]))
            if i % 25 == 0 or i == len(faltam):
                gravar_cache(cache)
                print(f"  {i} de {len(faltam)} buscadas")
    except LimiteOpenAlex:
        parou = True
    finally:
        gravar_cache(cache)  # nada do que já foi buscado se perde
    pendentes = {p["codigo"] for p in pubs if not completo(cache.get(p["codigo"]))}
    if parou:
        print(f"\nA OpenAlex atingiu o limite de uso. {len(pendentes)} publicações ficaram pendentes; "
              "rode de novo mais tarde (de preferência no dia seguinte) para buscá-las.")

    # 2. Comparação
    antigas = {l["codigo"]: l for l in ler_csv(ARQ_SAIDA)}
    linhas = []
    for pub in pubs:
        d = {"titulo": pub["titulo"], "ano": pub["ano"], "docente": pub["docente"]}
        guardado = cache.get(pub["codigo"])
        achado = escolher(d, resultados(guardado))
        linha = {c: "" for c in COLUNAS}
        linha.update({
            "id_docente": pub["docente_id"], "nome_docente": pub["docente"], "codigo": pub["codigo"],
            "titulo_scholar": pub["titulo"], "ano_scholar": pub["ano"] or "",
        })
        erros = [e for e in ((guardado or {}).get("erro_titulo"), (guardado or {}).get("erro_ampla")) if e]
        if achado is None and pub["codigo"] in pendentes:
            situacao = "PENDENTE"
        elif achado is None:
            situacao = "ERRO_BUSCA" if erros and not resultados(guardado) else "NAO_ENCONTRADO"
            linha["observacao_busca"] = "; ".join(erros)
        else:
            obra = achado["id"].rsplit("/", 1)[-1]
            autores = nomes_dos_autores(achado)
            chave = (str(pub["docente_id"]), obra)
            if chave in excluidas:
                situacao = "EXCLUIDO_ANTES"
            elif chave in no_banco:
                situacao = "JA_NO_BANCO"
            elif docente_entre_autores(autores, pub["docente"]):
                situacao = "ENCONTRADO"
            else:
                situacao = "SEM_O_DOCENTE"
            linha.update({
                "obra_openalex": obra,
                "titulo_openalex": achado.get("title") or "",
                "ano_openalex": achado.get("publication_year") or "",
                "autores_openalex": "; ".join(autores[:8]) + (" ..." if len(autores) > 8 else ""),
                "tem_resumo": "sim" if achado.get("abstract_inverted_index") else "",
                "doi": achado.get("doi") or "",
            })
        linha["situacao"] = situacao
        linha["sugestao"] = SUGESTAO[situacao]
        antiga = antigas.get(pub["codigo"], {})
        linha["decisao"], linha["observacao"] = antiga.get("decisao", ""), antiga.get("observacao", "")
        linhas.append(linha)

    ordem = {"SEM_O_DOCENTE": 0, "EXCLUIDO_ANTES": 1, "JA_NO_BANCO": 2, "ENCONTRADO": 3,
             "NAO_ENCONTRADO": 4, "ERRO_BUSCA": 5, "PENDENTE": 6}
    linhas.sort(key=lambda l: (ordem[l["situacao"]], l["nome_docente"], l["titulo_scholar"]))
    gravar_csv(ARQ_SAIDA, linhas)

    print("\nNada foi gravado no banco.")
    for situacao in ordem:
        qtd = [l for l in linhas if l["situacao"] == situacao]
        com_resumo = sum(1 for l in qtd if l["tem_resumo"])
        extra = f" ({com_resumo} com resumo)" if situacao not in ("NAO_ENCONTRADO", "ERRO_BUSCA", "PENDENTE") else ""
        print(f"  {situacao}: {len(qtd)}{extra}")
    print(f"\nPara conferir: {ARQ_SAIDA.relative_to(RAIZ)} (coluna decisao: usar ou nao_usar)")


# ---------------------------------------------------------------------------
# Aprovação e gravação
# ---------------------------------------------------------------------------
def aprovar_encontrados():
    linhas = ler_csv(ARQ_SAIDA)
    if not linhas:
        raise SystemExit(f"Rode antes a análise: {ARQ_SAIDA} não existe.")
    aprovadas = 0
    for l in linhas:
        if l["situacao"] == "ENCONTRADO" and not l["decisao"].strip():
            l["decisao"] = "usar"
            l["observacao"] = l["observacao"] or "aprovada em bloco (ENCONTRADO)"
            aprovadas += 1
    gravar_csv(ARQ_SAIDA, linhas)
    print(f"{aprovadas} linhas ENCONTRADO aprovadas em bloco.")
    pendentes = [l for l in linhas if l["situacao"] in ("SEM_O_DOCENTE", "EXCLUIDO_ANTES", "JA_NO_BANCO")
                 and not l["decisao"].strip()]
    print(f"Ainda sem decisão (SEM_O_DOCENTE, EXCLUIDO_ANTES, JA_NO_BANCO): {len(pendentes)}")


def aplicar():
    linhas = ler_csv(ARQ_SAIDA)
    if not linhas:
        raise SystemExit(f"Rode antes a análise: {ARQ_SAIDA} não existe.")
    invalidas = {l["decisao"].strip().lower() for l in linhas} - {"", "usar", "nao_usar"}
    if invalidas:
        raise SystemExit(f"Decisões que não reconheço: {', '.join(sorted(invalidas))}. Use usar ou nao_usar.")
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")

    if ARQ_COPIA.exists():
        print(f"Cópia de segurança já existe (mantida): {ARQ_COPIA.relative_to(RAIZ)}")
    else:
        shutil.copy2(ARQ_BANCO, ARQ_COPIA)
        print(f"Cópia de segurança: {ARQ_COPIA.relative_to(RAIZ)}")

    cache = ler_cache()
    conn = sqlite3.connect(ARQ_BANCO)
    colunas = {c[1] for c in conn.execute("PRAGMA table_info(publicacoes)")}
    if "obra_openalex" not in colunas:
        # Código W... do trabalho achado na OpenAlex; o openalex_id continua com o GS-...
        conn.execute("ALTER TABLE publicacoes ADD COLUMN obra_openalex TEXT")

    completadas = desfeitas = sem_resposta = 0
    for l in linhas:
        decisao = l["decisao"].strip().lower()
        chave = (int(l["id_docente"]), l["codigo"])
        if decisao == "usar":
            guardado = cache.get(l["codigo"])
            if isinstance(guardado, list):
                guardado = {"titulo": guardado}
            achado = next((t for t in resultados(guardado)
                           if t["id"].rsplit("/", 1)[-1] == l["obra_openalex"]), None)
            if achado is None:
                sem_resposta += 1
                continue
            completadas += conn.execute(
                """
                UPDATE publicacoes
                SET resumo = ?, doi = ?, tipo = ?, idioma = ?, topicos = ?, palavras_chave = ?,
                    ano = COALESCE(ano, ?), obra_openalex = ?
                WHERE docente_id = ? AND openalex_id = ? AND fonte = 'scholar'
                """,
                (montar_resumo(achado.get("abstract_inverted_index")), achado.get("doi"),
                 achado.get("type"), achado.get("language"), nomes(achado.get("topics")),
                 nomes(achado.get("keywords")), achado.get("publication_year"),
                 l["obra_openalex"], *chave),
            ).rowcount
        elif decisao == "nao_usar":
            # Desfaz só o que este script tenha preenchido antes
            desfeitas += conn.execute(
                """
                UPDATE publicacoes
                SET resumo = NULL, doi = NULL, tipo = NULL, idioma = NULL, topicos = NULL,
                    palavras_chave = NULL, obra_openalex = NULL
                WHERE docente_id = ? AND openalex_id = ? AND fonte = 'scholar'
                  AND obra_openalex IS NOT NULL
                """,
                chave,
            ).rowcount
    conn.commit()
    resumo_total = conn.execute(
        "SELECT COUNT(*), COUNT(resumo) FROM publicacoes WHERE fonte = 'scholar'").fetchone()
    conn.close()

    print(f"Publicações completadas: {completadas} | preenchimentos desfeitos: {desfeitas}")
    if sem_resposta:
        print(f"{sem_resposta} linhas com 'usar' sem resposta guardada: rode a análise de novo.")
    print(f"Publicações do Google Acadêmico com resumo agora: {resumo_total[1]} de {resumo_total[0]}")
    print("Lembrete: as marcadas EXCLUIDO_ANTES ou JA_NO_BANCO devem virar 'ignorar' em "
          "dados/triagem_scholar.csv, seguido de python coleta/triagem_scholar.py --aplicar")


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    if "--aplicar" in argumentos:
        aplicar()
    elif "--aprovar-encontrados" in argumentos:
        aprovar_encontrados()
    else:
        main()
