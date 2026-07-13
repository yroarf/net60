"""
```python
# =============================================================================
# analyze_site.py
# =============================================================================
#
# Módulo principal de análise técnica de acessibilidade digital (WCAG 2.1/2.2).
#
# VISÃO GERAL
# -----------
# Utiliza Playwright + axe-core para executar análises em navegador real,
# garantindo resultados confiáveis sobre o HTML renderizado e com suporte
# a JavaScript moderno.
#
# ESTRUTURA DO MÓDULO
# -------------------
# 1. Configuração Inicial
#    Ajusta a política de loop de eventos para compatibilidade com Windows
#    (WindowsProactorEventLoopPolicy), assegurando suporte a subprocessos.
#
# 2. Pesos e Penalidades (PESOS_WCAG)
#    Define os 8 indicadores WCAG priorizados e seus respectivos pesos.
#    A função _get_volume_multiplier() aplica penalidade escalonada conforme
#    o volume de violações (multiplicador de 1.0 até 2.5).
#
# 3. Mapeamento de Violações (_map_axe_violations)
#    Transforma o resultado bruto do axe-core em evidências estruturadas,
#    contendo: html_snippet, seletor, impacto, descrição, sumário de falha
#    e campos adicionais prontos para geração de relatórios.
#    Apenas regras presentes em PESOS_WCAG são processadas.
#
# 4. Função Principal (analyze_site)
#    Orquestra a análise em três etapas:
#    - Navegação real via Playwright + Chromium headless
#    - Injeção e execução do axe-core no DOM renderizado
#    - Cálculo do score com penalidade escalonada (cap máximo: 85 pontos)
#
# 5. Retorno Estruturado
#    Retorna score, evidências detalhadas e um bloco 'summary' com contagens
#    por indicador, breakdown de penalidade por regra e flag 'cap_applied'.
#
# 6. Tratamento de Erros
#    Erros de navegação, falhas do Playwright e exceções inesperadas são
#    capturados e retornados em formato padronizado (status + error_message),
#    sem interromper o fluxo da aplicação.
#
# INDICADORES AVALIADOS
# ---------------------
#    - meta-viewport            (peso: 0.19)
#    - color-contrast           (peso: 0.17)
#    - label                    (peso: 0.15)

#    Os indicadores abaixo foram descartados do processamento após a realização de testes
#    de identificação com páginas de HTML de teste. 
#    - aria-input-field-name    (peso: 0.13)
#    - target-size              (peso: 0.13)
#    - color-contrast-enhanced  (peso: 0.10)
#    - target-size-enhanced     (peso: 0.08)
#    - autocomplete-valid       (peso: 0.05)
#
# =============================================================================
```


"""

import sys
import asyncio

if sys.platform.startswith("win"):
    # Usa o ProactorEventLoop, que suporta subprocessos corretamente no Windows
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.sync_api import sync_playwright, Error as PlaywrightError
from collections import Counter
from typing import List, Dict, Any
import re

# =============================================================================
# PESOS E FUNÇÕES DE PENALIDADE (inalterados do Código 1 original)
# =============================================================================

PESOS_WCAG = {
    "meta-viewport": 0.38,
    "color-contrast": 0.33,
    "label": 0.29,
    # "aria-input-field-name": 0.13,
    # "target-size": 0.13,
    # "color-contrast-enhanced": 0.10,
    # "target-size-enhanced": 0.08,
    # "autocomplete-valid": 0.05,
}


def _get_volume_multiplier(count: int) -> float:
    """Penalidade escalonada por volume de evidências (lógica original preservada)."""
    if count <= 5:
        return 1.0
    elif count <= 15:
        return 1.5
    elif count <= 30:
        return 2.0
    else:
        return 2.5


# =============================================================================
# MAPEAMENTO E EXTRAÇÃO ENRIQUECIDA DE EVIDÊNCIAS
# =============================================================================

