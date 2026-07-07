"""
net60 — Análise Técnica de Acessibilidade Digital (WCAG)
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
import pandas as pd
import plotly.express as px
import streamlit as st

# =============================================================================
# IMPORT DO ANALYZER INTEGRADO (WCAG + evidências ricas)
# =============================================================================
from analisador import analyze_site  # ou: from analyzer_wcag_integrated import analyze_site

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA
# =============================================================================
st.set_page_config(
    page_title="net60",
    page_icon="👴🏻",
    layout="wide",
)
import os
import subprocess
import streamlit as st

# ============================================================
# INSTALAÇÃO DO NAVEGADOR PLAYWRIGHT (necessário no Streamlit Cloud)
# ============================================================
def ensure_playwright_browser():
    """Tenta instalar o Chromium se ele não existir (útil no deploy em nuvem)."""
    playwright_path = os.path.expanduser("~/.cache/ms-playwright")
    
    # Verifica se já existe algum chromium instalado
    if os.path.exists(playwright_path):
        chromium_dirs = [d for d in os.listdir(playwright_path) if "chromium" in d.lower()]
        if chromium_dirs:
            return  # Já está instalado

    try:
        with st.spinner("Instalando navegador Chromium (primeira execução)..."):
            subprocess.run(
                ["playwright", "install", "chromium"],
                check=True,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutos
            )
            st.success("Navegador Chromium instalado com sucesso!")
    except subprocess.TimeoutExpired:
        st.error("Tempo esgotado ao instalar o Chromium. Tente novamente ou use outra plataforma.")
    except Exception as e:
        st.error(f"Erro ao instalar o navegador: {str(e)}")


# Chame essa função no início da aplicação
ensure_playwright_browser()

if "urls_to_analyze" not in st.session_state:
    st.session_state["urls_to_analyze"] = []
if "df_results" not in st.session_state:
    st.session_state["df_results"] = None


def _fix_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u


def _classificar_score(score: float | None) -> dict:
    """Classificação simples e clara baseada no score WCAG (0-100)."""
    if score is None:
        return {"classificacao": "Não avaliável", "nivel_exclusao": "Falha na coleta ou análise"}
    if score >= 85:
        return {"classificacao": "Excelente", "nivel_exclusao": "Baixo risco de exclusão digital"}
    elif score >= 70:
        return {"classificacao": "Bom", "nivel_exclusao": "Risco moderado"}
    elif score >= 55:
        return {"classificacao": "Regular", "nivel_exclusao": "Risco significativo de exclusão"}
    else:
        return {"classificacao": "Ruim", "nivel_exclusao": "Alto risco de exclusão digital"}


# =============================================================================
# CABEÇALHO
# =============================================================================
st.markdown(
    """
<div style="background: linear-gradient(90deg, #1a237e 0%, #3949ab 100%);
            padding: 1.2rem; border-radius: 10px; color: white; text-align: center; margin-bottom: 1.5rem;">
    <h1 style="margin:0;">net60 — Análise Técnica de Acessibilidade WCAG</h1>
    <p style="margin:0.3rem 0 0; opacity:0.9;">axe-core + Playwright • Evidências HTML por violação • Score com penalidade escalonada</p>
</div>
""",
    unsafe_allow_html=True,
)

# =============================================================================
# SIDEBAR — CONFIGURAÇÕES (SIMPLIFICADA — SEM LLM)
# =============================================================================
with st.sidebar:
    st.header("⚙️ Configurações")
    max_workers = st.slider("Requisições paralelas", min_value=1, max_value=5, value=3, help="use valores menores para listas > 200")
    st.markdown("---")
    st.caption(
        """# net60
**Análise técnica de acessibilidade digital para o público idoso**

Ferramenta baseada em **WCAG 2.1/2.2** que utiliza o motor **axe-core** executado em navegador real via Playwright.

**Indicadores Avaliados**
- Contraste de cores
- Tamanhos de alvos de toque
- Rotulagem de campos
- Redimensionamento de viewport
- Suporte a autocomplete

**Metodologia**
Pontuação calculada por penalidade escalonada, considerando não apenas a existência, mas também o volume de violações — gerando scores mais precisos e justos.

