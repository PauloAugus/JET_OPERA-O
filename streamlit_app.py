"""
streamlit_app.py
=================
Camada VISUAL do dashboard J&T Operations.

Este arquivo não sabe "ler planilha" — quem faz isso é
`scripts/process_data.py` (função `process`). Aqui só existe: upload do
arquivo, filtros da barra lateral, KPIs e os gráficos/tabelas de cada
módulo (Dashboard, Franquias, Relatórios).
"""

# `from __future__ import annotations` deixa anotações de tipo modernas
# (como `float | int | None`) funcionarem em versões mais antigas do
# Python, tratando-as como texto em vez de avaliar na hora.
from __future__ import annotations

# `base64` converte o arquivo carregado (bytes) em texto Base64, formato
# que passamos para `process()` em process_data.py.
import base64

# `sys` é usado para adicionar a pasta `scripts/` à lista de lugares onde
# o Python procura módulos para importar.
import sys

# `Path` facilita montar caminhos de arquivo de forma independente de
# sistema operacional (Windows, Linux, Mac).
from pathlib import Path

# `numpy` é usado para marcar as células de "Total" do heatmap como
# vazias (NaN), fazendo elas se destacarem visualmente das demais.
import numpy as np

# `pandas` monta as tabelas usadas nos gráficos e na aplicação dos filtros.
import pandas as pd

# `plotly.graph_objects` desenha os gráficos interativos (área, gauge,
# heatmap) usados no dashboard.
import plotly.graph_objects as go

# `streamlit` é o framework que transforma este script em uma página web.
import streamlit as st

# Pasta onde este arquivo está salvo — é a "raiz" do projeto.
ROOT = Path(__file__).resolve().parent
# Adiciona a subpasta "scripts" ao caminho de importação do Python...
sys.path.insert(0, str(ROOT / "scripts"))
# ...para poder importar a função `process`, que faz toda a análise da
# planilha (implementada em scripts/process_data.py).
from process_data import process  # noqa: E402  (import fora do topo é intencional)

# Configura a aba do navegador: título, ícone, layout ocupando a largura
# toda e a barra lateral já aberta quando o app é carregado.
st.set_page_config(page_title="J&T Operations", page_icon="🚚", layout="wide", initial_sidebar_state="expanded")

