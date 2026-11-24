"""Gera o PDF a partir do snapshot original e dos resultados exportados do Neo4j."""

import argparse
import json
import re
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, PolyLine, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
    XPreformatted,
)

ROOT = Path(__file__).resolve().parents[1]
AUTHORS = "Murilo Eduardo Feijo Ramos e Renato Dias Ferreira Campos"
NAVY = colors.HexColor("#142844")
TEAL = colors.HexColor("#007268")
SLATE = colors.HexColor("#35465B")
MUTED = colors.HexColor("#566678")
PALE = colors.HexColor("#F0F5F7")
WHITE = colors.white
PAGE_WIDTH = A4[0] - 96

QUERIES = [
    ("Concordância entre partidos dentro das frentes",
     "Agrupa os pares de deputados com siglas partidárias observadas distintas por frente e mede a "
     "proporção de votos iguais. Exige ao menos 10 comparações por frente."),
    ("Coautoria de projetos de lei",
     "Conta os PLs assinados em comum por cada par de deputados. A consulta "
     "mostra até cinco identificadores de projetos por par."),
    ("Concordância entre pares de partidos",
     "Agrupa as comparações de votos pelos dois partidos observados e exige "
     "ao menos 30 comparações para incluir o par."),
    ("Divergência entre integrantes de uma frente",
     "Para cada deputado e frente, mede a proporção de votos diferentes dos "
     "outros integrantes. Exige ao menos 30 comparações por deputado e frente."),
    ("Concordância entre coautores em votações compartilhadas",
     "Identifica pares com pelo menos um PL em comum e compara seus votos Sim ou Não "
     "nas votações compartilhadas no recorte. Exige ao menos três votações em comum."),
]

INTERPRETATIONS = [
    (
        "As frentes são ordenadas pelo percentual de concordância. Pessoas que integram "
        "a mesma frente podem ser comparadas em muitas votações, e votações com mais "
        "pares elegíveis influenciam mais a taxa. Cada combinação de siglas distintas "
        "também pode contribuir quando há mais de uma filiação observada.",
        "A medida descreve a concordância nos votos registrados entre signatários da mesma frente. "
        "O tema da frente funciona como critério de agrupamento, enquanto as votações "
        "vêm do conjunto de PLs do recorte e podem tratar de outros assuntos.",
    ),
    (
        "As autorias compartilhadas mostram como um mesmo conjunto de PLs pode aproximar "
        "vários pares. Se um projeto reúne muitos signatários, a autoria desse único "
        "projeto gera diversos pares na tabela.",
        "O indicador de colaboração é a assinatura em comum. A intensidade do trabalho "
        "conjunto e o papel de cada autor exigiriam outras evidências, como o histórico "
        "de tramitação ou a atuação dos deputados na redação.",
    ),
    (
        "A ordenação por percentual pode colocar um par com poucas comparações acima de "
        "pares com uma base maior. Os volumes da tabela ajudam a contextualizar as "
        "taxas e representam combinações de deputados por votação.",
        "O cálculo exclui comparações de um deputado consigo mesmo. O relacionamento "
        "de filiação reúne siglas observadas e não tem vigência definida. Assim, a "
        "medida caracteriza os agrupamentos do grafo, com incerteza sobre a sigla "
        "de cada deputado no momento do voto.",
    ),
    (
        "A taxa é calculada separadamente para cada combinação de deputado e frente. "
        "Um deputado presente em várias frentes pode aparecer várias vezes, e duas "
        "frentes podem compartilhar integrantes e comparações.",
        "Um percentual alto identifica um padrão de votos distintos em relação aos "
        "colegas elegíveis do grupo. Vincular a divergência ao tema da frente exigiria "
        "classificar a pauta das votações e delimitar a participação em cada data.",
    ),
    (
        "A ordenação prioriza o número de votações compartilhadas e usa o percentual "
        "de concordância como desempate. Pares com igual número de PLs em comum e "
        "de votações compartilhadas ainda podem apresentar taxas bem diferentes.",
        "A autoria identifica quais pares estudar. As votações contabilizadas podem "
        "estar associadas a outros PLs do recorte. Medir o efeito da autoria conjunta "
        "sobre a concordância exigiria uma comparação com pares sem coautoria e "
        "controle da pauta, da filiação e da cobertura de votos.",
    ),
]

