# Dashboard J&T Operations — explicação do código

Este documento explica os dois arquivos Python do projeto. O código
(`streamlit_app.py` e `scripts/process_data.py`) está comentado **linha a
linha**; aqui está o fluxo geral e o porquê de cada decisão.

## 1. Estrutura

```text
streamlit_app.py          → camada visual (upload, filtros, KPIs, gráficos, módulos)
scripts/process_data.py   → camada de dados (lê a planilha e calcula os indicadores)
requirements.txt          → dependências
data/                     → planilha inicial (opcional)
```

O `streamlit_app.py` nunca abre a planilha: manda os bytes para `process()`
e recebe um dicionário pronto.

## 2. A planilha (4 abas)

| Aba | Conteúdo |
|---|---|
| `inserido em lote` | 1 linha = 1 pedido escaneado (coluna **Base Destino**) |
| `base` | Nome do destino do lote → **Código** |
| `Meta` | **CÓDIGO** → meta (contagem de pedidos) |
| `Distribuição de bases` | Grupos de bases (FRANQUIAS CAP, BASE SGM, BASE INTERIOR 01…) com nome e código de cada base |

### Associação das colunas (o "PROCV")

```text
inserido em lote          base                       Meta
"Base Destino"  ───►  "Nome do destino do lote" ──►  "CÓDIGO"
(nome da base)         "Código de dois segmentos"    "Contagem..." = META
```

- O nome é comparado **sem acento e sem espaços** (`"MCJ -PA"` = `"MCJ-PA"`).
- A associação usa **dicionários**, não `merge`: nomes repetidos nas abas de
  apoio nunca duplicam pedidos (o total do lote fica sempre igual às linhas).
- Se um nome tem mais de um código, usa-se o que **existe na aba Meta**.
- Bases que compartilham o mesmo código são somadas (a meta entra uma só vez).
- A meta total é a soma de **uma meta por código**, incluindo bases com meta
  e zero pedidos (elas aparecem com 0% e entram nos ofensores negativos).

## 3. `scripts/process_data.py` — blocos

1. **`COLUMN_SYNONYMS` / `_strip_accents` / `_norm_name` / `_find_column`** —
   tolerância a variações de nome de coluna e de base.
2. **`_read_source`** — Excel (todas as abas), XLS (via `xlrd`) ou CSV/TXT/TSV
   (separador e codificação detectados).
3. **`_build_lookups`** — transforma as abas `base` e `Meta` em dicionários
   (nome→códigos, código→nomes, código→meta) e registra códigos repetidos.
4. **`_resolve_code`** — escolhe o código de uma base (prefere o que tem meta).
5. **`_parse_distribution`** — lê a aba `Distribuição de bases`: blocos de 3
   colunas `[nome | código | vazio]`; a 1ª linha é o nome do grupo e uma linha
   com nome **sem código** (ex.: `BASE INTERIOR 02`) abre um novo grupo.
6. **`_build_report`** — para a aba operacional calcula: produção por hora e
   por dia, métricas por base, **resultado de cada grupo**, **verificação da
   associação**, ranking, heatmap, origem do pedido, peso e o índice de filtro.
7. **`_group_summary`** — soma meta e realizado de um grupo, calcula % e saldo.
8. **`process`** — ponto de entrada: separa abas de apoio das operacionais
   (`base`, `Meta` e `Distribuição…` nunca viram relatório) e monta o resultado.

## 4. `streamlit_app.py` — módulos

- **Dashboard** — KPIs, produção por hora, meta, heatmap
  (com totais e botão ampliar), ranking horizontal + pódio, origem do pedido.
- **Franquias** — 10 ofensores positivos/negativos e controle de metas por base.
- **Distribuição de bases (novo)** — resumo por grupo (bases, meta, realizado,
  %, saldo), gráfico Meta × Realizado, **uma aba para cada grupo** com cartões,
  gráfico e tabela das bases, e botão para baixar tudo em CSV.
- **Relatórios** — resumo das abas e a tabela **Associação: lote → base → meta**
  com o status de cada base (OK ou alerta).

## 5. Pontos de atenção encontrados na planilha

Eles aparecem em **Relatórios → Associação** e na **Distribuição de bases**:

- `F BEL FLUVIAL-PA` tem dois códigos na aba `base` (928 e 573); a aba `Meta`
  só tem 928, que é o usado.
- O código **738** tem duas metas na aba `Meta` (3 e 967) e dois nomes no lote
  (`BRV -PA` e `F BRV 02 -PA`); as metas são somadas (970) e os pedidos juntos.
- Bases com pedidos ou meta que não estão em nenhum grupo aparecem em
  **Sem grupo** (COQ -PA, BEL -PA, PDR -PA, ANA FLUVIAL - PA, ANA -PA, F CNC-PA).
- Três bases dos grupos não têm meta nem pedidos: F CDN-PA, PRM-PA e F TMC-PA.
- Com a planilha atual, a soma dos grupos + "Sem grupo" fecha exatamente com
  o total do lote (28.099 pedidos e meta de 25.541), sem bases repetidas.

## 6. Execução local e publicação

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python3 -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Repositório (mantenha exatamente esta estrutura):

```text
streamlit_app.py
requirements.txt
scripts/process_data.py
data/<planilha>.xlsx      # opcional
```

No Streamlit Community Cloud: **Create app** → repositório e branch →
**Main file path** = `streamlit_app.py` → **Deploy**. O app carrega a planilha
mais recente de `data/` (qualquer nome) ou a enviada pelo usuário.

## 7. Privacidade

A planilha tem dados de clientes e operação. Antes de publicar, confirme que
pode ser compartilhada; para app público, remova `data/` e use só o upload;
nunca coloque senhas ou tokens no código; use repositório privado ou
autenticação para dados restritos.
