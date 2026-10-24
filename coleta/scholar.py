"""
Robô do Google Acadêmico — Ponte-CETEC

Coleta perfis do Google Acadêmico de docentes da UFRB em 3 passos.
Cada passo é um comando separado, e você confere o resultado antes do próximo:

  1) python coleta/scholar.py listar
     Varre a busca de perfis com e-mail confirmado em ufrb.edu.br
     e salva TODOS os perfis da UFRB em dados/scholar_perfis_ufrb.csv

  2) python coleta/scholar.py cruzar
     Compara esses perfis com os docentes do CETEC (banco SQLite)
     e gera dados/scholar_vinculos.csv com sugestões (FORTE / VERIFICAR).
     Você abre o CSV e preenche a coluna "decisao" com: vincular, rejeitar ou incerto.

  3) python coleta/scholar.py coletar
     Para cada linha com decisao = vincular, abre o perfil e salva
     métricas e publicações em dados/scholar_metricas.csv e dados/scholar_publicacoes.csv

  4) python coleta/scholar.py validar
     Proteção contra homônimos: compara os títulos coletados no Google Acadêmico
     com as publicações já validadas no banco (OpenAlex + ORCID) de cada docente.
     Gera dados/scholar_validacao.csv com o resultado por perfil:
       CONFIRMADO  -> pelo menos MINIMO_TITULOS_EM_COMUM títulos iguais
       A_CONFERIR  -> poucos ou nenhum título em comum (você estuda o caso)
       SEM_BASE    -> o docente não tem publicações no banco para comparar
     A coluna "decisao_manual" é sua: escreva "confirmado" ou "rejeitado" (com o motivo,
     se quiser). Ela é mantida quando o validar roda de novo.
     Também gera dados/scholar_publicacoes_novas.csv: as publicações dos perfis
     confirmados que NÃO estão no banco (candidatas a entrar, para você conferir).

Regras do projeto respeitadas:
  - Este script NÃO grava no banco, só lê. Tudo sai em CSV.
  - Nada é vinculado automaticamente: o script sugere, você decide no CSV.
  - Antes de rodar, abra o Chrome do robô e faça login no Google nele:
      open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-robo"
    O script se conecta a essa janela (o Google exige login para buscar perfis).
  - Se aparecer CAPTCHA,
    você resolve na janela e aperta Enter no terminal para continuar.
    Se o CAPTCHA insistir, o script para, salva o que já coletou e,
    ao rodar de novo, continua de onde parou.
"""

import csv
import os
import random
import re
import sqlite3
import sys
import time
import unicodedata

from urllib.parse import urlencode

from bs4 import BeautifulSoup


# ----------------------------------------------------------------------
# CONFIGURAÇÕES — ajuste aqui se precisar
# ----------------------------------------------------------------------

# Banco do projeto e onde estão os nomes dos docentes do CETEC
CAMINHO_BANCO = "dados/ponte_cetec.db"
TABELA_DOCENTES = "docentes"      # nome da tabela de docentes no seu banco
COLUNA_ID = "id"                  # coluna com o id do docente
COLUNA_NOME = "nome"              # coluna com o nome completo do docente

# Arquivos de saída
ARQ_PERFIS = "dados/scholar_perfis_ufrb.csv"
ARQ_VINCULOS = "dados/scholar_vinculos.csv"
ARQ_METRICAS = "dados/scholar_metricas.csv"
ARQ_PUBLICACOES = "dados/scholar_publicacoes.csv"
ARQ_VALIDACAO = "dados/scholar_validacao.csv"
ARQ_NOVAS = "dados/scholar_publicacoes_novas.csv"

# Tabela de publicações já validadas (OpenAlex + ORCID)
TABELA_PUBLICACOES = "publicacoes"
COLUNA_DOCENTE_PUB = "docente_id"
COLUNA_TITULO_PUB = "titulo"

# Quantos títulos em comum bastam para confirmar que o perfil é do docente
MINIMO_TITULOS_EM_COMUM = 2

# Busca de perfis: "ufrb.edu.br" encontra quem confirmou o e-mail da UFRB
TERMO_BUSCA = "ufrb.edu.br"

# Pausa entre acessos (segundos). Pausas longas reduzem a chance de CAPTCHA.
PAUSA_MIN = 8
PAUSA_MAX = 20

ENDERECO_BASE = "https://scholar.google.com"

# Palavras que não contam na comparação de nomes
PALAVRAS_IGNORADAS = {"da", "de", "do", "das", "dos", "e"}


