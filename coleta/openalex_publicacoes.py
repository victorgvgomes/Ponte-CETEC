"""Baixa do OpenAlex as publicações de cada perfil vinculado a um docente.

Lê os perfis com status "vinculado" na tabela docente_openalex e grava os
trabalhos na tabela publicacoes. Se um docente tem vários perfis, ou se o
script roda mais de uma vez, o mesmo trabalho não é duplicado.

Perfis com status "misto" (que misturam trabalhos de várias pessoas) não são
baixados automaticamente: use --mistos para listar os trabalhos deles e
--incluir para gravar só os que forem do docente.

Uso:
    python coleta/openalex_publicacoes.py            # só perfis ainda não baixados
    python coleta/openalex_publicacoes.py --refazer  # baixa todos de novo
    python coleta/openalex_publicacoes.py --mistos   # lista trabalhos dos perfis mistos (não grava)
    python coleta/openalex_publicacoes.py --incluir 24 W123 W456   # grava esses trabalhos para o docente 24
    python coleta/openalex_publicacoes.py --excluir 24 W123 W456   # remove esses trabalhos do docente 24, de forma definitiva
    python coleta/openalex_publicacoes.py --perfis                 # relatório dos docentes com mais de um perfil (não grava)
    python coleta/openalex_publicacoes.py --rejeitar-perfil A123   # rejeita o perfil e apaga os trabalhos que vieram dele

O --excluir serve para perfis que são do docente mas trazem alguns trabalhos de
homônimos: os trabalhos excluídos são apagados e ficam registrados na tabela
publicacoes_excluidas, de modo que um novo download não os traz de volta.

Cada publicação guarda o perfil de onde veio (perfil_openalex) e a data em que
entrou no banco (incluido_em). Isso permite conferir perfil por perfil e ver o
que entrou de novo para os docentes que já tiveram trabalhos excluídos.
"""

import csv
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
UFRB_ID = "I129192303"
URL_TRABALHOS = "https://api.openalex.org/works"
ARQ_BANCO = RAIZ / "dados" / "ponte_cetec.db"

CAMPOS = "id,doi,title,publication_year,type,language,abstract_inverted_index,topics,keywords"

if not API_KEY:
    raise RuntimeError("OPENALEX_KEY não encontrada. Confira o arquivo .env na raiz do projeto.")


