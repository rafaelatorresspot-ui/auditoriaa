# Controle de Documentação — BKO / Bracell

Sistema para acompanhar a documentação dos promotores nas pastas
`K:\5. BRACELL\1. RH\1. Documentos\2. Promotores\COLIGADAS + FILIAIS`
(estrutura UF > Coligada > Nome), com visão dinâmica de pendências e
cruzamento com o status (Ativo/Inativo/Afastado) do `GERENCIAL.xlsx`.

## Arquivos

| Arquivo | Função |
|---|---|
| `config_documentos.py` | Lista de documentos obrigatórios/complementares e os padrões (regex) usados para reconhecê-los pelo nome do arquivo |
| `scanner_documentacao.py` | Varre as pastas, classifica os documentos, cruza com o Gerencial e grava a base em `dados/` |
| `dashboard_documentacao.py` | Painel Streamlit que lê a base e mostra a visão dinâmica |
| `AGENDAMENTO.md` | Passo a passo para agendar a varredura automática e publicar o painel via link |
| `requirements.txt` | Dependências Python |

## Documentos controlados

**Obrigatórios**: Termo de EPI · Termo de Telefonia · Contrato · Termo de Uso de Motocicleta

**Complementares**: RG ou CNH · Comprovante de Residência · Comprovante de Escolaridade · Título de Eleitor · CTPS · Exame Admissional

Um colaborador só é considerado **"Completo"** se tiver todos os
obrigatórios vigentes. Os complementares aparecem separadamente como
pendência, mas não bloqueiam o status geral — se quiser que também
bloqueiem, é só avisar que ajusto a regra em `montar_matriz_pendencias`.

### Vigência dos documentos obrigatórios

Cada documento obrigatório pode ter uma data de início de cobrança em
`VIGENCIA_OBRIGATORIOS` (`config_documentos.py`). Exemplo já configurado:
o **Termo de Uso de Motocicleta** só passa a contar como pendência a
partir de **01/06/2026** — antes disso ele existe na base (coluna
`OBR__Termo de Uso de Motocicleta`), mas não pesa no status "Completo/
Pendente". A partir da data, ele passa a ser cobrado de **todo mundo**,
inclusive colaboradores ativos antigos (não é retroativo por data de
admissão). Para adicionar vigência a outro documento, é só preencher a
data correspondente no dicionário.

## Base de colaboradores (Ativo / Inativo / Afastado) e Equipe

O `GERENCIAL.xlsx` é lido em 3 abas diferentes, configuradas em
`ABAS_GERENCIAL` no topo do `scanner_documentacao.py`:

| Aba | Cabeçalho | Status atribuído | Coluna do nome | Coluna da equipe |
|---|---|---|---|---|
| `GERENCIAL` | linha 3 | Ativo | `SUPERVISOR/PROMOTOR` | `SUPERVISOR/COORDENADOR` |
| `RESCISÃO` | linha 1 | Inativo | `NOME` | — (fica "Não informado") |
| `AFASTAMENTOS` | linha 1 | Afastado | `NOME` | — (fica "Não informado") |

Se um nome aparecer em mais de uma aba (base desatualizada, por exemplo),
prevalece o status "mais vivo": Ativo > Afastado > Inativo. Se alguma
coluna não bater com o nome real na planilha, o script avisa quais
colunas existem de fato — é só ajustar a tupla correspondente em
`ABAS_GERENCIAL`.

## Painel — recursos

- **Filtros**: UF, Coligada, Equipe, Status do colaborador, busca por nome
- **KPIs**: total no filtro, completos, com pendência, % completo
- **Gráficos**: colaboradores por status (Ativo/Inativo/Afastado), pendências
  obrigatórias por UF, documentos obrigatórios e complementares faltantes
- **Análise por Equipe x UF**: mapa de calor com o % de promotores com
  pendência, com opção de calcular considerando só obrigatórios, só
  complementares, ou todos os documentos — mais uma tabela com quantidade
  e percentual por combinação Equipe x UF
- **Tabela de pendências** filtrável e exportável em CSV
- **Botão "Atualizar dados agora"** na barra lateral: roda o
  `scanner_documentacao.py` na hora (mesma varredura do agendamento) e
  recarrega o painel com os dados novos — útil para forçar uma atualização
  fora do horário agendado, sem precisar abrir o terminal

## Como rodar pela primeira vez

```bash
pip install -r requirements.txt

# 1. Rodar a varredura (gera a base em dados/)
python scanner_documentacao.py

# 2. Abrir o painel
streamlit run dashboard_documentacao.py
```

## Ajuste fino necessário (importante)

Como os nomes de arquivo na pasta real variam, o regex em
`config_documentos.py` é um ponto de partida. Depois da primeira
execução:

1. Abra `dados/arquivos_nao_classificados.xlsx` — lista todo arquivo que
   não bateu com nenhum padrão.
2. Para cada nome recorrente que deveria ter sido reconhecido, adicione
   uma nova variação de regex na lista do documento correspondente em
   `config_documentos.py`.
3. Rode a varredura de novo. Repita até a cobertura ficar boa (não
   precisa ficar 100% perfeita, só reduzir os falsos-negativos mais
   comuns).

Também confira em `scanner_documentacao.py` se `COL_NOME` e `COL_STATUS`
batem com os nomes reais das colunas no `GERENCIAL.xlsx` — o script avisa
no erro quais colunas encontrou, caso não bata.

## Publicar via link para o time

Veja `AGENDAMENTO.md` para o passo a passo de:
- Agendar a varredura automática (Windows Task Scheduler)
- Publicar o Streamlit em servidor interno ou Streamlit Cloud, com link
  compartilhável para o time de BKO