class BloqueioCaptcha(Exception):
    """Levantada quando o Google pede CAPTCHA ou bloqueia o acesso."""


# ----------------------------------------------------------------------
# ACESSO ÀS PÁGINAS
# ----------------------------------------------------------------------

# O Chrome só é aberto no primeiro acesso e reaproveitado depois
navegador = None


# Endereço do Chrome que VOCÊ abre pelo terminal antes de rodar o script
ENDERECO_CHROME = "127.0.0.1:9222"


def abrir_navegador():
    """Conecta o Selenium ao Chrome que você abriu e onde já fez login no Google.
    (O Google exige login para buscar perfis e bloqueia login em janela aberta por robô.)"""
    global navegador
    if navegador is None:
        from selenium import webdriver
        opcoes = webdriver.ChromeOptions()
        opcoes.debugger_address = ENDERECO_CHROME
        try:
            navegador = webdriver.Chrome(options=opcoes)
        except Exception:
            print("Não achei o Chrome aberto para o robô. Abra-o primeiro com o comando:")
            print('  open -na "Google Chrome" --args --remote-debugging-port=9222 '
                  '--user-data-dir="$HOME/chrome-robo"')
            print("Faça login no Google nessa janela e rode o script de novo.")
            sys.exit(1)
    return navegador


def pausar():
    """Espera um tempo aleatório entre PAUSA_MIN e PAUSA_MAX."""
    segundos = random.uniform(PAUSA_MIN, PAUSA_MAX)
    print(f"   aguardando {segundos:.0f}s...")
    time.sleep(segundos)


def baixar_pagina(endereco, parametros):
    """Abre a página no Chrome e devolve o HTML.
    Se aparecer CAPTCHA, espera você resolver na janela do Chrome."""
    chrome = abrir_navegador()
    chrome.get(endereco + "?" + urlencode(parametros))
    time.sleep(2)  # tempo para a página carregar
    html = chrome.page_source

    if pagina_tem_captcha(html):
        print("   >>> CAPTCHA: resolva na janela do Chrome e aperte Enter aqui.")
        input()
        chrome.get(endereco + "?" + urlencode(parametros))
        time.sleep(2)
        html = chrome.page_source
        if pagina_tem_captcha(html):
            raise BloqueioCaptcha("CAPTCHA continua aparecendo.")
    return html


def pagina_tem_captcha(html):
    """Confere se a página é de CAPTCHA/bloqueio em vez de conteúdo."""
    sinais = ["gs_captcha", "unusual traffic", "tráfego incomum", "/sorry/"]
    html_minusculo = html.lower()
    return any(sinal in html_minusculo for sinal in sinais)


# ----------------------------------------------------------------------
# LEITURA DO HTML (separada do acesso, para poder testar com HTML salvo)
# ----------------------------------------------------------------------

def ler_pagina_busca(html):
    """Lê uma página da busca de perfis.
    Devolve (lista de perfis, código da próxima página ou None)."""
    sopa = BeautifulSoup(html, "html.parser")
    perfis = []

    for bloco in sopa.select("div.gsc_1usr"):
        link = bloco.select_one("h3.gs_ai_name a")
        if link is None:
            continue

        # O id do perfil vem no link: /citations?hl=pt-BR&user=XXXX
        achado = re.search(r"user=([\w-]+)", link.get("href", ""))
        id_perfil = achado.group(1) if achado else ""

        afiliacao = bloco.select_one("div.gs_ai_aff")
        email = bloco.select_one("div.gs_ai_eml")
        citacoes = bloco.select_one("div.gs_ai_cby")
        interesses = [a.get_text(strip=True) for a in bloco.select("a.gs_ai_one_int")]

        perfis.append({
            "id_scholar": id_perfil,
            "nome_scholar": link.get_text(strip=True),
            "afiliacao": afiliacao.get_text(strip=True) if afiliacao else "",
            "email_confirmado": email.get_text(strip=True) if email else "",
            "citacoes_total": somente_numero(citacoes.get_text() if citacoes else ""),
            "interesses": "; ".join(interesses),
        })

    # O botão "próxima" guarda o código da página seguinte no atributo onclick
    proxima = None
    botao = sopa.select_one("button.gs_btnPR")
    if botao is not None and not botao.has_attr("disabled"):
        achado = re.search(r"after_author\\x3d([^\\&']+)", botao.get("onclick", ""))
        if achado:
            proxima = achado.group(1)

    return perfis, proxima


