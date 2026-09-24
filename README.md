# Ponte CETEC

Sistema que recebe uma dor de mercado e indica quais setores e docentes do CETEC/UFRB podem resolvê-la.

![Status](https://img.shields.io/badge/status-em%20desenvolvimento-yellow)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Fase](https://img.shields.io/badge/fase-1-informational)

## Sobre o projeto

A UFRB não tem um setor que busque recursos privados para pesquisa. O Ponte CETEC usa IA para fazer parte desse trabalho. A partir de uma dor de mercado, como as que aparecem nos relatórios ESG de grandes empresas, o sistema aponta os setores e docentes do CETEC com experiência no assunto.

Com isso, a universidade pode propor projetos de P&D financiados por empresas, que visam resolver problemas dos setores da Indústria.
### Como funciona

```
Dor de mercado  →  Busca vetorial nos perfis  →  Docentes e setores ranqueados  →  Justificativa por IA
```

1. O sistema coleta do site do CETEC as áreas e os docentes, e depois as publicações de cada um.
2. Uma LLM lê as publicações e escreve um perfil de competências para cada docente.
3. Os perfis são convertidos em vetores e indexados.
4. Quando recebe uma dor, o sistema busca os perfis mais próximos e a LLM explica por que cada docente foi indicado.

## Roadmap

| Fase | Descrição | Status |
| --- | --- | --- |
| Fase 1 | Base de competências do CETEC e motor de *matching* | Em andamento |
| Fase 2 | Extração automática de dores dos relatórios ESG (RAG) | Planejada |
| Fase 3 | Minutas de projeto e identificação de contatos nas empresas | Planejada |

### Etapas da fase 1

- [ ] Etapa 1: estrutura e ambiente
- [ ] Etapa 2: coleta de setores e docentes do CETEC
- [ ] Etapa 3: coleta de publicações (OpenAlex e Google Acadêmico)
- [ ] Etapa 4: perfis de competência gerados pela LLM
- [ ] Etapa 5: motor de *matching* (busca vetorial e justificativa)
- [ ] Etapa 6: interface web (MVP)

## Tecnologias

| Camada | Ferramenta |
| --- | --- |
| Linguagem | Python 3.11+ |
| Coleta web | requests, BeautifulSoup, Selenium |
| Publicações | API OpenAlex, scholarly |
| Banco relacional | SQLite |
| LLM e embeddings | Ollama (`llama3.1:8b`, `nomic-embed-text`) |
| Banco vetorial | ChromaDB |
| Interface | Streamlit |

## Estrutura do repositório

```
ponte-cetec/
├── coleta/          # Scripts de coleta (site do CETEC, OpenAlex, Scholar)
├── dados/           # Banco SQLite e arquivos de dados
├── ia/              # Prompts, geração de perfis, embeddings e matching
├── app/             # Interface web (Streamlit)
├── docs/            # Documentação e plano de ação
├── requirements.txt
└── README.md
```

## Como executar

### Pré-requisitos

- Python 3.11 ou superior
- [Git](https://git-scm.com/)
- [Ollama](https://ollama.com/)

### Instalação

```bash
# 1. Clonar o repositório
git clone https://github.com/<seu-usuario>/ponte-cetec.git
cd ponte-cetec

# 2. Criar e ativar o ambiente virtual
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows

# 3. Instalar as dependências
pip install -r requirements.txt

# 4. Baixar os modelos no Ollama
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### Execução

```bash
streamlit run app/main.py
```

O projeto ainda está no começo, então estes passos vão mudar.

## Equipe

| Nome | Papel |
| --- | --- |
| Victor Gomes | Desenvolvimento |
| Prof. Tiago Palma Pagano | Orientação |

Centro de Ciências Exatas e Tecnológicas (CETEC), Universidade Federal do Recôncavo da Bahia (UFRB).

## Licença

A definir.
