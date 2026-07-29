# -*- coding: utf-8 -*-
"""
scanner_documentacao.py

Varre a árvore de pastas:

    K:\\5. BRACELL\\1. RH\\1. Documentos\\2. Promotores\\COLIGADAS + FILIAIS
        └── UF
            └── Coligada
                └── Nome do Colaborador
                    └── arquivos...

Classifica os documentos encontrados em cada pasta de colaborador em
OBRIGATÓRIOS e COMPLEMENTARES (definidos em config_documentos.py), cruza
com o status do colaborador (Ativo/Inativo/Afastado) da planilha
GERENCIAL.xlsx, e grava a base consolidada em /dados para o dashboard
Streamlit ler.

Feito para rodar de forma agendada (Windows Task Scheduler) — ver
AGENDAMENTO.md para o passo a passo.

Uso manual (varredura completa):
    python scanner_documentacao.py

Uso incremental (só reprocessa pastas de promotor modificadas a partir de
uma data — reaproveita o restante do último resultado salvo):
    python scanner_documentacao.py --desde 2026-07-01

Sem --desde nem --completo, o script já roda no modo incremental
automático: usa a data/hora da última execução (dados/ultima_atualizacao.txt)
como corte. Para forçar uma varredura completa (ex.: depois de alterar
config_documentos.py, já que padrões novos precisam reclassificar arquivos
antigos):
    python scanner_documentacao.py --completo

Depois de gravar a base, o script faz "git add/commit/push" da pasta
dados/ automaticamente (repositório configurado em CAMINHO_REPO_GIT),
para o Streamlit Community Cloud detectar a mudança e atualizar o
painel sozinho. Para pular esse passo (ex.: testes locais):
    python scanner_documentacao.py --sem-publicar
"""

import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from datetime import datetime

import pandas as pd

from config_documentos import (
    PADROES_OBRIGATORIOS,
    PADROES_COMPLEMENTARES,
    EXTENSOES_VALIDAS,
    VIGENCIA_OBRIGATORIOS,
)

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES — ajuste conforme o ambiente real
# ---------------------------------------------------------------------------
PASTA_RAIZ = r"K:\5. BRACELL\1. RH\1. Documentos\2. Promotores\COLIGADAS + FILIAIS"
GERENCIAL_PATH = r"K:\5. BRACELL\1. RH\2. Gerencial\GERENCIAL.xlsx"

# A base de colaboradores está espalhada em 3 abas do mesmo arquivo:
#   - GERENCIAL   -> colaboradores ATIVOS   (cabeçalho na linha 3 -> header=2)
#   - RESCISÃO    -> colaboradores INATIVOS (cabeçalho na linha 1 -> header=0)
#   - AFASTAMENTOS-> colaboradores AFASTADOS(cabeçalho na linha 1 -> header=0)
ABAS_GERENCIAL = [
    # (nome_da_aba, linha_do_cabecalho_0indexed, status_fixo, coluna_do_nome, coluna_da_equipe_ou_None)
    ("GERENCIAL", 2, "Ativo", "NOME", "SUPERVISOR"),
    ("RESCISÃO", 0, "Inativo", "NOME", None),
    ("AFASTAMENTOS", 0, "Afastado", "NOME", None),
]

# Se um colaborador aparecer em mais de uma aba (ex: base desatualizada),
# prioriza o status "mais vivo" nesta ordem:
PRIORIDADE_STATUS = {"Ativo": 0, "Afastado": 1, "Inativo": 2}

PASTA_SAIDA = Path(__file__).parent / "dados"
PASTA_SAIDA.mkdir(exist_ok=True)
ARQUIVO_BASE = PASTA_SAIDA / "dados_documentacao.parquet"
ATUALIZACAO_PATH = PASTA_SAIDA / "ultima_atualizacao.txt"

# Profundidade (nº de níveis abaixo da pasta do promotor) verificada pela
# checagem incremental de "mudou desde X". 2 cobre: arquivo direto na pasta
# do promotor + arquivo dentro de 1 subpasta. Se sua estrutura tiver
# subpastas aninhadas mais profundas, rode --completo periodicamente para
# não deixar alterações antigas escaparem da incremental.
PROFUNDIDADE_CHECAGEM_INCREMENTAL = 2

# Pasta onde está o clone LOCAL do repositório GitHub (o mesmo que o
# Streamlit Community Cloud lê). Se este script já roda dentro do próprio
# clone, deixe como está — senão, aponte para o caminho do clone.
CAMINHO_REPO_GIT = Path(__file__).parent


