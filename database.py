"""Banco SQLite: documentos, trechos (com o embedding de cada um) e registro de uso."""
import os
import sqlite3

CAMINHO = os.environ.get("BANCO", os.path.join(os.path.dirname(os.path.abspath(__file__)), "documentos.db"))


def conectar():
    con = sqlite3.connect(CAMINHO, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def criar_tabelas():
    with conectar() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS documentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                espaco TEXT NOT NULL,              -- quem enviou (cada visitante tem o seu) ou 'publico'
                nome TEXT NOT NULL,
                paginas INTEGER NOT NULL,
                modelo_embedding TEXT,             -- modelo usado para indexar
                status TEXT NOT NULL DEFAULT 'pronto',
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS trechos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                documento_id INTEGER NOT NULL,
                ordem INTEGER NOT NULL,
                pagina INTEGER NOT NULL,
                texto TEXT NOT NULL,
                vetor BLOB,                        -- embedding (float32, normalizado)
                FOREIGN KEY (documento_id) REFERENCES documentos (id) ON DELETE CASCADE
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_trechos_doc ON trechos (documento_id, ordem)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS respostas_salvas (
                chave TEXT PRIMARY KEY,            -- pergunta + documentos (para não gastar a cota com perguntas repetidas)
                resposta TEXT NOT NULL,
                fontes TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS uso (
                espaco TEXT NOT NULL,
                momento TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS ix_uso ON uso (espaco, momento)")