HEADERS = {
    "acordos": "Acordos",
    "comparacoes": "Comparações",
    "concordancia_percentual": "Acordo (%)",
    "deputado": "Deputado",
    "deputado_1": "Deputado 1",
    "deputado_2": "Deputado 2",
    "divergencia_percentual": "Divergência (%)",
    "divergencias": "Votos distintos",
    "exemplos": "Exemplos",
    "frente": "Frente",
    "id": "ID",
    "partido_1": "Partido 1",
    "partido_2": "Partido 2",
    "projeto": "Projeto",
    "projetos_em_comum": "PLs em comum",
    "votacoes_compartilhadas": "Votações em comum",
}
WEIGHTS = {
    "deputado": 1.55, "deputado_1": 1.65, "deputado_2": 1.65,
    "comparacoes": 1.15, "divergencias": 1.22, "divergencia_percentual": 1.18,
    "exemplos": 2.2, "frente": 3.3,
}
MODEL = [
    ("Deputado → Partido", "FILIACAO_OBSERVADA", "Sigla encontrada nos registros da API."),
    ("Deputado → Frente", "INTEGRA", "Signatário registrado na criação da frente."),
    ("Deputado → Proposição", "AUTOR_DE", "Autoria registrada para um PL."),
    ("Proposição → Votação", "SUBMETIDA_A", "Votação associada ao PL pela API."),
    ("Deputado → Votação", "VOTOU_EM", "Voto individual, com tipo e data de registro."),
]


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def fmt(value):
    if value is None:
        return "indisponível"
    if isinstance(value, list):
        return ", ".join(map(fmt, value))
    if isinstance(value, int):
        return f"{value:,}".replace(",", ".")
    if isinstance(value, float):
        return f"{value:.1f}".replace(".", ",")
    return str(value)


def styles():
    defaults = getSampleStyleSheet()
    definitions = {
        "label": dict(fontName="Helvetica-Bold", fontSize=9, leading=14, textColor=TEAL, spaceAfter=8),
        "title": dict(fontName="Helvetica-Bold", fontSize=34, leading=37, textColor=NAVY, spaceAfter=20),
        "heading": dict(fontName="Helvetica-Bold", fontSize=23, leading=27, textColor=NAVY, spaceAfter=12),
        "sub": dict(fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=NAVY, spaceBefore=12, spaceAfter=6),
        "body": dict(fontSize=10, leading=15, textColor=SLATE, spaceAfter=9),
        "small": dict(fontSize=8.5, leading=12, textColor=MUTED, spaceAfter=8),
        "cell": dict(fontSize=8.1, leading=10.6, textColor=SLATE),
        "number": dict(fontSize=8.1, leading=10.6, textColor=SLATE, alignment=TA_RIGHT),
        "th": dict(fontName="Helvetica-Bold", fontSize=8.2, leading=10.7, textColor=WHITE),
        "code": dict(fontName="Courier", fontSize=7.7, leading=10.5, textColor=NAVY, spaceAfter=12),
    }
    return {name: ParagraphStyle(name, parent=defaults["Normal"], **options)
            for name, options in definitions.items()}


def para(text, style):
    return Paragraph(escape(str(text)), style)