def normalizar(texto: str) -> str:
    """Remove acentos, caixa e troca separadores (_, -, .) por espaço —
    para que \\b (borda de palavra) funcione corretamente na comparação
    e nomes de arquivo como 'epi_pedro.pdf' ou 'cnh-pedro.jpg' sejam
    reconhecidos."""
    if not isinstance(texto, str):
        return ""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[_\-.]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip().lower()
    return texto


def classificar_arquivo(nome_arquivo: str):
    """Retorna lista de tuplas (categoria, tipo_documento) que o nome do
    arquivo corresponde, segundo os padrões configurados."""
    nome_norm = normalizar(nome_arquivo)
    encontrados = []
    for doc_tipo, padroes in PADROES_OBRIGATORIOS.items():
        if any(p.search(nome_norm) for p in padroes):
            encontrados.append(("obrigatorio", doc_tipo))
    for doc_tipo, padroes in PADROES_COMPLEMENTARES.items():
        if any(p.search(nome_norm) for p in padroes):
            encontrados.append(("complementar", doc_tipo))
    return encontrados


def _mtime(caminho: Path) -> float:
    """mtime em epoch; se não conseguir checar (permissão, link quebrado
    em rede), considera 'alterado' por segurança em vez de assumir que não mudou."""
    try:
        return caminho.stat().st_mtime
    except OSError:
        return float("inf")


def pasta_alterada_desde(pasta_promotor: Path, data_corte_ts: float,
                          profundidade: int = PROFUNDIDADE_CHECAGEM_INCREMENTAL) -> bool:
    """Heurística rápida para saber se algo mudou dentro da pasta do
    promotor desde `data_corte_ts` (epoch), SEM fazer um rglob recursivo
    completo — só olha o mtime da própria pasta e, até `profundidade`
    níveis abaixo, o mtime de cada entrada (arquivo ou subpasta).

    No Windows/NTFS, adicionar, remover ou sobrescrever um arquivo
    atualiza o mtime do próprio arquivo; adicionar/remover uma entrada
    também atualiza o mtime da pasta que a contém diretamente — por isso
    checar 2 níveis (pasta do promotor + 1 subpasta) já cobre a estrutura
    comum (promotor > [subpasta opcional] > arquivos).
    """
    if _mtime(pasta_promotor) >= data_corte_ts:
        return True
    if profundidade <= 0:
        return False
    try:
        entradas = list(pasta_promotor.iterdir())
    except OSError:
        return True
    for entrada in entradas:
        if _mtime(entrada) >= data_corte_ts:
            return True
        if entrada.is_dir() and pasta_alterada_desde(entrada, data_corte_ts, profundidade - 1):
            return True
    return False


def varrer_pastas(pasta_raiz: str, data_corte_ts: float = None, caminhos_anteriores: set = None):
    """Percorre UF > Coligada > Nome e monta um registro por colaborador,
    além de uma lista de arquivos não classificados (para ajuste do regex).

    Se `data_corte_ts` for informado, pastas de promotor que já existiam
    na varredura anterior (`caminhos_anteriores`) e que não tiveram
    nenhuma alteração detectada (via `pasta_alterada_desde`) são puladas
    — não entram em `registros` e devem ser reaproveitadas do resultado
    salvo anteriormente. Retorna também a lista de caminhos pulados
    (`caminhos_reaproveitados`) para quem chamar fazer esse reaproveitamento.
    """
    pasta_raiz = Path(pasta_raiz)
    if not pasta_raiz.exists():
        raise FileNotFoundError(f"Pasta raiz não encontrada: {pasta_raiz}")

    caminhos_anteriores = caminhos_anteriores or set()
    registros = []
    nao_classificados = []
    caminhos_reaproveitados = []

    ufs = sorted(p for p in pasta_raiz.iterdir() if p.is_dir())
    for uf_dir in ufs:
        uf = uf_dir.name
        for coligada_dir in sorted(p for p in uf_dir.iterdir() if p.is_dir()):
            coligada = coligada_dir.name
            for pessoa_dir in sorted(p for p in coligada_dir.iterdir() if p.is_dir()):
                nome_colaborador = pessoa_dir.name
                caminho_str = str(pessoa_dir)

                if (data_corte_ts is not None
                        and caminho_str in caminhos_anteriores
                        and not pasta_alterada_desde(pessoa_dir, data_corte_ts)):
                    caminhos_reaproveitados.append(caminho_str)
                    continue

                docs_encontrados = set()
                for arquivo in pessoa_dir.rglob("*"):
                    if not arquivo.is_file():
                        continue
                    if arquivo.suffix.lower() not in EXTENSOES_VALIDAS:
                        continue

                    matches = classificar_arquivo(arquivo.name)
                    if matches:
                        docs_encontrados.update(matches)
                    else:
                        nao_classificados.append({
                            "UF": uf, "Coligada": coligada, "Nome": nome_colaborador,
                            "Arquivo": arquivo.name, "Caminho": str(arquivo),
                        })

                registros.append({
                    "UF": uf,
                    "Coligada": coligada,
                    "Nome": nome_colaborador,
                    "Nome_Normalizado": normalizar(nome_colaborador),
                    "Documentos_Encontrados": docs_encontrados,
                    "Caminho": caminho_str,
                })

    return pd.DataFrame(registros), pd.DataFrame(nao_classificados), caminhos_reaproveitados