def _map_axe_violations(axe_results: dict) -> List[Dict[str, Any]]:
    """
    Mapeia violações do axe-core para evidências estruturadas e ricas para relatórios.

    Cada evidência agora contém:
    - Campos originais do Código 1
    - Campos extras do axe (help, helpUrl, failureSummary)
    - Estrutura inspirada em extratores especializados (Código 3):
      "tipo", "elemento", "detalhe" — prontos para exibição em relatórios
    """
    issues = []
    if not axe_results or "violations" not in axe_results:
        return issues

    rule_mapping = {
        "color-contrast": "contraste_textos_botoes_icones_links",
        "color-contrast-enhanced": "contraste_textos_botoes_icones_links",
        "target-size": "tamanhos_alvos_toque",
        "target-size-enhanced": "tamanhos_alvos_toque",
        "label": "prevencao_descricao_erros",
        "aria-input-field-name": "prevencao_descricao_erros",
        "meta-viewport": "redimensionamento_reflow",
        "autocomplete-valid": "identificacao_autocomplete",
    }

    for violation in axe_results.get("violations", []):
        rule_id = violation.get("id", "")
        if rule_id not in PESOS_WCAG:
            continue  # Respeita mandatório: só indicadores do Código 1

        indicator = rule_mapping.get(rule_id, rule_id)

        help_text = violation.get("help", "")
        help_url = violation.get("helpUrl", "")
        impact = violation.get("impact", "")
        description = violation.get("description", "")

        for node in violation.get("nodes", []):
            html_snippet = node.get("html", "")[:600]  # Trecho do elemento violador (enriquecido)
            target = node.get("target", [""])[0] if node.get("target") else ""
            failure_summary = node.get("failureSummary", "")

            evidence = {
                # === Campos originais do Código 1 ===
                "indicator": indicator,
                "rule_id": rule_id,
                "html_snippet": html_snippet,
                "selector": target,
                "impact": impact,
                "description": description,

                # === Campos extras do axe-core (úteis para relatório) ===
                "help": help_text,
                "help_url": help_url,
                "failure_summary": failure_summary,

                # === Estrutura de extração inspirada no Código 3 (para relatórios) ===
                "tipo": f"violacao_wcag_{rule_id}",
                "elemento": html_snippet,
                "detalhe": (
                    f"{help_text or description} "
                    f"| Impacto: {impact}. "
                    f"Seletor: {target or 'N/A'}"
                ).strip(),
            }
            issues.append(evidence)

    return issues


# =============================================================================
# FUNÇÃO PRINCIPAL
# =============================================================================

def analyze_site(url: str) -> Dict[str, Any]:
    """
    Analisa um site e retorna evidências WCAG + score técnico.

    Retorno:
    - status, url, error_message (mesmo padrão original)
    - evidences: lista de ocorrências com trecho HTML extraído + metadados completos
    - score: calculado exatamente conforme estrutura do Código 1 original
    - summary: NOVO — contagens por tipo de violação, breakdown de penalidade,
               total de ocorrências, etc. Ideal para relatório de resultados
               e relatório final.
    """
    result = {
        "url": url,
        "status": "success",
        "evidences": [],
        "score": 100.0,
        "error_message": None,
        "summary": {
            "total_evidences": 0,
            "counts_by_indicator": {},
            "counts_by_rule_id": {},
            "penalty_breakdown": {},
            "total_penalty_before_cap": 0.0,
            "cap_applied": False,
        },
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_navigation_timeout(90000)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
            except Exception as e:
                result["status"] = "error"
                result["error_message"] = f"Erro ao acessar o site: {str(e)}"
                browser.close()
                return result

            # Injeta axe-core
            page.add_script_tag(
                url="https://unpkg.com/axe-core@4.11.4/axe.min.js"
            # page.add_script_tag(
                # url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js"
            )
            page.wait_for_function("() => typeof axe !== 'undefined'", timeout=20000)

            # Executa análise WCAG
            axe_js = """
                (async () => {
                    return await axe.run(document, {
                        runOnly: {
                            type: 'tag',
                            values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa','wcag22a', 'wcag22aa']
                        }
                    });
                })()
            """

            axe_results = page.evaluate(axe_js)

            evidences = _map_axe_violations(axe_results)
            result["evidences"] = evidences

            # =================================================================
            # CÁLCULO DO SCORE (EXATAMENTE conforme Código 1 original)
            # =================================================================
            if evidences:
                counts = Counter(ev["rule_id"] for ev in evidences if ev["rule_id"] in PESOS_WCAG)

                total_penalty = 0.0

                for rule_id, count in counts.items():
                    weight = PESOS_WCAG[rule_id]
                    multiplier = _get_volume_multiplier(count)
                    contribution = weight * multiplier * 100
                    total_penalty += contribution

                total_penalty = min(total_penalty, 85)
                result["score"] = round(max(0, 100 - total_penalty), 1)

                # =================================================================
                # SUMMARY para relatórios (número de ocorrências + cálculo penalidade)
                # =================================================================
                result["summary"] = {
                    "total_evidences": len(evidences),
                    "counts_by_indicator": dict(Counter(e["indicator"] for e in evidences)),
                    "counts_by_rule_id": dict(counts),
                    "penalty_breakdown": {
                        rule_id: {
                            "count": count,
                            "weight": PESOS_WCAG[rule_id],
                            "multiplier": _get_volume_multiplier(count),
                            "contribution": round(PESOS_WCAG[rule_id] * _get_volume_multiplier(count) * 100, 2),
                        }
                        for rule_id, count in counts.items()
                    },
                    "total_penalty_before_cap": round(total_penalty, 2),
                    "cap_applied": total_penalty >= 85,
                }
            else:
                result["score"] = 100.0
                result["summary"] = {
                    "total_evidences": 0,
                    "counts_by_indicator": {},
                    "counts_by_rule_id": {},
                    "penalty_breakdown": {},
                    "total_penalty_before_cap": 0.0,
                    "cap_applied": False,
                }

            browser.close()

    except PlaywrightError as e:
        result["status"] = "error"
        result["error_message"] = f"Erro do Playwright: {str(e)}"
    except Exception as e:
        result["status"] = "error"
        result["error_message"] = f"Erro inesperado: {str(e)}"

    return result
