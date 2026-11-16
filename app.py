"""LumIA: converse com seus documentos usando RAG (busca + IA generativa)."""
import glob
import hashlib
import json
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session

load_dotenv()

import documentos  # noqa: E402  (precisa do .env carregado)
import ia  # noqa: E402
from database import conectar, criar_tabelas  # noqa: E402

PASTA = os.path.dirname(os.path.abspath(__file__))

# limites para proteger a cota gratuita da API (podem ser mudados no .env)
MAX_MB = int(os.environ.get("MAX_MB", 10))
MAX_PAGINAS = int(os.environ.get("MAX_PAGINAS", 100))
MAX_DOCUMENTOS = int(os.environ.get("MAX_DOCUMENTOS", 5))
PERGUNTAS_POR_HORA = int(os.environ.get("PERGUNTAS_POR_HORA", 30))
USO_TOTAL_POR_DIA = int(os.environ.get("USO_TOTAL_POR_DIA", 500))


def chave_secreta():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    caminho = os.path.join(PASTA, "chave_secreta.txt")
    if not os.path.exists(caminho):
        with open(caminho, "w") as f:
            f.write(secrets.token_hex(32))
    with open(caminho) as f:
        return f.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=chave_secreta(),
    MAX_CONTENT_LENGTH=(MAX_MB + 1) * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SAMESITE="Lax",
)
criar_tabelas()


def erro(mensagem, status=400):
    return jsonify({"erro": mensagem}), status


def espaco_atual():
    """Cada visitante tem seu próprio espaço: ninguém vê os documentos de outra pessoa."""
    if "espaco" not in session:
        session["espaco"] = secrets.token_hex(12)
        session.permanent = True
    return session["espaco"]


def garantir_exemplo():
    """Coloca o documento de exemplo (público) no banco. Ele é indexado na primeira pergunta."""
    with conectar() as con:
        if con.execute("SELECT 1 FROM documentos WHERE espaco = 'publico'").fetchone():
            return
        for caminho in sorted(glob.glob(os.path.join(PASTA, "exemplos", "*.pdf"))):
            with open(caminho, "rb") as f:
                paginas = documentos.ler_arquivo(caminho, f.read(), 500)
            trechos = documentos.dividir_em_trechos(paginas)
            doc_id = con.execute(
                "INSERT INTO documentos (espaco, nome, paginas, status) VALUES ('publico', ?, ?, 'pronto')",
                (os.path.basename(caminho), max(p for p, _ in paginas)),
            ).lastrowid
            con.executemany(
                "INSERT INTO trechos (documento_id, ordem, pagina, texto) VALUES (?, ?, ?, ?)",
                [(doc_id, i, p, t) for i, (p, t) in enumerate(trechos)],
            )


garantir_exemplo()


def limite_atingido(con, espaco, por_hora):
    usados = con.execute(
        "SELECT COUNT(*) AS n FROM uso WHERE espaco = ? AND momento >= datetime('now', '-1 hour')", (espaco,)
    ).fetchone()["n"]
    if usados >= por_hora:
        return "Você atingiu o limite de uso por hora desta demonstração. Tente de novo mais tarde."
    total = con.execute("SELECT COUNT(*) AS n FROM uso WHERE momento >= datetime('now', '-1 day')").fetchone()["n"]
    if total >= USO_TOTAL_POR_DIA:
        return "A demonstração atingiu o limite de uso de hoje. Volte amanhã!"
    return None


@app.errorhandler(413)
def arquivo_grande(_):
    return erro(f"Arquivo muito grande. O limite é {MAX_MB} MB.", 413)


@app.errorhandler(ia.ErroIA)
def erro_ia(e):
    return erro(str(e), 502)


# ================= páginas =================

@app.route("/")
def inicio():
    espaco_atual()
    return render_template(
        "index.html", ia_configurada=ia.configurada(), modo_teste=ia.modo_teste(),
        max_mb=MAX_MB, max_paginas=MAX_PAGINAS,
    )


# ================= API =================

def listar(con, espaco):
    linhas = con.execute(
        """SELECT d.id, d.nome, d.paginas, d.espaco = 'publico' AS exemplo, COUNT(t.id) AS trechos
           FROM documentos d LEFT JOIN trechos t ON t.documento_id = d.id
           WHERE d.espaco IN ('publico', ?) AND d.status = 'pronto'
           GROUP BY d.id ORDER BY exemplo DESC, d.id DESC""",
        (espaco,),
    ).fetchall()
    return [dict(l, exemplo=bool(l["exemplo"])) for l in linhas]


@app.route("/api/documentos")
def api_documentos():
    with conectar() as con:
        return jsonify(listar(con, espaco_atual()))