# ---------------------------------------------------------------------------
# Busca no OpenAlex
# ---------------------------------------------------------------------------
def buscar_trabalhos(openalex_id, so_ufrb=False):
    """Devolve os trabalhos de um perfil de autor, percorrendo as páginas.

    Com so_ufrb=True, só os trabalhos em que algum autor declarou afiliação à UFRB.
    """
    filtro = f"authorships.author.id:{openalex_id}"
    if so_ufrb:
        filtro += f",authorships.institutions.id:{UFRB_ID}"

    params = {
        "filter": filtro,
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


def buscar_trabalho(trabalho_id):
    """Busca um único trabalho pelo ID (W123...)."""
    resp = requests.get(f"{URL_TRABALHOS}/{trabalho_id}", params={"api_key": API_KEY}, timeout=60)
    resp.raise_for_status()
    time.sleep(0.2)
    return resp.json()


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
        "perfil_openalex": "TEXT",  # A123..., perfil de onde o trabalho veio ("manual" se incluído à mão)
        "incluido_em": "TEXT",      # data em que o trabalho entrou no banco
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

    # trabalhos que não pertencem ao docente, apesar de estarem em um perfil dele
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS publicacoes_excluidas (
            docente_id  INTEGER NOT NULL REFERENCES docentes(id),
            openalex_id TEXT    NOT NULL,
            excluido_em TEXT    NOT NULL,
            PRIMARY KEY (docente_id, openalex_id)
        )
        """
    )

    # impede que o mesmo trabalho seja gravado duas vezes para o mesmo docente
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_publicacoes_obra ON publicacoes(docente_id, openalex_id)"
    )


def gravar_trabalho(conn, docente_id, trabalho, perfil):
    """Grava o trabalho; se ele já existe para o docente, atualiza os dados.

    Devolve True quando o trabalho é novo no banco. O perfil de origem e a data
    de inclusão são gravados na primeira vez e não mudam depois.
    """
    trabalho_id = trabalho["id"].rsplit("/", 1)[-1]  # fica só o W123...
    ja_existia = conn.execute(
        "SELECT 1 FROM publicacoes WHERE docente_id = ? AND openalex_id = ?", (docente_id, trabalho_id)
    ).fetchone()

    conn.execute(
        """
        INSERT INTO publicacoes
            (docente_id, openalex_id, titulo, resumo, ano, doi, tipo, idioma, topicos, palavras_chave,
             fonte, perfil_openalex, incluido_em)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'openalex', ?, date('now'))
        ON CONFLICT(docente_id, openalex_id) DO UPDATE SET
            titulo = excluded.titulo,
            resumo = excluded.resumo,
            ano = excluded.ano,
            doi = excluded.doi,
            tipo = excluded.tipo,
            idioma = excluded.idioma,
            topicos = excluded.topicos,
            palavras_chave = excluded.palavras_chave,
            perfil_openalex = COALESCE(perfil_openalex, excluded.perfil_openalex)
        """,
        (
            docente_id,
            trabalho_id,
            trabalho["title"],
            montar_resumo(trabalho.get("abstract_inverted_index")),
            trabalho.get("publication_year"),
            trabalho.get("doi"),
            trabalho.get("type"),
            trabalho.get("language"),
            nomes(trabalho.get("topics")),
            nomes(trabalho.get("keywords")),
            perfil,
        ),
    )
    return ja_existia is None


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
def excluidos_do_docente(conn, docente_id):
    """IDs dos trabalhos marcados como não pertencentes ao docente."""
    linhas = conn.execute(
        "SELECT openalex_id FROM publicacoes_excluidas WHERE docente_id = ?", (docente_id,)
    )
    return {linha[0] for linha in linhas}


def baixar_vinculados(conn, refazer):
    """Baixa os trabalhos de todos os perfis vinculados."""
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

    # docentes que já tiveram trabalhos excluídos: o que entrar de novo para eles é mostrado no final
    em_observacao = {linha[0] for linha in conn.execute("SELECT DISTINCT docente_id FROM publicacoes_excluidas")}
    novos_a_conferir = []

    for docente_id, openalex_id, nome in perfis:
        excluidos = excluidos_do_docente(conn, docente_id)
        gravados = 0
        for trabalho in buscar_trabalhos(openalex_id):
            if not trabalho.get("title"):
                continue  # sem título não há o que aproveitar
            if trabalho["id"].rsplit("/", 1)[-1] in excluidos:
                continue  # marcado à mão como sendo de outra pessoa
            novo = gravar_trabalho(conn, docente_id, trabalho, openalex_id)
            gravados += 1
            if novo and docente_id in em_observacao:
                novos_a_conferir.append((docente_id, nome, trabalho))

        conn.execute(
            "UPDATE docente_openalex SET publicacoes_em = date('now') WHERE docente_id = ? AND openalex_id = ?",
            (docente_id, openalex_id),
        )
        conn.commit()  # salva a cada perfil: se a API cair, o que já foi feito fica
        print(f"  {gravados:>4} {'trabalho ' if gravados == 1 else 'trabalhos'}  {openalex_id}  {nome}")

    if novos_a_conferir:
        print("\nTrabalhos NOVOS de docentes que já tiveram trabalhos excluídos (confira se são deles):")
        for docente_id, nome, trabalho in novos_a_conferir:
            trabalho_id = trabalho["id"].rsplit("/", 1)[-1]
            print(f"  docente {docente_id}  {nome}")
            print(f"    {trabalho_id}  {trabalho.get('publication_year')}  {trabalho['title'][:90]}")
        print("  Para remover: python coleta/openalex_publicacoes.py --excluir ID_DO_DOCENTE W123 W456")


def listar_mistos(conn):
    """Mostra, sem gravar nada, os trabalhos com afiliação UFRB dos perfis mistos."""
    perfis = conn.execute(
        """
        SELECT v.docente_id, v.openalex_id, d.nome
        FROM docente_openalex v
        JOIN docentes d ON d.id = v.docente_id
        WHERE v.status = 'misto'
        ORDER BY v.docente_id
        """
    ).fetchall()
    if not perfis:
        print("Nenhum perfil com status misto.")
        return

    for docente_id, openalex_id, nome in perfis:
        print(f"\nDocente {docente_id}: {nome}  (perfil {openalex_id})")
        trabalhos = buscar_trabalhos(openalex_id, so_ufrb=True)
        if not trabalhos:
            print("  nenhum trabalho com afiliação UFRB")
        for t in trabalhos:
            print(f"  {t['id'].rsplit('/', 1)[-1]}  {t.get('publication_year')}  {t.get('title')}")

    print("\nPara gravar os que forem do docente:")
    print("  python coleta/openalex_publicacoes.py --incluir ID_DO_DOCENTE W123 W456")


def incluir_trabalhos(conn, argumentos):
    """Grava trabalhos escolhidos à mão: primeiro o id do docente, depois os IDs W..."""
    if len(argumentos) < 2 or not argumentos[0].isdigit():
        raise SystemExit("Uso: --incluir ID_DO_DOCENTE W123 W456 ...")

    docente_id, ids = int(argumentos[0]), argumentos[1:]
    linha = conn.execute("SELECT nome FROM docentes WHERE id = ?", (docente_id,)).fetchone()
    if not linha:
        raise SystemExit(f"Não existe docente com id {docente_id}.")
    print(f"Incluindo trabalhos para {linha[0]}:")

    excluidos = excluidos_do_docente(conn, docente_id)
    for trabalho_id in ids:
        trabalho = buscar_trabalho(trabalho_id)
        if not trabalho.get("title"):
            print(f"  {trabalho_id}  ignorado (sem título)")
            continue
        if trabalho["id"].rsplit("/", 1)[-1] in excluidos:
            print(f"  {trabalho_id}  ignorado (está na lista de excluídos desse docente)")
            continue
        gravar_trabalho(conn, docente_id, trabalho, "manual")
        print(f"  {trabalho_id}  {trabalho.get('publication_year')}  {trabalho['title']}")
    conn.commit()


def excluir_trabalhos(conn, argumentos):
    """Remove trabalhos que não são do docente e impede que voltem em um novo download."""
    if len(argumentos) < 2 or not argumentos[0].isdigit():
        raise SystemExit("Uso: --excluir ID_DO_DOCENTE W123 W456 ...")

    docente_id, ids = int(argumentos[0]), argumentos[1:]
    linha = conn.execute("SELECT nome FROM docentes WHERE id = ?", (docente_id,)).fetchone()
    if not linha:
        raise SystemExit(f"Não existe docente com id {docente_id}.")
    print(f"Excluindo trabalhos de {linha[0]}:")

    for trabalho_id in ids:
        titulo = conn.execute(
            "SELECT titulo FROM publicacoes WHERE docente_id = ? AND openalex_id = ?",
            (docente_id, trabalho_id),
        ).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO publicacoes_excluidas (docente_id, openalex_id, excluido_em) VALUES (?, ?, date('now'))",
            (docente_id, trabalho_id),
        )
        conn.execute(
            "DELETE FROM publicacoes WHERE docente_id = ? AND openalex_id = ?",
            (docente_id, trabalho_id),
        )
        print(f"  {trabalho_id}  {titulo[0] if titulo else '(não estava no banco; ficou só registrado)'}")
    conn.commit()


def amostra(itens, quantidade=10):
    """Até `quantidade` itens, espalhados do início ao fim da lista."""
    if len(itens) <= quantidade:
        return itens
    passo = (len(itens) - 1) / (quantidade - 1)
    return [itens[round(i * passo)] for i in range(quantidade)]


def relatorio_perfis(conn):
    """Mostra, para cada docente com mais de um perfil, os títulos de cada perfil secundário.

    Não grava nada. Serve para conferir se um perfil inteiro é de outra pessoa.
    O perfil principal é o que tem mais trabalhos; dele são mostrados até dez
    títulos, espalhados ao longo dos anos, como referência da área do docente.
    """
    linhas = conn.execute(
        """
        SELECT p.docente_id, d.nome, p.perfil_openalex, p.openalex_id, p.ano, p.titulo
        FROM publicacoes p
        JOIN docentes d ON d.id = p.docente_id
        WHERE p.perfil_openalex IS NOT NULL AND p.perfil_openalex != 'manual'
        ORDER BY p.docente_id, p.perfil_openalex, p.ano
        """
    ).fetchall()
    if not linhas:
        print("Nenhuma publicação tem o perfil de origem registrado.")
        print("Rode antes: python coleta/openalex_publicacoes.py --refazer")
        return

    por_docente = {}  # docente_id -> {"nome": ..., "perfis": {perfil: [(trabalho, ano, titulo)]}}
    for docente_id, nome, perfil, trabalho_id, ano, titulo in linhas:
        docente = por_docente.setdefault(docente_id, {"nome": nome, "perfis": {}})
        docente["perfis"].setdefault(perfil, []).append((trabalho_id, ano, titulo))

    registros = []
    secundarios = 0
    for docente_id, docente in por_docente.items():
        perfis = sorted(docente["perfis"].items(), key=lambda item: len(item[1]), reverse=True)
        if len(perfis) < 2:
            continue
        principal, trabalhos_principal = perfis[0]
        print(f"\nDocente {docente_id}: {docente['nome']}")
        print(f"  principal  {principal}  ({len(trabalhos_principal)} trabalhos), por exemplo:")
        for _, ano, titulo in amostra(trabalhos_principal):
            print(f"      {ano}  {titulo[:85]}")
        for perfil, trabalhos in perfis[1:]:
            secundarios += 1
            print(f"  secundário {perfil}  ({len(trabalhos)}):")
            for trabalho_id, ano, titulo in trabalhos:
                print(f"      {trabalho_id}  {ano}  {titulo[:85]}")
                registros.append({
                    "docente_id": docente_id, "nome": docente["nome"], "perfil_principal": principal,
                    "perfil": perfil, "trabalho": trabalho_id, "ano": ano, "titulo": titulo,
                })

    arquivo = RAIZ / "dados" / "openalex_perfis.csv"
    with open(arquivo, "w", encoding="utf-8-sig", newline="") as f:
        campos = ["docente_id", "nome", "perfil_principal", "perfil", "trabalho", "ano", "titulo"]
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(registros)

    print(f"\n{secundarios} perfis secundários, com {len(registros)} trabalhos. Detalhes em {arquivo}")
    print("Perfil inteiro de outra pessoa:  python coleta/openalex_publicacoes.py --rejeitar-perfil A123")
    print("Só alguns trabalhos alheios:     python coleta/openalex_publicacoes.py --excluir ID_DO_DOCENTE W123")


def rejeitar_perfis(conn, perfis):
    """Marca os perfis como rejeitados e apaga os trabalhos que vieram deles."""
    if not perfis or not all(p.startswith("A") for p in perfis):
        raise SystemExit("Uso: --rejeitar-perfil A123 A456 ...")

    for perfil in perfis:
        vinculos = conn.execute(
            """
            SELECT v.docente_id, d.nome, v.status
            FROM docente_openalex v JOIN docentes d ON d.id = v.docente_id
            WHERE v.openalex_id = ?
            """,
            (perfil,),
        ).fetchall()
        if not vinculos:
            print(f"  {perfil}  não está ligado a nenhum docente; nada feito")
            continue
        for docente_id, nome, status in vinculos:
            apagados = conn.execute(
                "DELETE FROM publicacoes WHERE docente_id = ? AND perfil_openalex = ?", (docente_id, perfil)
            ).rowcount
            conn.execute(
                "UPDATE docente_openalex SET status = 'rejeitado' WHERE docente_id = ? AND openalex_id = ?",
                (docente_id, perfil),
            )
            palavra = "trabalho apagado" if apagados == 1 else "trabalhos apagados"
            print(f"  {perfil}  rejeitado para {nome} (era {status}); {apagados} {palavra}")
    conn.commit()


def main():
    args = sys.argv[1:]

    # sqlite3.connect cria um banco vazio se o arquivo não existir; melhor parar antes
    if not ARQ_BANCO.exists() or ARQ_BANCO.stat().st_size == 0:
        raise SystemExit(f"Banco não encontrado ou vazio: {ARQ_BANCO}")

    with sqlite3.connect(ARQ_BANCO) as conn:
        preparar_banco(conn)

        if "--mistos" in args:
            listar_mistos(conn)
            return  # só consulta; não muda o banco
        if "--perfis" in args:
            relatorio_perfis(conn)
            return  # só consulta; não muda o banco
        if "--rejeitar-perfil" in args:
            rejeitar_perfis(conn, args[args.index("--rejeitar-perfil") + 1:])
        elif "--excluir" in args:
            excluir_trabalhos(conn, args[args.index("--excluir") + 1:])
        elif "--incluir" in args:
            incluir_trabalhos(conn, args[args.index("--incluir") + 1:])
        else:
            baixar_vinculados(conn, refazer="--refazer" in args)

        total, com_resumo, sem_resumo, docentes = conn.execute(SQL_RESUMO).fetchone()

    print()
    print(f"Publicações no banco: {total}")
    print(f"  com resumo: {com_resumo}")
    print(f"  sem resumo: {sem_resumo}")
    print(f"Docentes com ao menos uma publicação: {docentes}")


if __name__ == "__main__":
    main()