**Relatórios e Interface**
Resultados apresentados com gráficos comparativos (histograma de score e gráfico pizza das violações) e relatório detalhado por URL, incluindo os trechos de código HTML das não conformidades para facilitar a priorização das correções."""
    )

# =============================================================================
# 1. INTERFACE — CARREGAMENTO DE URLs (MANTIDO)
# =============================================================================
st.header("1. Interface — Carregar URLs")

col1, col2 = st.columns([3, 2])

with col1:
    uploaded = st.file_uploader(
        "📤 Carregar CSV ou Excel com URLs",
        type=["csv", "xlsx", "xls"],
        help="O arquivo deve conter uma coluna com URLs (nome: url, link, site ou primeira coluna)",
    )
    if uploaded is not None:
        try:
            if uploaded.name.lower().endswith((".xlsx", ".xls")):
                df_in = pd.read_excel(uploaded)
            else:
                df_in = pd.read_csv(uploaded)

            cols_lower = {str(c).lower().strip(): c for c in df_in.columns}
            url_col = None
            for cand in ["url", "link", "site", "website", "endereco", "address"]:
                if cand in cols_lower:
                    url_col = cols_lower[cand]
                    break
            if url_col is None:
                url_col = df_in.columns[0]

            raw_urls = df_in[url_col].dropna().astype(str).str.strip().tolist()
            urls_fixed = [_fix_url(u) for u in raw_urls if len(u) > 5]
            urls_fixed = list(dict.fromkeys(urls_fixed))
            st.session_state["urls_to_analyze"] = urls_fixed
            st.success(f"✅ {len(urls_fixed)} URLs carregadas (coluna '{url_col}')")
        except Exception as e:
            st.error(f"❌ Erro ao processar arquivo: {e}")

with col2:
    st.markdown("**Ou cole URLs manualmente (uma por linha):**")
    manual_text = st.text_area(
        "URLs",
        height=120,
        placeholder="https://www.gov.br\nhttps://www.ibge.gov.br\nhttps://www.bb.com.br",
        label_visibility="collapsed",
    )
    if st.button("➕ Adicionar URLs", use_container_width=True):
        if manual_text.strip():
            manual_list = [line.strip() for line in manual_text.splitlines() if line.strip()]
            manual_fixed = [_fix_url(u) for u in manual_list if len(u) > 5]
            current = st.session_state.get("urls_to_analyze", [])
            merged = list(dict.fromkeys(current + manual_fixed))
            st.session_state["urls_to_analyze"] = merged
            st.success(f"Total atualizado: {len(merged)} URLs")
            st.rerun()

# Lista atual (editável)
if st.session_state["urls_to_analyze"]:
    with st.expander(f"📋 Lista atual ({len(st.session_state['urls_to_analyze'])} URLs) — clique para editar", expanded=False):
        current_list = "\n".join(st.session_state["urls_to_analyze"])
        edited_text = st.text_area("Editar URLs (uma por linha)", value=current_list, height=180)
        if st.button("💾 Salvar alterações na lista"):
            new_list = [line.strip() for line in edited_text.splitlines() if line.strip()]
            new_list = [_fix_url(u) for u in new_list if len(u) > 5]
            st.session_state["urls_to_analyze"] = list(dict.fromkeys(new_list))
            st.success("Lista atualizada!")
            st.rerun()

# =============================================================================
# 2. ANÁLISE / PROCESSAMENTO (ADAPTADO PARA O NOVO ANALYZER)
# =============================================================================
st.header("2. Análise e Processamento")

urls_atuais = st.session_state.get("urls_to_analyze", [])
n = len(urls_atuais)

if n == 0:
    st.info("⬆️ Carregue URLs na seção acima para iniciar a análise.")
else:
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.metric("URLs a analisar", n)
    with col_info2:
        tempo_est = round(n * 2.5 / max_workers, 0)  # axe é mais pesado que requests simples
        st.metric("Tempo estimado", f"~{tempo_est}s")

    if st.button("🚀 Iniciar Análise WCAG", type="primary", use_container_width=True):
        progress = st.progress(0.0, text="Preparando análise WCAG...")
        status_box = st.empty()
        resultados = []
        t0 = time.time()


        def _analisar_um(url: str) -> dict:
            t_url = time.time()
            try:
                res = analyze_site(url)

                if res.get("status") != "success":
                    return {
                        "url": url,
                        "score_total": None,
                        "classificacao": "Não avaliável",
                        "nivel_exclusao": "Falha na análise",
                        "tempo_s": round(time.time() - t_url, 1),
                        "status": res.get("status", "erro"),
                        "erro_msg": res.get("error_message", "Erro desconhecido"),
                    }

                score = res["score"]
                classificacao = _classificar_score(score)

                return {
                    "url": url,
                    "score_total": score,
                    "classificacao": classificacao["classificacao"],
                    "nivel_exclusao": classificacao["nivel_exclusao"],
                    "tempo_s": round(time.time() - t_url, 1),
                    "status": "sucesso",
                    "evidences": res.get("evidences", []),
                    "summary": res.get("summary", {}),
                }

            except Exception as exc:
                return {
                    "url": url,
                    "score_total": None,
                    "classificacao": "Erro",
                    "nivel_exclusao": "Falha",
                    "tempo_s": round(time.time() - t_url, 1),
                    "status": "erro",
                    "erro_msg": str(exc)[:150],
                }


        # ====================== EXECUÇÃO (VERSÃO MAIS SEGURA) ======================

        resultados = []


        print("=== INICIANDO PROCESSAMENTO ===")
        print(f"Quantidade de URLs que serão enviadas ao executor: {len(urls_atuais)}")
        print(f"URLs únicas: {len(set(urls_atuais))}")
        # Execução paralela
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_analisar_um, u): u for u in urls_atuais}
            concluidos = 0
            for future in as_completed(future_map):
                res = future.result()
                resultados.append(res)
                concluidos += 1
                pct = concluidos / n
                progress.progress(pct, text=f"Processando {concluidos}/{n} — {res['url'][:65]}")
                status_box.caption(
                    f"⏱️ Decorrido: {time.time() - t0:.0f}s | "
                    f"Sucessos: {sum(r.get('status') == 'sucesso' for r in resultados)} | "
                    f"Falhas: {sum(r.get('status') in ('falha_coleta', 'erro') for r in resultados)}"
                )

        df_final = pd.DataFrame(resultados)
        st.session_state["df_results"] = df_final
        st.session_state["analysis_time"] = round(time.time() - t0, 1)
        progress.progress(1.0, text="Análise WCAG concluída!")
        status_box.success(f"✅ {concluidos} URLs processadas em {st.session_state['analysis_time']}s")
        time.sleep(0.6)
        st.rerun()

# =============================================================================
# 3. APRESENTAÇÃO DE RESULTADOS (MANTIDO + ADAPTADO)
# =============================================================================
st.header("3. Apresentação de Resultados")

df_res = st.session_state.get("df_results")

if df_res is None or df_res.empty:
    st.info("Execute a análise na seção 2 para visualizar os resultados.")
else:
    # ─────────────────────────────────────────────────────────────────────────
    # Resumo Executivo
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("Resumo Executivo")
    c1, c2, c3, c4 = st.columns(4)
    total = len(df_res)
    sucessos = len(df_res[df_res["status"] == "sucesso"]) if "status" in df_res.columns else 0
    falhas = len(df_res[df_res["status"].isin(["falha_coleta", "erro"])]) if "status" in df_res.columns else 0

    c1.metric("Total de URLs", total)
    c2.metric("Analisadas com sucesso", sucessos)
    c3.metric("Falhas / Erros", falhas)

    if sucessos > 0 and "score_total" in df_res.columns:
        media = df_res[df_res["status"] == "sucesso"]["score_total"].mean()
        c4.metric("Score médio (sucessos)", f"{media:.1f} / 100")
    else:
        c4.metric("Score médio (sucessos)", "—")

    # ─────────────────────────────────────────────────────────────────────────
    # Tabela Principal
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("Tabela de Resultados")
    cols_mostrar = ["url", "score_total", "classificacao", "nivel_exclusao", "status", "tempo_s"]
    if "erro_msg" in df_res.columns:
        cols_mostrar.append("erro_msg")

    df_show = df_res[cols_mostrar].copy()

    if "status" in df_show.columns:
        mask_falha = df_show["status"] != "sucesso"
        df_show.loc[mask_falha, "classificacao"] = df_show.loc[mask_falha, "classificacao"].fillna("Não avaliável")
        df_show.loc[mask_falha, "nivel_exclusao"] = df_show.loc[mask_falha, "nivel_exclusao"].fillna("Falha na coleta/análise")

    if "score_total" in df_show.columns:
        df_show = df_show.sort_values(
            by="score_total",
            ascending=False,
            key=lambda x: pd.to_numeric(x, errors="coerce")
        )

    st.dataframe(df_show, use_container_width=True, hide_index=True)


    st.subheader("📊 Visualização dos Resultados")

    col_graf1, col_graf2 = st.columns(2)

    # ====================== GRÁFICO 1: Histograma de Scores ======================
    with col_graf1:
        st.markdown("**Distribuição dos Scores WCAG**")

        if sucessos > 0 and "score_total" in df_res.columns:
            df_ok = df_res[df_res["status"] == "sucesso"]

            fig_hist = px.histogram(
                df_ok,
                x="score_total",
                nbins=min(20, max(5, len(df_ok) // 3)),
                title="Distribuição dos Scores (0–100)",
                labels={"score_total": "Score WCAG", "count": "Quantidade de Sites"},
                color_discrete_sequence=["#3949ab"],
            )
            fig_hist.update_layout(
                bargap=0.1,
                showlegend=False,
                height=380,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            st.plotly_chart(fig_hist, use_container_width=True)
        else:
            st.info("Sem dados de score para exibir.")

    # ====================== GRÁFICO 2: Pizza de Violações ======================
    with col_graf2:
        st.markdown("**Distribuição de Violações por Indicador WCAG**")

        if sucessos > 0:
            all_counts = Counter()
            for _, row in df_res.iterrows():
                if row.get("status") == "sucesso":
                    summary = row.get("summary", {})
                    counts = summary.get("counts_by_indicator", {})
                    if isinstance(counts, dict):
                        all_counts.update(counts)

            if all_counts:
                df_viol = pd.DataFrame(
                    [{"Indicador": k, "Ocorrências": v} for k, v in all_counts.items()]
                ).sort_values("Ocorrências", ascending=False)

                fig_pie = px.pie(
                    df_viol,
                    names="Indicador",
                    values="Ocorrências",
                    title="Proporção de Violações por Tipo de Indicador WCAG",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set3,  # Cores variadas e mais amigáveis
                )
                fig_pie.update_traces(
                    textposition='inside',
                    textinfo='percent+label',
                    hovertemplate="<b>%{label}</b><br>Ocorrências: %{value}<br>Percentual: %{percent}"
                )
                fig_pie.update_layout(
                    height=380,
                    margin=dict(l=20, r=20, t=40, b=20),
                    showlegend=True
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Nenhuma violação WCAG detectada nos sites analisados.")
        else:
            st.info("Sem dados de violações para exibir.")
    # ─────────────────────────────────────────────────────────────────────────
    # Classificação dos Sites
    # ─────────────────────────────────────────────────────────────────────────
    if "classificacao" in df_res.columns:
        st.subheader("Classificação dos Sites (WCAG)")
        df_class = df_res[df_res["status"] == "sucesso"]
        if not df_class.empty:
            resumo_class = (
                df_class.groupby("classificacao")
                .size()
                .reset_index(name="Quantidade")
                .sort_values("Quantidade", ascending=False)
            )
            st.dataframe(resumo_class, use_container_width=True, hide_index=True)

    # ═══════════════════════════════════════════════════════════════════════════
    # RELATÓRIO DETALHADO - EVIDÊNCIAS HTML POR URL (CORRIGIDO)
    # ═══════════════════════════════════════════════════════════════════════════
    st.subheader("📋 Relatório Detalhado por URL e Evidências de Violação")

    df_sucesso = df_res[df_res["status"] == "sucesso"]

    if df_sucesso.empty:
        st.info("Nenhum site foi analisado com sucesso.")
    else:
        for _, row in df_sucesso.iterrows():
            url = row["url"]
            score = row["score_total"]
            classificacao = row["classificacao"]
            evidences = row.get("evidences", [])
            summary = row.get("summary", {})

            if not evidences:
                continue

            with st.expander(f"🔗 {url}  |  Score: {score}  |  {classificacao}", expanded=False):

                # Resumo de violações
                counts = summary.get("counts_by_indicator", {})
                if counts:
                    st.markdown("**Resumo de Violações por Indicador:**")
                    resumo_df = pd.DataFrame(
                        [{"Indicador": k, "Ocorrências": v} for k, v in counts.items()]
                    ).sort_values("Ocorrências", ascending=False)
                    st.dataframe(resumo_df, use_container_width=True, hide_index=True)

                st.markdown("---")
                st.markdown("**Evidências HTML das Violações:**")

                # Agrupar evidências por indicador
                evidencias_por_indicador = defaultdict(list)
                for ev in evidences:
                    indicador = ev.get("indicator", "desconhecido")
                    html = ev.get("html_snippet", "")
                    if html:
                        evidencias_por_indicador[indicador].append(html)

                # Mostrar evidências por indicador
                for indicador, trechos in evidencias_por_indicador.items():
                    st.markdown(f"**{indicador.replace('_', ' ').title()}** ({len(trechos)} ocorrência(s))")

                    for i, trecho in enumerate(trechos[:5], 1):  # Mostra no máximo 5 por indicador
                        st.code(trecho, language="html")

                    if len(trechos) > 5:
                        st.caption(f"... e mais {len(trechos) - 5} ocorrências similares.")

                    st.markdown("")


    # ─────────────────────────────────────────────────────────────────────────
    # Exportação
    # ─────────────────────────────────────────────────────────────────────────
    st.subheader("Exportar")
    csv_bytes = df_res.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Baixar CSV completo com resultados e evidências",
        data=csv_bytes,
        file_name="net60_wcag_resultados.csv",
        mime="text/csv",
        use_container_width=True,
    )

# =============================================================================
# RODAPÉ
# =============================================================================
st.markdown("---")
st.caption(
    "net60 • Análise Técnica WCAG 2.1/2.2 com axe-core • "
    "Evidências HTML extraídas por violação • "
    "Score com penalidade escalonada por volume de ocorrências • "
    "Interface otimizada para relatórios de acessibilidade digital."
)
