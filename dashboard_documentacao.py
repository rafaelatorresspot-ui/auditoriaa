# -*- coding: utf-8 -*-
"""
dashboard_documentacao.py

Painel Streamlit — Controle de Documentação BKO / Bracell.
Lê a base gerada por scanner_documentacao.py (dados/dados_documentacao.parquet)
e exibe visão dinâmica de pendências, filtros por UF/Coligada/Equipe/Status,
análise de Ativos x Inativos x Afastados, ranking de documentos pendentes,
pendências por Coligada, mapas de calor de pendências por Equipe x Documento e
um detalhamento em hierarquia (Equipe → UF → Documento → Pessoas).

Rodar com:
    streamlit run dashboard_documentacao.py --server.port 8501

Para expor via link, publique este comando em servidor interno/cloud
(Streamlit Community Cloud, servidor Windows com IIS reverse proxy, etc.)
"""

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from config_documentos import VIGENCIA_OBRIGATORIOS

st.set_page_config(
    page_title="Controle de Documentação — BKO",
    layout="wide",
    page_icon="📋",
    initial_sidebar_state="expanded",
)

PASTA_PROJETO = Path(__file__).parent
DADOS_PATH = PASTA_PROJETO / "dados" / "dados_documentacao.parquet"
ATUALIZACAO_PATH = PASTA_PROJETO / "dados" / "ultima_atualizacao.txt"
SCANNER_SCRIPT = PASTA_PROJETO / "scanner_documentacao.py"

# ---------------------------------------------------------------------------
# IDENTIDADE VISUAL — paleta única usada em todos os gráficos do painel
# ---------------------------------------------------------------------------
COR_PRIMARIA = "#4F63E0"          # azul/índigo da marca — destaque principal
COR_OBRIGATORIO = "#4F63E0"       # documentos obrigatórios (prioridade)
COR_COMPLEMENTAR = "#94A3B8"      # documentos complementares (secundário, dessaturado)

# paleta de status — harmônica, distinguível e sempre acompanhada de rótulo
CORES_STATUS = {
    "Ativo": "#12B76A",                       # verde — positivo
    "Afastado": "#6172F3",                    # índigo — próximo da marca
    "Inativo": "#CBD5E1",                     # cinza neutro — desênfase
    "Não localizado no Gerencial": "#F79009", # âmbar — atenção
}

# rampa sequencial de severidade (verde → vermelho) — nº de documentos pendentes
CORES_FAIXAS = {
    "Nenhuma pendência": "#12B76A",
    "1 documento pendente": "#84CC16",
    "2 documentos pendentes": "#EAB308",
    "3 documentos pendentes": "#F79009",
    "4 documentos pendentes": "#F04438",
    "5 ou mais documentos pendentes": "#B42318",
}
ORDEM_FAIXAS = list(CORES_FAIXAS.keys())

# escala sequencial de uma cor só (claro → escuro) derivada da cor da marca
ESCALA_MARCA = [
    [0.00, "#F4F6FE"],
    [0.25, "#D7DDFA"],
    [0.50, "#A8B4F2"],
    [0.75, "#7182EA"],
    [1.00, "#3A4CC0"],
]

# tokens de tinta (texto/eixos) — nunca a cor da série
INK_PRIMARIO = "#101828"
INK_SECUNDARIO = "#475467"
INK_GRID = "#EAECF0"
FONTE_GRAFICOS = dict(family="Segoe UI, Arial, sans-serif", size=13, color=INK_SECUNDARIO)

# dimensionamento consistente das barras horizontais (mesma espessura em todos os gráficos)
ALTURA_POR_BARRA = 46   # px reservados por categoria
BARGAP_BARRAS = 0.34


def altura_barras(n, base=80):
    """Altura da figura para que a espessura de cada barra seja constante entre gráficos."""
    return int(base + ALTURA_POR_BARRA * max(int(n), 1))