def ler_pagina_perfil(html):
    """Lê a página de um perfil.
    Devolve (dicionário de métricas, lista de publicações)."""
    sopa = BeautifulSoup(html, "html.parser")

    # Tabela de métricas: Citações, índice h, índice i10 (total e últimos 5 anos)
    numeros = [somente_numero(td.get_text()) for td in sopa.select("#gsc_rsb_st td.gsc_rsb_std")]
    while len(numeros) < 6:
        numeros.append("")

    interesses = [a.get_text(strip=True) for a in sopa.select("#gsc_prf_int a")]
    afiliacao = sopa.select_one(".gsc_prf_il")

    metricas = {
        "afiliacao": afiliacao.get_text(strip=True) if afiliacao else "",
        "interesses": "; ".join(interesses),
        "citacoes_total": numeros[0],
        "citacoes_5anos": numeros[1],
        "indice_h": numeros[2],
        "indice_h_5anos": numeros[3],
        "indice_i10": numeros[4],
        "indice_i10_5anos": numeros[5],
    }

    publicacoes = []
    for linha in sopa.select("tr.gsc_a_tr"):
        titulo = linha.select_one("a.gsc_a_at")
        cinzas = linha.select("div.gs_gray")   # 1º = autores, 2º = revista/evento
        citacoes = linha.select_one("a.gsc_a_ac")
        ano = linha.select_one("td.gsc_a_y span")

        publicacoes.append({
            "titulo": titulo.get_text(strip=True) if titulo else "",
            "autores": cinzas[0].get_text(strip=True) if len(cinzas) > 0 else "",
            "veiculo": cinzas[1].get_text(strip=True) if len(cinzas) > 1 else "",
            "ano": ano.get_text(strip=True) if ano else "",
            "citacoes": somente_numero(citacoes.get_text() if citacoes else ""),
        })

    return metricas, publicacoes


def somente_numero(texto):
    """Tira tudo que não é dígito. 'Citado por 1.234' -> '1234'."""
    return re.sub(r"\D", "", texto or "")


# ----------------------------------------------------------------------
# COMPARAÇÃO DE NOMES
# ----------------------------------------------------------------------

def normalizar_nome(nome):
    """Minúsculas, sem acentos, sem pontos, sem 'da/de/dos'. Devolve lista de partes."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    sem_pontuacao = re.sub(r"[^a-zA-Z ]", " ", sem_acento).lower()
    return [p for p in sem_pontuacao.split() if p not in PALAVRAS_IGNORADAS]


def comparar_nomes(nome_docente, nome_scholar):
    """Compara o nome do docente com o nome do perfil.
    Devolve 'FORTE', 'VERIFICAR' ou None (sem relação)."""
    partes_doc = normalizar_nome(nome_docente)
    partes_sch = normalizar_nome(nome_scholar)
    if not partes_doc or not partes_sch:
        return None

    # Nome igual depois de normalizar
    if partes_doc == partes_sch:
        return "FORTE"

    # Primeiro e último nome precisam bater
    if partes_doc[0] != partes_sch[0] or partes_doc[-1] != partes_sch[-1]:
        return None

    # Os nomes do meio do perfil precisam existir no nome do docente,
    # por extenso ou como inicial (ex.: "Tiago P. Pagano")
    for parte in partes_sch[1:-1]:
        if len(parte) == 1:
            if not any(p.startswith(parte) for p in partes_doc[1:-1]):
                return None
        elif parte not in partes_doc:
            return None

    # Todas as partes do perfil existem no nome do docente (só faltam algumas)
    return "VERIFICAR"


# ----------------------------------------------------------------------
# ARQUIVOS CSV
# ----------------------------------------------------------------------

def ler_csv(caminho):
    if not os.path.exists(caminho):
        return []
    # utf-8-sig aceita CSV com ou sem marca BOM (o Excel e o Chrome costumam pôr)
    with open(caminho, encoding="utf-8-sig") as arquivo:
        return list(csv.DictReader(arquivo))


def gravar_csv(caminho, linhas, colunas):
    """Grava o CSV inteiro (substitui o anterior)."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        escritor.writeheader()
        escritor.writerows(linhas)