@app.route("/api/documentos", methods=["POST"])
def enviar_documento():
    espaco = espaco_atual()
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return erro("Escolha um arquivo.")
    nome = os.path.basename(arquivo.filename)[:120]
    dados = arquivo.read()
    if len(dados) > MAX_MB * 1024 * 1024:
        return erro(f"Arquivo muito grande. O limite é {MAX_MB} MB.", 413)

    with conectar() as con:
        # documentos de visitantes ficam guardados por 7 dias
        con.execute("DELETE FROM documentos WHERE espaco != 'publico' AND criado_em < datetime('now', '-7 days')")
        con.execute("DELETE FROM uso WHERE momento < datetime('now', '-2 days')")
        quantidade = con.execute("SELECT COUNT(*) AS n FROM documentos WHERE espaco = ?", (espaco,)).fetchone()["n"]
        if quantidade >= MAX_DOCUMENTOS:
            return erro(f"Você pode ter até {MAX_DOCUMENTOS} documentos. Exclua algum para enviar outro.")
        aviso = limite_atingido(con, espaco, PERGUNTAS_POR_HORA)
        if aviso:
            return erro(aviso, 429)

    try:
        paginas = documentos.ler_arquivo(nome, dados, MAX_PAGINAS)
    except documentos.ErroDocumento as e:
        return erro(str(e))

    con = conectar()
    try:
        doc_id, trechos = documentos.salvar_documento(con, espaco, nome, paginas)
        con.execute("INSERT INTO uso (espaco) VALUES (?)", (espaco,))
        con.commit()
    except ia.ErroIA:
        con.rollback()  # se a IA falhar, não deixa documento pela metade
        raise
    finally:
        con.close()
    return jsonify({"id": doc_id, "nome": nome, "paginas": max(p for p, _ in paginas), "trechos": trechos}), 201


@app.route("/api/documentos/<int:documento_id>", methods=["DELETE"])
def excluir_documento(documento_id):
    with conectar() as con:
        cursor = con.execute(
            "DELETE FROM documentos WHERE id = ? AND espaco = ?",  # só apaga os do próprio visitante
            (documento_id, espaco_atual()),
        )
    if cursor.rowcount == 0:
        return erro("Documento não encontrado.", 404)
    return jsonify({"ok": True})


@app.route("/api/perguntar", methods=["POST"])
def perguntar():
    espaco = espaco_atual()
    dados = request.get_json(silent=True) or {}
    pergunta = (dados.get("pergunta") or "").strip()
    if not pergunta:
        return erro("Escreva uma pergunta.")
    if len(pergunta) > 1000:
        return erro("Pergunta muito longa (máximo de 1000 caracteres).")
    if not ia.configurada():
        return erro("A IA não está configurada. Coloque sua GEMINI_API_KEY no arquivo .env.", 503)

    with conectar() as con:
        permitidos = {d["id"] for d in listar(con, espaco)}
        try:
            escolhidos = [int(i) for i in dados.get("documentos", [])]
        except (TypeError, ValueError):
            return erro("Lista de documentos inválida.")
        escolhidos = [i for i in escolhidos if i in permitidos]
        if not escolhidos:
            return erro("Selecione pelo menos um documento.")
        aviso = limite_atingido(con, espaco, PERGUNTAS_POR_HORA)
        if aviso:
            return erro(aviso, 429)

        historico = []
        for h in (dados.get("historico") or [])[-3:]:
            if isinstance(h, dict) and h.get("pergunta") and h.get("resposta"):
                historico.append((str(h["pergunta"])[:1000], str(h["resposta"])[:3000]))

        # pergunta repetida sobre os mesmos documentos (ex.: as sugestões do exemplo): reaproveita a resposta
        chave = None
        if not historico:
            texto_chave = f"{' '.join(pergunta.lower().split())}|{sorted(escolhidos)}"
            chave = hashlib.sha256(texto_chave.encode()).hexdigest()
            salva = con.execute(
                "SELECT resposta, fontes FROM respostas_salvas WHERE chave = ? AND criado_em >= datetime('now', '-7 days')",
                (chave,),
            ).fetchone()
            if salva:
                return jsonify({"resposta": salva["resposta"], "fontes": json.loads(salva["fontes"]), "modelo": "salva"})

        # para perguntas de continuação ("e as férias?"), busca também com a pergunta anterior
        consulta = f"{historico[-1][0]}\n{pergunta}" if historico and len(pergunta) < 80 else pergunta
        trechos = documentos.buscar(con, escolhidos, consulta)
        resposta = ia.responder(pergunta, trechos, historico)
        con.execute("INSERT INTO uso (espaco) VALUES (?)", (espaco,))

        fontes = [
            {"numero": i, "documento": t["documento"], "pagina": t["pagina"], "texto": t["texto"],
             "similaridade": t["similaridade"]}
            for i, t in enumerate(trechos, start=1)
        ]
        if chave and not ia.modo_teste():
            con.execute("INSERT OR REPLACE INTO respostas_salvas (chave, resposta, fontes) VALUES (?, ?, ?)",
                        (chave, resposta, json.dumps(fontes, ensure_ascii=False)))
    return jsonify({"resposta": resposta, "fontes": fontes, "modelo": ia.modelo_em_uso()})


if __name__ == "__main__":
    app.run(debug=True)