def documentos_obrigatorios_vigentes(data_referencia=None) -> set:
    """Retorna o conjunto de documentos obrigatórios que já estão 'em
    cobrança' na data de referência (hoje, por padrão), considerando a
    vigência configurada em VIGENCIA_OBRIGATORIOS. Documentos com vigência
    futura continuam existindo na matriz (coluna OBR__), mas não contam
    como pendência enquanto a data não chegar."""
    data_referencia = data_referencia or datetime.now().date()
    vigentes = set()
    for doc, vigencia in VIGENCIA_OBRIGATORIOS.items():
        if vigencia is None or data_referencia >= vigencia:
            vigentes.add(doc)
    return vigentes


def montar_matriz_pendencias(df_pastas: pd.DataFrame, data_referencia=None) -> pd.DataFrame:
    """Expande os documentos encontrados em colunas booleanas (uma por tipo)
    e calcula as pendências de cada colaborador, respeitando a vigência de
    cada documento obrigatório."""
    todos_obrigatorios = list(PADROES_OBRIGATORIOS.keys())
    todos_complementares = list(PADROES_COMPLEMENTARES.keys())
    obrigatorios_vigentes = documentos_obrigatorios_vigentes(data_referencia)

    linhas = []
    for _, row in df_pastas.iterrows():
        encontrados = {doc for _, doc in row["Documentos_Encontrados"]}
        linha = {
            "UF": row["UF"],
            "Coligada": row["Coligada"],
            "Nome": row["Nome"],
            "Nome_Normalizado": row["Nome_Normalizado"],
            "Caminho": row["Caminho"],
        }

        pendentes_obrig = []
        for doc in todos_obrigatorios:
            presente = doc in encontrados
            linha[f"OBR__{doc}"] = presente
            # só conta como pendência se o documento já estiver "em cobrança"
            if not presente and doc in obrigatorios_vigentes:
                pendentes_obrig.append(doc)

        pendentes_compl = []
        for doc in todos_complementares:
            presente = doc in encontrados
            linha[f"COMP__{doc}"] = presente
            if not presente:
                pendentes_compl.append(doc)

        linha["Qtd_Pendencias_Obrigatorias"] = len(pendentes_obrig)
        linha["Qtd_Pendencias_Complementares"] = len(pendentes_compl)
        linha["Qtd_Pendencias_Total"] = len(pendentes_obrig) + len(pendentes_compl)
        linha["Tem_Pendencia_Qualquer"] = linha["Qtd_Pendencias_Total"] > 0
        linha["Pendencias_Obrigatorias"] = ", ".join(pendentes_obrig)
        linha["Pendencias_Complementares"] = ", ".join(pendentes_compl)
        linha["Status_Documental"] = "Completo" if not pendentes_obrig else "Pendente"
        linhas.append(linha)

    return pd.DataFrame(linhas)