def acrescentar_csv(caminho, linhas, colunas):
    """Acrescenta linhas no fim do CSV (cria com cabeçalho se não existir)."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    novo = not os.path.exists(caminho)
    with open(caminho, "a", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas)
        if novo:
            escritor.writeheader()
        escritor.writerows(linhas)


COLUNAS_PERFIS = ["id_scholar", "nome_scholar", "afiliacao", "email_confirmado",
                  "citacoes_total", "interesses"]
COLUNAS_VINCULOS = ["id_docente", "nome_docente", "id_scholar", "nome_scholar",
                    "afiliacao", "interesses", "sugestao", "decisao"]
COLUNAS_METRICAS = ["id_docente", "id_scholar", "afiliacao", "interesses",
                    "citacoes_total", "citacoes_5anos", "indice_h", "indice_h_5anos",
                    "indice_i10", "indice_i10_5anos"]
COLUNAS_PUBLICACOES = ["id_docente", "id_scholar", "titulo", "autores", "veiculo",
                       "ano", "citacoes"]


# ----------------------------------------------------------------------
# PASSO 1 — LISTAR PERFIS DA UFRB
# ----------------------------------------------------------------------

def passo_listar():
    print(f"Passo 1: buscando perfis com '{TERMO_BUSCA}'")
    endereco = ENDERECO_BASE + "/citations"
    parametros = {"view_op": "search_authors", "mauthors": TERMO_BUSCA, "hl": "pt-BR"}

    todos = []
    pagina = 1
    while True:
        print(f"-> página {pagina}")
        try:
            html = baixar_pagina(endereco, parametros)
        except BloqueioCaptcha as erro:
            print(f"PAROU: {erro} Salvando os {len(todos)} perfis já lidos.")
            print("Espere algumas horas (ou troque de rede) e rode de novo.")
            break

        perfis, proxima = ler_pagina_busca(html)
        todos.extend(perfis)
        print(f"   {len(perfis)} perfis nesta página ({len(todos)} no total)")

        if proxima is None:
            print("Fim da lista.")
            break

        parametros["after_author"] = proxima
        parametros["astart"] = pagina * 10
        pagina += 1
        pausar()

    gravar_csv(ARQ_PERFIS, todos, COLUNAS_PERFIS)
    print(f"Salvo em {ARQ_PERFIS}")


# ----------------------------------------------------------------------
# PASSO 2 — CRUZAR COM OS DOCENTES DO CETEC
# ----------------------------------------------------------------------

def ler_docentes():
    """Lê id e nome dos docentes no banco (somente leitura)."""
    conexao = sqlite3.connect(f"file:{CAMINHO_BANCO}?mode=ro", uri=True)
    consulta = f"SELECT {COLUNA_ID}, {COLUNA_NOME} FROM {TABELA_DOCENTES}"
    linhas = conexao.execute(consulta).fetchall()
    conexao.close()
    return [{"id": str(i), "nome": n} for i, n in linhas]


def passo_cruzar():
    perfis = ler_csv(ARQ_PERFIS)
    if not perfis:
        print(f"Rode o passo 1 antes: {ARQ_PERFIS} não existe ou está vazio.")
        return

    docentes = ler_docentes()
    print(f"Comparando {len(docentes)} docentes com {len(perfis)} perfis da UFRB")

    # Decisões já tomadas antes não são apagadas ao rodar de novo
    decisoes_antigas = {(v["id_docente"], v["id_scholar"]): v["decisao"]
                        for v in ler_csv(ARQ_VINCULOS)}

    vinculos = []
    sem_perfil = 0
    for docente in docentes:
        achou = False
        for perfil in perfis:
            sugestao = comparar_nomes(docente["nome"], perfil["nome_scholar"])
            if sugestao is None:
                continue
            achou = True
            chave = (docente["id"], perfil["id_scholar"])
            vinculos.append({
                "id_docente": docente["id"],
                "nome_docente": docente["nome"],
                "id_scholar": perfil["id_scholar"],
                "nome_scholar": perfil["nome_scholar"],
                "afiliacao": perfil["afiliacao"],
                "interesses": perfil["interesses"],
                "sugestao": sugestao,
                "decisao": decisoes_antigas.get(chave, ""),
            })
        if not achou:
            sem_perfil += 1

    gravar_csv(ARQ_VINCULOS, vinculos, COLUNAS_VINCULOS)

    fortes = sum(1 for v in vinculos if v["sugestao"] == "FORTE")
    verificar = sum(1 for v in vinculos if v["sugestao"] == "VERIFICAR")
    print(f"Sugestões FORTE: {fortes} | VERIFICAR: {verificar}")
    print(f"Docentes sem perfil encontrado: {sem_perfil}")
    print(f"Abra {ARQ_VINCULOS} e preencha 'decisao' (vincular / rejeitar / incerto).")


# ----------------------------------------------------------------------
# PASSO 3 — COLETAR MÉTRICAS E PUBLICAÇÕES DOS PERFIS CONFIRMADOS
# ----------------------------------------------------------------------

def passo_coletar():
    confirmados = [v for v in ler_csv(ARQ_VINCULOS)
                   if v["decisao"].strip().lower() == "vincular"]
    if not confirmados:
        print(f"Nenhuma linha com decisao = vincular em {ARQ_VINCULOS}.")
        return

    # Pula perfis já coletados (para continuar depois de um CAPTCHA)
    ja_coletados = {m["id_scholar"] for m in ler_csv(ARQ_METRICAS)}
    pendentes = [v for v in confirmados if v["id_scholar"] not in ja_coletados]
    print(f"{len(confirmados)} confirmados, {len(pendentes)} faltando coletar")

    endereco = ENDERECO_BASE + "/citations"
    for numero, vinculo in enumerate(pendentes, start=1):
        print(f"-> [{numero}/{len(pendentes)}] {vinculo['nome_docente']}")
        try:
            metricas, publicacoes = coletar_perfil(endereco, vinculo["id_scholar"])
        except BloqueioCaptcha as erro:
            print(f"PAROU: {erro} O que já foi coletado está salvo.")
            print("Espere algumas horas (ou troque de rede) e rode de novo.")
            return

        # Grava um docente por vez, para não perder nada se parar no meio
        metricas["id_docente"] = vinculo["id_docente"]
        metricas["id_scholar"] = vinculo["id_scholar"]
        for pub in publicacoes:
            pub["id_docente"] = vinculo["id_docente"]
            pub["id_scholar"] = vinculo["id_scholar"]
        acrescentar_csv(ARQ_PUBLICACOES, publicacoes, COLUNAS_PUBLICACOES)
        acrescentar_csv(ARQ_METRICAS, [metricas], COLUNAS_METRICAS)

        print(f"   {len(publicacoes)} publicações | h = {metricas['indice_h']}")
        pausar()

    print("Coleta concluída.")


def coletar_perfil(endereco, id_scholar):
    """Abre o perfil de 100 em 100 publicações até acabar."""
    todas = []
    metricas = None
    inicio = 0
    while True:
        parametros = {"user": id_scholar, "hl": "pt-BR",
                      "cstart": inicio, "pagesize": 100, "sortby": "pubdate"}
        html = baixar_pagina(endereco, parametros)
        metricas_pagina, publicacoes = ler_pagina_perfil(html)
        if metricas is None:
            metricas = metricas_pagina
        todas.extend(publicacoes)

        if len(publicacoes) < 100:   # última página
            break
        inicio += 100
        pausar()
    return metricas, todas


# ----------------------------------------------------------------------
# PASSO 4 — VALIDAR PERFIS PELOS TÍTULOS (PROTEÇÃO CONTRA HOMÔNIMOS)
# ----------------------------------------------------------------------

def normalizar_titulo(titulo):
    """Minúsculas, sem acentos, só letras e números. Assim 'Análise de Dados.'
    e 'ANALISE DE DADOS' viram o mesmo texto."""
    sem_acento = unicodedata.normalize("NFKD", titulo or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def titulos_iguais(titulo_a, titulo_b):
    """Iguais depois de normalizar, ou um contém o outro
    (o Google às vezes corta ou acrescenta subtítulo).
    Títulos muito curtos só contam se forem idênticos."""
    if titulo_a == titulo_b:
        return True
    if min(len(titulo_a), len(titulo_b)) < 30:
        return False
    return titulo_a in titulo_b or titulo_b in titulo_a


def ler_titulos_do_banco():
    """Devolve {id_docente: [títulos normalizados]} das publicações do banco."""
    conexao = sqlite3.connect(f"file:{CAMINHO_BANCO}?mode=ro", uri=True)
    consulta = f"SELECT {COLUNA_DOCENTE_PUB}, {COLUNA_TITULO_PUB} FROM {TABELA_PUBLICACOES}"
    titulos = {}
    for id_docente, titulo in conexao.execute(consulta):
        normalizado = normalizar_titulo(titulo)
        if normalizado:
            titulos.setdefault(str(id_docente), []).append(normalizado)
    conexao.close()
    return titulos


def passo_validar():
    metricas = ler_csv(ARQ_METRICAS)
    publicacoes = ler_csv(ARQ_PUBLICACOES)
    if not metricas:
        print(f"Rode o passo 3 antes: {ARQ_METRICAS} não existe ou está vazio.")
        return

    vinculos = {(v["id_docente"], v["id_scholar"]): v for v in ler_csv(ARQ_VINCULOS)}
    titulos_banco = ler_titulos_do_banco()

    # Decisões manuais de rodadas anteriores não são apagadas
    decisoes_manuais = {(r["id_docente"], r["id_scholar"]): r.get("decisao_manual", "")
                        for r in ler_csv(ARQ_VALIDACAO)}
    novas = []

    resultado = []
    for m in metricas:
        id_docente, id_scholar = m["id_docente"], m["id_scholar"]
        nome = vinculos.get((id_docente, id_scholar), {}).get("nome_docente", "")
        do_banco = titulos_banco.get(id_docente, [])
        do_scholar = [p["titulo"] for p in publicacoes
                      if p["id_docente"] == id_docente and p["id_scholar"] == id_scholar]

        # Conta os títulos do Google Acadêmico que existem no banco
        # e guarda os que não existem (publicações novas)
        em_comum = []
        fora_do_banco = []
        for pub in publicacoes:
            if pub["id_docente"] != id_docente or pub["id_scholar"] != id_scholar:
                continue
            normalizado = normalizar_titulo(pub["titulo"])
            if not normalizado:
                continue
            if any(titulos_iguais(normalizado, b) for b in do_banco):
                em_comum.append(pub["titulo"])
            else:
                fora_do_banco.append(pub)

        if not do_banco:
            status = "SEM_BASE"
        elif len(em_comum) >= MINIMO_TITULOS_EM_COMUM:
            status = "CONFIRMADO"
        else:
            status = "A_CONFERIR"

        decisao_manual = decisoes_manuais.get((id_docente, id_scholar), "")

        # Perfil confirmado (pelos títulos ou por você): as publicações fora do banco
        # viram candidatas. Títulos repetidos no próprio perfil entram uma vez só.
        if status == "CONFIRMADO" or decisao_manual.strip().lower().startswith("confirmado"):
            vistos = set()
            for pub in fora_do_banco:
                chave = normalizar_titulo(pub["titulo"])
                if any(titulos_iguais(chave, v) for v in vistos):
                    continue
                vistos.add(chave)
                novas.append({**pub, "nome_docente": nome, "decisao": ""})

        resultado.append({
            "id_docente": id_docente,
            "nome_docente": nome,
            "id_scholar": id_scholar,
            "status": status,
            "decisao_manual": decisao_manual,
            "titulos_em_comum": len(em_comum),
            "publicacoes_scholar": len(do_scholar),
            "publicacoes_banco": len(do_banco),
            "exemplos_em_comum": " | ".join(em_comum[:3]),
        })

    colunas = ["id_docente", "nome_docente", "id_scholar", "status", "decisao_manual",
               "titulos_em_comum", "publicacoes_scholar", "publicacoes_banco", "exemplos_em_comum"]
    gravar_csv(ARQ_VALIDACAO, resultado, colunas)

    colunas_novas = ["id_docente", "nome_docente", "id_scholar", "titulo", "autores",
                     "veiculo", "ano", "citacoes", "decisao"]
    gravar_csv(ARQ_NOVAS, novas, colunas_novas)

    for status in ("CONFIRMADO", "A_CONFERIR", "SEM_BASE"):
        print(f"{status}: {sum(1 for r in resultado if r['status'] == status)}")
    confirmados_manual = sum(1 for r in resultado
                             if r["decisao_manual"].strip().lower().startswith("confirmado"))
    print(f"Confirmados por você (decisao_manual): {confirmados_manual}")
    print(f"Detalhes em {ARQ_VALIDACAO}. Os casos A_CONFERIR e SEM_BASE são para você estudar.")
    print(f"Publicações fora do banco, de perfis confirmados: {len(novas)} -> {ARQ_NOVAS}")


# ----------------------------------------------------------------------
# INÍCIO
# ----------------------------------------------------------------------

if __name__ == "__main__":
    comandos = {"listar": passo_listar, "cruzar": passo_cruzar,
                "coletar": passo_coletar, "validar": passo_validar}
    if len(sys.argv) != 2 or sys.argv[1] not in comandos:
        print("Uso: python coleta/scholar.py [listar | cruzar | coletar | validar]")
        sys.exit(1)
    comandos[sys.argv[1]]()
