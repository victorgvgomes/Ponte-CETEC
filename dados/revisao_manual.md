# Etapa 3: vínculo de docentes e coleta de publicações na OpenAlex

Projeto Ponte-CETEC. Registro do método, das decisões manuais e das limitações.
Trabalho realizado de 1 a 6 de outubro de 2026.

## 1. Resumo

| Indicador | Valor |
|---|---|
| Docentes do CETEC na base | 136 |
| Docentes com publicações no banco | 127 (93%) |
| Docentes com ao menos um perfil vinculado | 127 |
| Perfis da OpenAlex vinculados | 205 |
| Perfis rejeitados | 14 (listados na seção 3.2) |
| Perfis mistos (não baixados automaticamente) | 2 |
| Publicações no banco antes da auditoria | 1.987 |
| Trabalhos de homônimos excluídos | 45, de 12 docentes (seções 3.8 e 3.9) |
| Trabalhos excluídos na conferência de poucas publicações | 7, de 5 docentes (seção 3.10) |
| Trabalhos excluídos na triagem por semelhança | 12, de 9 docentes (seção 3.12) |
| Publicações no banco após as exclusões de 10/10/2026 | 1.956 |
| Publicações que entram nos perfis, após as triagens | 1.762 |
| Docentes com ORCID confirmado | 60 (seção 3.9) |
| Publicações confirmadas pelo ORCID | 688 |
| Publicações incluídas a partir do ORCID | 29 |
| Docentes sem nenhuma publicação na base | 9 |

Na primeira versão do script, apenas 60 docentes (44%) eram vinculados
automaticamente. O ganho veio de três mudanças: buscar também fora do filtro da
UFRB, comparar nomes por compatibilidade em vez de igualdade, e aceitar mais de
um perfil por docente.

## 2. Como a busca foi feita

### 2.1 Ponto de partida

- A lista de 136 docentes veio do site do CETEC (`coleta/coleta_docentes.py`),
  gravada na tabela `docentes` do banco `dados/ponte_cetec.db`.
- A fonte de publicações é a API da OpenAlex (`https://api.openalex.org`), com
  chave de acesso guardada no arquivo `.env`.
- Na OpenAlex, cada pesquisador é um "autor" com um identificador próprio
  (formato `A` seguido de números) e cada publicação é um "trabalho" (formato
  `W`). Para baixar as publicações de um docente é preciso antes descobrir qual
  é, ou quais são, os identificadores de autor dele. Essa descoberta é o
  "vínculo".
- A UFRB é a instituição `I129192303` na OpenAlex.

### 2.2 Primeira versão: nome completo com filtro da UFRB

A primeira versão de `coleta/openalex_autores.py` fazia uma única busca por
docente: o nome completo, restrito a autores com afiliação UFRB. Aceitava o
candidato se o nome fosse idêntico ao do cadastro, ou se houvesse um único
candidato.

Resultado para os 136 docentes:

| Situação | Docentes |
|---|---|
| Vinculado (nome idêntico) | 60 |
| Vinculado, conferir nome (candidato único) | 16 |
| Ambíguo (vários candidatos) | 5 |
| Não encontrado | 55 |

Os 40% de não encontrados indicavam um problema do método, não falta de
produção.

### 2.3 Diagnóstico dos não encontrados

Um script auxiliar, `coleta/openalex_diagnostico.py`, refez a busca dos 55 não
encontrados de outras formas, sem gravar nada no banco. Ele mostrou que:

1. **O filtro da UFRB era a principal causa.** A maioria dos docentes existe na
   OpenAlex com o nome completo correto, mas em perfis "sem instituição" ou
   ligados a outra instituição (UFBA, UEFS, IFBA, SENAI).
2. **Nomes abreviados eram a segunda causa.** Perfis como "Denis R. Petrucci" ou
   "Luis A. H. Mamani" estão na UFRB, mas não batem com o nome por extenso.
3. **A busca da OpenAlex exige todas as palavras.** O texto buscado precisa
   aparecer inteiro no nome principal ou nas variações do nome do perfil. Um
   nome completo longo falha se o perfil só tem a forma curta.
4. **Existem perfis poluídos**, que misturam dezenas de pessoas, e aceitar
   "qualquer candidato único" era arriscado.

Na versão final do diagnóstico, os 55 ficaram assim: 7 com nome inteiro na
UFRB, 40 com nome inteiro fora da UFRB, 4 só com nome parcial e 4 sem candidato
compatível. Dos 4 com nome parcial, 2 vieram da busca com filtro da UFRB (João
Cláudio Costa Pereira e Anderson Reis da Cruz) e 2 da busca de nome curto sem
filtro (Aldo Alfonso Raul Valcarce Bravo e Edilberto Andrade Silva).

### 2.4 Regra de compatibilidade de nomes

A igualdade de nomes foi substituída por uma regra de compatibilidade
(função `compativel`). Um perfil é compatível com o docente quando:

- cada palavra do nome do perfil é uma palavra do nome do docente, ou a inicial
  de uma;
- as palavras aparecem na mesma ordem, cada uma usada uma única vez;
- o último sobrenome é igual;
- o nome do perfil tem pelo menos duas palavras.

Acentos, maiúsculas, pontuação, partículas (de, da, do, dos, das, e) e sufixos
(Filho, Júnior, Neto, Sobrinho) são ignorados.

Exemplos para o docente "Denis Rinaldi Petrucci":

| Nome no perfil | Resultado | Motivo |
|---|---|---|
| Denis R. Petrucci | compatível, nome inteiro | "R" é inicial de Rinaldi |
| Denis Petrucci | compatível, nome parcial | falta uma palavra |
| Denis Almeida Petrucci | incompatível | "Almeida" não está no nome |

