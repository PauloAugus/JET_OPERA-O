"""
scripts/process_data.py
========================

Este arquivo é o "cérebro" do dashboard J&T Operations.

`streamlit_app.py` (a camada visual) não sabe nada sobre a estrutura da
planilha: ele apenas manda os bytes do arquivo carregado para `process()`
e recebe de volta um dicionário Python comum (sem DataFrames), pronto para
virar KPI, gráfico e tabela.

Estrutura da planilha de referência "DADOS_EXPEDIÇÃO_02_base.xlsx" (4 abas):

    1. "inserido em lote"       -> 1 linha = 1 pedido escaneado. Traz a coluna
                                   "Base Destino" (nome da base).
    2. "base"                   -> tabela de apoio: Nome do destino do lote
                                   -> Código de dois segmentos.
    3. "Meta"                   -> tabela de apoio: CÓDIGO -> meta (contagem).
    4. "Distribuição de bases"  -> agrupamentos (FRANQUIAS CAP, BASE SGM,
                                   BASE INTERIOR 01...), cada um com a lista
                                   de bases e seus códigos.

ASSOCIAÇÃO (o "PROCV" do projeto):

        inserido em lote          base                 Meta
        "Base Destino"  ───►  "Nome do destino"  ──►  "CÓDIGO"
        (nome da base)         + "Código"             + "Contagem" (meta)

Cada pedido do lote é ligado, pelo NOME da base, ao código da aba "base" e,
pelo código, à meta da aba "Meta". A associação é feita com dicionários
(e não com `merge`) para que nomes/códigos repetidos nas abas de apoio
NUNCA dupliquem linhas do lote e inflem o total de pedidos.
"""

# Permite anotações de tipo modernas (`str | None`) em versões mais antigas do Python.
from __future__ import annotations

# `base64` decodifica o arquivo, que chega codificado em Base64 vindo do Streamlit.
import base64

# `io` cria um "arquivo em memória" a partir dos bytes recebidos.
import io

# `re` (expressões regulares) é usado para remover espaços dos nomes de base.
import re

# `unicodedata` remove acentos para comparar nomes/colunas de forma tolerante.
import unicodedata

# `datetime`/`timezone` geram o carimbo "Gerado em" exibido no rodapé do app.
from datetime import datetime, timezone

# `Any` é um tipo genérico usado nas anotações abaixo.
from typing import Any

# `numpy` ajuda em alguns cálculos numéricos.
import numpy as np

# `pandas` lê a planilha e faz agrupamentos/tabelas cruzadas.
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Sinônimos de nomes de coluna (campo lógico -> nomes possíveis, sem acento)
# ---------------------------------------------------------------------------
COLUMN_SYNONYMS: dict[str, list[str]] = {
    "order_id": ["numero de pedido jms", "numero do pedido", "pedido"],
    "scan_time": ["tempo de digitalizacao", "data da digitalizacao", "data/hora"],
    "destination_base": ["base destino", "base de destino"],
    "code": ["codigo", "codigo de dois segmentos"],
    "goal": ["meta", "contagem de numero de pedido jms"],
    "digitalizer": ["digitalizador"],
    "billed_weight": ["peso faturado", "peso"],
    "order_source": ["nome da origem do pedido", "origem do pedido", "origem"],
}


# ---------------------------------------------------------------------------
# 2. Funções auxiliares de texto
# ---------------------------------------------------------------------------
def _strip_accents(text: str) -> str:
    """Remove acentos e deixa em minúsculas (para comparar nomes de aba/coluna)."""
    normalized = unicodedata.normalize("NFKD", str(text))  # separa letra e acento.
    sem_acento = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return sem_acento.strip().lower()


def _norm_name(text: Any) -> str:
    """Normaliza o NOME de uma base: sem acento, sem espaços, em MAIÚSCULAS.

    Assim "MCJ -PA", "MCJ-PA" e "mcj - pa" viram a mesma chave "MCJ-PA".
    É isso que permite casar o nome do lote com o nome da aba "base" mesmo
    quando alguém digitou um espaço a mais.
    """
    normalized = unicodedata.normalize("NFKD", str(text))
    sem_acento = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", "", sem_acento).upper()