def carregar_aba_colaboradores(caminho: str, aba: str, header: int, status_fixo: str,
                                col_nome: str, col_equipe: str = None) -> pd.DataFrame:
    """Lê uma aba do GERENCIAL.xlsx e devolve Nome/Nome_Normalizado/Status/Equipe,
    já com o status fixo daquela aba (Ativo/Inativo/Afastado). `col_equipe` é
    opcional — se a aba não tiver a coluna de equipe (ex: RESCISÃO/AFASTAMENTOS),
    passe None e a equipe fica como "Não informado" para esses colaboradores."""
    df = pd.read_excel(caminho, sheet_name=aba, header=header)
    df.columns = [str(c).strip().upper() for c in df.columns]
    col_nome_upper = col_nome.strip().upper()

    if col_nome_upper not in df.columns:
        raise KeyError(
            f"Coluna '{col_nome}' não encontrada na aba '{aba}' de {caminho}. "
            f"Colunas disponíveis: {list(df.columns)}. Ajuste ABAS_GERENCIAL "
            f"no topo do scanner_documentacao.py."
        )

    colunas_manter = [col_nome_upper]
    col_equipe_upper = col_equipe.strip().upper() if col_equipe else None
    if col_equipe_upper and col_equipe_upper in df.columns:
        colunas_manter.append(col_equipe_upper)
    elif col_equipe_upper:
        print(f"    ⚠ coluna de equipe '{col_equipe}' não encontrada na aba '{aba}' — "
              f"equipe ficará como 'Não informado' para esses colaboradores.")
        col_equipe_upper = None

    df = df[colunas_manter].copy()
    renomeio = {col_nome_upper: "Nome_Original"}
    if col_equipe_upper:
        renomeio[col_equipe_upper] = "Equipe"
    df = df.rename(columns=renomeio)
    if "Equipe" not in df.columns:
        df["Equipe"] = "Não informado"
    df["Equipe"] = df["Equipe"].fillna("Não informado").replace("", "Não informado")

    df["Status_Colaborador"] = status_fixo
    df["Nome_Normalizado"] = df["Nome_Original"].apply(normalizar)
    df = df[df["Nome_Normalizado"] != ""].reset_index(drop=True)
    return df


def carregar_gerencial(caminho: str) -> pd.DataFrame:
    """Lê as 3 abas configuradas em ABAS_GERENCIAL (Ativos/Inativos/Afastados)
    e consolida numa única base de colaboradores."""
    partes = []
    for aba, header, status_fixo, col_nome, col_equipe in ABAS_GERENCIAL:
        df_aba = carregar_aba_colaboradores(caminho, aba, header, status_fixo, col_nome, col_equipe)
        print(f"    aba '{aba}': {len(df_aba)} colaboradores ({status_fixo})")
        partes.append(df_aba)

    df_todos = pd.concat(partes, ignore_index=True)

    # se o mesmo nome aparecer em mais de uma aba, mantém o status "mais vivo"
    df_todos["_prioridade"] = df_todos["Status_Colaborador"].map(PRIORIDADE_STATUS)
    df_todos = (
        df_todos.sort_values("_prioridade")
        .drop_duplicates(subset="Nome_Normalizado", keep="first")
        .drop(columns=["_prioridade"])
        .reset_index(drop=True)
    )
    return df_todos


def cruzar_com_gerencial(df_matriz: pd.DataFrame, df_gerencial: pd.DataFrame) -> pd.DataFrame:
    df_g = df_gerencial[["Nome_Normalizado", "Status_Colaborador", "Equipe"]].drop_duplicates(subset="Nome_Normalizado")
    df_final = df_matriz.merge(df_g, on="Nome_Normalizado", how="left")
    df_final["Status_Colaborador"] = df_final["Status_Colaborador"].fillna("Não localizado no Gerencial")
    df_final["Equipe"] = df_final["Equipe"].fillna("Não informado")
    return df_final


def parse_args():
    parser = argparse.ArgumentParser(
        description="Varredura de documentação dos promotores (BKO / Bracell)."
    )
    parser.add_argument(
        "--desde", type=str, default=None, metavar="AAAA-MM-DD",
        help="Reprocessa só pastas de promotor modificadas a partir dessa data; "
             "as demais são reaproveitadas do último resultado salvo.",
    )
    parser.add_argument(
        "--completo", action="store_true",
        help="Força varredura completa, ignorando o modo incremental (padrão "
             "após alterar config_documentos.py, já que padrões novos precisam "
             "reclassificar arquivos que não mudaram).",
    )
    parser.add_argument(
        "--sem-publicar", action="store_true",
        help="Não faz o git add/commit/push da pasta dados/ ao final (útil "
             "para testes locais, sem afetar o painel publicado).",
    )
    return parser.parse_args()


def publicar_no_github(mensagem: str = None):
    """git add/commit/push da pasta dados/ no repositório local configurado
    em CAMINHO_REPO_GIT — o push dispara o redeploy automático no Streamlit
    Community Cloud. Retorna (sucesso: bool, log: str).

    Pré-requisitos (configurar uma vez só na máquina que roda o scanner):
      1. git instalado e no PATH.
      2. CAMINHO_REPO_GIT já é um clone do repositório (git clone ...).
      3. Credenciais salvas (Git Credential Manager no Windows já resolve
         isso após o primeiro `git push` manual com um Personal Access
         Token do GitHub) — sem isso o push aqui vai falhar pedindo login.
    """
    mensagem = mensagem or f"Atualização automática — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    comandos = [
        ["git", "-C", str(CAMINHO_REPO_GIT), "add", "dados"],
        ["git", "-C", str(CAMINHO_REPO_GIT), "commit", "-m", mensagem],
        ["git", "-C", str(CAMINHO_REPO_GIT), "push"],
    ]
    log = ""
    for cmd in comandos:
        resultado = subprocess.run(cmd, capture_output=True, text=True)
        log += f"$ {' '.join(cmd)}\n{resultado.stdout}{resultado.stderr}\n"
        if resultado.returncode != 0:
            saida = (resultado.stdout + resultado.stderr).lower()
            # "nada a submeter" (commit vazio) não é uma falha real — só
            # significa que a base não mudou desde o último push
            if "nothing to commit" in saida or "nada adicionado" in saida:
                continue
            return False, log
    return True, log