A regra foi testada contra os candidatos reais dos 55 docentes antes de ir para
o script principal. Dois ajustes saíram desse teste: exigir a ordem das
palavras (para rejeitar "Gilberto Piña Piña" como candidato de "Gilberto da
Silva Pina") e separar "nome inteiro" de "nome parcial".

### 2.5 Versão final do vínculo

`coleta/openalex_autores.py` passou a fazer três buscas por docente:

1. nome completo, com filtro da UFRB;
2. primeiro nome e último sobrenome, com filtro da UFRB;
3. nome completo, sem filtro.

A busca de nome curto sem filtro foi descartada, porque só trazia homônimos.

Todos os perfis de nome compatível são gravados na tabela `docente_openalex`,
uma linha por perfil, com um status:

| Status | Critério |
|---|---|
| `vinculado` | nome inteiro, primeiro nome por extenso e afiliação UFRB |
| `conferir` | nome compatível, mas fora da UFRB, parcial ou só com iniciais |
| `rejeitado` | definido na revisão manual |
| `misto` | definido na revisão manual: perfil que mistura várias pessoas, mas contém trabalho do docente |

O script nunca altera um status já gravado, e a tabela `openalex_busca`
registra quem já foi buscado, de modo que uma nova execução não repete buscas
nem desfaz a revisão.

Resultado da execução para os 136 docentes: 216 perfis gravados, sendo 103
vinculados e 113 a conferir. Por docente: 81 vinculados, 47 a conferir e 8 não
encontrados.

### 2.6 Revisão manual

A revisão dos 113 perfis "conferir" e dos docentes sem perfil foi feita em
quatro rodadas, seguidas de uma auditoria. As decisões estão listadas na seção 3.

1. **Aprovação em bloco de 77 perfis prováveis**, por critério de nome.
2. **Verificação individual de 36 perfis duvidosos.** Dois foram rejeitados de
   imediato pela instituição. Os outros 34 foram verificados com um agente de
   navegação (Claude no Chrome), que comparou a área de atuação de cada docente
   com os trabalhos, coautores e afiliações de cada perfil.
3. **Três perfis incertos**, resolvidos pela leitura do Currículo Lattes.
4. **Busca dos docentes sem perfil** por ORCID e por DOI de artigos
   comprovadamente deles, também com o agente de navegação.
5. **Auditoria dos perfis vinculados**, feita em 06/10/2026, depois de se
   descobrir que perfis aceitos automaticamente traziam trabalhos de homônimos
   (seção 3.8).

Fontes usadas na verificação: página "Corpo Docente e Áreas de Conhecimento"
do CETEC, Escavador, ORCID, Crossref e a própria OpenAlex. O Lattes e o SIGAA
da UFRB pedem CAPTCHA e só puderam ser consultados manualmente.

### 2.7 Coleta das publicações

`coleta/openalex_publicacoes.py` lê os perfis com status `vinculado` e baixa os
trabalhos de cada um, 100 por página, pelo filtro `authorships.author.id`. O
filtro é só pelo autor, sem instituição, então trabalhos feitos em outras
universidades também entram.

Para cada trabalho são gravados na tabela `publicacoes`: título, resumo, ano,
DOI, tipo, idioma, tópicos e palavras-chave. Detalhes:

- O resumo vem da OpenAlex como um índice de palavras e posições, e é remontado
  em texto corrido.
- Um índice único em (docente, trabalho) impede duplicatas quando o docente tem
  vários perfis ou quando o script roda mais de uma vez.
- Trabalhos sem título são ignorados.
- Se dois docentes são coautores do mesmo trabalho, ele é gravado uma vez para
  cada um.
- Perfis `misto` não são baixados. O modo `--mistos` lista os trabalhos desses
  perfis que têm afiliação UFRB, e o modo `--incluir` grava trabalhos escolhidos
  à mão, por ID ou por DOI.
- Cada publicação guarda o perfil de onde veio (`perfil_openalex`) e a data em
  que entrou no banco (`incluido_em`).
- O modo `--excluir` apaga trabalhos que não são do docente e os registra na
  tabela `publicacoes_excluidas`, para que um novo download não os traga de
  volta. O perfil continua vinculado.
- A cada download, o script lista os trabalhos novos dos docentes que já
  tiveram exclusões, para conferência pelos títulos.
- O modo `--perfis` gera um relatório dos docentes com mais de um perfil, com
  os títulos de cada perfil secundário. O modo `--rejeitar-perfil` rejeita um
  perfil inteiro e apaga os trabalhos que vieram dele.

Na primeira coleta (197 perfis) foram gravadas 1.906 publicações, 1.393 com
resumo (73%) e 513 sem (27%). Após a revisão manual, o total chegou a 1.987, e a
auditoria excluiu depois 44 trabalhos de homônimos.

### 2.8 Complemento previsto no plano: Google Acadêmico

O plano de ação previa complementar a OpenAlex pelo Google Acadêmico nos casos
não encontrados. Esse complemento foi feito por ORCID e por DOI (seções 2.6 e
3.9), pelos seguintes motivos:

- O Google Acadêmico não oferece API. O acesso por script é bloqueado com
  CAPTCHA e contraria os termos de uso do serviço, o mesmo obstáculo do Lattes.
- As listas de trabalhos não trazem DOI. A comparação com o banco teria de ser
  feita pelo título, que é menos preciso.
- O ORCID e a OpenAlex têm consulta aberta e identificam cada trabalho pelo
  DOI, o que permitiu tratar os 136 docentes por script.

O Google Acadêmico não foi usado nesta etapa, nem como fonte de conferência
manual. Para esse uso ele serviria: o perfil é mantido pelo próprio
pesquisador, costuma estar mais completo que o ORCID e mostra o domínio do
e-mail confirmado, como `ufrb.edu.br`. As restrições são que nem todo docente
tem perfil e que a conferência é feita página por página.

O ganho maior estaria nos 76 docentes sem ORCID confirmado, que hoje dependem
só da OpenAlex. O uso sugerido é o mesmo dado ao Lattes: conferir os casos que
uma triagem apontar como duvidosos, e não todos os docentes.

## 3. Registro das decisões manuais

Os identificadores de docente (`docente_id`) são os do banco em 05/10/2026.

### 3.1 Aprovação em bloco (77 perfis)

Foram aprovados todos os perfis "conferir" que não estavam na lista de 36
duvidosos da seção 3.2. Critérios:

- nome completo idêntico e incomum (ex.: Danívio Batista Carvalho de
  Vasconcellos, Clarivaldo Santos de Sousa, Joanito de Andrade Oliveira);
- sobrenome raro, mesmo com o nome abreviado ou parcial (ex.: Maria A. P.
  Hohlenwerger, Alexandra Passuello, Carlos H. F. Poncio);
- perfil extra de docente já vinculado, com nome específico (ex.: os dois
  perfis "sem instituição" de Andréia da Silva Magaton).

São aprovações por probabilidade, não por verificação individual. A lista
completa está em `dados/openalex_vinculos.csv`.

### 3.2 Verificação individual (36 perfis)

| Docente | Perfil | Decisão | Evidência |
|---|---|---|---|
| Sérgio Santos de Jesus | A5109855598 | rejeitado | Engenharia química na Unicamp e UFABC; o docente é de engenharia civil |
| Genilson Ribeiro de Melo | A5064860710 | vinculado | Sólitons; afiliações UFRB, Unesp e Alberta, iguais à trajetória |
| Jerre Cristiano Alves dos Santos | A5072662417 | vinculado | ORCID no nome completo dele; afiliação UFRB |
| Jilvan Lemos de Melo | A5053231967 | vinculado | Níveis de Landau com o orientador da UFPB; afiliações UFPB e UFRB |
| João Cláudio Costa Pereira | A5028459243 | rejeitado | Perfil de outra pessoa (Universidade do Porto). Ver seção 3.4 |
| Joanito de Andrade Oliveira | A5113867618 | misto | Tem o ORCID dele e um artigo de estradas, mas mistura vinhos e medicina |
| Adilson Gomes dos Santos | A5122104620 | vinculado | Artigos com outros docentes do CETEC |
| Anderson Reis da Cruz | A5019106913 | vinculado | Sistemas dinâmicos com o orientador da UFBA; afiliação UFRB |
| Andrêssa Lima de Souza | A5007500838 | rejeitado | Artigo de saúde bucal; a docente é de matemática |
| Andrêssa Lima de Souza | A5154181894 | rejeitado | Estrutura metálica em Curitiba; nome e área diferentes |
| Celso Luiz Borges de Oliveira | A5065222994 | rejeitado | Mistura literatura, urologia e mineração |
| Danilo de Jesus Ferreira | A5028891547 | vinculado | Nome idêntico; dissertação e tese em equações diferenciais |
| Elaine Ferreira Rocha | A5083167832 | misto | ORCID de outra pesquisadora e artigos de nefrologia, com três trabalhos de 2024 pela UNIVASF |
| Luiz Alberto de Oliveira Silva | A5038074295 | vinculado | Nome idêntico; geometria diferencial |
| Luiz Alberto de Oliveira Silva | A5133922865 | vinculado | Capítulo com outros docentes do CETEC |
| Luiz Alberto de Oliveira Silva | A5148708676 | rejeitado | Botânica e fitoquímica |
| Carlos Borges Filho | A5060515185 | incerto | Ver seção 3.3 |
| Manuela Oliveira de Souza | A5155390927 | vinculado | Nome idêntico; artigo de 2025 sobre plantas alimentícias |
| Vinicius Santos da Silva | A5014017307 | rejeitado | "Vinicius da Silva", instituição em Portugal |
| Adriano Humberto de Oliveira Maia | A5086166845 | vinculado | ORCID no nome completo dele; computação pela UFBA |
| Basílio Fernandez Fernandez | A5082597243 | vinculado | Séries temporais com o orientador, em Feira de Santana |
| Basílio Fernandez Fernandez | A5084259267 | rejeitado | Medicina, hospital na Espanha |
| Basílio Fernandez Fernandez | A5108363179 | rejeitado | Medicina, artigo de 2000 |
| Basílio Fernandez Fernandez | A5155972266 | rejeitado | Texto em espanhol sobre empresas |
| Luiz Carlos Simões Soares Júnior | A5089712801 | vinculado | Afiliação CETEC/UFRB; instrumentação e motores |
| Moisés Araújo Oliveira | A5109749422 | incerto | Ver seção 3.3 |
| Nilton Cardoso da Silva | A5054222059 | vinculado | Próteses ativas com pesquisador da Unicamp, onde fez o doutorado |
| Talison Augusto Correia de Melo | A5048857941 | vinculado | ORCID no nome dele, com vínculo UFRB |
| Diego Lima Medeiros | A5137870693 | vinculado | Pegada de carbono, afiliação UFMA; compatível com a área |
| Selma Cristina da Silva | A5129354873 | vinculado | Coagulantes e tratamento de efluentes, a linha dela |
| Selma Cristina da Silva | A5122223530 | vinculado | Tese de 2007 sobre wetlands, igual ao doutorado na UnB |
| Selma Cristina da Silva | A5122118650 | rejeitado | Observatórios e instituições culturais |
| Selma Cristina da Silva | A5060468308 | rejeitado | Área biomédica |
| Selma Cristina da Silva | A5044186763 | rejeitado | "S Silva", instituição no México |
| Aline de Oliveira Moreira | A5082271514 | rejeitado | Mistura enfermagem e direito |
| Flávio Silva Santos | A5074422924 | incerto | Ver seção 3.3 |

### 3.3 Incertos resolvidos pelo Lattes (3 perfis)

| Docente | Perfil | Decisão | Evidência no Lattes |
|---|---|---|---|
| Carlos Borges Filho | A5060515185 | vinculado | Mestre e doutor em Bioquímica pela Unipampa; o perfil é uma dissertação de 2016 sobre efeito tipo-antidepressivo |
| Moisés Araújo Oliveira | A5109749422 | vinculado | Atua com ultrassom, TOFD, EMAT e robótica mole; o perfil trata de ensaios não destrutivos e robótica |
| Flávio Silva Santos | A5074422924 | vinculado | Mestrado no PPGEE da UFBA sobre metamateriais absorvedores, tema dos dois trabalhos do perfil |

### 3.4 Busca por ORCID e DOI dos docentes sem perfil

Doze docentes sem perfil aproveitável foram buscados a partir de um ORCID ou
de um artigo comprovadamente deles.

| Docente | Resultado |
|---|---|
| Aldo Alfonso Raul Valcarce Bravo | Perfil encontrado pelo ORCID 0000-0003-4623-3961 |
| Gilberto da Silva Pina | Dois perfis encontrados por DOI |
| Tassio Ferreira Valle | Perfil encontrado pelo ORCID 0000-0002-7223-3263 |
| João Cláudio Costa Pereira | Um perfil limpo e um trabalho dentro de perfil misto |
| Andrêssa Lima de Souza | Um artigo indexado, sem perfil de autor |
| José Hidalgo Suárez | Um artigo indexado, sem perfil de autor |
| Luciano de Santana Rocha | Nada encontrado |
| Fabricio de Jesus Ribeiro | Nada encontrado |
| Edilberto Andrade Silva | Nada encontrado |
| Heber Christiane Antunes Franca | Nada encontrado |
| Sérgio Santos de Jesus | ORCID existe, sem trabalhos; nenhum título indexado |
| Aline de Oliveira Moreira | Nenhum título indexado |

### 3.5 Perfis inseridos manualmente (5)

| docente_id | Docente | Perfil | Nome na OpenAlex | Evidência |
|---|---|---|---|---|
| 16 | Aldo Alfonso Raul Valcarce Bravo | A5040528710 | A. A. R. Valcarce | ORCID; 47 trabalhos de astrofísica estelar, vários com outra docente do CETEC |
| 54 | Gilberto da Silva Pina | A5083535739 | Gilberto S. Pina | Preprint de 2020 com a orientadora da UnB |
| 54 | Gilberto da Silva Pina | A5129029009 | G. S. Pina | Artigo de 2026, afiliação CETEC/UFRB |
| 103 | Tassio Ferreira Valle | A5073246165 | Tassio Ferreira Vale | ORCID com vínculo UFRB; 19 trabalhos de engenharia de software |
| 24 | João Cláudio Costa Pereira | A5074373429 | J.C.C. Pereira | Artigo de 2022 com o orientador da UFBA, afiliação CETEC/UFRB |

### 3.6 Trabalhos incluídos manualmente (4)

| docente_id | Docente | Trabalho | Motivo |
|---|---|---|---|
| 37 | Joanito de Andrade Oliveira | W4404755358 | Artigo de estradas não pavimentadas (2024), preso no perfil misto A5113867618 |
| 45 | Andrêssa Lima de Souza | DOI 10.1007/s10884-018-9723-6 | Artigo com o orientador da UFBA; a autoria não tem perfil na OpenAlex |
| 94 | José Hidalgo Suárez | DOI 10.3390/en18205371 (W4415210663) | Artigo de 2025 sobre sistemas híbridos de energia, tema do Lattes dele; a autoria não tem perfil |
| 24 | João Cláudio Costa Pereira | W3129881038 | Artigo de 2021 com o orientador, preso no perfil misto A5048280947 |

Trabalhos avaliados e não incluídos:

- W4400001822 (degradação de corantes, 2024): aparecia no perfil antigo de
  João Cláudio, mas o autor é João Victor Docílio Pereira, outra pessoa do
  CETEC.
- W4285227172: versão preprint de um artigo de João Cláudio já incluído.
- Dez trabalhos de 2002 a 2011 ligados ao ORCID de José Hidalgo Suárez: são de
  outro autor ("J.J. Suárez"), a quem a OpenAlex atribuiu o ORCID por engano.

### 3.7 Docentes sem publicações na base (9)

| Docente | Situação |
|---|---|
| Luciano de Santana Rocha | Nenhuma publicação encontrada |
| Fabricio de Jesus Ribeiro | Nenhuma publicação encontrada |
| Edilberto Andrade Silva | Nenhuma publicação encontrada |
| Heber Christiane Antunes Franca | Nenhuma publicação encontrada |
| Aline de Oliveira Moreira | Dissertação e TCC não indexados |
| Sérgio Santos de Jesus | Dissertação e trabalhos de congresso não indexados |
| Elaine Ferreira Rocha | Só perfil misto, sem trabalho com afiliação UFRB; em espera |
| Inacio Oliveira Borges | Único trabalho excluído na conferência de 09/10/2026 (seção 3.10) |
| Silvio de Cerqueira Mazza | Os dois trabalhos excluídos na conferência de 09/10/2026 (seção 3.10) |

Para os 4 primeiros, "nenhuma publicação encontrada" significa que as
buscas por nome não retornaram nada. Não foi possível testar por DOI, porque
não se achou nenhuma publicação deles em fontes abertas. Não é prova de que
não tenham produção.

### 3.8 Auditoria dos perfis vinculados (06/10/2026)

**O que motivou.** A leitura dos títulos de Selma Cristina da Silva mostrou 8
trabalhos de cultura e de relações de trabalho em meio à produção de
saneamento. Eles vinham de dois perfis vinculados automaticamente, que
misturavam a docente com homônimas.

**Como foi feita.**

1. Auditoria automática (`coleta/openalex_auditoria.py`): busca a área que a
   OpenAlex atribui a cada trabalho e sinaliza os que estão em uma área
   minoritária do docente, com menos de 30% da produção. Apontou 312 trabalhos
   de 69 docentes. Outros 29 docentes ficaram de fora, por terem menos de 4
   trabalhos classificados.
2. Triagem dos 312 pelos títulos: cerca de 17 eram contaminação real, 20
   duvidosos e 275 alarmes falsos.
3. Leitura da lista completa de títulos dos docentes apontados, que revelou
   trabalhos alheios não sinalizados.
4. Relatório de perfis (`--perfis`): revisão dos 77 perfis secundários, com 169
   trabalhos. Nenhum era inteiro de outra pessoa; saíram 5 trabalhos avulsos.
5. Conferência de 12 docentes duvidosos no Currículo Lattes, com apoio do
   Escavador quando o Lattes não ajudou.

**Trabalhos excluídos na auditoria: 44, de 12 docentes.** Um 45º saiu depois, na validação pelo ORCID (seção 3.9). Em todos, o perfil continua
vinculado e só os trabalhos alheios foram bloqueados.

| docente_id | Docente | Área do docente | Excluídos | Tema dos trabalhos alheios |
|---|---|---|---|---|
| 11 | Mário Sérgio de Souza Almeida | pavimentação e geotecnia | 12 | finanças, valuation, Ibovespa, controladoria, laticínios |
| 82 | Vinicius Santos da Silva | química de porfirinas | 12 | saúde coletiva, história, linguagem urbana, inovação e patentes |
| 128 | Selma Cristina da Silva | saneamento | 9 | cultura, ciência da informação, precarização do trabalho, programas sociais |
| 91 | Igor Dantas dos Santos Miranda | eletrônica e processamento de sinais | 2 | geometria diferencial, engenharia de software |
| 27 | Leandro Cerqueira Santos | física atômica | 2 | contraceptivos nas Filipinas, gerador termoelétrico solar |
| 22 | Jerre Cristiano Alves dos Santos | cerâmicas | 1 | escolha da via de parto por gestantes |
| 106 | Carlos Alberto Tosta Machado | manufatura e óleos essenciais | 1 | estudo de cardiologia |
| 115 | Marcus Vinícius Ivo da Silva | engenharia automotiva | 1 | banco de leite humano |
| 81 | Sivanildo da Silva Borges | química analítica | 1 | articulação social e poder político |
| 53 | Erikson Alexandre Fonseca dos Santos | matemática | 1 | marketing em micro varejo |
| 109 | Felipe Andrade Torres | motores e energia | 1 (mais 1 na seção 3.9) | medicina intensiva |
| 21 | Genilson Ribeiro de Melo | física teórica | 1 | registro cujo título é o nome de uma revista ambiental |

Os comandos estão na seção 5, para permitir refazer a limpeza.

**Conferência no Lattes: 12 docentes.** Em 9, toda a produção duvidosa era
mesmo deles.

| Docente | Resultado |
|---|---|
| Vinicius Santos da Silva | 3 excluídos: os de inovação e patentes não constam no Lattes nem no ORCID |
| Selma Cristina da Silva | 1 excluído: o trabalho de Serra Branca-PB (2004) não consta |
| Leandro Cerqueira Santos | 1 excluído: o do gerador termoelétrico não é dele |
| Pollyane Vieira da Silva | confirmado: 7 trabalhos sobre São Paulo e paisagem urbana |
| Lívia Menezes da Paz | confirmado: 4 trabalhos de áreas diferentes |
| Rogelma Maria da Silva Ferreira | confirmado: trabalho de 2008 sobre águas subterrâneas, da iniciação científica na UFC |
| Ariston de Lima Cardoso, Eniel do Espírito Santo, Euzelina dos Santos Borges Inácio, Renê Medeiros de Souza, José Roberto Fernandes Galindo e José Humberto Teixeira Santos | confirmados |

Nesse processo, o ORCID de Vinicius Santos da Silva foi obtido do Lattes
(0000-0002-5194-3418) e gravado no banco.

### 3.9 Segunda via: validação pelo ORCID (06/10/2026)

Depois da auditoria, o registro de cada docente no ORCID passou a ser usado
como segunda fonte, pelo script `coleta/orcid.py`. O ORCID é mantido pelo
próprio pesquisador, e por isso erra de forma diferente da OpenAlex: não
mistura pessoas, mas costuma estar incompleto. A regra adotada foi que o ORCID
confirma e acrescenta, mas nunca exclui, e que essa via roda depois da busca na
OpenAlex.

**Passo 1: recuperar os ORCIDs.** O script de vínculo só gravava o ORCID de
perfis aceitos automaticamente. Os perfis aprovados na revisão manual não
tinham o ORCID copiado para o banco. Lendo o ORCID de cada um dos 205 perfis
vinculados, os docentes com ORCID passaram de 51 para 67. Nenhum docente tinha
dois ORCIDs diferentes nos perfis. Houve uma divergência, a de Felipe Andrade
Torres, descrita adiante.

**Passo 2: validar.** Um ORCID é confirmado quando o nome no registro é
compatível com o do docente e há ao menos uma destas evidências:

- emprego na UFRB declarado no registro;
- um trabalho-âncora no registro, isto é, uma publicação do docente em
  coautoria com outro docente da base. Um homônimo de outra área não publica
  com colegas do CETEC.

A coincidência das obras com o banco, sozinha, não confirma. O ORCID veio do
perfil da OpenAlex e as publicações do banco vieram do mesmo perfil, de modo
que elas tendem a coincidir mesmo quando o perfil é de um homônimo.

| Resultado da validação automática | Docentes |
|---|---|
| Confirmado por emprego na UFRB | 41 |
| Confirmado por trabalho-âncora | 5 |
| A conferir | 19 |
| Suspeito (nome não reconhecido) | 2 |

**Conferência manual dos 21 não confirmados.**

| Decisão | Docentes |
|---|---|
| Confirmados manualmente (14) | Aldo Alfonso Raul Valcarce Bravo e Eleazar Gerardo Madriz Lozada, cujos nomes hispânicos a regra não reconhece; Pollyane Vieira da Silva e Carlos Borges Filho, já conferidos no Lattes; Tiago Palma Pagano; Jerre Cristiano Alves dos Santos; Diego Lima Medeiros; Leonardo da Silva Lessa; Fernanda Nepomuceno Costa; Gilmar Emanoel Silva de Oliveira; Manoel Leandro Araújo e Farias; Luan Aleixo Canário Mendonça; Filipe Luigi Dantas Lima Santos; Cássia Juliana Fernandes Torres |
| Deixados em aberto (7) | seis registros vazios (Adilson Brito de Arruda Filho, Pablo Pedreira Pedra, Francisco de Souza Fadigas, Márcia Luciana Cazetta, Carlos Alberto Tosta Machado, Lidiane Mendes Kruschewsky Lordelo) e o de Inacio Oliveira Borges, com uma única obra |

Ao final, 60 docentes ficaram com ORCID confirmado.

**ORCIDs rejeitados (2).** Ficam registrados na tabela `orcid_rejeitados`, para
que o passo 1 não os grave de novo.

| Docente | ORCID rejeitado | De quem é |
|---|---|---|
| Selma Cristina da Silva | 0000-0002-5658-6448 | de uma homônima da área de cultura (seção 4.6) |
| Felipe Andrade Torres | 0009-0004-2896-3121 | de Felipe Torres-Rivera |

**O caso de Felipe Andrade Torres.** O perfil secundário dele na OpenAlex
(A5100784378) trazia um ORCID diferente do que estava no banco. O registro era
de outra pessoa, Felipe Torres-Rivera, com uma única obra: um artigo sobre
pré-tratamento de palha de trigo, publicado com um grupo alemão. Esse artigo
(W4306178141) estava no banco como do docente e foi excluído. É um homônimo da
mesma área, o tipo de caso que a auditoria por área não detecta. Os demais
trabalhos do perfil são do docente, conferidos pelos coautores.

**Passo 3: aplicar**, só para os 60 ORCIDs confirmados.

| Resultado | Quantidade |
|---|---|
| Publicações do banco marcadas como confirmadas pelo ORCID | 659 |
| Obras incluídas a partir do ORCID, buscadas na OpenAlex pelo DOI | 29 |
| Total de publicações confirmadas pelo ORCID | 688 |
| Obras sem DOI, não incluídas | 94 |
| Obras com DOI que a OpenAlex não tem | 1 |

As 29 inclusões: Manuela Oliveira de Souza (11), André Dias de Azevedo Neto (4),
Adriano Humberto de Oliveira Maia (4), João Carlos Nunes Bittencourt (3), Luiz
Carlos Simões Soares Júnior (3), Manoel Leandro Araújo e Farias (2), Mário
Sérgio de Souza Almeida (1) e Carlos Borges Filho (1).

Nenhuma obra de um ORCID confirmado estava na lista de bloqueio da auditoria.
As exclusões feitas não foram contrariadas por essa segunda fonte.

### 3.10 Conferência dos docentes com poucas publicações (09/10/2026)

Feita no início da Etapa 4, antes da geração dos perfis de competência.

**Critério.** Docentes com até 3 publicações na base e nenhuma confirmada pelo
ORCID: 30 docentes e 60 publicações. É um critério de risco: com tão pouco
material, um único trabalho de homônimo dominaria o perfil, e a triagem por
semelhança de conteúdo não funciona. Oito desses docentes já tinham sido
conferidos na Etapa 3 (Andrêssa, José Hidalgo, João Cláudio, Gilberto Pina,
Danilo, Flávio, Nilton e Celso), e suas 14 publicações não foram reabertas.
Renê Medeiros de Souza, conferido no Lattes na auditoria (seção 3.8), foi
conferido de novo.

**Método.** Para cada docente, os títulos foram comparados com o Lattes ou com
o Escavador, que replica o Lattes; em alguns casos, com a coautoria de outros
docentes do CETEC e com a afiliação declarada no trabalho. As decisões e a
fonte de cada uma estão em `dados/conferir_poucas_publicacoes.csv`, colunas
`e_do_docente` e `observacao`.

**Resultado: 46 publicações de 22 docentes.**

| Decisão | Publicações |
|---|---|
| sim | 39 (85%) |
| não | 7 (15%) |

Dezessete dos 22 docentes tiveram todas as publicações confirmadas. Fontes das
confirmações: Escavador na maioria; Lattes; coautoria com docentes do CETEC
(Balbino José da Silva Pomponet Filho).

A taxa de 85% vale para este grupo, escolhido por ser o de maior risco, e não
deve ser estendida à base inteira. Os vínculos desses docentes vieram em parte
do script e em parte da aprovação em bloco da seção 3.1.

**Trabalhos marcados como não sendo do docente (7).**

| docente_id | Docente | Trabalho | Evidência |
|---|---|---|---|
| 3 | Carlos Frederico Macedo Cortês | W4402031261, W4402258293 | não constam nas fontes consultadas; são o mesmo trabalho em artigo e capítulo |
| 133 | Inacio Oliveira Borges | W7135167129 | não consta nas fontes consultadas |
| 112 | Janailson Oliveira Cavalcanti | W4404139295 | o trabalho declara afiliação à UFPE, sem relação com o currículo dele |
| 63 | Marília Conceição de Souza Caceres | W2065899962 | não encontrado em nenhuma fonte, embora trabalhos mais recentes dela constem no Escavador |
| 134 | Silvio de Cerqueira Mazza | W2587400349, W7215165680 | não constam nas fontes consultadas |

Antes da decisão, foi levantada a hipótese de que os trabalhos de Carlos
Frederico (estruturas de aço, mesma área da dissertação), Janailson (risco em
óleo e gás, mesma linha do trabalho de 2016) e Marília (área da saúde, como os
outros dois trabalhos dela) fossem dos docentes. Após nova consulta, as
marcações foram mantidas. O preprint de 2025 de Gislana Santana Machado, de
início marcado como não sendo dela, foi confirmado por tratar dos mesmos
materiais do artigo dela de 2022.

**Consequência.** Depois das exclusões, Inacio Oliveira Borges e Silvio de
Cerqueira Mazza ficam sem nenhuma publicação, e os docentes sem publicação na
base passam de 7 para 9.

**Dúvida resolvida.** As duas publicações de José Valentim dos Santos Filho
são o mesmo trabalho, de 2026, com dois registros no Zenodo. Ficaram de início
em dúvida e foram confirmadas pela coautoria com Gabriel Marcolino Silva e
Douglas Santos Moura, ligados à UFRB e ao CETEC. Nenhum dos dois consta na
lista de docentes coletada do site do CETEC, e por isso a coautoria não
aparece como trabalho-âncora no banco. Gabriel Marcolino Silva é estudante,
o que explica a ausência; a situação de Douglas Santos Moura não foi
verificada. Coautoria com estudantes do CETEC é evidência de vínculo, mas o
banco não a detecta, porque só conhece os docentes.

**Achados de passagem.**

- Repetições que a comparação de títulos idênticos não pega: as duas
  publicações de Erikson Alexandre Fonseca dos Santos são a mesma dissertação,
  em português e em inglês, e as de José Valentim são dois registros do mesmo
  trabalho. As duas de Nilton Cardoso da Silva também são o mesmo trabalho.
- Vários desses docentes têm no Escavador muito mais trabalhos do que na base
  (limitação G6, seção 4.16).
- Não se mediu quantos docentes têm perfil no Google Acadêmico.

### 3.11 Triagem de repetidos, títulos e resumos sem conteúdo (09/10/2026)

Feita na Etapa 4, antes dos perfis de competência, pelo script
`coleta/triagem_conteudo.py`. O script aponta os casos em
`dados/triagem_conteudo.csv`; as decisões confirmadas na coluna `conferido`
são gravadas pelo modo `--aplicar` na tabela `publicacoes_ajustes`. Nenhuma
publicação sai da tabela `publicacoes`: os ajustes só decidem o que entra no
prompt que gera o perfil.

**Os três casos e as regras.**

| Caso | Quando é apontado | Sugestão |
|---|---|---|
| repetido | mesmo docente, mesmo título (sem acentos, maiúsculas e pontuação) ou mesmo DOI | manter uma cópia por grupo; ignorar as outras |
| título sem conteúdo | título genérico ("Apresentação", "Errata"), tipo `erratum`, ou título de até 4 palavras sem DOI e sem resumo útil | ignorar |
| resumo sem conteúdo | resumo com menos de 100 caracteres, ou que começa com "Submitted by", "Orientador" ou "Texto completo" | manter o trabalho e usar só título e tópicos |

Em cada grupo de repetidos, a cópia mantida é a que tem resumo útil; em
empate, a confirmada pelo ORCID; depois, a que tem DOI; por fim, a que entrou
primeiro no banco. Uma publicação que aparece em dois casos fica com a decisão
mais forte (ignorar o trabalho vence ignorar só o resumo). Nos dados atuais,
em nenhum grupo só parte das cópias era confirmada pelo ORCID (48 grupos com
todas confirmadas, 85 com nenhuma), de modo que a escolha da cópia não afetou
nenhuma confirmação.

**Resultado.** 322 linhas conferidas, todas com decisão.

| Caso | Apontados | Decisão |
|---|---|---|
| repetido | 133 grupos, 270 linhas | 137 cópias ignoradas |
| título sem conteúdo | 13 | 7 títulos corrigidos pelo Lattes, 4 ignorados, 2 mantidos |
| resumo sem conteúdo | 39 | 34 resumos ignorados, 5 mantidos |

Depois da triagem, 1.828 das 1.968 publicações entram nos perfis; as demais
continuam no banco.

**Títulos corrigidos pelo Lattes (7).** Os registros tinham como título o
nome da revista e, como resumo, só o número das páginas. O título verdadeiro
foi buscado no Lattes do docente e gravado em `publicacoes_ajustes`, coluna
`titulo_corrigido`, com a referência completa na observação. A tabela
`publicacoes` mantém o título original do OpenAlex.

| Docente | Revista | Título do Lattes |
|---|---|---|
| Mariese Conceição Alves dos Santos | BMC Immunology, 2013 | Blomia tropicalis Blo t 5 and Blo t 21 recombinant allergens might confer higher specificity to serodiagnostic assays than whole mite extract |
| Sandra Maria Conceição Pinheiro | Public Health Nutrition, 2007 | Determinants of mild-to-moderate malnutrition in preschoolers in an urban area of Northeastern Brazil: a hierarchical approach |
| Clarivaldo Santos de Sousa | Analytica Chimica Acta, 2001 | Effects of ultrasonic irradiation on the spectrophotometric determination of nickel with dimethylglyoxime |
| Francisco de Souza Fadigas | Cadernos de Geociências, 2010 | Estimativa da concentração de metais pesados em solos dos tabuleiros do Recôncavo da Bahia |
| Gilmara Fernandes Eça | Atlântica, 2009 | Distribuição de nutrientes dissolvidos e clorofila-a no estuário do rio Cachoeira, Nordeste do Brasil |
| Sivanildo da Silva Borges | Ultrasonics, 2004 | Reagent Generation for Chemical Analysis assisted by Ultrasonic Irradiation |
| Gildeberto de Souza Cardoso | Mathematical Problems in Engineering, 2011 | Analysis of Exact Linearization and Aproximate Feedback Linearization Techniques |

Francisco de Souza Fadigas tinha dois registros "Cadernos de Geociências"
(p. 1-11 e p. 1/9). Só o primeiro consta no Lattes; o outro foi ignorado, por
ser outra versão do mesmo artigo ou um trabalho sem título identificável.

**Mantidos apesar do apontamento.** "On Tverberg type theorems", dissertação
de Carlos Henrique Felício Poncio, caiu na regra do título curto por não ter
DOI e ter como "resumo" só o agradecimento à FAPESP; foi mantida. "Preço
maduro", de Euzelina dos Santos Borges Inácio, também foi mantido. Entre os
resumos, foram mantidos os que são trechos do resumo verdadeiro (por exemplo,
"to formulate indicators and indices for urban stormwater management").

**Autoria conferida.** A referência do artigo de Gildeberto de Souza Cardoso
copiada de início mostrava só "SCHNITMAN, L."; conferido no Lattes, o docente
é coautor, e a correção do título foi mantida.

**Limites da triagem.**

- Repetições com títulos diferentes, como a mesma dissertação em português e
  em inglês (Erikson Alexandre Fonseca dos Santos), não são detectadas. Ficam
  para a triagem por semelhança de conteúdo.
- A regra do título curto confunde títulos legítimos com nomes de revista,
  como no caso de Carlos Henrique; por isso toda sugestão passa por conferência.

### 3.12 Triagem por semelhança de conteúdo (10/10/2026)

Feita na Etapa 4 pelo script `coleta/triagem_embeddings.py`, que não altera o
banco. O texto de cada publicação que entra nos perfis (título, ou título
corrigido, mais o resumo útil; sem resumo, título, até 8 palavras-chave e até
3 tópicos) é transformado num vetor pelo modelo `nomic-embed-text`, no Ollama.
As publicações de cada docente são então comparadas entre si. Os vetores ficam
em `dados/embeddings/` e só são recalculados quando o texto muda.

**Calibração.** Os limites foram ajustados depois de uma primeira execução,
olhando a distribuição das semelhanças e casos de resposta conhecida: os
quatro docentes cuja produção foi revisada um a um (Vinicius Santos da Silva,
Selma Cristina da Silva, Mário Sérgio de Souza Almeida e Felipe Andrade Torres)
e a dissertação de Erikson Alexandre Fonseca dos Santos registrada em português
e em inglês.

| Critério | Primeira versão | Versão final | Motivo da mudança |
|---|---|---|---|
| Isolado (escore robusto da semelhança com os 3 vizinhos mais parecidos) | -2,5 | -3,0 | lista de 56 para cerca de 35 trabalhos |
| Longe das obras confirmadas pelo ORCID | apontava sozinho | só informa | gerou apenas alarmes falsos nos quatro docentes conhecidos |
| Repetição no mesmo idioma | semelhança 0,90 | 0,97 | com 0,90 saíam 573 pares, quase todos trabalhos diferentes do mesmo tema |
| Tradução | não existia | títulos em idiomas diferentes, até 1 ano, semelhança 0,88 | o modelo dá notas menores entre idiomas |
| Duas dissertações no mesmo período | não existia | mesmo docente, até 1 ano, sem exigir semelhança | o par de Erikson teve semelhança 0,71 |

O idioma do título é identificado pelo script, contando palavras que só
existem numa língua ("da", "com" para o português; "the", "of" para o inglês;
"del", "los" para o espanhol). O campo de idioma do OpenAlex não serve para
isso: ele informa a língua do texto, e uma dissertação em português com título
em inglês aparece como "pt". Sem a detecção do título, o critério de tradução
trazia 87 pares, 58 deles com os dois títulos na mesma língua.

**Resultado da triagem de homônimos.** Na primeira rodada, 45 trabalhos
apontados, de 34 docentes; nenhum dos quatro docentes conhecidos teve
trabalho apontado. Depois que as repetições foram retiradas dos perfis, uma
segunda análise apontou mais 11 trabalhos: sem a cópia repetida, o trabalho
que ficou perdeu o "vizinho" que o fazia parecer acompanhado.

| Decisão | 1ª rodada | 2ª rodada | Total |
|---|---|---|---|
| do docente | 34 | 10 | 44 |
| não é do docente (excluídos) | 11 | 1 | 12, de 9 docentes |

Trabalhos excluídos, com o comando `--excluir`:

| docente_id | Docente | Trabalho | Tema |
|---|---|---|---|
| 84 | Acbal Rucas Andrade Achy | W3021502267 | incrustação em campos de petróleo offshore |
| 41 | Adilson Gomes dos Santos | W7214802054 | pensão alimentícia entre ex-cônjuges |
| 43 | Alex Santana dos Santos | W4290988382, W4402126039 | redes ópticas elásticas |
| 106 | Carlos Alberto Tosta Machado | W3008540800 | veículo submarino autônomo |
| 6 | Fernanda Nepomuceno Costa | W2336706901 | elementos-traço em peixes |
| 93 | Joaquim Jorge Martins Galo | W2621195124 | dissertação sobre redes inteligentes |
| 96 | Leonardo da Silva Lessa | W2893298749, W2292545202 | criptografia em redes ópticas; direção elétrica |
| 66 | Pollyane Vieira da Silva | W4416254858 | parasitismo de vespas |
| 40 | Thomas Vincent Gloaguen | W4367058711 | linha costeira do Mar Báltico |
| 106 | Carlos Alberto Tosta Machado | W4396496919 | descomissionamento de estruturas offshore (2ª rodada) |

Os dois trabalhos excluídos de Carlos Alberto Tosta Machado (o veículo
submarino e o descomissionamento offshore) são de um homônimo que atua nos
Estados Unidos. Os outros 12 trabalhos do docente, sobre óleos essenciais,
destilação e gêmeo digital, são coerentes entre si.

A dissertação de 2025 de Leonardo da Silva Lessa foi marcada de início como
alheia e depois mantida: trata do mesmo tema da linha principal do docente
(localização de faltas por ondas viajantes) e foi apontada só por estar em
português, enquanto a maior parte da produção dele está em inglês. O trabalho
de Cleidson Carneiro Guimarães sobre nanopartículas de prata ficou de início em
dúvida e foi confirmado: um dos coautores parece ser o orientador de doutorado
dele.

Como na auditoria da Etapa 3, a maioria dos trabalhos que destoam da produção
é mesmo do docente: 44 dos 56.

**Resultado da triagem de repetições.** 94 pares apontados, mais 1
acrescentado à mão: o artigo de Sandra Maria Conceição Pinheiro que tinha dois
registros e passou a ter o mesmo título depois da correção da seção 3.11.

| Critério | Pares | Eram o mesmo trabalho | Precisão |
|---|---|---|---|
| duas dissertações no mesmo período | 19 | 18 | 95% |
| quase idênticos | 30 | 19 | 63% |
| possível tradução | 45 | 16 | 36% |
| acrescentado à mão | 1 | 1 | |
| total | 95 | 54 | |

O par de Pablo Pedreira Pedra sobre nanopartículas de CoFe2O4 foi reavaliado
e marcado como o mesmo trabalho: o "agente quelante" do título em inglês é o
"precursor orgânico" do título em português. Os quatro estudos de Eniel do
Espírito Santo com a escala DigCompEdu foram mantidos como diferentes, porque
avaliam grupos distintos de professores.

O modo `--aplicar` do script gravou as 54 decisões em `publicacoes_ajustes`
(caso `similar`): em cada grupo fica uma cópia, pela mesma regra da seção
3.11, e as outras saem dos perfis. Em 8 casos a cópia que saiu tinha um ajuste
anterior (resumo ignorado ou título corrigido), anotado na observação.

Depois das duas triagens e das exclusões, o banco tem 1.956 publicações, das
quais 1.762 entram nos perfis.

**Fontes da conferência.** Escavador na maior parte dos casos. Trabalhos de
2026 em geral ainda não constam no Lattes nem no Escavador; para eles, o
artigo foi aberto pelo OpenAlex e conferida a afiliação ou a menção à UFRB e
ao CETEC.

**Limites.**

- O `nomic-embed-text` foi treinado sobretudo em inglês e compara mal textos
  em idiomas diferentes. Trabalhos em português num conjunto em inglês tendem
  a parecer isolados (caso de Leonardo), e traduções de artigos com títulos
  curtos e sem resumo podem não ser encontradas.
- A triagem de homônimos só vale para docentes com 4 ou mais publicações; os
  com até 3 foram conferidos à mão (seção 3.10).
- Um homônimo com vários trabalhos parecidos entre si não fica isolado e pode
  passar despercebido.
- Retirar repetições muda as medidas de isolamento; por isso a triagem de
  homônimos foi refeita depois de aplicar as repetições.

**Conferência posterior (12/10/2026).** No piloto dos perfis, os dois
capítulos de 2025 sobre análise de fósforo no solo atribuídos a Maria Amelia
de Pinho Barbosa Hohlenwerger (W4416598312, W4416598343), sem ORCID, pareciam
fora da produção em matemática dela. Conferidos pelo usuário: são dela.
Ficam na base. O caso mostra que um trabalho fora da área habitual do
docente não indica, por si só, homônimo: a conferência humana continua
necessária.

### 3.13 Piloto dos perfis de competência (12/10/2026)

**Objetivo.** Antes de gerar os perfis de todos os docentes, testar o prompt
e o modelo em poucos casos e conferir o resultado à mão. O piloto não grava no
banco: os resultados ficam em `dados/perfis_piloto/`, um JSON com o registro
completo (data, modelo, prompt, parâmetros, respostas) e um CSV para a
conferência, com as colunas `faz_sentido` e `observacao`.

**Docentes do piloto (7).** Vinicius Santos da Silva (82), Selma Cristina da
Silva (128), Mário Sérgio de Souza Almeida (11) e Felipe Andrade Torres (109),
de produção conhecida; Eniel do Espírito Santo (52), o de maior volume (91
publicações); Tassio Gabriel Ribeiro Lopes (136), com material limitado (2
publicações, 1 com conteúdo); Maria Amelia de Pinho Barbosa Hohlenwerger (61),
de matemática pura.

**Variantes comparadas.** O mesmo prompt e os mesmos docentes, mudando uma
coisa por vez:

| Variante | Modelo | Exemplos no prompt | Pergunta que responde |
|---|---|---|---|
| 1 | gemma3:4b | com | (referência) |
| 2 | gemma3:4b | sem | Os exemplos ajudam ou levam o modelo a imitar? (1 contra 2) |
| 3 | llama3.2 (3b) | com | Qual modelo é melhor com o mesmo prompt? (1 contra 3) |

Os exemplos são três pares de áreas que não existem no CETEC (cardiologia,
odontologia, oftalmologia), que mostram a diferença entre uma área genérica e
uma competência concreta. O script descarta competências parecidas com eles.
Modelos maiores não foram testados: o computador tem 8 GB de memória.

Parâmetros fixos: contexto de 8192 tokens, temperatura 0 na primeira tentativa
e 0,3 nas outras duas, semente 42, resumo de cada publicação cortado em 400
caracteres. Docentes com material acima de 5000 tokens são processados em
lotes de até 4000 tokens, com uma chamada final que junta os perfis parciais.

**Rodada 1 (gemma3:4b, com exemplos).** 6 perfis gerados, 1 falha, 19 min 42 s.
Arquivos: `gemma3-4b_com-exemplos_rodada1.csv` e `.json`.

- As competências de Mário, Felipe e Vinicius batem com a produção conhecida e
  citam trabalhos corretos. Nenhuma competência citou trabalho de fora do
  docente nem copiou os exemplos.
- **Selma falhou** nas 3 tentativas, repetida numa segunda execução: o modelo
  escrevia o resumo e devolvia a lista de competências vazia.
- **Eixos e tipos de dor marcados demais**: Eniel recebeu os 5 eixos e os 4
  tipos de dor; Maria Amelia, de matemática pura, recebeu "processos".
- **Competências repetidas com outras palavras**, citando quase os mesmos
  trabalhos (Vinicius: "catálise biomimética" e "porfirinas de manganês").
- **A junção dos lotes perdeu temas**: as 8 competências finais de Eniel citam
  só trabalhos do lote 1; MOOCs, tutoria em EAD, videoaulas e os trabalhos de
  2025–2026, que estavam nos lotes 2 a 4, sumiram. Os lotes são cortados na
  ordem do banco, sem olhar o assunto.
- Os capítulos sobre fósforo no solo de Maria Amelia pareciam de outra pessoa;
  o usuário conferiu e são dela (seção 3.12).

**Mudanças feitas depois da rodada 1.**

1. O modelo escreve as competências antes do resumo, e o formato exige ao
   menos 1 competência (causa provável da falha da Selma).
2. Eixo e tipos de dor passam a ser dados por competência. Os do docente são
   calculados pelo script: um eixo entra se as competências daquele eixo
   somarem pelo menos 2 trabalhos diferentes. Se nenhum chegar a 2, como nos
   docentes de material limitado, entram todos os citados.
3. Regra no prompt contra repetir a mesma competência com outras palavras, e
   aviso do script quando uma competência repete 80% dos trabalhos de outra.
4. A resposta recusada passa a ser guardada no JSON, para entender as falhas.

**Rodada 2 (as 3 variantes, com as mudanças acima).** Em andamento. Por
decisão do usuário, as correções da junção dos lotes (lotes por assunto e
aviso de publicações não citadas) ficam para depois desta rodada, para decidir
com os resultados das 3 variantes.

### 3.14 Google Acadêmico: perfis, validação pelos títulos e publicações novas (22/10/2026)

**Objetivo.** Complementar a OpenAlex com o Google Acadêmico, a pedido do
orientador. Script: `coleta/scholar.py` (não grava no banco; tudo sai em CSV).

**Como a coleta foi feita.** O acesso automático ao Google Acadêmico foi
bloqueado (CAPTCHA logo no primeiro acesso e exigência de login, que o Google
não aceita em navegador controlado por robô). A listagem dos perfis e a coleta
das publicações foram feitas pelo Claude no Chrome do usuário, já logado, com
pausas de 3 a 7 segundos entre as páginas. Os CSVs gerados seguem o formato do
script, que faz o cruzamento e a validação.

**Números.**
- 484 perfis com e-mail confirmado em ufrb.edu.br (`scholar_perfis_ufrb.csv`).
- Cruzamento com os 136 docentes do CETEC: 45 com perfil (40 com nome igual,
  5 com nome abreviado); 91 sem perfil encontrado (`scholar_vinculos.csv`).
- Os 45 foram marcados `vincular` para a coleta, que trouxe 1.515 publicações e
  as métricas de cada perfil (`scholar_publicacoes.csv`, `scholar_metricas.csv`).

**Proteção contra homônimos (4 camadas).** (1) só perfis com e-mail da UFRB
confirmado; (2) nome comparado com a lista do CETEC; (3) confirmação do usuário
para coletar; (4) `validar`: os títulos do Google Acadêmico são comparados com
as publicações do docente já validadas no banco (OpenAlex + ORCID). Com pelo
menos 2 títulos em comum, o perfil é CONFIRMADO. Resultado: 40 CONFIRMADOS,
5 A_CONFERIR, 0 SEM_BASE (`scholar_validacao.csv`).

**Decisão manual: os 5 A_CONFERIR foram confirmados.** Danívio Batista Carvalho
de Vasconcellos, José Valentim dos Santos Filho, Vânio Vicente Santos de Souza,
Erikson Alexandre Fonseca dos Santos e Paulo Henrique Ribeiro do Nascimento.
Motivo: todos têm só 1 ou 2 publicações no banco, então o teste não tinha base
para chegar a 2 títulos em comum; a falha é de base, não indício de homônimo.
Área, afiliação e tipo de trabalho são compatíveis com o CETEC (José Valentim
declara "Professor CETEC-UFRB" no perfil; Erikson e Paulo Henrique têm 1 título
igual ao banco). Registrado na coluna `decisao_manual`, que o `validar` mantém
ao rodar de novo.

**Publicações novas.** Dos perfis confirmados (40 + 5), 726 publicações não
estão no banco (`scholar_publicacoes_novas.csv`, títulos repetidos no mesmo
perfil contados uma vez). Ainda não entraram no banco: a coluna `decisao` é
para a conferência, que pode passar pela triagem por embeddings. Exemplo:
José Valentim tinha 2 publicações no banco e ganha 22 candidatas.

**Triagem das 726 publicações novas (23/10/2026).** Script
`coleta/triagem_scholar.py`, que aplica às publicações do Google Acadêmico as
mesmas regras já usadas no banco, item por item, porque confirmar o perfil não
garante que cada item dele seja do docente (o Google acrescenta trabalhos
sozinho). Seis checagens, nesta ordem:

| Apontamento | Regra | Apontados | Sugestão |
|---|---|---|---|
| ja_excluido | título de trabalho já excluído antes como homônimo do docente (tabela `publicacoes_excluidas`, títulos buscados na OpenAlex e guardados em `dados/excluidas_titulos.csv`) | 4 | ignorar |
| sem_conteudo | regras da seção 3.11 (título genérico, curto, o próprio nome do docente, metadado) | 23 | ignorar |
| ja_no_banco | mesmo trabalho de uma publicação do banco, com outro título ou idioma (embeddings, limites da seção 3.12) | 30 | ignorar |
| repetido | mesmo trabalho de outra publicação nova do docente | 9 | ignorar |
| destoa | assunto isolado da produção do docente: possível homônimo (escore ≤ -3,0, seção 3.12) | 34 | conferir |
| autoria | o nome do docente não aparece entre os autores | 30 | conferir |

Uma das 64 obras excluídas antes (W4287018518) não existe mais na OpenAlex e
ficou sem título para comparar. A comparação por embeddings usou só títulos,
porque o Google Acadêmico não traz resumo; o escore de isolamento ficou abaixo
de -2,96 em 5% das publicações novas (no banco, cerca de 2% eram apontadas).

**Conferência manual.** O usuário revisou a triagem numa planilha e conferiu os
casos no Lattes. Resultado final, em `dados/triagem_scholar.csv`:

| Decisão | Qtd. |
|---|---|
| incluir | 627 (599 sem apontamento, aprovadas em bloco; 28 conferidas) |
| ignorar | 86 |
| orientacao | 13 |

- **Homônimos e trabalhos sem o docente (28, removidos na planilha):** André
  Dias de Azevedo Neto (11: osteoporose, varizes esofágicas, espectroscopia
  gama, duas de antenas, UTI, radiologia, micorrizas em aceroleira (2),
  Crotalaria e Centropomus); Jaildo Santos Pereira (3: leishmaniose, Furnas,
  câncer cervical); Jânia Betânia Alves da Silva (3, de "J Silva"); Ivanoé João
  Rodowanski (2: gestão de cooperativa, livro de biorreatores); Vinicius Santos
  da Silva (2, Revista JOPIC, já excluídos antes); e um de cada: Eniel (via
  férrea), Fernanda Nepomuceno (veículos autônomos), Mário Sérgio (energia
  solar em shoppings), Márcia Cazetta (algas perifíticas), Cleidson (currículo),
  Anaxsandra (limpeza hospitalar), Marcus Vinícius Ivo (banco de leite).
- **Perfil misturado:** o perfil de André Dias de Azevedo Neto no Google
  Acadêmico junta trabalhos de outros "AD Neto" (medicina, engenharia
  elétrica); a lista dele foi conferida inteira, não aprovada em bloco.
- **Falsos "mesmo trabalho" (10 casos conferidos):** a comparação só por
  título juntou trabalhos diferentes de títulos parecidos. Decididos como
  outro trabalho, e incluídos: III-090 e III-084 (Anaxsandra e Lidiane),
  pigmentos em girassol (André), modelo pedagógico virtual UFRB (Ariston e
  Eniel), autorreflexão das competências digitais (Eniel), aspectos
  hidrográficos e geomorfologia da Serra da Jiboia (Thomas, ambos no Lattes).
  Ignorados: "EAD e ensino remoto emergencial: aproximações e distanciamentos"
  (Eniel, mesmo trabalho de "convergências e divergências") e a flambagem
  lateral de viga (Paulo Henrique, não consta no Lattes; só a de coluna).
- **Falsos "destoa":** trabalhos do próprio docente em uma segunda linha de
  pesquisa, ou de docentes com pouca base no banco, foram apontados e mantidos
  (por exemplo, José Valentim em redes e telecomunicações; Paulo Fábio em
  potenciais evocados auditivos, tema que já tem no banco).
- **Orientações (13):** trabalhos de alunos orientados pelo docente, que o
  Google atribui ao orientador (um só autor, que não é o docente; registro na
  UFRB). Não entram como publicação: ficam na tabela `orientacoes`, para uso
  eventual com peso menor nos perfis.
- Divergência resolvida: nos 10 casos acima, as observações da planilha diziam
  "mantém ignorar"; valeram as respostas dadas depois, na conversa.

**Gravação no banco.** `python coleta/triagem_scholar.py --aplicar`. As
publicações entram com `fonte = 'scholar'` e um código próprio no campo
`openalex_id` ("GS-" + 12 caracteres, fixo para o mesmo docente e título), para
que as triagens e o `--excluir` de `openalex_publicacoes.py` funcionem com
elas. Entram só título e ano: o Google não traz resumo, DOI, tipo nem tópicos.
Antes da primeira gravação, o banco é copiado para
`dados/ponte_cetec_antes_scholar.db`.

**Erro da aprovação em bloco e regra acrescentada.** A aprovação em bloco
(`--aprovar-sem-apontamento`) marcou como incluir as 602 publicações que a
triagem não apontou. Ela confia na triagem: o que nenhuma das seis regras sabe
reconhecer passa. Na conferência das aprovadas, três títulos eram, na verdade,
nome de evento ou revista ("14º Congresso Brasileiro de Geologia de
Engenharia e Ambiental", "Revista de Engenharia Civil IMED", "Encontro de
Outono da SBF 2018/ID: 550-1"). A regra de título sem conteúdo passou a
apontar títulos que começam com congresso, simpósio, encontro, seminário,
revista, journal etc., ou que trazem um "ID" numérico. Os três foram mudados
para ignorar (decisão do usuário). Erro que restou na aprovação em bloco:
3 de 602 (0,5%), a registrar no TCC como medida do que a triagem automática
deixa passar.

**Busca do resumo na OpenAlex (23/10/2026, em andamento).** As 627
publicações vindas do Google Acadêmico só têm título. O script
`coleta/scholar_openalex.py` procura cada título na OpenAlex (primeiro só no
campo título; se nada voltar, numa busca ampla em título, resumo e texto) e
aceita o resultado só com título igual, ano compatível (até 1 ano) e, para a
sugestão "usar", o docente entre os autores. Resultado parcial, sem nada
gravado no banco:

| Situação | Qtd. |
|---|---|
| ENCONTRADO (mesmo trabalho, com o docente) | 42 (30 com resumo) |
| SEM_O_DOCENTE (mesmo título, docente não aparece entre os autores) | 42 |
| NAO_ENCONTRADO | 381 |
| ERRO_BUSCA | 1 |
| PENDENTE (busca ampla interrompida pelo limite de uso da OpenAlex) | 161 |

A busca ampla trouxe resultados em 294 de 375 títulos, mas quase nenhum era o
mesmo trabalho. **Decisão:** não esperar a liberação do limite para as 161
pendentes, porque o ganho esperado é de 1 ou 2 trabalhos; a conferência das 84
encontradas (aprovar ENCONTRADO, conferir SEM_O_DOCENTE) e a gravação com
`--aplicar` ficaram para depois. Em SEM_O_DOCENTE há erros de nome da própria
OpenAlex ("Eniel do Eniel", "José Filho", "Gabriela Laura Peixot Botelho"),
além de autores de fato diferentes. A checagem de autoria aceita o nome
invertido ("Dias de Azevedo Neto André", "Azevedo Neto Ad").

**Pendências desta etapa (deixadas para depois, 24/10/2026).**
1. Conferir as 84 publicações achadas na OpenAlex (aprovar as 42 ENCONTRADO com
   `--aprovar-encontrados`, decidir as 42 SEM_O_DOCENTE) e gravar com
   `python coleta/scholar_openalex.py --aplicar`.
2. Opcional: buscar as 161 PENDENTE quando o limite de uso da OpenAlex liberar
   (ganho esperado de 1 ou 2 trabalhos).
3. Testar outras fontes de resumo com uma amostra de 50 títulos não achados na
   OpenAlex: Semantic Scholar (busca por título, grátis) e Crossref (resumos
   enviados pelas revistas, inclusive SciELO); CORE (repositórios, teses e
   dissertações) como terceira opção. Medir o ganho antes de construir a busca
   completa. Trabalhos de anais de congresso (ABES etc.) provavelmente só têm
   resumo no site do evento.

## 4. Limitações

Esta seção reúne todos os problemas encontrados ou previstos na etapa. O quadro
geral abaixo lista cada um em tópicos, com exemplo, efeito e situação. As
subseções 4.1 a 4.16, em seguida, trazem o detalhamento dos casos observados.

Situação de cada item:

- **Tratado**: há uma solução em uso.
- **Parcial**: reduzido, mas não eliminado.
- **Em aberto**: sem solução nesta etapa.

### Quadro geral das limitações

#### A. Cobertura e qualidade dos dados da OpenAlex

- **A1. Docentes sem produção indexada.**
  - Exemplo: Luciano de Santana Rocha, Fabricio de Jesus Ribeiro, Edilberto
    Andrade Silva, Heber Christiane Antunes Franca, Aline de Oliveira Moreira e
    Sérgio Santos de Jesus.
  - Efeito: 7 dos 136 docentes ficam sem publicações e, portanto, sem perfil de
    competências. O sétimo é Elaine Ferreira Rocha, cujo único perfil é misto.
  - Situação: em aberto. Alternativas não adotadas: perfil genérico pela área
    do CETEC ou inclusão manual a partir do Lattes. Detalhe na seção 3.7.
- **A2. Cobertura fraca de certos tipos de trabalho.**
  - Teses, dissertações, trabalhos de congresso, capítulos de livro e artigos
    de revistas regionais sem DOI muitas vezes não estão na base.
  - Efeito: a produção registrada é menor que a real, sobretudo para quem
    publica em veículos locais ou em português.
  - Situação: em aberto.
- **A3. Publicações sem resumo.**
  - Na primeira coleta, 27% das publicações vieram sem resumo.
  - Efeito: para elas, o texto de apoio é só o título e os tópicos atribuídos
    pela OpenAlex.
  - Situação: parcial. Não se concentra em poucos docentes. Detalhe na
    seção 4.7.
- **A4. Registros cujo título é apenas o nome da revista.**
  - Exemplo: "BMC Immunology", "Analytica Chimica Acta", "Ultrasonics".
  - Efeito: o registro não informa o conteúdo do trabalho e polui o perfil.
  - Situação: em aberto. A filtrar antes dos embeddings.
- **A5. O mesmo trabalho em mais de um registro.**
  - A OpenAlex guarda o mesmo trabalho com identificadores diferentes: versão
    em português e em inglês, preprint e artigo final, trabalho de congresso e
    artigo de revista.
  - Exemplo: vários títulos de 2026 de Selma Cristina da Silva aparecem duas
    vezes.
  - Efeito: infla a contagem e dá peso dobrado a um tema.
  - Situação: em aberto. A tratar antes dos embeddings.
- **A6. Classificação de áreas pouco confiável em português.**
  - Exemplo: um artigo sobre inspeção de pontes com drone foi classificado em
    ciências sociais, e um de matemática pura em medicina.
  - Efeito: a área atribuída pela OpenAlex não serve como medida da produção
    do docente.
  - Situação: em aberto. Detalhe na seção 4.14.
- **A7. Datas possivelmente erradas.**
  - Exemplo: um trabalho de Moisés Araújo Oliveira datado de 2010, antes da
    graduação dele (2013).
  - Situação: em aberto, de baixo impacto.

#### B. Identificação dos autores na OpenAlex

- **B1. Perfis fragmentados.** A mesma pessoa aparece dividida em vários
  perfis.
  - Exemplo: Eniel do Espírito Santo e André Dias de Azevedo Neto têm seis
    perfis cada. São 205 perfis vinculados para 127 docentes.
  - Efeito: fragmentos não encontrados significam produção perdida.
  - Situação: parcial. O banco aceita vários perfis por docente. Detalhe na
    seção 4.3.
- **B2. Perfis que misturam pessoas.** Um único perfil reúne trabalhos de
  homônimos.
  - Exemplo: o perfil principal de Selma Cristina da Silva tinha 5 trabalhos
    de cultura; o de Vinicius Santos da Silva, 12 trabalhos alheios em 27.
  - Efeito: o docente apareceria com competências que não tem.
  - Situação: parcial. Catorze perfis foram identificados e limpos, mas pode
    haver outros. Detalhe nas seções 3.8 e 4.14.
- **B3. Homônimo da mesma universidade.**
  - Exemplo: outro Vinícius Santos da Silva, formado em Museologia pela própria
    UFRB.
  - Efeito: a afiliação UFRB deixa de distinguir as duas pessoas.
  - Situação: tratado no caso encontrado; em aberto como risco geral.
- **B4. Homônimo da mesma área.**
  - Exemplo: Felipe Torres-Rivera, com um artigo de combustão de biomassa
    atribuído a Felipe Andrade Torres.
  - Efeito: nem a leitura do título nem a comparação de áreas o detectam.
  - Situação: tratado no caso encontrado, graças ao ORCID; em aberto como risco
    geral.
- **B5. Trabalhos sem perfil de autor.** O trabalho está indexado, mas a
  autoria não foi ligada a nenhum perfil.
  - Exemplo: os artigos de Andrêssa Lima de Souza e de José Hidalgo Suárez.
  - Efeito: só se chega ao trabalho conhecendo o DOI.
  - Situação: parcial. Quatro trabalhos foram incluídos à mão (seção 3.6).
- **B6. ORCID ligado ao perfil errado.**
  - Exemplo: o ORCID de José Hidalgo Suárez leva a um perfil de outra pessoa; o
    perfil de Selma carregava o ORCID de uma homônima.
  - Efeito: ter o ORCID não garante chegar ao perfil certo.
  - Situação: parcial. Os ORCIDs passam por validação (seção 3.9). Detalhe na
    seção 4.6.
- **B7. Os perfis mudam com o tempo.** A OpenAlex reorganiza os agrupamentos.
  - Efeito: um perfil limpo pode receber depois um trabalho de homônimo, e um
    perfil rejeitado pode receber um trabalho verdadeiro do docente.
  - Situação: em aberto. Não há solução definitiva pelo identificador do
    perfil.

#### C. Regras e scripts deste projeto

- **C1. O vínculo automático confere nome e instituição, não o conteúdo.**
  - Efeito: 103 perfis foram aceitos sem que ninguém olhasse os trabalhos, e
    vários misturavam homônimos.
  - Situação: parcial, após a auditoria. É a limitação mais importante da
    etapa. Detalhe na seção 4.14.
- **C2. Regra de comparação de nomes.**
  - Não reconhece quem assina pelo primeiro sobrenome, no padrão hispânico
    ("Valcarce", "Madriz").
  - Não reconhece grafias diferentes ("Valle" e "Vale").
  - Não reconhece nome principal em ordem invertida ("Dutra, Fabrício M.").
  - Aceita nomes curtos e genéricos como compatíveis ("João Pereira").
  - Efeito: os três primeiros fazem perder perfis; o último exige revisão.
  - Situação: parcial. Os casos conhecidos foram resolvidos por ORCID ou DOI.
    Detalhe na seção 4.11.
- **C3. Alcance das buscas.** A busca da OpenAlex exige que todas as palavras
  do nome constem no perfil, e a busca de nome curto sem filtro da UFRB foi
  descartada por só trazer homônimos.
  - Efeito: docente que publica com nome curto e sem afiliação UFRB não é
    encontrado pelo nome.
  - Exemplo: Aldo Alfonso Raul Valcarce Bravo e Gilberto da Silva Pina, achados
    só por ORCID e DOI.
  - Situação: parcial.
- **C4. Auditoria por área.**
  - Gerou cerca de 275 alarmes falsos em 312 trabalhos sinalizados.
  - Falha quando a mistura é grande: no perfil de Vinicius, os trabalhos
    alheios eram um terço e passaram por segunda linha de pesquisa.
  - Não detecta homônimo da mesma área.
  - Deixou de fora 29 docentes com menos de 4 trabalhos classificados.
  - Situação: em aberto. Serve para localizar docentes com problema, não para
    listar todos os trabalhos errados.
- **C5. Trabalhos novos entram sem conferência.**
  - Só os docentes que já tiveram exclusões têm os trabalhos novos listados
    para leitura.
  - Efeito: para os demais, um trabalho de homônimo entraria sem aviso.
  - Situação: em aberto. Requisito da etapa de embeddings.
- **C6. Contagem inflada por coautoria.** Um trabalho com dois docentes do
  CETEC é gravado uma vez para cada um.
  - Efeito: o total de linhas é maior que o de trabalhos distintos.
  - Situação: é intencional, mas deve ser lembrado ao citar números.
- **C7. ORCID gravado automaticamente.** O script copiava para o docente o
  ORCID encontrado em um perfil vinculado.
  - Efeito: em perfil misturado, o ORCID gravado podia ser o do homônimo, como
    ocorreu com Selma.
  - Situação: tratado. Os ORCIDs agora são validados antes do uso.

#### D. Decisões manuais

- **D1. Aprovação em bloco.** Setenta e sete perfis foram aprovados só pelo
  nome, por probabilidade.
  - Situação: parcial. O relatório de perfis revisou depois os perfis
    secundários e não achou nenhum inteiro de outra pessoa.
- **D2. Aprovações de menor confiança.** Aceitas por nome idêntico e área
  compatível, sem afiliação UFRB.
  - Exemplo: Danilo de Jesus Ferreira, Luiz Alberto de Oliveira Silva e Manuela
    Oliveira de Souza.
  - Situação: em aberto. Detalhe na seção 4.8.
- **D3. Exclusões decididas só pelo título.** Parte dos 45 trabalhos excluídos
  saiu sem conferência no Lattes, por destoar da área do docente.
  - Efeito: risco de ter excluído um trabalho legítimo.
  - Situação: parcial. A exclusão é reversível, e nenhuma foi contrariada pelo
    ORCID.
- **D4. O título engana nos dois sentidos.** Em 9 dos 12 docentes levados ao
  Lattes, os trabalhos que pareciam de outra área eram mesmo deles.
  - Exemplo: os trabalhos de Pollyane Vieira da Silva sobre parques de São
    Paulo, e o de Rogelma Maria da Silva Ferreira sobre águas subterrâneas.
  - Efeito: não se pode excluir só porque o tema destoa.
- **D5. Fontes de verificação limitadas.** O Lattes e o SIGAA exigem CAPTCHA, e
  o Escavador pode estar desatualizado.
  - Exemplo: o Escavador descrevia Basílio e Talison como ex-substitutos; os
    dois são professores do CETEC desde 2026.
  - Situação: em aberto. Detalhe nas seções 4.9 e 4.10.
- **D6. Dependência de julgamento humano.** Vínculos, exclusões e confirmações
  de ORCID envolveram decisões de uma pessoa.
  - Efeito: outra pessoa poderia decidir diferente em casos de fronteira.
  - Situação: parcial. Todas as decisões estão registradas neste documento e
    podem ser refeitas (seção 5).
- **D7. Google Acadêmico não consultado.** Estava previsto no plano como
  complemento e foi substituído por ORCID e DOI, por não ter API.
  - Efeito: uma fonte mantida pelos próprios docentes ficou sem uso, inclusive
    para conferência manual.
  - Situação: em aberto. Seria mais útil para os 76 docentes sem ORCID
    confirmado. Detalhe na seção 2.8.

#### E. Validação pelo ORCID

- **E1. Cobertura.** Só 67 dos 136 docentes têm ORCID conhecido, e 60 foram
  confirmados.
- **E2. Registros vazios ou incompletos.** Vários registros, inclusive de
  ORCIDs confirmados, não têm nenhuma obra, e os demais costumam listar menos
  do que a OpenAlex.
  - Efeito: a ausência de um trabalho no ORCID não prova nada.
- **E3. Obras sem DOI.** Noventa e quatro obras do ORCID não foram incluídas,
  por não haver como localizá-las com segurança.
- **E4. Emprego autodeclarado.** O critério depende de o docente manter o
  registro atualizado.
  - Exemplo: Diego Lima Medeiros não declara emprego nenhum.
- **E5. Coincidência é evidência fraca.** O ORCID veio do perfil da OpenAlex, e
  as publicações do banco vieram do mesmo perfil. Elas tendem a coincidir mesmo
  quando o perfil é de um homônimo.
  - Situação: tratado. A confirmação exige emprego na UFRB ou trabalho-âncora.
- **E6. Confirmações manuais.** Catorze ORCIDs foram confirmados por evidência
  externa, e sete ficaram em aberto. Detalhe nas seções 3.9 e 4.15.

#### F. A lista de docentes

- **F1. É um retrato do site em 01/10/2026.** Quem entrou ou saiu depois não
  aparece, e o site pode estar desatualizado.
  - Exemplo: há dúvida sobre o vínculo de Elaine Ferreira Rocha, Diego Lima
    Medeiros e Aldo Alfonso Raul Valcarce Bravo.
  - Efeito: a ferramenta pode indicar alguém que não está mais no centro.
  - Situação: em aberto. A confirmar com o centro. Detalhe na seção 4.10.
- **F2. Docentes recém-contratados.** Têm quase toda a produção feita em outras
  instituições.
  - Situação: tratado. A busca inclui perfis fora da UFRB, e as publicações são
    baixadas sem filtro de instituição.
- **F3. Dados não coletados do site.** O endereço do Lattes e o ORCID não vieram
  na coleta.
  - Efeito: a conferência no Lattes foi manual, e o ORCID veio da OpenAlex.
  - Situação: em aberto.

#### G. Efeitos sobre o resultado da ferramenta

- **G1. Distribuição desigual.** A média é de cerca de 15 publicações por
  docente, mas alguns têm em torno de 100 e mais de uma dezena tem uma ou duas.
  - Efeito: a ferramenta tende a favorecer quem tem mais texto indexado.
  - Detalhe na seção 4.2.
- **G2. Poucas publicações para quem tem doutorado.**
  - Exemplo: José Hidalgo Suárez, doutor desde 2019, com 1 publicação; João
    Cláudio Costa Pereira, com 2.
  - Efeito: não deve ser lido como baixa produção. É efeito da indexação.
  - Detalhe na seção 4.1.
- **G3. Só entra o que é publicação indexada.** Projetos de extensão, produção
  técnica, patentes, orientações e consultorias não estão na base.
  - Efeito: competências práticas, que interessam às empresas, ficam
    sub-representadas.
  - Situação: em aberto.
- **G4. Produção antiga ou de outra fase pesa no perfil.**
  - Exemplo: os trabalhos de gestão hospitalar de Eniel do Espírito Santo, de
    2012 a 2017.
  - Efeito: o perfil pode refletir uma competência que o docente não exerce
    mais.
  - Situação: em aberto. A decidir se o perfil deve dar mais peso ao recente.
- **G5. Contaminação residual.** Pode haver trabalhos de homônimos ainda não
  detectados.
  - Efeito: risco de indicar um docente por uma competência que ele não tem. É
    o erro mais grave para o propósito da ferramenta.
  - Situação: parcial.

- **G6. Produção no Lattes muito maior que na base, nos docentes com poucas
  publicações.**
  - Exemplo: Renê Medeiros de Souza tem 3 publicações na base; no Escavador, que
    replica o Lattes, aparecem muitos títulos a mais.
  - Efeito: o perfil de competências desses docentes mostra só uma parte da
    produção, e a ferramenta tende a indicá-los menos do que a competência real
    justificaria.
  - Situação: em aberto. A diferença está sendo medida na conferência manual da
    Etapa 4 (seção 4.16). Complementar a base com o Lattes depende de decisão do
    orientador (ponto 4 abaixo).

#### H. Operação e reprodução

- **H1. O banco fica fora do Git.** Foi encontrado vazio em 05/10/2026, por
  causa não identificada.
  - Situação: parcial. Os scripts param se o banco estiver vazio, e as decisões
    ficam neste documento e no CSV versionado. Detalhe na seção 4.13.
- **H2. Dependência de serviços externos.** A OpenAlex exige chave e cobra por
  consulta; a API do ORCID falhou por demora em uma execução.
  - Efeito: mudança de preço, de formato ou indisponibilidade afeta a coleta.
  - Situação: parcial. As consultas ao ORCID tentam três vezes.
- **H3. O resultado é datado.** A OpenAlex, o ORCID e o site do CETEC mudam.
  Rodar tudo de novo em outra data dará números diferentes.
  - Situação: a data da coleta deve constar no texto do TCC.
- **H4. Identificadores internos.** O número de cada docente depende da ordem
  da coleta do site.
  - Situação: tratado na restauração, que localiza o docente pelo nome.
- **H5. Scripts testados com dados simulados.** Erros apareceram só no uso
  real, como a comparação de DOIs com prefixo e o nome gravado sem espaço.
  - Situação: corrigidos quando encontrados; podem existir outros.

#### Pontos que dependem de decisão do orientador

1. Se Elaine Ferreira Rocha, Diego Lima Medeiros e Aldo Alfonso Raul Valcarce
   Bravo continuam no CETEC.
2. O que fazer com os 7 docentes sem publicações na base.
3. Se a produção antiga, de outra área ou de outra instituição deve contar no
   perfil de competências.
4. Se vale complementar a OpenAlex com o Lattes, para produção técnica e
   trabalhos sem DOI.
5. Se o centro pode orientar os docentes a reivindicar o perfil na OpenAlex e a
   manter o ORCID atualizado, o que reduz vários dos problemas acima na origem.
6. Se as aprovações em bloco e as exclusões feitas só pelo título são
   aceitáveis, ou se pedem conferência adicional.

### 4.1 Poucas publicações para quem tem doutorado

Vários docentes com doutorado aparecem com uma ou duas publicações. Isso não
deve ser lido como baixa produção: é um efeito da forma como a OpenAlex indexa
e agrupa os trabalhos.

| Docente | Formação conhecida | Publicações na base | O que se observou |
|---|---|---|---|
| José Hidalgo Suárez | Doutorado na UFBA (2019) | 1 | O ORCID dele está ligado ao perfil de outro autor; o único artigo achado não tem perfil |
| João Cláudio Costa Pereira | Tese na UFBA (2015) | 2 | Um artigo em perfil de um trabalho só, outro em perfil misto; tese e dissertação não indexadas |
| Andrêssa Lima de Souza | Doutorado na UFBA | 1 | Artigo indexado sem perfil de autor; tese e dissertação não indexadas |
| Nilton Cardoso da Silva | Doutorado na Unicamp | 2 | Só um perfil pequeno, fora da UFRB |
| Celso Luiz Borges de Oliveira | Doutorado na Unicamp | 2 | O outro candidato era um perfil poluído, rejeitado |
| Danilo de Jesus Ferreira | Tese de 2017 (UFSCar, pelo perfil) | 2 | As duas publicações são a dissertação e a tese |
| Gilberto da Silva Pina | Pós-graduação na UnB | 2 | Dois perfis de um trabalho cada |
| Elaine Ferreira Rocha | Doutorado na UFBA | 0 | Os trabalhos dela estão em um perfil misto |

Causas prováveis, em ordem de frequência observada:

1. **Fragmentação.** A OpenAlex divide a mesma pessoa em vários perfis, e os
   que não têm nome compatível ou afiliação reconhecível não são encontrados.
2. **Autoria sem perfil.** O trabalho está indexado, mas o autor não foi ligado
   a nenhum perfil. Só se chega a ele conhecendo o DOI.
3. **Trabalhos presos em perfis mistos**, que não podem ser vinculados inteiros.
4. **Cobertura.** Teses, dissertações, trabalhos de congresso, capítulos e
   artigos de revistas regionais sem DOI muitas vezes não estão na base.
5. **Variação do nome.** O docente publica com uma forma que a regra de nomes
   não reconhece (seção 4.11).

Há ainda docentes com uma ou duas publicações cuja formação não foi
verificada: Sânzia Alves do Nascimento, Sílvia Patrícia Barreto Santana,
Janailson Oliveira Cavalcanti, Silvio de Cerqueira Mazza, Thamara Vier Vieira,
Tassio Gabriel Ribeiro Lopes, Danívio Batista Carvalho de Vasconcellos,
Junilson Cerqueira da Silva, Vânio Vicente Santos de Souza, Roberta Alessandra
Bruschi Goncalves Gloaguen e Inacio Oliveira Borges.

Consequência para o projeto: o perfil de competências desses docentes será
raso, e a ferramenta tende a indicá-los menos do que a competência real
justificaria.

### 4.2 Distribuição desigual

A média é de cerca de 15 publicações por docente, mas a distribuição é muito
desigual. Um docente tem em torno de 100, vários passam de 50, e mais de uma
dezena tem só uma ou duas. A ferramenta favorece naturalmente quem tem mais texto
indexado.

### 4.3 Perfis fragmentados

Os 205 perfis vinculados pertencem a 127 docentes, cerca de 1,6 por docente.
Alguns têm cinco ou seis perfis (Eniel do Espírito Santo, André Dias de Azevedo
Neto, Selma Cristina da Silva, Adilson Brito de Arruda Filho). Os perfis extras
costumam ser pequenos, "sem instituição", com o nome idêntico ao principal. É
provável que existam outros fragmentos não encontrados.

**Por que há tantos perfis por docente.** Os perfis de autor da OpenAlex não
são cadastrados por ninguém. Segundo a documentação da própria OpenAlex, um
modelo de aprendizado de máquina decide quais autorias, entre milhões de
trabalhos, pertencem à mesma pessoa, pesando seis sinais, entre eles os padrões
de coautoria e o ORCID. A OpenAlex reconhece que, nessa escala, o resultado
nunca é perfeito, e descreve duas falhas típicas: a mesma pessoa dividida em
perfis duplicados e trabalhos de pessoas diferentes reunidos em um perfil só.
Esta etapa encontrou as duas (a segunda está na seção 4.4).

Nos dados desta etapa, a divisão aparece associada a quatro situações:

1. **Trabalho sem afiliação registrada.** É o caso mais frequente. A maioria
   dos perfis extras está "sem instituição" e tem de um a três trabalhos, o
   que é típico de teses, dissertações, resumos de eventos e artigos de
   revistas menores, cujos metadados chegam incompletos.
2. **Variação na grafia do nome.** "Ariston de Lima Cardoso" e "Ariston Lima
   Cardoso"; "Sivanildo S. Borges" e "Sivanildo da Silva Borges"; nomes em
   maiúsculas ou sem acento.
3. **Mudança de instituição.** Trabalhos da pós-graduação ou de um vínculo
   anterior ficam em um perfil, e os da UFRB em outro (por exemplo, perfis
   ligados à UFBA, à Universidade Federal de Viçosa ou à UFMG).
4. **Ausência de ORCID.** Sem um identificador único informado nos artigos,
   falta ao algoritmo o sinal que a OpenAlex considera o mais forte.

Muitos dos perfis extras têm identificadores na mesma faixa numérica (iniciados
por A5122), o que sugere que foram criados em uma mesma carga de dados. Isso é
uma inferência a partir dos identificadores, não uma informação documentada
pela OpenAlex.

Efeito no projeto: foi preciso aceitar vários perfis por docente e impedir, no
banco, que o mesmo trabalho fosse gravado duas vezes.

**O que a OpenAlex recomenda para corrigir.** A orientação oficial é que a
correção seja feita pelo próprio autor:

1. O autor cria uma conta gratuita em openalex.org, localiza o seu perfil e o
   reivindica (opção "Claim").
2. No perfil reivindicado, ele acrescenta os trabalhos que faltam, buscando
   por título, colando DOIs ou enviando o currículo.
3. Não existe um botão de "unir perfis". Unir duplicatas consiste em mover para
   o perfil reivindicado os trabalhos que estão no outro; separar pessoas
   misturadas consiste em remover do perfil os trabalhos alheios.
4. Nome alternativo, instituição e métricas não são editáveis: derivam dos
   trabalhos ligados ao perfil e se atualizam quando esses trabalhos mudam.
5. Corrigir o perfil de outra pessoa (como bibliotecário, coautor ou setor de
   pesquisa) não é direto: exige abrir um pedido de correção à OpenAlex.

Sobre o ORCID, a OpenAlex faz duas ressalvas que coincidem com o que foi
observado aqui. Perfis com o mesmo ORCID não são unidos automaticamente, e um
ORCID pode aparecer em mais de um perfil, ou no perfil errado, por erro nos
dados enviados pelas editoras. A recomendação é tratar o ORCID compartilhado
como indício, não como prova. O caso de José Hidalgo Suárez (seção 4.6) é um
exemplo.

Implicação para o projeto: não é possível corrigir os perfis dos docentes por
conta própria, porque eles não pertencem a quem faz a coleta. O caminho de
maior efeito seria orientar os docentes do CETEC a reivindicar e revisar o
próprio perfil na OpenAlex. Isso reduziria a fragmentação na origem e poderia
recuperar parte da produção que esta etapa não alcançou.

Fontes (documentação da OpenAlex, consultada em 06/10/2026):
[Disambiguation](https://help.openalex.org/data/authors/disambiguation/),
[Fixing errors: Authors](https://help.openalex.org/access/fixing-errors/authors/),
[Fixing authors](https://help.openalex.org/how-to/fixing-authors/) e
[ORCID](https://help.openalex.org/data/authors/orcid/).

### 4.4 Perfis poluídos e registros defeituosos

- **Perfis poluídos:** um único identificador reúne dezenas de pessoas
  diferentes. O sinal típico é o nome principal só com iniciais e um sobrenome
  comum ("E P Silva", "OLIVEIRA F.F.", "L A Gomes"), com dezenas de variações
  de nome sem relação entre si.
- **Registros defeituosos:** a lista inteira de autores de um trabalho gravada
  como se fosse o nome de uma pessoa só. Um desses registros tinha quinze nomes.
- **Perfis mistos de docentes:** "J. Oliveira" (Joanito) e "João Pereira" (João
  Cláudio) tinham ao menos um trabalho real ligado ao CETEC, misturado com
  trabalhos de outras pessoas.

A regra de compatibilidade de nomes barra a maior parte desses casos, mas os
perfis mistos só foram identificados na verificação individual.

### 4.5 Homônimos

Nome completo idêntico não garante que seja a mesma pessoa. Exemplos
encontrados: um Sérgio S. de Jesus engenheiro químico, três perfis "Basilio
Fernández" de medicina e administração, perfis de Selma Cristina da Silva de
áreas sem relação, e uma Andressa Lima de Souza da área de saúde. A OpenAlex às vezes marca homônimos
com "(2)" no nome, mas não de forma consistente: "Adilson Brito (2) Arruda
Filho" é o próprio docente, com afiliação UFRB.

### 4.6 ORCID no perfil errado

Ter o ORCID não garante chegar ao perfil certo. O ORCID de José Hidalgo Suárez
leva a um perfil com dez trabalhos de outra pessoa. O perfil misto de Joanito
de Andrade Oliveira carrega o ORCID dele junto com trabalhos alheios. Já o
ORCID de João Cláudio Costa Pereira existe, mas não retorna nada na OpenAlex.

O inverso também ocorre: o perfil do docente pode carregar o ORCID de um
homônimo. O perfil principal de Selma Cristina da Silva (A5012710225) traz o
ORCID 0000-0002-5658-6448, que pertence à outra Selma. O registro desse ORCID
lista apenas dois artigos da Liinc em Revista, sobre cultura e ciência da
informação, que são dois dos trabalhos excluídos na auditoria (seção 3.8).

Isso afeta o banco. O script de vínculo grava no docente o ORCID encontrado em
um perfil vinculado automaticamente, quando o campo está vazio. Quando o perfil
mistura pessoas, o ORCID gravado pode ser o do homônimo. Portanto, os ORCIDs da
tabela `docentes` vieram da OpenAlex por esse caminho, e não do próprio
docente, e só são confiáveis depois de conferidos no Lattes ou na página do
ORCID. O de Vinicius Santos da Silva foi corrigido assim. No caso de Selma, o
ORCID da homônima tinha sido gravado no banco e foi removido; o currículo dela
não informa ORCID próprio. Os outros quatro ORCIDs gravados para docentes com
trabalhos excluídos na auditoria (Mário Sérgio de Souza Almeida, Leandro
Cerqueira Santos, Igor Dantas dos Santos Miranda e Felipe Andrade Torres)
foram conferidos na página do ORCID e estão corretos. Os ORCIDs dos demais
docentes não passaram por essa conferência.

### 4.7 Publicações sem resumo

Na primeira coleta, 27% das publicações vieram sem resumo. Para elas, o texto
de apoio será o título mais os tópicos atribuídos pela OpenAlex. A falta de
resumo não se concentra em poucos docentes: dos 14 docentes com no máximo um
resumo, 13 tinham só uma ou duas publicações no total. O único caso de falta de
resumo propriamente dita é Joaquim Jorge Martins Galo, com 7 publicações e 1
resumo. Naquela coleta, quatro docentes dependiam apenas de título e tópicos.

### 4.8 Decisões de menor confiança

- Os 77 perfis aprovados em bloco (seção 3.1) não foram verificados um a um.
- Os 103 perfis vinculados automaticamente também não foram abertos um a um. A
  auditoria (seções 3.8 e 4.14) mostrou que vários misturavam homônimos.
- Três perfis foram aceitos por nome idêntico e área compatível, sem afiliação
  UFRB: Danilo de Jesus Ferreira (A5028891547), Luiz Alberto de Oliveira Silva
  (A5038074295) e Manuela Oliveira de Souza (A5155390927).
- O perfil de Moisés Araújo Oliveira tem um trabalho datado de 2010, anterior à
  graduação dele (2013). Pode ser iniciação científica ou erro de data.
- O perfil de Aldo Valcarce, com 47 trabalhos, não tem a UFRB entre as
  afiliações.

### 4.9 Verificação limitada por CAPTCHA

O Lattes e o SIGAA da UFRB bloqueiam leitura automática, e as páginas
individuais dos docentes no site do CETEC retornavam erro. A formação de vários
docentes foi obtida pelo Escavador, que replica o Lattes e pode estar
desatualizado. Só três currículos foram lidos diretamente no Lattes.

### 4.10 Docentes possivelmente fora do CETEC

O Escavador registrava Elaine Ferreira Rocha na UNIVASF desde 2019 e Diego Lima
Medeiros na UFMA desde 2022, e descrevia Basílio Fernandez Fernandez e Talison
Augusto Correia de Melo como ex-professores substitutos. Os quatro constam na
lista do site do CETEC coletada em 01/10/2026.

Para Basílio e Talison, a dúvida foi resolvida pelo ORCID. Os dois declaram
emprego como professores do CETEC "até o presente", com início em 20/08/2026 e
01/07/2026. O Escavador estava desatualizado: eles foram substitutos, saíram e
voltaram como professores em 2026. Retirá-los da base com base naquela
informação teria sido um erro.

Continuam sem confirmação, e devem ser verificados com o centro:

- Elaine Ferreira Rocha, que não tem ORCID próprio na base;
- Diego Lima Medeiros, cujo ORCID não declara nenhum emprego;
- Aldo Alfonso Raul Valcarce Bravo, cujo ORCID declara emprego na Universidade
  Estadual de Feira de Santana, e não na UFRB.

Docentes contratados em 2026 têm quase toda a produção feita em outras
instituições. É o caso em que buscar perfis também fora do filtro da UFRB faz
mais diferença.

### 4.11 Limites da regra de nomes

A regra exige que o último sobrenome seja igual, e por isso falhou em dois
casos resolvidos depois pelo ORCID:

- Aldo Alfonso Raul Valcarce Bravo publica como "Valcarce", o primeiro
  sobrenome, no padrão hispânico.
- Tassio Ferreira Valle aparece como "Vale", com um L só.

Ela também aceita, por desenho, nomes curtos e genéricos como compatíveis
("João Pereira" para João Cláudio Costa Pereira). Esses casos caem em
"conferir" e dependem da revisão manual.

A regra não reconhece nomes em ordem invertida, no formato de referência
bibliográfica ("Dutra, Fabrício M."). A comparação usa só o nome principal do
perfil e exige a mesma ordem das palavras e o último sobrenome no final. Um
perfil cujo nome principal esteja invertido é descartado, mesmo que a busca da
OpenAlex o encontre. O erro é para o lado seguro: o perfil deixa de ser
vinculado, mas ninguém é vinculado por engano. A inversão é frequente nas
variações de nome dos perfis, que a regra não consulta, e rara no nome
principal; nos casos vistos, apareceu apenas em perfis poluídos ("OLIVEIRA
F.F."). Não foi identificado docente perdido por esse motivo, mas não se pode
descartar que algum perfil pequeno tenha ficado de fora. O tratamento possível,
não implementado, é reordenar o nome quando houver vírgula antes de comparar.

### 4.12 Coautoria e contagem

Um trabalho com dois docentes do CETEC como coautores é gravado duas vezes, uma
para cada docente. O total de 1.987 linhas é maior que o número de trabalhos
distintos.

### 4.13 Perda do banco em 05/10/2026

O arquivo `dados/ponte_cetec.db` foi encontrado vazio no dia 5, por causa não
identificada. Foi reconstruído rodando de novo `dados/criar_banco.py` e
`coleta/coleta_docentes.py`. Os vínculos gravados pela primeira versão do
script se perderam, o que não teve impacto porque a versão nova refaz tudo.
Desde então, os scripts param com erro se o banco não existir ou estiver sem
docentes, em vez de criar um banco em branco, e as decisões da revisão ficam
versionadas em `dados/openalex_vinculos.csv`.

### 4.14 O vínculo automático não garante um perfil de uma pessoa só

É a limitação mais importante encontrada na etapa. A regra de vínculo
automático conferia o nome e a instituição do perfil, mas não o conteúdo dele.

- **A OpenAlex junta homônimos no mesmo perfil.** Basta um trabalho do perfil
  declarar a UFRB para ele passar no filtro; os demais podem ser de outra
  pessoa. Dos 205 perfis vinculados, 14 tinham trabalhos alheios, entre os que foram
  examinados.
- **A afiliação UFRB não distingue homônimos da mesma universidade.** O perfil
  de Vinicius Santos da Silva, químico do CETEC, reunia trabalhos de outro
  Vinícius Santos da Silva, formado em Museologia e mestre em Ciências Sociais
  pela própria UFRB. Dos 27 trabalhos do perfil, 12 eram alheios.
- **A classificação de áreas da OpenAlex não serve de medida.** Em títulos em
  português ela erra com frequência: um artigo sobre inspeção de pontes foi
  posto em ciências sociais e um de matemática pura em medicina. Dos 312
  trabalhos sinalizados pela auditoria, cerca de 275 eram alarmes falsos.
- **A auditoria por área falha quando a mistura é grande.** No perfil do
  Vinicius, os trabalhos alheios eram um terço do total. A área deles deixou de
  ser minoritária e passou por segunda linha de pesquisa, e nenhum foi
  sinalizado.
- **O título sozinho engana nos dois sentidos.** Em 9 dos 12 docentes levados
  ao Lattes, os trabalhos que pareciam de outra área eram mesmo deles, por
  colaboração, orientação ou fase anterior da carreira.

O que permanece em aberto:

- Um homônimo que publique na mesma grande área do docente não é detectado.
- Os 29 docentes com menos de 4 trabalhos classificados não foram auditados.
- Só 10 docentes tiveram a lista completa de títulos lida.
- A OpenAlex reorganiza os perfis com o tempo. Um perfil limpo pode receber
  depois um trabalho de homônimo, e um perfil rejeitado pode receber um
  trabalho verdadeiro do docente.
- Hoje, só os docentes que já tiveram exclusões têm os trabalhos novos listados
  para conferência. Para os demais, um trabalho de homônimo entraria sem aviso.

Encaminhamento: na etapa de embeddings, medir a semelhança de cada trabalho
com a produção do docente e sinalizar os que destoam, para confirmação manual
e sem exclusão automática. Esse método lê o conteúdo do texto e não depende da
classificação da OpenAlex. Nessa etapa convém também filtrar os registros cujo
título é apenas o nome de uma revista.

### 4.15 Limites da validação pelo ORCID

- **Cobertura.** Só 67 dos 136 docentes têm ORCID conhecido, e 60 foram
  confirmados. Os demais continuam dependendo apenas da OpenAlex.
- **Registros incompletos ou vazios.** Vários registros confirmados não têm
  nenhuma obra, e os que têm costumam listar menos trabalhos do que a OpenAlex.
  Por isso a ausência de um trabalho no ORCID nunca é usada para excluí-lo.
- **Obras sem DOI.** As 94 obras sem DOI não foram incluídas, porque não há
  como localizá-las com segurança na OpenAlex. São sobretudo capítulos de livro
  e trabalhos de congresso.
- **Nomes hispânicos.** A regra de nomes exige o último sobrenome, e não
  reconhece quem assina pelo primeiro ("Aldo Valcarce", "Eleazar Madriz").
- **Emprego autodeclarado.** O critério do emprego depende de o docente manter
  o registro atualizado. Diego Lima Medeiros e Pollyane Vieira da Silva, por
  exemplo, não declaram a UFRB.
- **Confirmações manuais.** Catorze ORCIDs foram confirmados por evidência
  externa (Lattes, nome completo raro, perfil com afiliação UFRB), e não pelos
  dois critérios automáticos.
- **Versões do mesmo trabalho.** Uma obra pode ter mais de um DOI, como o
  preprint e o artigo final, ou o trabalho de congresso e o de revista. Parte
  das 29 inclusões pode ser outra versão de algo que já estava no banco.
- **ORCID divergente como sinal.** Quando um perfil de um docente traz um ORCID
  diferente do confirmado, o perfil provavelmente mistura pessoas. Só um caso
  apareceu, o de Felipe Andrade Torres, e ele revelou um homônimo da mesma
  área.

### 4.16 Diferença entre a base e o Lattes nos docentes com poucas publicações

Na Etapa 4, os docentes com até 3 publicações e nenhuma confirmada pelo ORCID
passaram por conferência manual: 30 docentes e 60 publicações, listados em
`dados/conferir_poucas_publicacoes.csv`. O critério é de risco: com tão pouco
material, um único trabalho de homônimo dominaria o perfil de competências.

Durante a conferência, em 09/10/2026, observou-se que vários desses docentes
têm no Lattes (consultado pelo Escavador) muito mais trabalhos do que na base.
Para eles, a pouca produção na base é efeito da indexação da OpenAlex, e não
de baixa produção, o que confirma a limitação G2 e a seção 4.1.

Consequência para o projeto: o perfil de competências desses docentes será
gerado a partir de uma fração da produção real, e tende a subestimá-los no
cruzamento com as dores de mercado.

Medição em andamento: para cada docente conferido, anota-se no CSV o total de
trabalhos que aparecem no Lattes, contando só os tipos que a OpenAlex também
cobre (artigos, trabalhos em congresso, capítulos e livros). A comparação com o
número de publicações na base dará a cobertura da OpenAlex para esse grupo e
será registrada nesta seção ao fim da conferência.

O complemento pelo Lattes não foi feito, pelos seguintes motivos:

- O Lattes e o Escavador bloqueiam a leitura automática, e a coleta automática
  contraria os termos de uso do Escavador. O caminho viável seria a cópia manual
  dos títulos, restrita aos docentes com poucas publicações.
- O Lattes traz basicamente título, ano e veículo, sem resumo, o que dá menos
  texto ao modelo que gera os perfis.
- Os títulos teriam de ser comparados com os já presentes na base, para evitar
  duplicatas.

A favor do complemento: o Lattes é preenchido pelo próprio docente, então não
mistura homônimos, e inclui produção técnica, patentes e trabalhos sem DOI, que
a OpenAlex não cobre. A tabela `publicacoes` já tem a coluna `fonte`, que
permitiria identificar esses trabalhos.

### 4.17 Limites do Google Acadêmico

- **Cobertura.** Só 45 dos 136 docentes têm perfil com e-mail da UFRB
  confirmado; os demais não ganham nada com esta fonte. Um critério que use
  dados do Google Acadêmico (por exemplo, citações no ranking) penaliza quem
  não tem perfil; para comparar docentes, a fonte comum é a OpenAlex.
- **Acesso.** Não há API oficial; o acesso automático foi bloqueado por CAPTCHA
  e exigência de login, e os termos de uso do Google proíbem a coleta
  automatizada. A coleta foi feita no navegador do usuário e não roda sozinha.
- **Qualidade dos registros.** O próprio Google adiciona trabalhos ao perfil e
  pode incluir trabalho de homônimo; há registros sem ano (200 das 726
  publicações novas) ou sem veículo (306), e o mesmo trabalho às vezes aparece
  duas vezes (versão em português e em inglês, ou evento e revista).
- **Sem resumo.** O Google Acadêmico traz só o título, o que deixa o conteúdo
  dessas publicações mais raso para os perfis de competência.
- **Validação fraca para quem tem pouca base.** A regra de 2 títulos em comum
  não funciona para docentes com 1 ou 2 publicações no banco (seção 3.14).
- **Docentes sem perfil.** 91 dos 136 docentes não têm perfil com e-mail da
  UFRB confirmado. A busca manual de 10 deles, os com menos publicações no
  banco (Aline de Oliveira Moreira, Edilberto Andrade Silva, Elaine Ferreira
  Rocha, Fabricio de Jesus Ribeiro, Heber Christiane Antunes Franca, Inacio
  Oliveira Borges, Luciano de Santana Rocha, Silvio de Cerqueira Mazza, Sérgio
  Santos de Jesus e Andrêssa Lima de Souza), não encontrou perfil.
- **Lattes nem sempre localizável.** O de Camila Angélica Baum não foi
  encontrado; nesses casos a conferência se apoiou no ORCID confirmado e nos
  títulos em comum com o banco.
- **Comparação só por título.** Sem resumo, a triagem por embeddings confunde
  trabalhos diferentes de títulos parecidos (seção 3.14) e aponta como
  "destoa" trabalhos de uma segunda linha de pesquisa do docente; por isso as
  sugestões passaram por conferência.
- **Perfis do Google com trabalhos de terceiros.** O caso mais grave foi o de
  André Dias de Azevedo Neto (homônimos "AD Neto" de outras áreas).
- **A aprovação em bloco herda os pontos cegos da triagem.** Dos 602 itens sem
  apontamento, 3 (0,5%) não eram trabalhos (nome de evento ou revista com
  título longo). A regra foi ampliada, mas outros tipos de lixo que nenhuma
  regra conhece podem ter passado.
- **A OpenAlex não cobre a maior parte do que o Google Acadêmico trouxe.**
  Das 627 publicações novas, só cerca de 84 (13%) foram achadas na OpenAlex pelo
  título, e só cerca de 57 delas com resumo. O restante são sobretudo trabalhos
  em anais de congressos brasileiros (por exemplo, os da ABES), revistas locais
  e trabalhos sem DOI. Por isso cerca de 540 publicações ficam só com o título,
  o que deixa o conteúdo delas raso nos perfis de competência. A busca por
  título também depende do limite diário de uso da chave da OpenAlex.
- **Orientações misturadas às publicações.** O Google atribui ao orientador
  trabalhos de alunos; foram separados na tabela `orientacoes`.
- **Por que a OpenAlex tem pouco de alguns docentes.** A comparação mostrou que
  muito do que falta saiu em anais de eventos brasileiros, revistas locais da
  UFRB e trabalhos sem DOI, que a OpenAlex cobre mal (ver 4.1 e 4.16).

## 5. Como restaurar as decisões se o banco se perder

1. Recriar o banco e os docentes:

```bash
python dados/criar_banco.py
python coleta/coleta_docentes.py
```

2. Refazer a busca de perfis, o que também cria as tabelas de vínculo:

```bash
python coleta/openalex_autores.py
```

3. Reaplicar os status da revisão a partir do CSV versionado. O trecho abaixo
   localiza cada docente pelo nome, então funciona mesmo que os identificadores
   mudem, e insere os perfis que foram adicionados à mão:

```python
import sqlite3
import pandas as pd

csv = pd.read_csv("dados/openalex_vinculos.csv", encoding="utf-8-sig").dropna(subset=["openalex_id"])

with sqlite3.connect("dados/ponte_cetec.db") as conn:
    for r in csv.itertuples():
        docente = conn.execute("SELECT id FROM docentes WHERE nome = ?", (r.nome,)).fetchone()
        if not docente:
            print("docente não encontrado:", r.nome)
            continue
        conn.execute(
            """
            INSERT INTO docente_openalex
                (docente_id, openalex_id, status, nome_openalex, na_ufrb, nome_inteiro, publicacoes, instituicao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(docente_id, openalex_id) DO UPDATE SET status = excluded.status
            """,
            (
                docente[0], r.openalex_id, r.status, r.nome_openalex,
                int(r.na_ufrb), int(r.nome_inteiro),
                None if pd.isna(r.publicacoes) else int(r.publicacoes),
                None if pd.isna(r.instituicao) else r.instituicao,
            ),
        )
```

4. Registrar as exclusões da auditoria e das conferências (seções 3.8, 3.10 e 3.12), antes de baixar as
   publicações. O comando funciona mesmo com o banco ainda sem os trabalhos:
   ele só os põe na lista de bloqueio. Antes, conferir o `docente_id` de cada
   um pelo nome:

```bash
python coleta/openalex_publicacoes.py --excluir 128 W2738663337 W2884238447 W3217518686 W3217797797 W4409045074 W2987420323 W4226229034 W4412073007 W3186056693
python coleta/openalex_publicacoes.py --excluir 11 W3044958600 W4388788464 W1970291547 W1893430842 W1906494303 W1913829163 W2182619052 W2229881684 W2618774127 W2930651807 W3025994390 W3159762057
python coleta/openalex_publicacoes.py --excluir 82 W4408848503 W4415518634 W7128512482 W2247997289 W3210008959 W4255261400 W2791069502 W4408848459 W7126266505 W4408696228 W4416708158 W4417405377
python coleta/openalex_publicacoes.py --excluir 91 W4287018518 W53300594
python coleta/openalex_publicacoes.py --excluir 27 W3188772115 W774947380
python coleta/openalex_publicacoes.py --excluir 22 W3196489541
python coleta/openalex_publicacoes.py --excluir 106 W4300542563
python coleta/openalex_publicacoes.py --excluir 115 W3010671977
python coleta/openalex_publicacoes.py --excluir 81 W2610545354
python coleta/openalex_publicacoes.py --excluir 53 W7219242552
python coleta/openalex_publicacoes.py --excluir 109 W2795120010 W4306178141
python coleta/openalex_publicacoes.py --excluir 21 W7120482577
python coleta/openalex_publicacoes.py --excluir 3 W4402031261 W4402258293
python coleta/openalex_publicacoes.py --excluir 133 W7135167129
python coleta/openalex_publicacoes.py --excluir 112 W4404139295
python coleta/openalex_publicacoes.py --excluir 63 W2065899962
python coleta/openalex_publicacoes.py --excluir 134 W2587400349 W7215165680
python coleta/openalex_publicacoes.py --excluir 84 W3021502267
python coleta/openalex_publicacoes.py --excluir 41 W7214802054
python coleta/openalex_publicacoes.py --excluir 43 W4290988382 W4402126039
python coleta/openalex_publicacoes.py --excluir 106 W3008540800
python coleta/openalex_publicacoes.py --excluir 6 W2336706901
python coleta/openalex_publicacoes.py --excluir 93 W2621195124
python coleta/openalex_publicacoes.py --excluir 96 W2893298749 W2292545202
python coleta/openalex_publicacoes.py --excluir 66 W4416254858
python coleta/openalex_publicacoes.py --excluir 40 W4367058711
python coleta/openalex_publicacoes.py --excluir 106 W4396496919
```

5. Baixar as publicações e refazer as inclusões manuais da seção 3.6, também
   conferindo o `docente_id` de cada um:

```bash
python coleta/openalex_publicacoes.py
python coleta/openalex_publicacoes.py --incluir 37 W4404755358
python coleta/openalex_publicacoes.py --incluir 45 doi:10.1007/s10884-018-9723-6
python coleta/openalex_publicacoes.py --incluir 94 doi:10.3390/en18205371
python coleta/openalex_publicacoes.py --incluir 24 W3129881038
```

Perfis novos que a busca trouxer e que não estavam no CSV ficarão como
"conferir" e precisarão de revisão.

6. Refazer a validação pelo ORCID (seção 3.9). As rejeições vêm antes do passo
   de recuperação, para que os ORCIDs de homônimos não sejam gravados de novo:

```bash
python coleta/orcid.py --rejeitar 128 0000-0002-5658-6448
python coleta/orcid.py --rejeitar 109 0009-0004-2896-3121
sqlite3 dados/ponte_cetec.db "UPDATE docentes SET orcid='0000-0002-5194-3418' WHERE id=82;"
python coleta/orcid.py --recuperar
python coleta/orcid.py
python coleta/orcid.py --confirmar 16 51 66 73 104 22 121 96 6 110 10 97 130 120
python coleta/orcid.py --aplicar
```

O ORCID de Vinicius Santos da Silva (docente 82) foi obtido do Lattes e deve
ser gravado à mão antes da recuperação, como na terceira linha.

7. Reaplicar a triagem de conteúdo (seção 3.11). O CSV conferido guarda todas
   as decisões, inclusive os títulos corrigidos. A análise preserva o que já
   foi conferido; casos novos aparecem sem marcação e precisam de revisão:

```bash
python coleta/triagem_conteudo.py
python coleta/triagem_conteudo.py --aplicar
```

8. Reaplicar as repetições da triagem por semelhança (seção 3.12). O Ollama só
   é necessário se os vetores de `dados/embeddings/` tiverem se perdido:

```bash
python coleta/triagem_embeddings.py
python coleta/triagem_embeddings.py --aplicar
```

## 6. Arquivos da etapa

| Arquivo | Papel |
|---|---|
| `coleta/openalex_autores.py` | Busca e grava os perfis de cada docente; gera o CSV de revisão |
| `coleta/openalex_diagnostico.py` | Script auxiliar usado para validar a regra de nomes; não altera o banco |
| `coleta/openalex_publicacoes.py` | Baixa as publicações; modos `--refazer`, `--mistos`, `--incluir`, `--excluir`, `--perfis` e `--rejeitar-perfil` |
| `coleta/openalex_auditoria.py` | Aponta trabalhos em área minoritária do docente; não altera o banco |
| `coleta/orcid.py` | Segunda via: recupera, valida e aplica os ORCIDs; modos `--recuperar`, `--aplicar`, `--confirmar` e `--rejeitar` |
| `coleta/conferir_coautores.py` | Etapa 4: autores e afiliações dos trabalhos da conferência manual; não altera o banco |
| `coleta/triagem_conteudo.py` | Etapa 4: aponta repetidos, títulos e resumos sem conteúdo; modo `--aplicar` grava em `publicacoes_ajustes` |
| `dados/openalex_vinculos.csv` | Status final de cada perfil, versionado |
| `dados/conferir_poucas_publicacoes.csv` | Etapa 4: decisões da conferência dos docentes com poucas publicações (seção 3.10) |
| `dados/triagem_conteudo.csv` | Etapa 4: decisões da triagem de conteúdo (seção 3.11) |
| `coleta/triagem_embeddings.py` | Etapa 4: compara as publicações de cada docente por semelhança de conteúdo; não altera o banco |
| `dados/triagem_homonimos.csv` | Etapa 4: decisões da triagem de homônimos (seção 3.12) |
| `dados/triagem_similares.csv` | Etapa 4: pares que podem ser o mesmo trabalho (seção 3.12) |
| `dados/embeddings/` | vetores guardados das publicações, fora do Git, recalculáveis |
| `coleta/gerar_perfis.py` | Etapa 4: piloto dos perfis de competência com o Ollama; não altera o banco |
| `dados/perfis_piloto/` | Etapa 4: resultados do piloto, um JSON e um CSV por variante (seção 3.13) |
| `coleta/scholar.py` | Google Acadêmico: cruzamento com o CETEC e validação pelos títulos; não altera o banco (seção 3.14) |
| `dados/scholar_perfis_ufrb.csv` | 484 perfis do Google Acadêmico com e-mail da UFRB |
| `dados/scholar_vinculos.csv` | Sugestões de vínculo docente–perfil e a decisão de coletar |
| `dados/scholar_metricas.csv` | Citações, índice h e i10 de cada perfil coletado |
| `dados/scholar_publicacoes.csv` | 1.515 publicações dos 45 perfis |
| `dados/scholar_validacao.csv` | Resultado do `validar` e decisões manuais |
| `dados/scholar_publicacoes_novas.csv` | Publicações fora do banco, de perfis confirmados, para conferência |
| `coleta/triagem_scholar.py` | Triagem item a item das publicações novas do Google Acadêmico; só o modo `--aplicar` grava no banco (seção 3.14) |
| `dados/triagem_scholar.csv` | Apontamentos, sugestões e decisões de cada publicação nova |
| `dados/excluidas_titulos.csv` | Títulos, buscados na OpenAlex, dos trabalhos já excluídos como homônimos |
| `coleta/scholar_openalex.py` | Procura na OpenAlex o resumo das publicações do Google Acadêmico; só o modo `--aplicar` grava no banco (seção 3.14) |
| `dados/scholar_openalex.csv` | Situação de cada publicação na busca e a decisão (usar ou nao_usar) |
| `dados/scholar_openalex_cache.json` | Respostas da OpenAlex guardadas, para retomar a busca sem repetir chamadas |
| `dados/ponte_cetec_antes_scholar.db` | Cópia do banco antes da gravação das publicações do Google Acadêmico, fora do Git |
| `dados/ponte_cetec.db` | Banco local, fora do Git |