# Bloco de CSS injetado na página (cores da marca J&T, cartões, cabeçalho
# etc.). `unsafe_allow_html=True` é necessário porque estamos passando
# HTML/CSS puro, não um componente nativo do Streamlit.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
:root { --red:#d7192f; --navy:#173652; --ink:#26394d; --muted:#718394; --line:#e4e8ed; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:#f7f8fa; }
[data-testid="stHeader"] { background:linear-gradient(110deg,#b9081c 0%,#e51b2d 58%,#f02f40 100%); }
[data-testid="stSidebar"] { background:#fff; border-right:1px solid #e6e9ed; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color:var(--ink); }
.brand { display:flex; align-items:center; gap:12px; margin:-1rem 0 1rem; padding:16px 18px; color:#fff; background:linear-gradient(110deg,#b9081c,#e51b2d); border-radius:0 0 10px 10px; }
.brand b { font:700 19px 'Space Grotesk'; } .brand small { display:block; opacity:.8; }
.page-title { margin:4px 0 2px; color:var(--ink); font:700 30px 'Space Grotesk'; letter-spacing:-.04em; }
.page-subtitle { color:var(--muted); font-size:12px; }
.card { background:#fff; border:1px solid var(--line); border-radius:10px; padding:16px; box-shadow:0 5px 16px rgba(31,58,80,.055); }
.card-title { margin:0 0 10px; color:#34495d; font:700 13px 'Space Grotesk'; }
.kpi { min-height:94px; padding:14px 16px; background:#fff; border:1px solid var(--line); border-top:4px solid var(--accent); border-radius:10px; }
.kpi label { display:block; color:#687887; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }
.kpi strong { display:block; margin:9px 0 3px; color:var(--ink); font:700 25px 'Space Grotesk'; }
.kpi small { color:#7e8a96; }
.goal-box { padding:0 4px 4px; } .goal-row { display:flex; justify-content:space-between; margin:7px 0; padding:9px 11px; border-radius:7px; color:#6f7882; background:#f1f1f1; font-size:11px; } .goal-row b { color:#303944; }
.offender { background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px; box-shadow:0 5px 16px rgba(31,58,80,.055); } .offender.pos { border-top:4px solid #2aa985; } .offender.neg { border-top:4px solid #d93651; }
.offender h3 { margin:0; color:#34495d; font:700 13px 'Space Grotesk'; } .offender p { margin:2px 0 10px; color:#8b98a3; font-size:10px; }
div[data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:9px; padding:10px; }
@media (max-width: 800px) { .page-title { font-size:24px; } }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Funções de formatação de número (padrão brasileiro: "." nos milhares,
# "," na casa decimal).
# ---------------------------------------------------------------------------
def fmt(value: float | int | None) -> str:
    # `value or 0` trata `None` como zero antes de formatar.
    # `:,.0f` formata no padrão americano (vírgula = milhar, ponto = decimal)...
    # ...e as duas trocas de `.replace(...)` invertem para o padrão brasileiro.
    return f"{float(value or 0):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value: float | None) -> str:
    # Sem valor (meta não informada, por exemplo): mostra travessão.
    # `pd.isna` também cobre NaN, que aparece quando o valor passa por um DataFrame.
    return "—" if value is None or pd.isna(value) else f"{value:.1f}%".replace(".", ",")


def signed(value: float) -> str:
    # Sempre mostra o sinal (+ ou −) na frente do saldo da meta.
    return ("+" if value >= 0 else "−") + fmt(abs(value))


def display_number(value: float | int | None) -> str:
    return "—" if value is None else fmt(value)


# `@st.cache_data` evita reprocessar o MESMO arquivo toda vez que o
# usuário mexe em um filtro da barra lateral (o Streamlit reexecuta o
# script inteiro a cada interação).
@st.cache_data(show_spinner=False)
def analyze_file(name: str, raw: bytes) -> dict:
    # Empacota o arquivo no formato que `process()` espera e delega toda
    # a análise para scripts/process_data.py.
    return process({"filename": name, "content": base64.b64encode(raw).decode("ascii"), "size": len(raw)})


def load_default() -> tuple[str, bytes] | None:
    """Procura uma base padrão dentro do próprio repositório (opcional).

    Aceita QUALQUER planilha Excel/CSV na pasta `data/` (ou na raiz do
    projeto) — assim não importa se o arquivo foi renomeado ao subir no
    GitHub. Se houver mais de uma, usa a mais recente.
    """
    found: list[Path] = []
    for folder in (ROOT / "data", ROOT):
        if folder.is_dir():
            for pattern in ("*.xlsx", "*.xlsm", "*.xls", "*.csv"):
                found.extend(folder.glob(pattern))
    if not found:
        return None  # nenhum arquivo: o app vai pedir upload ao usuário.
    newest = max(found, key=lambda path: path.stat().st_mtime)  # a mais recente.
    return newest.name, newest.read_bytes()


def metric_card(label: str, value: str, detail: str, accent: str) -> None:
    """Desenha um cartão de KPI (título + valor grande + detalhe)."""
    st.markdown(
        f'<div class="kpi" style="--accent:{accent}"><label>{label}</label>'
        f'<strong>{value}</strong><small>{detail}</small></div>',
        unsafe_allow_html=True,
    )


def chart_area(data: list[dict]) -> None:
    """Gráfico de área: volume produzido em cada hora do dia."""
    frame = pd.DataFrame(data)
    if frame.empty:
        st.info("Sem produção horária disponível.")
        return
    fig = go.Figure(
        go.Scatter(
            x=frame["hour"],
            y=frame["value"],
            mode="lines+markers",
            line={"color": "#7657d9", "width": 3},
            marker={"size": 5, "color": "#7657d9"},
            fill="tozeroy",
            fillcolor="rgba(139,92,246,.16)",
        )
    )
    fig.update_layout(
        height=280,
        margin={"l": 10, "r": 10, "t": 8, "b": 20},
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="Hora",
        yaxis_title="Volume",
        font={"size": 10, "color": "#708090"},
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def chart_origin(data: list[dict]) -> None:
    """MELHORIA: gráfico de barras horizontais com a origem dos pedidos
    (ex.: SHEIN, SHOPEE, TikTok, Mercado Livre) — ajuda a enxergar qual
    canal/cliente concentra o volume escaneado."""
    frame = pd.DataFrame(data)
    if frame.empty:
        st.info("Sem dados de origem do pedido nesta planilha.")
        return
    # Ordena do menor para o maior porque barras horizontais no Plotly
    # desenham de baixo para cima — assim o maior valor fica no topo.
    frame = frame.sort_values("value")
    fig = go.Figure(
        go.Bar(x=frame["value"], y=frame["label"], orientation="h", marker={"color": "#5d8fc4"})
    )
    fig.update_layout(
        height=max(220, len(frame) * 28),
        margin={"l": 10, "r": 10, "t": 8, "b": 20},
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="Pedidos",
        font={"size": 10, "color": "#708090"},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def chart_meta_vs_real(items: list[dict], label_key: str, height: int = 380) -> None:
    """NOVO: barras agrupadas Meta x Realizado, com o % de atingimento
    escrito acima da barra de "Realizado". Usado na Distribuição de bases."""
    frame = pd.DataFrame(items)
    if frame.empty:
        st.info("Sem dados para o gráfico.")
        return
    fig = go.Figure()
    # Barra cinza = meta; barra vermelha = realizado (com o % no topo).
    fig.add_trace(go.Bar(name="Meta", x=frame[label_key], y=frame["meta"], marker={"color": "#b8c4d0"},
                         text=frame["meta"].map(fmt), textposition="inside"))
    fig.add_trace(go.Bar(name="Realizado", x=frame[label_key], y=frame["realized"], marker={"color": "#e51b2d"},
                         text=frame["percent"].map(pct), textposition="outside"))
    fig.update_layout(
        barmode="group",  # barras lado a lado (não empilhadas).
        height=height,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend={"orientation": "h", "y": 1.12},
        xaxis={"tickangle": -30},
        yaxis_title="Pedidos",
        font={"size": 10, "color": "#708090"},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def goal_chart(realized: float, goal: float) -> None:
    """Velocímetro (gauge) de atingimento da meta + resumo em texto."""
    # Limita o progresso entre 0% e 100% mesmo que o realizado ultrapasse
    # a meta (evita um ponteiro "fora da escala").
    progress = max(0.0, min(realized / goal * 100 if goal else 0, 100))
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=progress,
            number={"suffix": "%", "font": {"size": 29, "color": "#327fdd"}},
            gauge={
                "axis": {"range": [0, 100], "visible": False},
                "bar": {"color": "#3d8de0", "thickness": .32},
                "bgcolor": "#e9eef5",
                "borderwidth": 0,
            },
        )
    )
    fig.update_layout(height=210, margin={"l": 25, "r": 25, "t": 8, "b": 0}, paper_bgcolor="white", font={"family": "DM Sans"})
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.caption("Próximo da Meta")
    # Cor do saldo: verde se bateu a meta, vermelho se ficou abaixo.
    saldo_cor = "#268b70" if realized >= goal else "#d22b4a"
    st.markdown(
        f'<div class="goal-box">'
        f'<div class="goal-row"><span>Pedidos Expedidos:</span><b>{fmt(realized)}</b></div>'
        f'<div class="goal-row"><span>Meta Total (Bases):</span><b>{fmt(goal)}</b></div>'
        f'<div class="goal-row"><span>Saldo da meta:</span><b style="color:{saldo_cor}">{signed(realized - goal)}</b></div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.progress(progress / 100, text=f"Progresso · {fmt(realized)} / {fmt(goal)}")


def heatmap_chart(items: list[dict], expanded: bool = False) -> None:
    """Mapa de calor: produtividade de cada digitalizador, hora a hora.

    MELHORIAS:
    - linha e coluna "Total" (soma de cada digitalizador e de cada hora);
    - digitalizadores ordenados do maior para o menor total (decrescente);
    - parâmetro `expanded`: quando True, desenha um heatmap maior (usado
      dentro do modal de "Ampliar").
    """
    frame = pd.DataFrame(items)
    if frame.empty:
        st.info("Sem dados para o Heatmap.")
        return
    # `pivot_table` transforma a lista de {digitalizer, hour, value} numa
    # matriz: linhas = digitalizador, colunas = hora, células = volume.
    pivot = frame.pivot_table(index="digitalizer", columns="hour", values="value", aggfunc="sum", fill_value=0)
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)  # garante horas em ordem crescente.

    # MELHORIA: coluna "Total" = soma de todas as horas daquele digitalizador.
    pivot["Total"] = pivot.sum(axis=1)
    # MELHORIA: ordena os digitalizadores do maior para o menor total.
    pivot = pivot.sort_values("Total", ascending=False)
    # MELHORIA: linha "Total" = soma de todos os digitalizadores em cada hora.
    totals_row = pivot.sum(axis=0)
    totals_row.name = "Total"
    pivot = pd.concat([pivot, totals_row.to_frame().T])

    # Texto exibido dentro de cada célula (inclui a linha/coluna Total).
    text = pivot.map(lambda v: fmt(v) if v else "")

    # Matriz usada só para definir a COR: a linha e a coluna "Total" viram
    # NaN aqui, o que faz o Plotly deixar essas células sem preenchimento
    # de cor (destacando-as das demais, que seguem a escala normal).
    color_matrix = pivot.astype(float).copy()
    color_matrix.loc["Total", :] = np.nan
    color_matrix.loc[:, "Total"] = np.nan

    colors = [[0, "#ffffff"], [.2, "#e2f4f8"], [.4, "#9bdeed"], [.6, "#43b9dc"], [.8, "#1599c8"], [1, "#236b8e"]]
    # zmax é calculado SEM a linha/coluna Total, senão os valores somados
    # (muito maiores) esmagariam a escala de cor das células normais.
    only_data = color_matrix.drop(index="Total").drop(columns="Total")
    max_value = max(float(np.nanmax(only_data.to_numpy())), 1)

    # Rótulos do eixo X: horas viram "08h", "09h"...; a última coluna
    # continua mostrando o texto "Total".
    x_labels = ["Total" if col == "Total" else f"{int(col):02d}h" for col in pivot.columns]

    fig = go.Figure(
        go.Heatmap(
            z=color_matrix.values,
            x=x_labels,
            y=pivot.index,
            text=text.values,
            texttemplate="%{text}",
            textfont={"color": "#111827", "size": 10},
            colorscale=colors,
            zmin=0,
            zmax=max_value,
            showscale=False,
            hovertemplate="%{y}<br>%{x}: %{z:,.0f}<extra></extra>",
        )
    )
    base_height = 390 if not expanded else 620
    fig.update_layout(
        height=max(base_height, len(pivot.index) * (28 if not expanded else 34)),
        margin={"l": 5, "r": 5, "t": 5, "b": 5},
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"size": 10 if not expanded else 12, "color": "#111827"},
        xaxis={"side": "top", "showgrid": True, "gridcolor": "#fff"},
        yaxis={"autorange": "reversed", "showgrid": True, "gridcolor": "#fff"},
    )
    # No modo ampliado habilitamos a barra de ferramentas do Plotly (zoom,
    # pan, download em PNG) — no modo normal ela fica escondida para não
    # poluir o card compacto do dashboard.
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": expanded})


@st.dialog("Heatmap de produtividade por digitalizador", width="large")
def _heatmap_dialog(items: list[dict]) -> None:
    """MELHORIA: modal que mostra o heatmap em tamanho ampliado, com as
    ferramentas de zoom/pan/download do Plotly habilitadas."""
    heatmap_chart(items, expanded=True)


def chart_ranking(data: list[dict], expanded: bool = False) -> None:
    """MELHORIA: ranking de digitalizadores como gráfico de barras
    HORIZONTAIS (Plotly), com os valores escritos dentro de cada barra e
    ordem decrescente. `expanded=True` desenha uma versão maior (usada no
    modal de "Ampliar")."""
    frame = pd.DataFrame(data)
    if frame.empty:
        st.info("Sem dados de ranking.")
        return
    # Ordena do menor para o maior porque barras horizontais no Plotly
    # desenham de baixo para cima — assim o maior valor fica no topo
    # (mesmo padrão usado no gráfico "Distribuição por origem do pedido").
    frame = frame.sort_values("value", ascending=True)
    fig = go.Figure(
        go.Bar(
            x=frame["value"],
            y=frame["label"],
            orientation="h",
            text=frame["value"].map(fmt),
            textposition="inside",
            textfont={"color": "white", "size": 10 if not expanded else 12},
            marker={"color": "#5d8fc4"},
        )
    )
    base_height = 460 if not expanded else 650
    fig.update_layout(
        height=max(base_height, len(frame) * (24 if not expanded else 30)),
        margin={"l": 10, "r": 10, "t": 8, "b": 20},
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="Pedidos",
        font={"size": 10 if not expanded else 12, "color": "#708090"},
    )
    # No modo ampliado habilitamos a barra de ferramentas do Plotly (zoom,
    # pan, download em PNG); no card compacto ela fica escondida.
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": expanded})


@st.dialog("Ranking de digitalizadores", width="large")
def _ranking_dialog(data: list[dict]) -> None:
    """MELHORIA: modal com o ranking em tamanho ampliado + pódio."""
    chart_ranking(data, expanded=True)
    podium_cards(data)


def podium_cards(data: list[dict]) -> None:
    """MELHORIA: pódio com os 3 digitalizadores que mais escanearam pedidos."""
    top3 = sorted(data, key=lambda x: -x["value"])[:3]
    if not top3:
        return
    medals = ["🥇 1º lugar", "🥈 2º lugar", "🥉 3º lugar"]
    accents = ["#e9c46a", "#b8c4d0", "#c98a4b"]  # ouro, prata, bronze
    cols = st.columns(len(top3))
    for col, medal, accent, item in zip(cols, medals, accents, top3):
        with col:
            st.markdown(
                f'<div class="kpi" style="--accent:{accent}; text-align:center;">'
                f'<label>{medal}</label>'
                f'<strong style="font-size:15px;">{item["label"]}</strong>'
                f'<small>{fmt(item["value"])} pedidos</small>'
                f'</div>',
                unsafe_allow_html=True,
            )


def offenders_table(items: list[dict]) -> None:
    """Tabela de bases acima/abaixo da meta (ofensores positivos/negativos)."""
    frame = pd.DataFrame(items)
    if frame.empty:
        st.info("Nenhuma base nesta categoria.")
        return
    frame["Base destino"] = frame["base"]
    frame["Código"] = frame["code"]
    frame["Atingimento"] = frame["percent"].map(pct)
    frame["Saldo"] = frame.apply(lambda row: signed(row["realized"] - row["meta"]), axis=1)
    frame["Meta"] = frame["meta"].map(fmt)
    frame["Realizado"] = frame["realized"].map(fmt)
    st.dataframe(
        frame[["Base destino", "Código", "Meta", "Realizado", "Atingimento", "Saldo"]],
        hide_index=True,
        use_container_width=True,
        height=355,
    )


# ---------------------------------------------------------------------------
# Barra lateral: marca, upload do arquivo e base padrão (se existir)
# ---------------------------------------------------------------------------
st.sidebar.markdown(
    '<div class="brand"><div>🚚</div><div><b>J&T Operations</b>'
    '<small>Centro de acompanhamento logístico</small></div></div>',
    unsafe_allow_html=True,
)
# Aceita os formatos pedidos: CSV, TXT, TSV, XLS e XLSX.
upload = st.sidebar.file_uploader("Carregar relatório", type=["csv", "txt", "tsv", "xls", "xlsx"])
default = load_default()

if upload is not None:
    # Usuário enviou um arquivo agora: usa ele.
    filename, raw = upload.name, upload.getvalue()
elif default is not None:
    # Nenhum upload ainda, mas existe uma base padrão no repositório.
    filename, raw = default
    st.sidebar.info("Base inicial carregada. Envie outro arquivo para substituir.")
else:
    # Sem upload e sem base padrão: fica vazio (tratado logo abaixo).
    filename, raw = "", b""

if not raw:
    st.title("J&T Operations")
    st.info("Carregue um arquivo Excel, CSV, TXT ou TSV para iniciar o dashboard.")
    st.stop()  # interrompe a execução do script aqui — nada mais roda sem dados.

# Processa o arquivo (com spinner de carregamento) e trata erro amigável.
with st.spinner("Analisando planilhas e relações…"):
    analysis = analyze_file(filename, raw)
if "error" in analysis:
    st.error(analysis["error"])
    st.stop()

reports = analysis.get("reports", [])
report_names = [r["sheet"] for r in reports]
# Se houver mais de um relatório (mais de uma aba operacional), o usuário
# escolhe qual visualizar; com apenas um, o seletor mostra só essa opção.
report_name = st.sidebar.selectbox(
    "Relatório",
    report_names,
    index=report_names.index(analysis.get("primarySheet")) if analysis.get("primarySheet") in report_names else 0,
)
current = next((r for r in reports if r["sheet"] == report_name), reports[0])

# Opções dos filtros vêm dos próprios dados (bases e digitalizadores
# realmente presentes no relatório selecionado).
all_bases = sorted({str(x["base"]) for x in current.get("baseMetrics", []) if x.get("base")})
all_digitalizers = sorted({str(x["label"]) for x in current.get("digitalizerRanking", []) if x.get("label")})
selected_base = st.sidebar.selectbox("Base / franquia", ["Todas as bases"] + all_bases)
selected_digitalizer = st.sidebar.selectbox("Digitalizador", ["Todos os digitalizadores"] + all_digitalizers)
query = st.sidebar.text_input("Busca", placeholder="Pedido, cliente, base…")

# ---------------------------------------------------------------------------
# Aplicação dos filtros sobre o índice pré-calculado (rápido: não reabre
# a planilha original, só filtra a tabela já processada).
# ---------------------------------------------------------------------------
index = pd.DataFrame(current.get("filterIndex", []))
if not index.empty:
    mask = pd.Series(True, index=index.index)
    if selected_base != "Todas as bases":
        mask &= index["base"].eq(selected_base)
    if selected_digitalizer != "Todos os digitalizadores":
        mask &= index["digitalizer"].eq(selected_digitalizer)
    if query:
        mask &= index["search"].str.lower().str.contains(query.lower(), na=False)
    filtered = index[mask]
else:
    filtered = index
has_filter = selected_base != "Todas as bases" or selected_digitalizer != "Todos os digitalizadores" or bool(query)

# Realizado: soma do relatório inteiro, ou do recorte filtrado.
realized = float(filtered["volume"].sum()) if has_filter else float(current.get("totalRealized", 0))
# Meta: total do arquivo, ou recalculada por base/código quando há filtro
# (evita somar a mesma meta várias vezes, já que ela se repete por linha).
goal = float(analysis.get("metaTotal") or analysis.get("totalGoal") or current.get("totalGoal", 0))
if has_filter and not filtered.empty:
    goal = float(filtered.groupby(["base", "code"], dropna=False)["meta"].max().sum())
elif has_filter:
    goal = 0.0  # filtro sem nenhum pedido (ex.: base só com meta): não compara com a meta total.
inserted = realized if current["sheet"].lower() == "inserido em lote" else float(
    next((r["totalRealized"] for r in reports if r["sheet"].lower() == "inserido em lote"), realized)
)
attainment = inserted / goal * 100 if goal else 0
# MELHORIA: peso faturado total, respeitando o mesmo filtro do realizado.
weight_total = float(filtered["weight"].sum()) if has_filter else float(current.get("weightTotal", 0))

st.markdown('<div class="page-title">Acompanhamento da operação</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="page-subtitle">{fmt(len(filtered) if has_filter else current.get("totalRows", 0))} '
    f'registros visíveis · {filename}</div>',
    unsafe_allow_html=True,
)

# MELHORIA: 5 cartões de KPI (o quinto mostra o peso faturado total).
kpis = st.columns(5)
with kpis[0]:
    metric_card("Inserido em lote", fmt(inserted), "expedição", "#f4a340")
with kpis[1]:
    metric_card("Meta", fmt(goal), analysis.get("goalSource", "Dinâmica Meta"), "#5d8fc4")
with kpis[2]:
    metric_card("Atingimento", pct(attainment), "inserido / meta", "#e9c46a")
with kpis[3]:
    metric_card("Digitalizadores", fmt(len(all_digitalizers)), "todos identificados", "#8b7ac8")
with kpis[4]:
    metric_card("Peso faturado (kg)", fmt(weight_total), "total do recorte", "#2aa985")

page = st.sidebar.radio("Módulo", ["Dashboard", "Franquias", "Distribuição de bases", "Relatórios"])

if page == "Dashboard":
    top = st.columns([1.75, .9])
    with top[0]:
        st.markdown('<div class="card"><div class="card-title">Produção por hora</div>', unsafe_allow_html=True)
        chart_area(current.get("areaSeries", []))
        st.markdown('</div>', unsafe_allow_html=True)
    with top[1]:
        st.markdown('<div class="card"><div class="card-title">Monitoramento de Meta</div>', unsafe_allow_html=True)
        goal_chart(inserted, goal)
        st.markdown('</div>', unsafe_allow_html=True)

    bottom = st.columns([1.35, 1])
    with bottom[0]:
        st.markdown('<div class="card"><div class="card-title">Heatmap de produtividade por digitalizador</div>', unsafe_allow_html=True)
        # MELHORIA: botão que abre o mesmo heatmap em tamanho ampliado
        # (modal), com zoom/pan/download habilitados.
        if st.button("🔍 Ampliar heatmap", key="expand_heatmap"):
            _heatmap_dialog(current.get("heatmap", []))
        heatmap_chart(current.get("heatmap", []))
        st.markdown('</div>', unsafe_allow_html=True)
    with bottom[1]:
        st.markdown('<div class="card"><div class="card-title">Ranking de digitalizadores</div>', unsafe_allow_html=True)
        # MELHORIA: botão que abre o mesmo ranking em tamanho ampliado.
        if st.button("🔍 Ampliar ranking", key="expand_ranking"):
            _ranking_dialog(current.get("digitalizerRanking", []))
        # MELHORIA: gráfico de barras HORIZONTAIS (Plotly) com valores dentro
        # das barras e ordem decrescente, em vez do st.bar_chart simples.
        chart_ranking(current.get("digitalizerRanking", []))
        # MELHORIA: pódio com os 3 primeiros colocados.
        podium_cards(current.get("digitalizerRanking", []))
        st.markdown('</div>', unsafe_allow_html=True)

    # MELHORIA: nova análise — distribuição de pedidos por origem/cliente
    # (ex.: SHEIN, SHOPEE, TikTok), útil para entender de onde vem o volume.
    origin = current.get("originBreakdown", [])
    if origin:
        st.markdown('<div class="card"><div class="card-title">Distribuição por origem do pedido</div>', unsafe_allow_html=True)
        chart_origin(origin)
        st.markdown('</div>', unsafe_allow_html=True)

elif page == "Franquias":
    metrics = sorted(current.get("baseMetrics", []), key=lambda x: (x.get("percent") is None, -(x.get("percent") or -1)))
    # 10 bases que mais superaram a meta (realizado - meta positivo, do maior para o menor).
    positive = sorted(
        [x for x in metrics if x.get("realized", 0) > x.get("meta", 0)],
        key=lambda x: x["realized"] - x["meta"],
        reverse=True,
    )[:10]
    # 10 bases mais distantes da meta (realizado - meta mais negativo primeiro).
    negative = sorted(
        [x for x in metrics if x.get("realized", 0) < x.get("meta", 0)],
        key=lambda x: x["realized"] - x["meta"],
    )[:10]
    cols = st.columns(2)
    with cols[0]:
        st.markdown('<div class="offender pos"><h3>↑ 10 ofensores positivos</h3><p>Acima da meta planejada</p>', unsafe_allow_html=True)
        offenders_table(positive)
        st.markdown('</div>', unsafe_allow_html=True)
    with cols[1]:
        st.markdown('<div class="offender neg"><h3>↓ 10 ofensores negativos</h3><p>Abaixo da meta planejada</p>', unsafe_allow_html=True)
        offenders_table(negative)
        st.markdown('</div>', unsafe_allow_html=True)
    st.subheader("Controle de metas por base destino")
    table = pd.DataFrame(metrics)
    if not table.empty:
        table["meta"] = table["meta"].map(fmt)
        table["realized"] = table["realized"].map(fmt)
        table["percent"] = table["percent"].map(pct)
        st.dataframe(
            table.rename(columns={"base": "Base destino", "code": "Código", "meta": "Meta", "realized": "Realizado", "percent": "Atingimento"}),
            hide_index=True,
            use_container_width=True,
        )

elif page == "Distribuição de bases":
    # NOVO MÓDULO: resultado (meta, % e realizado) de cada grupo de bases
    # definido na aba "Distribuição de bases" da planilha, de forma separada.
    st.subheader("Distribuição de bases")
    dist = current.get("distribution")
    if not dist:
        st.info("A aba 'Distribuição de bases' não foi encontrada neste arquivo. Envie a planilha completa (com essa aba) para ver este módulo.")
    else:
        # Lista de grupos + o grupo "Sem grupo" (bases que não estão na aba).
        all_groups = dist["groups"] + ([dist["ungrouped"]] if dist.get("ungrouped") else [])

        # --- Resumo: uma linha por grupo ---------------------------------
        st.markdown("##### Resumo por grupo")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Grupo": g["group"],
                        "Bases": g["count"],
                        "Meta": fmt(g["meta"]),
                        "Realizado": fmt(g["realized"]),
                        "Atingimento": pct(g["percent"]),
                        "Saldo": signed(g["balance"]),
                    }
                    for g in all_groups
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        with st.container(border=True):
            chart_meta_vs_real(
                [{"label": g["group"], "meta": g["meta"], "realized": g["realized"], "percent": g["percent"]} for g in all_groups],
                "label",
            )

        # Avisos sobre a aba (bases em 2 grupos / bases fora dos grupos).
        if dist.get("overlaps"):
            itens = "; ".join(f"{o['base']} ({' e '.join(o['groups'])})" for o in dist["overlaps"])
            st.warning(f"Base listada em mais de um grupo (entra nos dois resultados): {itens}.")
        if dist.get("ungrouped"):
            st.caption("O grupo 'Sem grupo' reúne bases com pedidos/meta que não aparecem na aba 'Distribuição de bases'.")

        # --- Cada grupo separadamente (uma aba por grupo) -----------------
        st.markdown("##### Resultado de cada grupo")
        tabs = st.tabs([g["group"] for g in all_groups])
        for tab, g in zip(tabs, all_groups):
            with tab:
                cards = st.columns(4)
                with cards[0]:
                    metric_card("Meta", fmt(g["meta"]), f"{g['count']} bases", "#5d8fc4")
                with cards[1]:
                    metric_card("Realizado", fmt(g["realized"]), "pedidos expedidos", "#e51b2d")
                with cards[2]:
                    metric_card("Atingimento", pct(g["percent"]), "realizado / meta", "#e9c46a")
                with cards[3]:
                    metric_card("Saldo", signed(g["balance"]), "realizado − meta", "#2aa985" if g["balance"] >= 0 else "#d93651")
                with st.container(border=True):
                    chart_meta_vs_real(g["bases"], "base", height=340)
                bases = pd.DataFrame(g["bases"])
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Base": bases["base"],
                            "Código": bases["code"],
                            "Meta": bases["meta"].map(fmt),
                            "Realizado": bases["realized"].map(fmt),
                            "Atingimento": bases["percent"].map(pct),
                            "Saldo": (bases["realized"] - bases["meta"]).map(signed),
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

        # --- Exportação de todos os grupos em CSV --------------------------
        export = pd.DataFrame(
            [
                {"Grupo": g["group"], "Base": b["base"], "Código": b["code"], "Meta": b["meta"],
                 "Realizado": b["realized"], "Atingimento (%)": b["percent"], "Saldo": b["realized"] - b["meta"]}
                for g in all_groups for b in g["bases"]
            ]
        )
        st.download_button(
            "⬇️ Baixar distribuição (CSV)",
            export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            file_name="distribuicao_de_bases.csv",
            mime="text/csv",
        )

else:  # page == "Relatórios"
    st.subheader("Relatórios operacionais")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Planilha": r["sheet"],
                    "Registros": r["totalRows"],
                    "Bases": len(r.get("baseMetrics", [])),
                    "Digitalizadores": len(r.get("digitalizerRanking", [])),
                }
                for r in reports
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    # NOVO: verificação da associação "inserido em lote → base → meta".
    assoc = pd.DataFrame(current.get("associations", []))
    if not assoc.empty:
        st.subheader("Associação: inserido em lote → base → meta")
        alerts = assoc[assoc["status"] != "OK"]
        if alerts.empty:
            st.success("Todas as bases do lote foram associadas a um código e a uma meta.")
        else:
            st.warning(f"{len(alerts)} base(s) com alerta de associação — confira a coluna Status.")
        only_alerts = st.checkbox("Mostrar apenas alertas", value=not alerts.empty)
        view = alerts if only_alerts else assoc
        st.dataframe(
            pd.DataFrame(
                {
                    "Base destino (lote)": view["base"],
                    "Código (aba base)": view["code"].astype("Int64"),
                    "Meta (aba Meta)": view["meta"].map(lambda v: "—" if pd.isna(v) else fmt(v)),
                    "Pedidos no lote": view["rows"].map(fmt),
                    "Status": view["status"],
                }
            ),
            hide_index=True,
            use_container_width=True,
        )
    st.caption(
        f"Relação de bases: {analysis.get('baseMapCount', 0)} · "
        f"metas: {analysis.get('metaMapCount', 0)} · "
        f"IDs relacionados: {analysis.get('idRelation', {}).get('ids', 0)}"
    )

st.caption(f"Fonte: {filename} · Meta: {analysis.get('goalSource', 'Dinâmica Meta')} · Gerado em {analysis.get('generatedAt', '')}")