def main():
    inicio = datetime.now()
    args = parse_args()

    df_anterior = pd.read_parquet(ARQUIVO_BASE) if ARQUIVO_BASE.exists() else None

    data_corte_ts = None
    modo = "completa"
    if not args.completo and df_anterior is not None:
        if args.desde:
            data_corte_ts = datetime.strptime(args.desde, "%Y-%m-%d").timestamp()
            modo = f"incremental (--desde {args.desde})"
        elif ATUALIZACAO_PATH.exists():
            data_corte_ts = datetime.fromisoformat(ATUALIZACAO_PATH.read_text().strip()).timestamp()
            modo = "incremental (automático, desde a última execução)"

    print(f"[{inicio}] Iniciando varredura {modo} em: {PASTA_RAIZ}")

    caminhos_anteriores = set(df_anterior["Caminho"]) if df_anterior is not None else set()
    df_pastas, df_nao_classificados, caminhos_reaproveitados = varrer_pastas(
        PASTA_RAIZ, data_corte_ts=data_corte_ts, caminhos_anteriores=caminhos_anteriores
    )
    print(f"  {len(df_pastas)} pastas de colaboradores reprocessadas; "
          f"{len(caminhos_reaproveitados)} reaproveitadas sem alteração.")
    if not df_nao_classificados.empty:
        print(f"  ⚠ {len(df_nao_classificados)} arquivos não foram classificados "
              f"(veja dados/arquivos_nao_classificados.xlsx e ajuste config_documentos.py).")

    df_matriz_novas = montar_matriz_pendencias(df_pastas)

    # colunas que compõem a matriz (OBR__/COMP__/pendências) — reaproveitadas
    # tal como estavam; Status_Colaborador/Equipe serão recalculados por
    # inteiro logo abaixo, pois o GERENCIAL.xlsx pode ter mudado mesmo sem
    # a pasta do promotor ter mudado.
    if caminhos_reaproveitados:
        colunas_matriz = [c for c in df_matriz_novas.columns]
        df_matriz_antigas = df_anterior[df_anterior["Caminho"].isin(caminhos_reaproveitados)][
            [c for c in colunas_matriz if c in df_anterior.columns]
        ]
        df_matriz = pd.concat([df_matriz_novas, df_matriz_antigas], ignore_index=True)
    else:
        df_matriz = df_matriz_novas

    print(f"[{datetime.now()}] Carregando GERENCIAL.xlsx (abas: GERENCIAL/RESCISÃO/AFASTAMENTOS)")
    df_gerencial = carregar_gerencial(GERENCIAL_PATH)
    df_final = cruzar_com_gerencial(df_matriz, df_gerencial)

    # --- grava saídas ---
    df_final.to_parquet(ARQUIVO_BASE, index=False)
    df_final.to_excel(PASTA_SAIDA / "dados_documentacao.xlsx", index=False)
    if not df_nao_classificados.empty:
        df_nao_classificados.to_excel(PASTA_SAIDA / "arquivos_nao_classificados.xlsx", index=False)

    with open(ATUALIZACAO_PATH, "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat())

    fim = datetime.now()
    print(f"[{fim}] Concluído em {(fim - inicio).total_seconds():.1f}s. "
          f"{len(df_final)} colaboradores no total ({len(df_pastas)} reprocessados + "
          f"{len(caminhos_reaproveitados)} reaproveitados).")
    print(f"  Base salva em: {ARQUIVO_BASE}")

    if not args.sem_publicar:
        print(f"[{datetime.now()}] Publicando dados/ no GitHub...")
        ok_push, log_push = publicar_no_github()
        if ok_push:
            print("  ✔ Publicado — o Streamlit Community Cloud deve atualizar em instantes.")
        else:
            print("  ⚠ Falha ao publicar no GitHub. Log:", file=sys.stderr)
            print(log_push, file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)