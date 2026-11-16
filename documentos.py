"""Etapas do RAG: ler o PDF, dividir em trechos, indexar e buscar os trechos mais parecidos com a pergunta."""
import io
import re

import numpy as np
from pypdf import PdfReader

import ia

TAMANHO_TRECHO = 1000   # caracteres por trecho
SOBREPOSICAO = 200      # parte do fim de um trecho que se repete no próximo (não corta ideias no meio)


class ErroDocumento(Exception):
    pass


# ---------------- 1. leitura ----------------

def _limpar(texto):
    texto = texto.replace("\x00", "")
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)       # junta palavras quebradas com hífen
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _assinatura(linha):
    """Linha sem números: 'Página 2' e 'Página 3' viram a mesma coisa."""
    return re.sub(r"\d+", "#", linha.strip().lower())


def _linhas_repetidas(paginas):
    """Linhas que aparecem em mais da metade das páginas (só para documentos com 3 páginas ou mais)."""
    if len(paginas) < 3:
        return set()
    contagem = {}
    for texto in paginas:
        for assinatura in {_assinatura(l) for l in texto.splitlines() if l.strip()}:
            contagem[assinatura] = contagem.get(assinatura, 0) + 1
    return {a for a, n in contagem.items() if n > len(paginas) / 2 and len(a) < 120}


def ler_arquivo(nome, dados, max_paginas):
    """Devolve uma lista de (número da página, texto). Aceita PDF e TXT/MD."""
    extensao = nome.lower().rsplit(".", 1)[-1]
    if extensao in ("txt", "md"):
        texto = _limpar(dados.decode("utf-8", errors="ignore"))
        if not texto:
            raise ErroDocumento("O arquivo está vazio.")
        # arquivos de texto não têm páginas: cada ~3000 caracteres conta como uma
        return [(i // 3000 + 1, texto[i:i + 3000]) for i in range(0, len(texto), 3000)]

    if extensao != "pdf":
        raise ErroDocumento("Formato não suportado. Envie um PDF, TXT ou MD.")
    try:
        leitor = PdfReader(io.BytesIO(dados))
        if leitor.is_encrypted:
            leitor.decrypt("")
        paginas = leitor.pages
    except Exception:
        raise ErroDocumento("Não consegui abrir esse PDF. Ele pode estar corrompido ou protegido por senha.")
    if len(paginas) > max_paginas:
        raise ErroDocumento(f"O PDF tem {len(paginas)} páginas. O limite é {max_paginas}.")

    brutos = []
    for numero, pagina in enumerate(paginas, start=1):
        try:
            brutos.append((numero, pagina.extract_text() or ""))
        except Exception:
            brutos.append((numero, ""))
    repetidas = _linhas_repetidas([t for _, t in brutos])

    resultado = []
    for numero, texto in brutos:
        # tira cabeçalhos e rodapés (linhas que se repetem em quase todas as páginas)
        linhas = [l for l in texto.splitlines() if _assinatura(l) not in repetidas]
        texto = _limpar("\n".join(linhas))
        if texto:
            resultado.append((numero, texto))
    if not resultado:
        raise ErroDocumento(
            "Não encontrei texto nesse PDF. Ele parece ser escaneado (imagem); envie um PDF com texto selecionável."
        )
    return resultado


# ---------------- 2. divisão em trechos ----------------

def dividir_em_trechos(paginas):
    """Junta parágrafos até ~1000 caracteres, sem cortar frases no meio. Cada trecho guarda a página onde começa."""
    trechos = []
    for numero, texto in paginas:
        frases = re.split(r"(?<=[.!?;:])\s+|\n+", texto)
        atual = ""
        for frase in frases:
            frase = frase.strip()
            if not frase:
                continue
            while len(frase) > TAMANHO_TRECHO:  # frase gigante (tabelas, listas sem pontuação)
                trechos.append((numero, frase[:TAMANHO_TRECHO]))
                frase = frase[TAMANHO_TRECHO - SOBREPOSICAO:]
            if len(atual) + len(frase) + 1 > TAMANHO_TRECHO and atual:
                trechos.append((numero, atual))
                # sobreposição: começa o próximo trecho com o final do anterior
                atual = atual[-SOBREPOSICAO:].split(" ", 1)[-1] + " " + frase
            else:
                atual = f"{atual} {frase}".strip()
        if atual:
            trechos.append((numero, atual))
    return trechos


# ---------------- 3. indexação ----------------

def _para_blob(vetor):
    return np.asarray(vetor, dtype=np.float32).tobytes()


def indexar(con, documento_id):
    """Gera os embeddings de todos os trechos de um documento e salva no banco."""
    linhas = con.execute(
        "SELECT id, texto FROM trechos WHERE documento_id = ? ORDER BY ordem", (documento_id,)
    ).fetchall()
    vetores = ia.gerar_embeddings([l["texto"] for l in linhas], tipo="documento")
    con.executemany("UPDATE trechos SET vetor = ? WHERE id = ?",
                    [(_para_blob(v), l["id"]) for v, l in zip(vetores, linhas)])
    con.execute("UPDATE documentos SET modelo_embedding = ?, status = 'pronto' WHERE id = ?",
                (modelo_atual(), documento_id))


def modelo_atual():
    return "simulado" if ia.modo_teste() else ia.modelo_embedding()


def salvar_documento(con, espaco, nome, paginas):
    trechos = dividir_em_trechos(paginas)
    total_paginas = max(p for p, _ in paginas)
    cursor = con.execute(
        "INSERT INTO documentos (espaco, nome, paginas, status) VALUES (?, ?, ?, 'indexando')",
        (espaco, nome, total_paginas),
    )
    documento_id = cursor.lastrowid
    con.executemany(
        "INSERT INTO trechos (documento_id, ordem, pagina, texto) VALUES (?, ?, ?, ?)",
        [(documento_id, i, p, t) for i, (p, t) in enumerate(trechos)],
    )
    indexar(con, documento_id)
    return documento_id, len(trechos)


# ---------------- 4. busca ----------------

def buscar(con, documento_ids, pergunta, quantidade=6):
    """Encontra os trechos com o significado mais próximo da pergunta (similaridade de cosseno)."""
    if not documento_ids:
        return []
    # documentos indexados com outro modelo de embedding precisam ser reindexados
    marcadores = ",".join("?" * len(documento_ids))
    for d in con.execute(
        f"SELECT id FROM documentos WHERE id IN ({marcadores}) AND COALESCE(modelo_embedding, '') != ?",
        (*documento_ids, modelo_atual()),
    ).fetchall():
        indexar(con, d["id"])

    linhas = con.execute(
        f"""SELECT t.texto, t.pagina, t.vetor, d.nome AS documento
            FROM trechos t JOIN documentos d ON d.id = t.documento_id
            WHERE t.documento_id IN ({marcadores}) AND t.vetor IS NOT NULL""",
        documento_ids,
    ).fetchall()
    if not linhas:
        return []

    matriz = np.vstack([np.frombuffer(l["vetor"], dtype=np.float32) for l in linhas])
    consulta = np.asarray(ia.gerar_embeddings([pergunta], tipo="pergunta")[0], dtype=np.float32)
    # vetores normalizados: o produto escalar já é a similaridade de cosseno (1 = mesmo sentido)
    notas = matriz @ consulta
    melhores = np.argsort(-notas)[:quantidade]
    return [
        {"texto": linhas[i]["texto"], "pagina": linhas[i]["pagina"], "documento": linhas[i]["documento"],
         "similaridade": round(float(notas[i]), 3)}
        for i in melhores
    ]