def table(headers, rows, sheet, widths, numeric=(), padding=6):
    cells = [[para(header, sheet["th"]) for header in headers]]
    cells.extend([
        [para(value, sheet["number"] if index in numeric else sheet["cell"])
         for index, value in enumerate(row)]
        for row in rows
    ])
    result = LongTable(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PALE, WHITE]),
        ("LINEBELOW", (0, -1), (-1, -1), 0.55, colors.HexColor("#CCD8DF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]))
    return result


def model_diagram():
    drawing = Drawing(PAGE_WIDTH, 174)
    drawing.add(Rect(0, 0, PAGE_WIDTH, 174, rx=6, ry=6, fillColor=PALE, strokeColor=None))

    # As setas chegam ao lado esquerdo ou à base do nó de destino.
    edges = [
        ([(103, 103), (125, 103), (125, 147), (248, 147)], (129, 153), "FILIACAO_OBSERVADA"),
        ([(103, 95), (248, 95)], (165, 101), "INTEGRA"),
        ([(103, 87), (125, 87), (125, 44), (248, 44)], (167, 50), "AUTOR_DE"),
        ([(333, 44), (407, 44)], (338, 51), "SUBMETIDA_A"),
        ([(61, 82), (61, 15), (449, 15), (449, 32)], (225, 20), "VOTOU_EM"),
    ]
    for points, (x, y), name in edges:
        drawing.add(PolyLine(points, strokeColor=TEAL, strokeWidth=1))
        tip_x, tip_y = points[-1]
        if points[-2][0] == tip_x:
            head = [tip_x, tip_y, tip_x - 3, tip_y - 5, tip_x + 3, tip_y - 5]
        else:
            head = [tip_x, tip_y, tip_x - 5, tip_y + 3, tip_x - 5, tip_y - 3]
        drawing.add(Polygon(head, fillColor=TEAL, strokeColor=None))
        drawing.add(String(x, y, name, fontName="Helvetica", fontSize=7.2, fillColor=SLATE))

    for x, y, name in [
        (18, 82, "Deputado"), (248, 135, "Partido"), (248, 83, "Frente"),
        (248, 32, "Proposição"), (407, 32, "Votação"),
    ]:
        drawing.add(Rect(x, y, 85, 24, rx=4, ry=4, fillColor=NAVY, strokeColor=None))
        drawing.add(String(x + 42.5, y + 8.5, name, textAnchor="middle",
                           fontName="Helvetica-Bold", fontSize=10, fillColor=WHITE))
    return drawing


def emphasis(query_id, rows):
    if not rows:
        return "A consulta retornou zero linhas para o recorte e os filtros aplicados."
    first = rows[0]
    count = fmt(len(rows))
    prefix = f"A consulta exibiu {count} resultado(s). "
    if query_id == 1:
        return (prefix + f"{first['frente']} aparece no topo com "
                f"{fmt(first['acordos'])} acordos em {fmt(first['comparacoes'])} "
                f"comparações ({fmt(first['concordancia_percentual'])}%).")
    if query_id == 2:
        return (prefix + f"O primeiro par, {first['deputado_1']} e {first['deputado_2']}, "
                f"assinou {fmt(first['projetos_em_comum'])} PL(s) em comum.")
    if query_id == 3:
        return (prefix + f"O par {first['partido_1']}/{first['partido_2']} aparece no topo, "
                f"com {fmt(first['concordancia_percentual'])}% de concordância em "
                f"{fmt(first['comparacoes'])} comparações.")
    if query_id == 4:
        return (prefix + f"{first['deputado']} aparece no topo na frente "
                f"{first['frente']}, com divergência de "
                f"{fmt(first['divergencia_percentual'])}% em "
                f"{fmt(first['comparacoes'])} comparações.")
    return (prefix + f"{first['deputado_1']} e {first['deputado_2']} têm "
            f"{fmt(first['projetos_em_comum'])} PL em comum e concordaram em "
            f"{fmt(first['acordos'])} de {fmt(first['votacoes_compartilhadas'])} "
            f"votações compartilhadas ({fmt(first['concordancia_percentual'])}%).")


def result_context(query_id, rows):
    if len(rows) < 5:
        return ""
    first, fifth = rows[0], rows[4]
    if query_id == 1:
        spread = first["concordancia_percentual"] - fifth["concordancia_percentual"]
        return f"A taxa da primeira frente supera a da quinta em {fmt(spread)} pontos percentuais."
    if query_id == 2 and first["exemplos"] == fifth["exemplos"]:
        return f"O primeiro e o quinto pares listam os mesmos projetos ({fmt(first['exemplos'])})."
    if query_id == 3:
        other = max(rows[:5], key=lambda row: row["comparacoes"])
        return (f"Entre as cinco linhas da tabela, {other['partido_1']}/{other['partido_2']} "
                f"teve a maior base ({fmt(other['comparacoes'])} comparações).")
    if query_id == 4 and first["frente"] == fifth["frente"]:
        return (f"{first['deputado']} e {fifth['deputado']} aparecem na mesma frente, "
                f"com taxas de {fmt(first['divergencia_percentual'])}% "
                f"e {fmt(fifth['divergencia_percentual'])}%.")
    if query_id == 5:
        return (f"O primeiro e o quinto pares registraram taxas de "
                f"{fmt(first['concordancia_percentual'])}% e "
                f"{fmt(fifth['concordancia_percentual'])}%.")
    return ""


def node_label(label, properties):
    if label == "Proposicao":
        return f"{properties['siglaTipo']} {properties['numero']}/{properties['ano']}"
    if label == "Votacao":
        return f"{properties['id']} · {date_label(properties.get('data'))}"
    return properties.get("nome") or properties.get("titulo") or properties.get("sigla") or str(properties["id"])


def date_label(value):
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        year, month, day = value[:10].split("-")
        return f"{day}/{month}/{year}"
    return fmt(value)


def page(canvas, doc):
    canvas.setFillColor(TEAL)
    canvas.rect(48, A4[1] - 36, 27, 3, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#CCD8DF"))
    canvas.line(48, 47, A4[0] - 48, 47)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(48, 31, "Câmara dos Deputados em grafo")
    canvas.drawRightString(A4[0] - 48, 31, str(doc.page))


def build(snapshot, results, blocks, destination, repository=None):
    meta = snapshot["metadados"]
    raw = snapshot["dados"]
    load = results["carga"]
    period = load["periodo_votacoes"]
    query_rows = {int(query["id"]): query["linhas"] for query in results["consultas"]}
    if len(blocks) != len(QUERIES) or set(query_rows) != set(range(1, len(QUERIES) + 1)):
        raise ValueError("São necessários os cinco blocos Cypher e os cinco resultados correspondentes.")

    sheet = styles()
    story = []

    def add(text, style="body"):
        story.append(para(text, sheet[style]))

    add("RELATÓRIO ACADÊMICO  /  BDCD", "label")
    add("Câmara dos Deputados em grafo", "title")
    add("Modelagem e análise de dados legislativos com Neo4j", "sub")
    add("Murilo Eduardo Feijo Ramos  |  824389")
    add("Renato Dias Ferreira Campos  |  821328")
    story.append(Spacer(1, 19))
    add("Objetivo", "sub")
    add("Investigar como a coautoria de projetos de lei, a participação em frentes "
        "parlamentares e a filiação partidária observada se relacionam com os "
        "votos individuais registrados pela Câmara dos Deputados.")
    add("Recorte e extração", "sub")
    add(f"O snapshot reúne {fmt(len(raw['proposicoes']))} projetos de lei com ano de identificação "
        f"{meta['ano_proposicoes']} e {fmt(len(raw['frentes']))} frentes da "
        f"{meta['legislatura_frentes']}ª legislatura. A coleta foi registrada em "
        f"{date_label(meta['coletado_em_utc'])} (UTC).")
    add(f"A coleta selecionou PLs em ordem crescente de ID "
        f"(limite configurado de {fmt(meta['limite_proposicoes'])}) e consultou, para cada "
        "projeto, os autores e as votações associadas. O processo buscou os votos "
        "individuais de cada votação e os signatários de cada frente. "
        f"O limite de frentes foi {fmt(meta['limite_frentes'])}. O valor zero representa "
        "coleta sem limite, respeitados os filtros da API.")
    add(f"Período das datas de votação na base: {date_label(period['inicio'])} "
        f"a {date_label(period['fim'])}. O filtro de ano usa o campo ano do PL na API.")
    first_pl = raw["proposicoes"][0]
    add(f"Exemplo do snapshot: {first_pl['siglaTipo']} {first_pl['numero']}/{first_pl['ano']} "
        f"(ID {first_pl['id']}, campo dataApresentacao em "
        f"{date_label(first_pl.get('dataApresentacao'))}). "
        f"Ementa: {first_pl['ementa']}")
    add("Fonte dos registros", "sub")
    add(f"Dados Abertos da Câmara dos Deputados. API v2. {meta['fonte']}", "small")
    add(f"Repositório: {repository}" if repository else
        "O endereço do repositório está pendente.", "small")
    add("Para atender ao enunciado, faltam as capturas de tela do grafo e dos "
        "resultados no Neo4j Browser. O relatório inclui o diagrama do modelo "
        "e tabelas geradas com as consultas executadas.", "small")

    story.append(PageBreak())
    add("MODELO E CARGA", "label")
    add("Estrutura do grafo", "heading")
    add("Os nós Deputado, Frente, Proposição e Votação usam os IDs da API. "
        "O nó Partido usa a sigla observada como chave. A importação cria "
        "restrições de unicidade e aplica MERGE em lotes.")
    story.append(model_diagram())
    story.append(Spacer(1, 9))
    story.append(table(
        ["Origem → destino", "Relacionamento", "Semântica"],
        MODEL, sheet, [143, 128, PAGE_WIDTH - 271],
    ))
    add("Contagens obtidas no Neo4j", "sub")
    rows = [("Nó", label, fmt(total)) for label, total in load["nos"].items()]
    rows.extend(("Relação", label, fmt(total)) for label, total in load["relacoes"].items())
    story.append(table(
        ["Categoria", "Rótulo ou tipo", "Total"], rows, sheet,
        [92, PAGE_WIDTH - 166, 74], numeric=[2],
    ))
    story.append(PageBreak())
    add("MODELO E CARGA", "label")
    add("Exemplos do grafo", "heading")
    add("As linhas abaixo foram obtidas no Neo4j após a importação.")
    node_rows = []
    for label, examples in load["exemplos_nos"].items():
        for example in examples[:2]:
            identifier = example.get("id", example.get("sigla"))
            node_rows.append((label, identifier, node_label(label, example)))
    story.append(table(
        ["Rótulo", "Chave", "Registro"], node_rows, sheet, [94, 95, PAGE_WIDTH - 189],
    ))
    add("Relações registradas", "sub")
    relation_rows = []
    for kind, examples in load["exemplos_relacoes"].items():
        for example in examples[:2]:
            details = example["rel"].get("tipo")
            relation_rows.append((
                node_label(example["origem"], example["a"]),
                f"{kind} ({details})" if details else kind,
                node_label(example["destino"], example["b"]),
            ))
    story.append(table(
        ["Origem", "Relacionamento", "Destino"], relation_rows,
        sheet, [163, 147, PAGE_WIDTH - 310],
    ))

    add("Comparações de voto", "sub")
    add("As consultas de concordância e divergência consideram Sim e Não. "
        "Quando dois deputados têm um voto elegível na mesma votação, "
        "o par contribui com uma comparação para o grupo correspondente.")

    for index, (title, method) in enumerate(QUERIES, 1):
        story.append(PageBreak())
        add(f"RESULTADO {index} / {len(QUERIES)}", "label")
        add(title, "heading")
        add(method)
        rows = query_rows[index]
        add(emphasis(index, rows))
        if rows:
            keys = list(rows[0])
            total_weight = sum(WEIGHTS.get(key, 1) for key in keys)
            widths = [PAGE_WIDTH * WEIGHTS.get(key, 1) / total_weight for key in keys]
            numeric = [
                j for j, key in enumerate(keys)
                if key != "id" and any(isinstance(row.get(key), (int, float)) for row in rows)
            ]
            story.append(table(
                [HEADERS.get(key, key) for key in keys],
                [[str(row[key]) if key == "id" else fmt(row.get(key)) for key in keys]
                 for row in rows[:5]],
                sheet, widths, numeric, padding=5,
            ))
            story.append(Spacer(1, 7))
            add(f"A tabela mostra as primeiras {min(5, len(rows))} linhas entre as "
                f"{len(rows)} retornadas. A consulta limita o resultado a 20 linhas. "
                "A exportação completa está em output/resultados.json.", "small")
            add("Interpretação", "sub")
            contrast = result_context(index, rows)
            for paragraph in INTERPRETATIONS[index - 1]:
                add((contrast + " " + paragraph) if contrast else paragraph)
                contrast = ""

    story.append(PageBreak())
    add("INTERPRETAÇÃO E REPRODUÇÃO", "label")
    add("Limites da análise", "heading")
    add("O recorte por ano, tipo e ID dos projetos condiciona as inferências. "
        "As relações de autoria excluem autores institucionais e de outros cargos. "
        "A API fornece votos individuais quando há registro nominal; a ausência "
        "de um voto individual pode decorrer do modo de registro da votação.")
    add("A filiação observada agrega siglas encontradas em diferentes respostas da API. "
        "Como o modelo não registra a vigência da filiação, deputados com mais de "
        "uma sigla podem entrar em mais de um grupo partidário. As frentes refletem "
        "signatários da criação. Uma votação associada a um PL pode tratar de "
        "procedimentos ou de matérias vinculadas ao projeto.")
    add("Cada taxa descreve os pares e as votações elegíveis no recorte. Os limiares "
        "reduzem a presença de grupos com poucas comparações, e o LIMIT 20 restringe "
        "a apresentação. Os resultados permitem descrever padrões no grafo carregado. "
        "Uma taxa alta pode refletir a composição do recorte, o conteúdo da votação "
        "ou a seleção dos projetos.")
    add("O menor e o maior valor do campo de data de votação foram extraídos do "
        "grafo carregado. Há vínculos com votações anteriores ao ano do recorte. "
        "O exemplo do PL 4148/2023 também mostra uma data de apresentação "
        "registrada em 2007. A semântica desses registros e a causa da discrepância "
        "exigem investigação na origem antes de interpretar a cronologia.")
    add("Conclusão", "sub")
    add("As consultas de votação encontraram padrões de acordo e divergência entre "
        "deputados agrupados por frente, coautoria ou filiação observada. A consulta de "
        "autoria identificou quais pares assinaram mais PLs juntos. O grafo permitiu "
        "cruzar essas relações e comparar separadamente a coautoria e os votos "
        "compartilhados. Uma análise longitudinal dependeria de validar as datas "
        "e modelar a vigência das filiações.")
    add("Reprodução", "sub")
    add("A coleta usou scripts/coletar_relatorio.py, com paralelismo e cache. Os "
        "endpoints /proposicoes/{id}/autores e /proposicoes/{id}/votacoes fornecem "
        "as listas por PL. O script também consulta /votacoes/{id}/votos e "
        "/frentes/{id}/membros. As respostas e os parâmetros ficam no snapshot.")
    add("A importação usou scripts/importar.sh --arquivo relatorio.json. O código "
        "em src/cli.py normaliza as listas, agrupa chaves e usa UNWIND com "
        "MERGE para inserir os lotes. A carga é cumulativa. Use uma base vazia "
        "para reproduzir as contagens de um único snapshot.")
    add("scripts/registrar_resultados.sh executa scripts/executar_analises.py, que "
        "usa o driver Neo4j e grava output/resultados.json. Cada bloco de "
        "queries/analises.cypher também pode ser executado no Neo4j Browser.")
    add("Referências", "sub")
    add("Câmara dos Deputados. Documentação da API de Dados Abertos. "
        "https://dadosabertos.camara.leg.br/swagger/api.html", "small")
    add("Câmara dos Deputados. Orientações sobre os dados de votações. "
        "https://dadosabertos.camara.leg.br/howtouse/2020-02-07-dados-votacoes.html", "small")

    story.append(PageBreak())
    add("RELATO DE USO DE IA", "label")
    add("Inteligência artificial no trabalho", "heading")
    add("Ferramentas e escopo", "sub")
    add("Conforme informado pelos integrantes, o trabalho foi desenvolvido em outra "
        "sessão e esta conversa foi usada para comparação. A IA, com o modelo GPT-6.1 "
        "Terra informado pelos integrantes, auxiliou na correção de sintaxe, na "
        "configuração do ambiente Docker e na melhoria de consultas preexistentes. "
        "A formatação do PDF também foi refeita com auxílio de IA.")
    add("Interações e comparação", "sub")
    add("Nesta conversa, a IA também gerou uma implementação para comparação, "
        "incluindo scripts, consultas e o texto deste relatório. As consultas foram "
        "executadas no Neo4j sobre o recorte descrito, e seus resultados foram "
        "utilizados nas tabelas apresentadas.")
    add("Intervenção humana", "sub")
    add("Os integrantes informaram ter desenvolvido o trabalho em outra sessão, "
        "definiram os requisitos e orientaram a comparação e a apresentação. O "
        "registro desta conversa não permite identificar quais trechos da versão "
        "desenvolvida fora dela foram escritos ou modificados por cada integrante.")
    add("Validação e testes", "sub")
    add("A validação nesta conversa consistiu em importar o snapshot, conferir "
        "as contagens e executar as cinco consultas no Neo4j. O PDF foi revisado "
        "por extração de texto e renderização. Os testes automatizados gerados "
        "durante o desenvolvimento foram removidos a pedido dos integrantes.")

    story.append(PageBreak())
    add("APÊNDICE", "label")
    add("Consultas Cypher", "heading")
    for index, ((title, _), block) in enumerate(zip(QUERIES, blocks), 1):
        wrapped = "\n".join(
            textwrap.fill(line, 100, subsequent_indent="    ", replace_whitespace=False)
            if len(line) > 100 else line
            for line in block.splitlines()
        )
        code = XPreformatted(escape(wrapped), sheet["code"])
        story.append(KeepTogether([para(f"{index}. {title}", sheet["sub"]), code]))

    destination.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(destination), pagesize=A4, title="Câmara dos Deputados em grafo",
        author=AUTHORS, leftMargin=42, rightMargin=42, topMargin=58, bottomMargin=63,
    )
    doc.build(story, onFirstPage=page, onLaterPages=page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=ROOT / "data/raw/relatorio.json")
    parser.add_argument("--resultados", type=Path, default=ROOT / "output/resultados.json")
    parser.add_argument("--saida", type=Path, default=ROOT / "output/pdf/relatorio-camara-neo4j.pdf")
    parser.add_argument("--repositorio", help="URL do repositório para registrar no relatório.")
    args = parser.parse_args()
    source = (ROOT / "queries/analises.cypher").read_text(encoding="utf-8")
    query_text = "\n".join(line for line in source.splitlines()
                           if not line.lstrip().startswith("//"))
    blocks = [block.strip() + ";" for block in query_text.split(";") if block.strip()]
    build(read_json(args.snapshot), read_json(args.resultados), blocks, args.saida, args.repositorio)
    print(args.saida)


if __name__ == "__main__":
    main()