def _find_column(frame: pd.DataFrame, field: str) -> str | None:
    """Localiza no DataFrame a coluna real que corresponde a um campo lógico."""
    lookup = {_strip_accents(col): col for col in frame.columns}
    for candidate in COLUMN_SYNONYMS.get(field, []):
        if candidate in lookup:
            return lookup[candidate]
    return None  # a coluna não existe nesta planilha.


# ---------------------------------------------------------------------------
# 3. Leitura do arquivo (Excel multi-aba ou tabela única CSV/TXT/TSV)
# ---------------------------------------------------------------------------
def _read_source(filename: str, raw: bytes) -> dict[str, pd.DataFrame]:
    """Lê o arquivo enviado e devolve {nome_da_aba: DataFrame}."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    buffer = io.BytesIO(raw)  # transforma bytes em objeto "tipo arquivo".

    if extension in {"xlsx", "xlsm"}:
        return pd.read_excel(buffer, sheet_name=None, engine="openpyxl")  # todas as abas.
    if extension == "xls":
        return pd.read_excel(buffer, sheet_name=None, engine="xlrd")  # Excel antigo.

    # CSV/TXT/TSV: tabela única. Tenta UTF-8 e depois Latin-1 (Excel/Windows).
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            buffer.seek(0)
            # `sep=None` + engine python: o pandas ADIVINHA o separador.
            return {"Dados": pd.read_csv(buffer, sep=None, engine="python", encoding=encoding)}
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    return {}  # nenhuma codificação funcionou.


# ---------------------------------------------------------------------------
# 4. Tabelas de apoio: aba "base" e aba "Meta"
# ---------------------------------------------------------------------------
def _build_lookups(base_table: pd.DataFrame | None, meta_table: pd.DataFrame | None) -> dict[str, Any]:
    """Transforma as abas "base" e "Meta" em dicionários de consulta rápida."""
    name_codes: dict[str, list[int]] = {}   # nome normalizado -> códigos possíveis.
    code_names: dict[int, list[str]] = {}   # código -> nomes (como escritos na aba).
    code_meta: dict[int, float] = {}        # código -> meta (soma, se repetido).
    meta_dups: set[int] = set()             # códigos que aparecem 2+ vezes na Meta.

    if base_table is not None and base_table.shape[1] >= 2:
        names = base_table.iloc[:, 0]  # 1ª coluna: Nome do destino do lote.
        codes = pd.to_numeric(base_table.iloc[:, 1], errors="coerce")  # 2ª: código.
        for name, code in zip(names, codes):
            if pd.isna(name) or pd.isna(code):
                continue  # ignora linhas vazias.
            key, code = _norm_name(name), int(code)
            # Guarda cada código só uma vez por nome (nome repetido com o
            # mesmo código não conta como conflito).
            if code not in name_codes.setdefault(key, []):
                name_codes[key].append(code)
            if str(name).strip() not in code_names.setdefault(code, []):
                code_names[code].append(str(name).strip())

    if meta_table is not None and meta_table.shape[1] >= 2:
        codes = pd.to_numeric(meta_table.iloc[:, 0], errors="coerce")  # 1ª: CÓDIGO.
        values = pd.to_numeric(meta_table.iloc[:, 1], errors="coerce")  # 2ª: contagem.
        for code, value in zip(codes, values):
            if pd.isna(code) or pd.isna(value):
                continue  # ignora cabeçalhos/linha de total.
            code = int(code)
            if code in code_meta:
                meta_dups.add(code)  # código repetido: marca para o alerta.
            code_meta[code] = code_meta.get(code, 0.0) + float(value)  # soma as metas.

    return {
        "name_codes": name_codes,
        "code_names": code_names,
        "code_meta": code_meta,
        "meta_dups": meta_dups,
        "has_meta": meta_table is not None,
    }


def _resolve_code(norm_name: str, lookups: dict[str, Any], extra: int | None = None) -> int | None:
    """Descobre o código de uma base a partir do nome.

    Se o nome tiver mais de um código na aba "base", escolhe o primeiro que
    tenha meta na aba "Meta" (assim a base não fica sem meta por engano).
    `extra` é um código adicional informado (ex.: o da aba Distribuição).
    """
    candidates = list(lookups["name_codes"].get(norm_name, []))
    if extra is not None and extra not in candidates:
        candidates.append(extra)
    for code in candidates:
        if code in lookups["code_meta"]:
            return code
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# 5. Aba "Distribuição de bases": lê os grupos (blocos de 3 colunas)
# ---------------------------------------------------------------------------
def _parse_distribution(sheet: pd.DataFrame) -> dict[str, list[tuple[str, int]]]:
    """Lê a aba "Distribuição de bases" e devolve {grupo: [(nome, código), ...]}.

    Layout da aba: blocos lado a lado [nome | código | coluna vazia]. A 1ª
    linha do bloco é o nome do grupo; dentro do bloco, uma linha com nome mas
    SEM código (ex.: "BASE INTERIOR 02") inicia um novo grupo.
    """
    # O pandas leu a 1ª linha como cabeçalho; devolvemos ela para os dados.
    header = [None if str(c).startswith("Unnamed") else c for c in sheet.columns]
    body = sheet.copy()
    body.columns = range(body.shape[1])  # colunas numeradas 0, 1, 2...
    raw = pd.concat([pd.DataFrame([header]), body], ignore_index=True)

    # Quantos valores numéricos cada coluna tem (exceto a linha de cabeçalho).
    numeric_counts = raw.iloc[1:].apply(pd.to_numeric, errors="coerce").notna().sum()

    groups: dict[str, list[tuple[str, int]]] = {}
    for col in range(raw.shape[1] - 1):
        # Coluna de NOMES = sem números, seguida de uma coluna com números (códigos).
        if numeric_counts[col] != 0 or numeric_counts[col + 1] == 0:
            continue
        first = raw.iloc[0, col]
        current = str(first).strip() if pd.notna(first) else f"Grupo {col // 3 + 1}"
        groups.setdefault(current, [])
        for row in range(1, len(raw)):
            name, code = raw.iloc[row, col], pd.to_numeric(raw.iloc[row, col + 1], errors="coerce")
            if pd.isna(name):
                continue  # linha vazia.
            if pd.isna(code):
                current = str(name).strip()  # nome sem código = novo grupo.
                groups.setdefault(current, [])
            else:
                groups[current].append((str(name).strip(), int(code)))
    return {g: members for g, members in groups.items() if members}  # descarta grupos vazios.


# ---------------------------------------------------------------------------
# 6. Construção de um "relatório" (o que o front-end chama de `report`)
# ---------------------------------------------------------------------------
def _build_report(
    sheet_name: str,
    frame: pd.DataFrame,
    lookups: dict[str, Any],
    groups: dict[str, list[tuple[str, int]]],
) -> dict[str, Any]:
    """Transforma uma aba operacional em todos os blocos usados na tela."""
    col_destino = _find_column(frame, "destination_base")
    col_codigo = _find_column(frame, "code")
    col_meta = _find_column(frame, "goal")
    col_digitalizador = _find_column(frame, "digitalizer")
    col_tempo = _find_column(frame, "scan_time")
    col_peso = _find_column(frame, "billed_weight")
    col_origem = _find_column(frame, "order_source")

    total_rows = int(len(frame))
    total_realized = total_rows  # 1 linha = 1 pedido (a coluna "Quantidade de volumes" vem zerada).

    # --- Data/hora do escaneamento --------------------------------------
    if col_tempo:
        scan_times = pd.to_datetime(frame[col_tempo], errors="coerce")  # inválido vira NaT.
    else:
        scan_times = pd.Series([pd.NaT] * total_rows, index=frame.index)

    # --- Produção por hora ------------------------------------------------
    hours = scan_times.dt.hour.dropna()
    area_series = [{"hour": int(h), "value": int(v)} for h, v in hours.value_counts().sort_index().items()]

    # --- Produção por dia (só se o arquivo cobre mais de um dia) ---------
    days = scan_times.dt.date.dropna()
    if days.nunique() > 1:
        daily_series = [{"date": str(d), "value": int(v)} for d, v in days.value_counts().sort_index().items()]
    else:
        daily_series = []

    # =====================================================================
    # ASSOCIAÇÃO  inserido em lote  ->  base  ->  Meta
    # =====================================================================
    names_raw = frame[col_destino].fillna("").astype(str).str.strip() if col_destino else pd.Series([""] * total_rows, index=frame.index)
    row_norm = names_raw.map(_norm_name)  # nome normalizado de cada pedido.

    inline_code_meta: dict[int, float] = {}
    if col_codigo and col_meta:
        # Planilha antiga: o lote JÁ traz "código" e "meta" pré-unidos.
        # Aproveitamos esses valores em vez de refazer a associação.
        inline = pd.DataFrame(
            {
                "n": row_norm,
                "c": pd.to_numeric(frame[col_codigo], errors="coerce"),
                "m": pd.to_numeric(frame[col_meta], errors="coerce"),
            }
        ).dropna(subset=["c"])
        name_code = {n: int(c) for n, c in inline.groupby("n")["c"].first().items()}
        inline_code_meta = {int(c): float(m) for c, m in inline.groupby("c")["m"].max().dropna().items()}
        for n in row_norm.unique():  # nomes sem código na linha: tenta pelas abas de apoio.
            name_code.setdefault(n, _resolve_code(n, lookups))
    else:
        # Planilha nova: associa pelo NOME -> código (aba base) -> meta (aba Meta).
        name_code = {n: _resolve_code(n, lookups) for n in row_norm.unique()}

    # Meta de cada código: aba "Meta" (preferencial) + valores já presentes no lote.
    code_meta: dict[int, float] = dict(lookups["code_meta"])
    for code, value in inline_code_meta.items():
        code_meta.setdefault(code, value)

    def key_of(norm: str) -> str:
        """Chave de agrupamento: "c<código>" (bases com o mesmo código somam
        juntas, evitando contar a mesma meta duas vezes) ou "n<nome>" quando
        o nome não tem código."""
        code = name_code.get(norm)
        return f"c{code}" if code is not None else f"n{norm}"

    row_key = row_norm.map(key_of)  # chave de cada pedido.

    # Pedidos realizados por chave e nomes (como escritos) de cada chave.
    realized_by_key = row_key.value_counts().to_dict()
    name_counts = pd.DataFrame({"key": row_key, "name": names_raw}).groupby(["key", "name"], sort=False).size()
    names_by_key: dict[str, list[str]] = {}
    for (key, name), _ in name_counts.sort_values(ascending=False).items():
        names_by_key.setdefault(key, []).append(name)  # mais volumoso primeiro.

    def label_of(key: str) -> str:
        """Texto exibido para a base (une nomes que compartilham o código)."""
        names = names_by_key.get(key)
        if names:
            return " + ".join(names[:3])
        if key.startswith("c"):  # código só existente na aba Meta (sem pedidos).
            known = lookups["code_names"].get(int(key[1:]), [])
            return " + ".join(known[:2]) if known else f"Código {key[1:]}"
        return key[1:]

    # --- Métricas por base (inclui bases com meta e ZERO pedidos) --------
    all_keys = set(realized_by_key) | {f"c{c}" for c in code_meta}
    base_metrics: list[dict[str, Any]] = []
    metrics_by_key: dict[str, dict[str, Any]] = {}  # chave -> métrica (usado nos grupos).
    for key in all_keys:
        code = int(key[1:]) if key.startswith("c") else None
        realized = int(realized_by_key.get(key, 0))
        meta_value = float(code_meta.get(code, 0.0)) if code is not None else 0.0
        metrics_by_key[key] = {
            "base": label_of(key),
            "code": code,
            "meta": meta_value,
            "realized": realized,
            "percent": (realized / meta_value * 100) if meta_value else None,
        }
    base_metrics = sorted(metrics_by_key.values(), key=lambda item: -item["realized"])
    # A meta total é a soma de UMA meta por código (nunca repetida por pedido).
    total_goal = float(sum(m["meta"] for m in base_metrics if m["code"] is not None))

    # =====================================================================
    # DISTRIBUIÇÃO DE BASES: resultado de cada grupo, separadamente
    # =====================================================================
    distribution = None
    if groups:
        grouped_keys: set[str] = set()
        key_to_groups: dict[str, list[str]] = {}
        group_results: list[dict[str, Any]] = []
        for group, members in groups.items():
            seen: set[str] = set()
            bases: list[dict[str, Any]] = []
            for name, stated_code in members:
                norm = _norm_name(name)
                code = name_code.get(norm)  # 1º: código usado no lote.
                if code is None:
                    code = _resolve_code(norm, lookups, stated_code)  # 2º: abas de apoio/Distribuição.
                key = f"c{code}" if code is not None else f"n{norm}"
                if key in seen:
                    continue  # mesma base repetida no grupo: conta uma vez.
                seen.add(key)
                grouped_keys.add(key)
                key_to_groups.setdefault(key, []).append(group)
                realized = int(realized_by_key.get(key, 0))
                meta_value = float(code_meta.get(code, 0.0)) if code is not None else 0.0
                bases.append(
                    {
                        "base": name,
                        "code": code if code is not None else stated_code,
                        "meta": meta_value,
                        "realized": realized,
                        "percent": (realized / meta_value * 100) if meta_value else None,
                    }
                )
            group_results.append(_group_summary(group, bases))

        # Bases com pedidos ou meta que NÃO estão em nenhum grupo.
        ungrouped_bases = [
            {"base": m["base"], "code": m["code"], "meta": m["meta"], "realized": m["realized"], "percent": m["percent"]}
            for key, m in metrics_by_key.items()
            if key not in grouped_keys and (m["realized"] or m["meta"])
        ]
        # Bases listadas em mais de um grupo (somam nos dois grupos).
        overlaps = [
            {"base": label_of(key), "groups": gs} for key, gs in key_to_groups.items() if len(gs) > 1
        ]
        distribution = {
            "groups": group_results,
            "ungrouped": _group_summary("Sem grupo", ungrouped_bases) if ungrouped_bases else None,
            "overlaps": overlaps,
        }

    # =====================================================================
    # VERIFICAÇÃO DA ASSOCIAÇÃO (aba "Relatórios")
    # =====================================================================
    users_by_code: dict[int, set[str]] = {}
    for norm, code in name_code.items():
        if code is not None:
            users_by_code.setdefault(code, set()).add(norm)
    associations: list[dict[str, Any]] = []
    display_counts = names_raw.value_counts()
    for display, count in display_counts.items():
        norm = _norm_name(display)
        code = name_code.get(norm)
        candidates = lookups["name_codes"].get(norm, [])
        issues: list[str] = []
        if code is None:
            issues.append("Sem código na aba base")
        elif code not in code_meta:
            issues.append("Sem meta na aba Meta")
        if len(candidates) > 1:
            issues.append(f"Nome com {len(candidates)} códigos na aba base ({', '.join(map(str, candidates))}); usado {code}")
        if code is not None and len(users_by_code.get(code, ())) > 1:
            issues.append("Código compartilhado por mais de um nome do lote (somados)")
        if code in lookups["meta_dups"]:
            issues.append("Código repetido na aba Meta (valores somados)")
        associations.append(
            {
                "base": display or "(vazio)",
                "code": code,
                "meta": code_meta.get(code) if code is not None else None,
                "rows": int(count),
                "status": "OK" if not issues else "; ".join(issues),
            }
        )
    for code in sorted(code_meta):  # metas de códigos sem nenhum pedido no lote.
        if f"c{code}" not in realized_by_key:
            associations.append(
                {
                    "base": label_of(f"c{code}"),
                    "code": code,
                    "meta": code_meta[code],
                    "rows": 0,
                    "status": "Meta sem pedidos no lote",
                }
            )

    # --- Ranking de digitalizadores ---------------------------------------
    if col_digitalizador:
        digitalizer_ranking = [{"label": str(k), "value": int(v)} for k, v in frame[col_digitalizador].value_counts().items()]
    else:
        digitalizer_ranking = []

    # --- Heatmap digitalizador x hora -------------------------------------
    heatmap: list[dict[str, Any]] = []
    if col_digitalizador and not hours.empty:
        heat = pd.DataFrame({"digitalizer": frame.loc[hours.index, col_digitalizador], "hour": hours})
        for (digitalizer, hour), value in heat.groupby(["digitalizer", "hour"]).size().items():
            heatmap.append({"digitalizer": str(digitalizer), "hour": int(hour), "value": int(value)})

    # --- Origem do pedido e peso faturado ----------------------------------
    origin_breakdown: list[dict[str, Any]] = []
    if col_origem:
        origin_counts = frame[col_origem].fillna("Não informado").value_counts().head(10)
        origin_breakdown = [{"label": str(k), "value": int(v)} for k, v in origin_counts.items()]
    weight_total = float(pd.to_numeric(frame[col_peso], errors="coerce").fillna(0).sum()) if col_peso else 0.0

    # --- Índice de filtro (uma linha por pedido) ----------------------------
    row_code = row_norm.map(name_code)  # código de cada pedido (ou NaN).
    filter_index = pd.DataFrame(
        {
            "base": row_key.map(label_of),  # mesmo rótulo usado nas métricas por base.
            "code": row_code,
            "digitalizer": frame[col_digitalizador].fillna("").astype(str) if col_digitalizador else "",
            "meta": row_code.map(code_meta).fillna(0.0),
            "volume": 1,  # cada linha conta como 1 pedido.
            "weight": pd.to_numeric(frame[col_peso], errors="coerce").fillna(0.0) if col_peso else 0.0,
            # Texto de busca livre. `.fillna("")` ANTES do astype(str) é
            # essencial: sem isso o NaN continua float e quebra o join.
            "search": frame.fillna("").astype(str).agg(" ".join, axis=1),
        }
    )

    return {
        "sheet": sheet_name,
        "totalRows": total_rows,
        "totalRealized": total_realized,
        "totalGoal": total_goal,
        "baseMetrics": base_metrics,
        "digitalizerRanking": digitalizer_ranking,
        "areaSeries": area_series,
        "dailySeries": daily_series,
        "heatmap": heatmap,
        "originBreakdown": origin_breakdown,
        "weightTotal": weight_total,
        "distribution": distribution,
        "associations": associations,
        "filterIndex": filter_index.to_dict("records"),
    }


def _group_summary(name: str, bases: list[dict[str, Any]]) -> dict[str, Any]:
    """Soma meta e realizado das bases de um grupo e calcula % e saldo."""
    meta_value = float(sum(b["meta"] for b in bases))
    realized = int(sum(b["realized"] for b in bases))
    return {
        "group": name,
        "bases": sorted(bases, key=lambda b: -b["realized"]),  # maiores primeiro.
        "count": len(bases),
        "meta": meta_value,
        "realized": realized,
        "percent": (realized / meta_value * 100) if meta_value else None,
        "balance": realized - meta_value,
    }


# ---------------------------------------------------------------------------
# 7. Ponto de entrada usado pelo streamlit_app.py
# ---------------------------------------------------------------------------
def process(payload: dict[str, Any]) -> dict[str, Any]:
    """Recebe {filename, content (base64), size} e devolve o dicionário de análise."""
    filename = payload.get("filename", "")
    try:
        raw = base64.b64decode(payload["content"])  # Base64 -> bytes do arquivo.
    except Exception:
        return {"error": "Não foi possível ler o conteúdo do arquivo enviado."}

    sheets = _read_source(filename, raw)
    if not sheets:
        return {"error": "Formato de arquivo não reconhecido. Envie CSV, TXT, TSV, XLS ou XLSX."}

    # Separa as abas de apoio ("base", "Meta", "Distribuição de bases") das operacionais.
    base_table = meta_table = dist_table = None
    operational: dict[str, pd.DataFrame] = {}
    for name, frame in sheets.items():
        key = _strip_accents(name)
        if key == "base":
            base_table = frame
        elif key == "meta":
            meta_table = frame
        elif key.startswith("distribuicao"):
            dist_table = frame
        else:
            operational[name] = frame
    if not operational:
        return {"error": "Nenhuma aba com dados operacionais foi encontrada no arquivo."}

    lookups = _build_lookups(base_table, meta_table)
    groups = _parse_distribution(dist_table) if dist_table is not None else {}

    reports = [_build_report(name, frame, lookups, groups) for name, frame in operational.items()]
    primary = max(reports, key=lambda r: r["totalRows"])  # aba com mais linhas.

    # Pedidos com "Número do ID" preenchido (indicador informativo).
    id_count = 0
    for frame in operational.values():
        for candidate in ("Número do ID", "numero do id"):
            if candidate in frame.columns:
                id_count += int(frame[candidate].notna().sum())
                break

    return {
        "reports": reports,
        "primarySheet": primary["sheet"],
        "metaTotal": primary["totalGoal"],
        "totalGoal": primary["totalGoal"],
        "goalSource": "Abas base → Meta (por código)" if lookups["has_meta"] else "Coluna 'meta' da planilha",
        "generatedAt": datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        "baseMapCount": len(lookups["name_codes"]),
        "metaMapCount": len(lookups["code_meta"]),
        "groupCount": len(groups),
        "idRelation": {"ids": id_count},
    }
