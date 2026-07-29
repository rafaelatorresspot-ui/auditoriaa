# -*- coding: utf-8 -*-
"""
config_documentos.py

Configuração central dos tipos de documento (obrigatórios e complementares)
e dos padrões (regex) usados para identificar cada tipo a partir do NOME
do arquivo encontrado nas pastas dos colaboradores.

⚠️ IMPORTANTE: os nomes de arquivo na pasta real variam bastante (não seguem
um padrão único). Os padrões abaixo são um ponto de partida — depois da
primeira varredura, revise o relatório de "não classificados" (gerado pelo
scanner) e vá ajustando/adicionando variações aqui até a cobertura ficar boa.
Não é necessário mexer em mais nenhum arquivo além deste para ajustar a
classificação.
"""

import re
from datetime import date

# ---------------------------------------------------------------------------
# VIGÊNCIA DOS DOCUMENTOS OBRIGATÓRIOS
# ---------------------------------------------------------------------------
# Para cada documento obrigatório, defina a partir de qual data a auditoria
# passa a cobrar (marcar como pendência se estiver faltando). Use `None` para
# documentos que já são cobrados desde sempre. O documento continua sendo
# obrigatório para TODOS os colaboradores (inclusive os mais antigos) — só a
# cobrança na auditoria começa a valer a partir da data informada.
VIGENCIA_OBRIGATORIOS = {
    "Termo de EPI": None,
    "Termo de Telefonia": None,
    "Contrato": None,
    "Termo de Uso de Motocicleta": date(2026, 6, 1),
}

# ---------------------------------------------------------------------------
# DOCUMENTOS OBRIGATÓRIOS
# ---------------------------------------------------------------------------
DOCUMENTOS_OBRIGATORIOS = {
    "Termo de EPI": [
        r"termo.*epi",
        r"\bepi\b",
        r"equipamento.*protecao.*individual",
    ],
    "Termo de Telefonia": [
        r"termo.*telefon",
        r"telefon.*termo",
        r"termo.*aparelho.*celular",
        r"comodato.*celular",
    ],
    "Contrato": [
        r"contrato.*trabalho",
        r"contrato.*experiencia",
        r"\bcontrato\b",
    ],
    "Termo de Uso de Motocicleta": [
        r"termo.*mot(o|ocicleta)",
        r"mot(o|ocicleta).*termo",
        r"uso.*motocicleta",
        r"comodato.*mot(o|ocicleta)",
        r"desloc\w*",
        r"desloc\w*.*mot(o|ocicleta)",
        r"mot(o|ocicleta).*desloc\w*",
        r"autoriza(c|ç)(a|ã)o.*desloc\w*",
    ]
}

# ---------------------------------------------------------------------------
# DOCUMENTOS COMPLEMENTARES
# ---------------------------------------------------------------------------
DOCUMENTOS_COMPLEMENTARES = {
    "RG ou CNH": [
        r"\brg\b",
        r"\bcnh\b",
        r"identidade",
        r"carteira.*identidade",
        r"carteira.*motorista",
        r"habilitacao",
    ],
    "Comprovante de Residência": [
        r"comp.*resid",
        r"resid.*comp",
        r"comprovante.*endereco",
    ],
    "Comprovante de Escolaridade": [
        r"comp.*escolar",
        r"escolarid",
        r"diploma",
        r"hist[oó]rico.*escolar",
        r"certificado.*conclusao",
    ],
    "Título de Eleitor": [
        r"t[ií]tulo.*eleitor",
        r"\beleitor\b",
    ],
    "CTPS": [
        r"\bctps\b",
        r"carteira.*trabalho",
    ],
    "Exame Admissional": [
        r"exame.*admission",
        r"admission.*exame",
        r"\baso\b",
        r"atestado.*saude.*ocupacional",
    ],
}


def _compilar(dic):
    return {
        doc: [re.compile(p, re.IGNORECASE) for p in padroes]
        for doc, padroes in dic.items()
    }


PADROES_OBRIGATORIOS = _compilar(DOCUMENTOS_OBRIGATORIOS)
PADROES_COMPLEMENTARES = _compilar(DOCUMENTOS_COMPLEMENTARES)

EXTENSOES_VALIDAS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".tif", ".tiff"}