# chaves dos widgets de filtro (usadas pelo botão "Limpar filtros")
FILTER_KEYS = [
    "f_uf", "f_coligada", "f_equipe", "f_status",
    "f_ativos", "f_pend_obr", "f_min_pend", "f_busca",
]


# ---------------------------------------------------------------------------
# ESTILO / TEMA
# ---------------------------------------------------------------------------
def injetar_estilo():
    """CSS leve para dar um acabamento mais profissional ao painel."""
    st.markdown(
        """
        <style>
          /* usa a largura total da tela (layout wide sem limite estreito) */
          .block-container {padding: 1.6rem 3rem 2.5rem 3rem; max-width: 100%;}
          h1, h2, h3 {font-family: "Segoe UI", Arial, sans-serif; letter-spacing: -0.01em;}

          /* cartões de KPI: mesma altura e mesmo tamanho de número */
          [data-testid="stHorizontalBlock"] {align-items: stretch;}
          [data-testid="stMetric"] {
              background: #FFFFFF; border: 1px solid #E6E9F0; border-radius: 14px;
              padding: 16px 20px; box-shadow: 0 1px 2px rgba(16,24,40,0.04);
              height: 100%; display: flex; flex-direction: column; justify-content: center;
          }
          [data-testid="stMetricLabel"] p {font-weight: 600; color: #475467; line-height: 1.2;}
          [data-testid="stMetricValue"] {
              font-size: 1.85rem !important; font-weight: 700; color: #101828; line-height: 1.15;
          }
          [data-testid="stMetricDelta"] {font-size: 0.8rem;}

          section[data-testid="stSidebar"] {border-right: 1px solid #E6E9F0;}
          div[data-testid="stTabs"] button[data-baseweb="tab"] {font-weight: 600;}
          hr {margin: 1.1rem 0;}
          .chip {
              display: inline-block; padding: 2px 10px; margin: 2px 4px 2px 0;
              background: #EEF2FF; color: #3538CD; border-radius: 999px;
              font-size: 0.78rem; font-weight: 600;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def aplicar_tema(fig, remover_eixo_x=False, remover_eixo_y=False, legenda_topo_centro=False):
    """Aplica o estilo visual padrão do painel a uma figura Plotly."""
    fig.update_layout(
        template="plotly_white",
        font=FONTE_GRAFICOS,
        margin=dict(t=40, b=30, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=None,  # sem título no Plotly (usamos st.subheader) — evita render "undefined"
        hoverlabel=dict(font_size=13, font_family="Segoe UI, Arial, sans-serif"),
        legend=dict(title_text=""),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=INK_GRID)
    fig.update_yaxes(gridcolor=INK_GRID, zeroline=False, linecolor=INK_GRID)
    if remover_eixo_x:
        fig.update_xaxes(title=None, showticklabels=True)
    if remover_eixo_y:
        fig.update_yaxes(title=None, showgrid=False)
    if legenda_topo_centro:
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5, title_text="")
        )
    return fig


# ---------------------------------------------------------------------------
# DADOS
# ---------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def carregar_dados():
    if not DADOS_PATH.exists():
        return None
    return pd.read_parquet(DADOS_PATH)


def rodar_atualizacao():
    """Executa o scanner_documentacao.py como subprocesso e retorna (ok, log)."""
    resultado = subprocess.run(
        [sys.executable, str(SCANNER_SCRIPT)],
        cwd=str(PASTA_PROJETO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log = (resultado.stdout or "") + "\n" + (resultado.stderr or "")
    return resultado.returncode == 0, log


def colunas_documento(df, base_calculo):
    """Retorna as colunas OBR__/COMP__ relevantes conforme a base de cálculo escolhida."""
    if base_calculo == "Somente obrigatórios":
        return [c for c in df.columns if c.startswith("OBR__")]
    if base_calculo == "Somente complementares":
        return [c for c in df.columns if c.startswith("COMP__")]
    return [c for c in df.columns if c.startswith("OBR__") or c.startswith("COMP__")]


def nome_documento(coluna):
    return coluna.split("__", 1)[1] if "__" in coluna else coluna


def tipo_documento(coluna):
    return "Obrigatório" if coluna.startswith("OBR__") else "Complementar"


def ranking_documentos(df_scope, cols_doc):
    """% e quantidade de colaboradores SEM cada documento (visão geral, vetorizado)."""
    n = len(df_scope)
    falta = ~df_scope[cols_doc]
    dados = pd.DataFrame({
        "Documento": [nome_documento(c) for c in cols_doc],
        "Tipo": [tipo_documento(c) for c in cols_doc],
        "Qtd_Sem": falta.sum().to_numpy(),
    })
    dados["Pct_Sem"] = (dados["Qtd_Sem"] / n * 100).round(1) if n else 0.0
    return dados.sort_values("Qtd_Sem", ascending=False)


def matriz_equipe_documento(df_eq, cols_doc):
    """Matrizes (Equipe x Documento) de % e quantidade sem o documento — vetorizado."""
    falta = (~df_eq[cols_doc]).rename(columns={c: nome_documento(c) for c in cols_doc})
    grp = falta.groupby(df_eq["Equipe"])
    ordem_cols = [nome_documento(c) for c in cols_doc]
    pct = (grp.mean() * 100).round(1)[ordem_cols].sort_index()
    qtd = grp.sum().astype(int)[ordem_cols].sort_index()
    return pct, qtd


# ---------------------------------------------------------------------------
# APP
# ---------------------------------------------------------------------------
def main():
    injetar_estilo()

    df = carregar_dados()

    # -------------------------------------------------------------
    # Sidebar — atualização
    # -------------------------------------------------------------
    with st.sidebar:
        st.header("⚙️ Painel")
        if st.button("🔄 Atualizar dados agora", use_container_width=True):
            with st.spinner("Rodando varredura das pastas e cruzamento com o Gerencial... "
                             "isso pode levar alguns minutos."):
                ok, log = rodar_atualizacao()
            if ok:
                st.success("Base atualizada com sucesso!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Falha ao atualizar a base. Veja o log abaixo.")
                with st.expander("Log da execução"):
                    st.code(log)
        st.divider()

    # -------------------------------------------------------------
    # Cabeçalho
    # -------------------------------------------------------------
    ultima_txt = None
    if ATUALIZACAO_PATH.exists():
        try:
            ultima = datetime.fromisoformat(ATUALIZACAO_PATH.read_text().strip())
            ultima_txt = ultima.strftime("%d/%m/%Y às %H:%M")
        except ValueError:
            ultima_txt = None

    col_tit, col_data = st.columns([0.68, 0.32])
    with col_tit:
        st.title("📋 Controle de Documentação")
        st.caption("Auditoria de documentação obrigatória e complementar — Promotores BKO / Bracell")
    with col_data:
        if ultima_txt:
            st.markdown(
                f"<div style='text-align:right; color:#475569; font-size:0.85rem; padding-top:0.6rem;'>"
                f"🕒 Última atualização<br><b style='color:#0F172A;'>{ultima_txt}</b></div>",
                unsafe_allow_html=True,
            )

    if df is None:
        st.error(
            "Nenhuma base de dados encontrada ainda. Clique em **Atualizar dados agora** "
            "na barra lateral, ou rode `scanner_documentacao.py` manualmente uma vez."
        )
        return

    vigencias_futuras = [
        (doc, vig) for doc, vig in VIGENCIA_OBRIGATORIOS.items()
        if vig is not None and vig > date.today()
    ]
    if vigencias_futuras:
        texto = " · ".join(f"{doc} (a partir de {vig.strftime('%d/%m/%Y')})" for doc, vig in vigencias_futuras)
        st.info(f"ℹ️ Ainda não cobrados na auditoria (vigência futura): {texto}")

    # -------------------------------------------------------------
    # Sidebar — filtros
    # -------------------------------------------------------------
    with st.sidebar:
        st.header("🔎 Filtros")

        ufs = st.multiselect("UF", sorted(df["UF"].dropna().unique()), key="f_uf")
        coligadas_disp = (
            sorted(df[df["UF"].isin(ufs)]["Coligada"].dropna().unique()) if ufs
            else sorted(df["Coligada"].dropna().unique())
        )
        coligadas = st.multiselect("Coligada", coligadas_disp, key="f_coligada")
        equipes = st.multiselect(
            "Equipe (Supervisor/Coordenador)", sorted(df["Equipe"].dropna().unique()), key="f_equipe"
        )
        status_colab = st.multiselect(
            "Status do Colaborador", sorted(df["Status_Colaborador"].dropna().unique()), key="f_status"
        )

        st.markdown("**Atalhos**")
        apenas_ativos = st.checkbox("Somente colaboradores ativos", value=False, key="f_ativos")
        apenas_pendentes = st.checkbox("Somente com pendências obrigatórias", value=False, key="f_pend_obr")

        max_pend = int(df["Qtd_Pendencias_Total"].max())
        min_pend = st.slider(
            "Mínimo de documentos pendentes (total)", 0, max_pend, 0, key="f_min_pend"
        )
        busca_nome = st.text_input("Buscar por nome", key="f_busca")

        st.divider()
        if st.button("🧹 Limpar filtros", use_container_width=True):
            for k in FILTER_KEYS:
                st.session_state.pop(k, None)
            st.rerun()

    # -------------------------------------------------------------
    # Aplicação dos filtros
    # -------------------------------------------------------------
    df_f = df.copy()
    if ufs:
        df_f = df_f[df_f["UF"].isin(ufs)]
    if coligadas:
        df_f = df_f[df_f["Coligada"].isin(coligadas)]
    if equipes:
        df_f = df_f[df_f["Equipe"].isin(equipes)]
    if status_colab:
        df_f = df_f[df_f["Status_Colaborador"].isin(status_colab)]
    if apenas_ativos:
        df_f = df_f[df_f["Status_Colaborador"] == "Ativo"]
    if apenas_pendentes:
        df_f = df_f[df_f["Qtd_Pendencias_Obrigatorias"] > 0]
    if min_pend > 0:
        df_f = df_f[df_f["Qtd_Pendencias_Total"] >= min_pend]
    if busca_nome:
        df_f = df_f[df_f["Nome"].str.contains(busca_nome, case=False, na=False)]

    # resumo dos filtros ativos
    chips = []
    if ufs:
        chips.append(f"UF: {', '.join(ufs)}")
    if coligadas:
        chips.append(f"Coligada: {len(coligadas)} selec.")
    if equipes:
        chips.append(f"Equipe: {len(equipes)} selec.")
    if status_colab:
        chips.append(f"Status: {', '.join(status_colab)}")
    if apenas_ativos:
        chips.append("Somente ativos")
    if apenas_pendentes:
        chips.append("Com pendência obrigatória")
    if min_pend > 0:
        chips.append(f"≥ {min_pend} pendências")
    if busca_nome:
        chips.append(f"Nome ~ '{busca_nome}'")

    resumo = (
        "<span class='chip'>Exibindo "
        f"{len(df_f)} de {len(df)} colaboradores</span>"
        + "".join(f"<span class='chip'>{c}</span>" for c in chips)
    )
    st.markdown(resumo, unsafe_allow_html=True)

    if df_f.empty:
        st.warning("Nenhum colaborador atende aos filtros selecionados. Ajuste os filtros na barra lateral.")
        return

    st.divider()

    # -------------------------------------------------------------
    # KPIs
    # -------------------------------------------------------------
    total = len(df_f)
    ativos = int((df_f["Status_Colaborador"] == "Ativo").sum())
    completos = int((df_f["Status_Documental"] == "Completo").sum())
    pendentes_obr = int((df_f["Qtd_Pendencias_Obrigatorias"] > 0).sum())
    media_pend = float(df_f["Qtd_Pendencias_Total"].mean())
    pct_completo = (completos / total * 100) if total else 0
    pct_ativos = (ativos / total * 100) if total else 0
    pct_pend = (pendentes_obr / total * 100) if total else 0

    fmt = lambda v: f"{v:,}".replace(",", ".")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Colaboradores", fmt(total),
              delta=f"de {fmt(len(df))} na base", delta_color="off",
              help="Total no filtro atual.")
    k2.metric("Ativos", fmt(ativos),
              delta=f"{pct_ativos:.0f}% do total", delta_color="off",
              help="Colaboradores com Status = Ativo.")
    k3.metric("Com pendência obrigatória", fmt(pendentes_obr),
              delta=f"{pct_pend:.0f}% do total", delta_color="off",
              help="Faltando ao menos 1 documento obrigatório.")
    k4.metric("Doc. obrigatória completa", fmt(completos),
              delta=f"{pct_completo:.1f}% do total", delta_color="off",
              help="Sem nenhuma pendência obrigatória.")
    k5.metric("Média de pendências", f"{media_pend:.1f}",
              delta=f"máx. {int(df_f['Qtd_Pendencias_Total'].max())} no filtro", delta_color="off",
              help="Média de documentos pendentes (total) por colaborador.")

    st.divider()

    # -------------------------------------------------------------
    # Base de cálculo (afeta as abas de Documentos e Equipes)
    # -------------------------------------------------------------
    opcoes_base = [
        "Todos os documentos (obrigatórios + complementares)",
        "Somente obrigatórios",
        "Somente complementares",
    ]
    base_calculo = st.segmented_control(
        "Base de cálculo da pendência (análises por documento e equipe)",
        opcoes_base, default=opcoes_base[0], key="base_calculo",
    ) or opcoes_base[0]
    cols_doc = colunas_documento(df_f, base_calculo)

    df_eq = df_f.copy()
    if base_calculo == "Somente obrigatórios":
        df_eq["_tem_pendencia"] = df_eq["Qtd_Pendencias_Obrigatorias"] > 0
    elif base_calculo == "Somente complementares":
        df_eq["_tem_pendencia"] = df_eq["Qtd_Pendencias_Complementares"] > 0
    else:
        df_eq["_tem_pendencia"] = df_eq["Qtd_Pendencias_Total"] > 0

    aba_geral, aba_doc, aba_equipe, aba_base = st.tabs([
        "📊 Visão Geral", "📄 Documentos", "👥 Equipes & Detalhamento", "📋 Base & Exportar",
    ])

    # =============================================================
    # ABA 1 — VISÃO GERAL
    # =============================================================
    with aba_geral:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Colaboradores por Status")
            fig_status = px.pie(
                df_f, names="Status_Colaborador", hole=0.6,
                color="Status_Colaborador", color_discrete_map=CORES_STATUS,
            )
            fig_status.update_traces(
                textinfo="percent", textposition="outside",
                marker=dict(line=dict(color="#FFFFFF", width=2)),
                hovertemplate="<b>%{label}</b><br>%{value} colaboradores (%{percent})<extra></extra>",
            )
            fig_status.update_layout(
                height=altura_barras(6),
                annotations=[dict(text=f"<b>{total}</b><br>total", x=0.5, y=0.5,
                                  font=dict(size=18, color=INK_PRIMARIO), showarrow=False)]
            )
            aplicar_tema(fig_status, legenda_topo_centro=True)
            st.plotly_chart(fig_status, use_container_width=True)

        with col2:
            st.subheader("Promotores por Faixa de Pendências")

            def _rotulo_faixa(n):
                n = int(n)
                if n == 0:
                    return "Nenhuma pendência"
                if n == 1:
                    return "1 documento pendente"
                if n < 5:
                    return f"{n} documentos pendentes"
                return "5 ou mais documentos pendentes"

            faixas = df_f["Qtd_Pendencias_Total"].apply(_rotulo_faixa)
            contagem = (
                faixas.value_counts().reindex(ORDEM_FAIXAS).fillna(0).astype(int).reset_index()
            )
            contagem.columns = ["Faixa", "Qtd"]
            contagem["cor"] = contagem["Faixa"].map(CORES_FAIXAS)

            # trace único (barras com largura cheia) e cor por barra
            fig_faixas = px.bar(
                contagem, x="Qtd", y="Faixa", orientation="h", text="Qtd",
                category_orders={"Faixa": ORDEM_FAIXAS},
            )
            fig_faixas.update_traces(
                textposition="outside", cliponaxis=False,
                marker=dict(color=contagem["cor"].tolist(), cornerradius=4, line_width=0),
                hovertemplate="<b>%{y}</b><br>%{x} promotores<extra></extra>",
            )
            aplicar_tema(fig_faixas, remover_eixo_x=True, remover_eixo_y=True)
            fig_faixas.update_layout(
                showlegend=False, bargap=BARGAP_BARRAS, height=altura_barras(len(contagem)),
            )
            fig_faixas.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_faixas, use_container_width=True)

        st.divider()
        col3, col4 = st.columns(2)

        with col3:
            st.subheader("Colaboradores com pendência por UF")
            st.caption("Considera a base de cálculo selecionada acima.")
            pend_uf = (
                df_eq[df_eq["_tem_pendencia"]]
                .groupby("UF").size().reset_index(name="Qtd")
                .sort_values("Qtd", ascending=False)
            )
            if not pend_uf.empty:
                fig_uf = px.bar(
                    pend_uf, x="UF", y="Qtd", text="Qtd",
                    color_discrete_sequence=[COR_PRIMARIA],
                )
                fig_uf.update_traces(
                    textposition="outside", cliponaxis=False,
                    marker=dict(cornerradius=4),
                    hovertemplate="<b>%{x}</b><br>%{y} colaboradores<extra></extra>",
                )
                aplicar_tema(fig_uf, remover_eixo_x=True, remover_eixo_y=True)
                st.plotly_chart(fig_uf, use_container_width=True)
            else:
                st.info("Nenhuma pendência no filtro atual.")

        with col4:
            st.subheader("Colaboradores com pendência por Coligada")
            st.caption("Top coligadas com mais colaboradores pendentes.")
            pend_col = (
                df_eq[df_eq["_tem_pendencia"]]
                .groupby("Coligada").size().reset_index(name="Qtd")
                .sort_values("Qtd", ascending=False).head(15)
            )
            if not pend_col.empty:
                fig_col = px.bar(
                    pend_col, x="Qtd", y="Coligada", orientation="h", text="Qtd",
                    color_discrete_sequence=[COR_PRIMARIA],
                )
                fig_col.update_traces(
                    textposition="outside", cliponaxis=False,
                    marker=dict(color=COR_PRIMARIA, cornerradius=4, line_width=0),
                    hovertemplate="<b>%{y}</b><br>%{x} colaboradores<extra></extra>",
                )
                aplicar_tema(fig_col, remover_eixo_x=True)
                fig_col.update_layout(bargap=BARGAP_BARRAS, height=altura_barras(len(pend_col)))
                fig_col.update_yaxes(title=None, autorange="reversed")
                st.plotly_chart(fig_col, use_container_width=True)
            else:
                st.info("Nenhuma pendência no filtro atual.")

    # =============================================================
    # ABA 2 — DOCUMENTOS
    # =============================================================
    with aba_doc:
        if not cols_doc:
            st.info("Nenhum documento disponível para essa base de cálculo.")
        else:
            st.subheader("Documentos mais pendentes")
            st.caption("Quantos colaboradores estão sem cada documento (no filtro atual).")
            rk = ranking_documentos(df_f, cols_doc)
            fig_rk = px.bar(
                rk, x="Qtd_Sem", y="Documento", orientation="h", text="Qtd_Sem",
                color="Tipo",
                color_discrete_map={"Obrigatório": COR_OBRIGATORIO, "Complementar": COR_COMPLEMENTAR},
                custom_data=["Pct_Sem", "Tipo"],
            )
            fig_rk.update_traces(
                textposition="outside", cliponaxis=False,
                marker=dict(cornerradius=4),
                hovertemplate="<b>%{y}</b> (%{customdata[1]})<br>"
                              "%{x} colaboradores sem o documento (%{customdata[0]:.1f}%)<extra></extra>",
            )
            aplicar_tema(fig_rk, remover_eixo_x=True, legenda_topo_centro=True)
            fig_rk.update_yaxes(title=None, autorange="reversed")
            fig_rk.update_layout(barmode="overlay", bargap=BARGAP_BARRAS,
                                 height=altura_barras(len(rk), base=110))
            st.plotly_chart(fig_rk, use_container_width=True)

            st.divider()
            st.subheader("Mapa de calor — Equipe x Documento")
            st.caption("% de colaboradores da equipe sem cada documento. Tons mais escuros = mais pendência.")
            pct_mat, qtd_mat = matriz_equipe_documento(df_eq, cols_doc)

            fig_heat = px.imshow(
                pct_mat, text_auto=".0f", color_continuous_scale=ESCALA_MARCA,
                zmin=0, zmax=100, aspect="auto",
            )
            fig_heat.update_traces(
                xgap=3, ygap=3,
                textfont=dict(size=12, family="Segoe UI, Arial, sans-serif"),
                hovertemplate="<b>%{y}</b><br>%{x}<br>%{z:.0f}% sem o documento<extra></extra>",
            )
            fig_heat.update_xaxes(title=None, side="top", tickangle=-30, showgrid=False)
            fig_heat.update_yaxes(title=None, showgrid=False)
            fig_heat.update_coloraxes(showscale=False)
            aplicar_tema(fig_heat)
            fig_heat.update_layout(height=max(320, 46 * len(pct_mat)))
            st.plotly_chart(fig_heat, use_container_width=True)

            with st.expander("Ver quantidades absolutas (nº de promotores sem cada documento, por equipe)"):
                st.dataframe(qtd_mat, use_container_width=True)

    # =============================================================
    # ABA 3 — EQUIPES & DETALHAMENTO
    # =============================================================
    with aba_equipe:
        st.subheader("Detalhamento por Equipe → UF → Documento → Pessoas")
        st.caption("Escolha a Equipe e a UF para ver quais documentos estão pendentes e quem são os promotores.")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            equipe_sel = st.selectbox("Equipe", ["Todas"] + sorted(df_eq["Equipe"].dropna().unique()))
        with col_d2:
            base_uf = df_eq if equipe_sel == "Todas" else df_eq[df_eq["Equipe"] == equipe_sel]
            uf_sel = st.selectbox("UF", ["Todas"] + sorted(base_uf["UF"].dropna().unique()))

        df_drill = df_eq.copy()
        if equipe_sel != "Todas":
            df_drill = df_drill[df_drill["Equipe"] == equipe_sel]
        if uf_sel != "Todas":
            df_drill = df_drill[df_drill["UF"] == uf_sel]

        if df_drill.empty:
            st.info("Nenhum colaborador para essa combinação de Equipe/UF no filtro atual.")
        elif not cols_doc:
            st.info("Nenhum documento disponível para essa base de cálculo.")
        else:
            faltando = (~df_drill[cols_doc]).sum().reset_index()
            faltando.columns = ["ColunaOriginal", "Qtd_Sem_Documento"]
            faltando["Documento"] = faltando["ColunaOriginal"].apply(nome_documento)
            faltando["Tipo"] = faltando["ColunaOriginal"].apply(tipo_documento)
            faltando = faltando[faltando["Qtd_Sem_Documento"] > 0].sort_values(
                "Qtd_Sem_Documento", ascending=False
            )

            if faltando.empty:
                st.success(f"Nenhuma pendência para Equipe: **{equipe_sel}** / UF: **{uf_sel}**.")
            else:
                fig_drill = px.bar(
                    faltando, x="Qtd_Sem_Documento", y="Documento", orientation="h",
                    text="Qtd_Sem_Documento", color="Tipo",
                    color_discrete_map={"Obrigatório": COR_OBRIGATORIO, "Complementar": COR_COMPLEMENTAR},
                )
                fig_drill.update_traces(
                    textposition="outside", cliponaxis=False, marker=dict(cornerradius=4),
                    hovertemplate="<b>%{y}</b><br>%{x} promotores sem o documento<extra></extra>",
                )
                aplicar_tema(fig_drill, remover_eixo_x=True, legenda_topo_centro=True)
                fig_drill.update_yaxes(title=None, autorange="reversed")
                fig_drill.update_layout(barmode="overlay", bargap=BARGAP_BARRAS,
                                        height=altura_barras(len(faltando), base=110))
                st.plotly_chart(fig_drill, use_container_width=True)

                doc_sel = st.selectbox("Ver os promotores sem qual documento?", faltando["Documento"].tolist())
                col_original = faltando.loc[faltando["Documento"] == doc_sel, "ColunaOriginal"].iloc[0]
                pessoas = df_drill[~df_drill[col_original]][
                    ["Nome", "UF", "Equipe", "Coligada", "Status_Colaborador"]
                ].sort_values("Nome").rename(columns={"Status_Colaborador": "Status"})
                st.markdown(f"**{len(pessoas)} promotor(es) sem \"{doc_sel}\":**")
                st.dataframe(pessoas, use_container_width=True, hide_index=True)

                st.download_button(
                    f"⬇️ Baixar lista — sem '{doc_sel}' (CSV)",
                    data=pessoas.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"sem_{doc_sel}.csv".replace(" ", "_"),
                    mime="text/csv",
                )

    # =============================================================
    # ABA 4 — BASE & EXPORTAR
    # =============================================================
    with aba_base:
        st.subheader("Colaboradores com pendências obrigatórias")
        df_pend = df_f[df_f["Qtd_Pendencias_Obrigatorias"] > 0][
            ["UF", "Coligada", "Equipe", "Nome", "Status_Colaborador",
             "Pendencias_Obrigatorias", "Pendencias_Complementares",
             "Qtd_Pendencias_Obrigatorias", "Qtd_Pendencias_Complementares"]
        ].sort_values(["Qtd_Pendencias_Obrigatorias", "UF", "Equipe", "Nome"],
                      ascending=[False, True, True, True]).rename(columns={
            "Status_Colaborador": "Status",
            "Pendencias_Obrigatorias": "Pendências Obrigatórias",
            "Pendencias_Complementares": "Pendências Complementares",
            "Qtd_Pendencias_Obrigatorias": "Qtd. Obrigatórias",
            "Qtd_Pendencias_Complementares": "Qtd. Complementares",
        })

        st.caption(f"{len(df_pend)} colaborador(es) com pendência obrigatória no filtro atual.")
        st.dataframe(
            df_pend, use_container_width=True, hide_index=True,
            column_config={
                "Qtd. Obrigatórias": st.column_config.ProgressColumn(
                    "Qtd. Obrigatórias", min_value=0,
                    max_value=int(df_pend["Qtd. Obrigatórias"].max()) if len(df_pend) else 1,
                    format="%d",
                ),
            },
        )

        c_dl1, c_dl2 = st.columns(2)
        c_dl1.download_button(
            "⬇️ Baixar pendências obrigatórias (CSV)",
            data=df_pend.to_csv(index=False).encode("utf-8-sig"),
            file_name="pendencias_documentacao.csv",
            mime="text/csv",
            use_container_width=True,
        )
        c_dl2.download_button(
            "⬇️ Baixar base filtrada completa (CSV)",
            data=df_f.to_csv(index=False).encode("utf-8-sig"),
            file_name="base_documentacao_filtrada.csv",
            mime="text/csv",
            use_container_width=True,
        )

        with st.expander("Ver base completa (todos os colaboradores e documentos do filtro)"):
            st.dataframe(df_f, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
