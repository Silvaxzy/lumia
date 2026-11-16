/* LumIA — interface do chat */
const $ = (s) => document.querySelector(s);

const estado = {
    documentos: [],
    selecionados: new Set(),
    historico: [],        // [{ pergunta, resposta }] enviado junto para perguntas de continuação
    perguntando: false,
};

const ICONE_IA = '<svg class="avatar-ia" viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="14" fill="var(--petroleo)"/><path d="M15 10h13l7 7v21H15z" fill="#fff"/><rect x="18.5" y="22" width="13" height="5" rx="1.6" fill="var(--luz)"/><path d="M19 31h8" stroke="var(--petroleo)" stroke-width="2" stroke-linecap="round"/></svg>';

// ---------------- preferências (tema e tamanho do texto) ----------------

function salvarPreferencia(chave, valor) {
    try { localStorage.setItem(chave, valor); } catch (e) { /* navegador sem armazenamento: só não lembra */ }
}

function alternarTema() {
    const novo = document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro";
    document.documentElement.dataset.tema = novo;
    salvarPreferencia("lumia-tema", novo);
}

function alternarTamanhoTexto() {
    const grande = document.documentElement.dataset.texto !== "grande";
    if (grande) document.documentElement.dataset.texto = "grande";
    else delete document.documentElement.dataset.texto;
    $("#tamanho-texto").setAttribute("aria-pressed", String(grande));
    salvarPreferencia("lumia-texto", grande ? "grande" : "normal");
    avisar(grande ? "Texto aumentado." : "Texto no tamanho normal.");
}

// ---------------- utilidades ----------------

async function api(url, opcoes = {}) {
    const config = { headers: {}, ...opcoes };
    if (opcoes.body && !(opcoes.body instanceof FormData)) {
        config.headers["Content-Type"] = "application/json";
        config.body = JSON.stringify(opcoes.body);
    }
    let resposta;
    try {
        resposta = await fetch(url, config);
    } catch {
        throw new Error("Sem conexão com o servidor.");
    }
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(dados.erro || "Algo deu errado. Tente de novo.");
    return dados;
}

let timerToast;
function avisar(texto, tipo = "") {
    const t = $("#toast");
    t.textContent = texto;
    t.className = `toast visivel ${tipo}`;
    clearTimeout(timerToast);
    timerToast = setTimeout(() => (t.className = "toast"), 4000);
}

function escapar(texto) {
    const div = document.createElement("div");
    div.textContent = texto;
    return div.innerHTML;
}

function rolarParaBaixo() {
    const m = $("#mensagens");
    m.scrollTop = m.scrollHeight;
}

/** Markdown simples e seguro: escapa o HTML primeiro e depois aplica negrito, listas e citações [n]. */
function formatarResposta(texto) {
    const linhas = escapar(texto).split("\n");
    let html = "";
    let lista = null;
    const fecharLista = () => {
        if (lista) html += `</${lista}>`;
        lista = null;
    };
    for (const bruta of linhas) {
        const linha = bruta.trim();
        const item = linha.match(/^[-*•]\s+(.*)/);
        const numerado = linha.match(/^\d+[.)]\s+(.*)/);
        if (item || numerado) {
            const tipo = item ? "ul" : "ol";
            if (lista !== tipo) {
                fecharLista();
                html += `<${tipo}>`;
                lista = tipo;
            }
            html += `<li>${(item || numerado)[1]}</li>`;
        } else if (linha) {
            fecharLista();
            html += `<p>${linha.replace(/^#{1,4}\s+/, "")}</p>`;
        } else {
            fecharLista();
        }
    }
    fecharLista();
    return html
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\[(\d{1,2})\]/g, '<button type="button" class="cita" data-fonte="$1">$1</button>');
}

// ---------------- documentos ----------------

async function carregarDocumentos(selecionarId = null) {
    const primeiraVez = estado.documentos.length === 0 && estado.selecionados.size === 0;
    estado.documentos = await api("/api/documentos");
    const ids = new Set(estado.documentos.map((d) => d.id));
    estado.selecionados.forEach((id) => !ids.has(id) && estado.selecionados.delete(id));
    if (primeiraVez) estado.documentos.forEach((d) => estado.selecionados.add(d.id));
    if (selecionarId) estado.selecionados.add(selecionarId);
    renderDocumentos();
}

function renderDocumentos() {
    const ul = $("#lista-docs");
    ul.innerHTML = "";
    $("#contador-docs").textContent = estado.documentos.length;
    $("#contador-topo").textContent = estado.documentos.length;

    if (!estado.documentos.length) {
        ul.innerHTML = '<li class="lista-vazia">Nenhum documento ainda. Envie o primeiro no botão acima.</li>';
    }
    estado.documentos.forEach((d) => {
        const li = document.createElement("li");
        const marcado = estado.selecionados.has(d.id);
        li.className = `doc ${marcado ? "selecionado" : ""}`;

        const caixa = document.createElement("input");
        caixa.type = "checkbox";
        caixa.checked = marcado;
        caixa.setAttribute("aria-label", `Usar ${d.nome} nas respostas`);
        caixa.addEventListener("change", () => alternarDocumento(d.id));

        const info = document.createElement("div");
        info.className = "doc-info";
        info.addEventListener("click", () => alternarDocumento(d.id));
        const nome = document.createElement("span");
        nome.className = "doc-nome";
        nome.textContent = d.nome;
        nome.title = d.nome;
        const meta = document.createElement("span");
        meta.className = "doc-meta";
        meta.textContent = `${d.paginas} ${d.paginas === 1 ? "página" : "páginas"}`;
        if (d.exemplo) {
            const selo = document.createElement("span");
            selo.className = "selo-exemplo";
            selo.textContent = "Exemplo";
            meta.append(selo);
        }
        info.append(nome, meta);
        li.append(caixa, info);

        if (!d.exemplo) {
            const excluir = document.createElement("button");
            excluir.className = "excluir-doc";
            excluir.title = "Excluir documento";
            excluir.setAttribute("aria-label", `Excluir ${d.nome}`);
            excluir.innerHTML = '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
            excluir.addEventListener("click", () => excluirDocumento(d));
            li.append(excluir);
        }
        ul.append(li);
    });
    atualizarEscopo();
}

function alternarDocumento(id) {
    if (estado.selecionados.has(id)) estado.selecionados.delete(id);
    else estado.selecionados.add(id);
    renderDocumentos();
}

function atualizarEscopo() {
    const n = estado.selecionados.size;
    const nomes = estado.documentos.filter((d) => estado.selecionados.has(d.id)).map((d) => d.nome);
    const escopo = $("#escopo");
    escopo.textContent = n === 0 ? "Nenhum documento marcado" : "Lendo: ";
    if (n === 1) {
        const forte = document.createElement("strong");
        forte.textContent = nomes[0];
        escopo.append(forte);
    } else if (n > 1) {
        escopo.append(`${n} documentos`);
    }
    $("#enviar").disabled = estado.perguntando;
}

async function excluirDocumento(d) {
    if (!confirm(`Excluir "${d.nome}"?`)) return;
    try {
        await api(`/api/documentos/${d.id}`, { method: "DELETE" });
        estado.selecionados.delete(d.id);
        avisar("Documento excluído.");
        await carregarDocumentos();
    } catch (e) {
        avisar(e.message, "erro");
    }
}

async function enviarArquivo(arquivo) {
    if (!arquivo) return;
    if (arquivo.size > window.CONFIG.maxMb * 1024 * 1024) {
        avisar(`Arquivo muito grande. O limite é ${window.CONFIG.maxMb} MB.`, "erro");
        return;
    }
    const area = $("#area-envio");
    area.classList.add("enviando");
    $("#progresso").hidden = false;
    $("#envio-titulo").textContent = "Lendo o documento...";
    $("#envio-sub").textContent = arquivo.name;

    const dados = new FormData();
    dados.append("arquivo", arquivo);
    try {
        const r = await api("/api/documentos", { method: "POST", body: dados });
        await carregarDocumentos(r.id);
        avisar(`Pronto! "${r.nome}" foi lido (${r.paginas} ${r.paginas === 1 ? "página" : "páginas"}). Já pode perguntar.`);
        fecharLateral();
        $("#pergunta").focus();
    } catch (e) {
        avisar(e.message, "erro");
    } finally {
        area.classList.remove("enviando");
        $("#progresso").hidden = true;
        $("#envio-titulo").textContent = "Escolher um arquivo";
        $("#envio-sub").textContent = `ou arraste para cá. PDF, TXT ou MD de até ${window.CONFIG.maxMb} MB.`;
        $("#arquivo").value = "";
    }
}

// ---------------- conversa ----------------

function adicionarMensagemUsuario(texto) {
    $("#boas-vindas").hidden = true;
    const div = document.createElement("div");
    div.className = "msg msg-usuario";
    const bolha = document.createElement("div");
    bolha.className = "bolha";
    bolha.textContent = texto;
    div.append(bolha);
    $("#mensagens").append(div);
    rolarParaBaixo();
}

function adicionarCarregando() {
    const div = document.createElement("div");
    div.className = "msg msg-ia";
    div.innerHTML = `${ICONE_IA}<div class="corpo"><div class="pensando"><span class="pensando-linhas"><i></i><i></i><i></i></span><span class="etapa">Procurando no documento...</span></div></div>`;
    $("#mensagens").append(div);
    rolarParaBaixo();
    const etapa = div.querySelector(".etapa");
    const timer = setTimeout(() => (etapa.textContent = "Escrevendo a resposta..."), 1800);
    return { div, parar: () => clearTimeout(timer) };
}

function renderResposta(div, dados) {
    const citadas = new Set([...dados.resposta.matchAll(/\[(\d{1,2})\]/g)].map((m) => Number(m[1])));
    const corpo = div.querySelector(".corpo");
    corpo.innerHTML = `<div class="resposta">${formatarResposta(dados.resposta)}</div>`;

    // mostra as fontes citadas; se a IA não citou nenhuma, mostra as 3 mais parecidas
    const fontes = dados.fontes.filter((f) => citadas.has(f.numero));
    const mostrar = fontes.length ? fontes : dados.fontes.slice(0, 3);
    if (mostrar.length) {
        const bloco = document.createElement("div");
        bloco.className = "fontes";
        bloco.innerHTML = `<div class="fontes-titulo">${fontes.length ? "De onde veio a resposta" : "Trechos mais parecidos com a pergunta"}</div>`;
        const lista = document.createElement("div");
        lista.className = "fontes-lista";
        mostrar.forEach((f) => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = `fonte ${citadas.has(f.numero) ? "citada" : ""}`;
            b.innerHTML = `<b>${f.numero}</b><span></span><em>p. ${f.pagina}</em>`;
            b.querySelector("span").textContent = f.documento;
            b.setAttribute("aria-label", `Ver trecho ${f.numero}: ${f.documento}, página ${f.pagina}`);
            b.addEventListener("click", () => abrirFonte(f, dados.resposta));
            lista.append(b);
        });
        bloco.append(lista);
        corpo.append(bloco);
    }
    corpo.querySelectorAll(".cita").forEach((c) => {
        const f = dados.fontes.find((x) => x.numero === Number(c.dataset.fonte));
        if (f) {
            c.setAttribute("aria-label", `Ver trecho ${f.numero} do documento`);
            c.addEventListener("click", () => abrirFonte(f, dados.resposta));
        }
        else c.replaceWith(document.createTextNode(`[${c.dataset.fonte}]`));
    });
}

const PALAVRAS_VAZIAS = new Set("para pela pelo como mais mesmo isso essa esse esta este qual quais quando onde pode podem deve devem sobre entre também ainda cada todo toda todos todas seus suas você voce com sem que dos das nos nas uma umas uns por foi ser são sao tem têm estão está".split(" "));

function palavras(texto) {
    return (texto.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").match(/[a-z0-9]{3,}/g) || [])
        .filter((p) => !PALAVRAS_VAZIAS.has(p));
}

/** Marca no trecho as frases que mais combinam com o que a resposta disse ao citar essa fonte. */
function destacarTrecho(trecho, resposta, numero) {
    const citacoes = resposta.split(/(?<=[.!?\n])\s+/).filter((f) => f.includes(`[${numero}]`));
    const alvo = new Set(palavras(citacoes.join(" ") || resposta));
    const frases = trecho.split(/(?<=[.!?;:])\s+/);
    const notas = frases.map((f) => palavras(f).filter((p) => alvo.has(p)).length);
    const maior = Math.max(...notas);
    const quadro = document.createDocumentFragment();
    frases.forEach((frase, i) => {
        if (maior >= 2 && notas[i] >= Math.max(2, maior * 0.6)) {
            const m = document.createElement("mark");
            m.textContent = frase;
            quadro.append(m);
        } else {
            quadro.append(frase);
        }
        if (i < frases.length - 1) quadro.append(" ");
    });
    return quadro;
}

function abrirFonte(f, resposta) {
    $("#fonte-numero").textContent = `Trecho ${f.numero}`;
    $("#fonte-documento").textContent = f.documento;
    $("#fonte-meta").textContent = `Página ${f.pagina}. Semelhança com a pergunta: ${(f.similaridade * 100).toFixed(0)}%`;
    const bloco = $("#fonte-texto");
    bloco.innerHTML = "";
    bloco.append(destacarTrecho(f.texto, resposta || "", f.numero));
    $(".fonte-legenda").hidden = !bloco.querySelector("mark");
    $("#modal-fonte").showModal();
}

async function perguntar(texto) {
    texto = texto.trim();
    if (!texto || estado.perguntando) return;
    if (!estado.selecionados.size) {
        avisar("Marque pelo menos um documento na lista para a LumIA ler.", "erro");
        abrirLateral();
        return;
    }
    estado.perguntando = true;
    atualizarEscopo();
    adicionarMensagemUsuario(texto);
    const campo = $("#pergunta");
    campo.value = "";
    ajustarAltura();
    const carregando = adicionarCarregando();

    try {
        const dados = await api("/api/perguntar", {
            method: "POST",
            body: { pergunta: texto, documentos: [...estado.selecionados], historico: estado.historico.slice(-3) },
        });
        carregando.parar();
        renderResposta(carregando.div, dados);
        estado.historico.push({ pergunta: texto, resposta: dados.resposta });
    } catch (e) {
        carregando.parar();
        carregando.div.classList.add("msg-erro");
        carregando.div.querySelector(".corpo").innerHTML = '<div class="resposta"><p></p></div>';
        carregando.div.querySelector(".resposta p").textContent = e.message;
    } finally {
        estado.perguntando = false;
        atualizarEscopo();
        rolarParaBaixo();
        campo.focus();
    }
}

function novaConversa() {
    estado.historico = [];
    $("#mensagens").querySelectorAll(".msg").forEach((m) => m.remove());
    $("#boas-vindas").hidden = false;
    $("#pergunta").focus();
}

function ajustarAltura() {
    const c = $("#pergunta");
    c.style.height = "auto";
    c.style.height = `${Math.min(c.scrollHeight, 180)}px`;
}

// ---------------- menu lateral (celular) ----------------

function abrirLateral() {
    $("#lateral").classList.add("aberta");
    $("#sombra-lateral").classList.add("visivel");
}

function fecharLateral() {
    $("#lateral").classList.remove("aberta");
    $("#sombra-lateral").classList.remove("visivel");
}

// ---------------- eventos ----------------

function iniciar() {
    $("#form-pergunta").addEventListener("submit", (e) => {
        e.preventDefault();
        perguntar($("#pergunta").value);
    });
    $("#pergunta").addEventListener("input", ajustarAltura);
    $("#pergunta").addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {  // Enter envia, Shift+Enter quebra linha
            e.preventDefault();
            perguntar($("#pergunta").value);
        }
    });
    $("#sugestoes").querySelectorAll("button").forEach((b) =>
        b.addEventListener("click", () => {
            const exemplo = estado.documentos.find((d) => d.exemplo);
            if (exemplo && !estado.selecionados.has(exemplo.id)) {
                estado.selecionados.add(exemplo.id);
                renderDocumentos();
            }
            perguntar(b.textContent);
        })
    );
    $("#nova-conversa").addEventListener("click", novaConversa);
    $("#alternar-tema").addEventListener("click", alternarTema);
    $("#tamanho-texto").addEventListener("click", alternarTamanhoTexto);
    $("#tamanho-texto").setAttribute("aria-pressed", String(document.documentElement.dataset.texto === "grande"));
    $("#hero-enviar").addEventListener("click", () => $("#arquivo").click());
    $("#fechar-fonte").addEventListener("click", () => $("#modal-fonte").close());
    $("#modal-fonte").addEventListener("click", (e) => e.target === e.currentTarget && e.currentTarget.close());

    const area = $("#area-envio");
    $("#arquivo").addEventListener("change", (e) => enviarArquivo(e.target.files[0]));
    area.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), $("#arquivo").click()));
    ["dragenter", "dragover"].forEach((ev) => area.addEventListener(ev, (e) => {
        e.preventDefault();
        area.classList.add("arrastando");
    }));
    ["dragleave", "drop"].forEach((ev) => area.addEventListener(ev, () => area.classList.remove("arrastando")));
    area.addEventListener("drop", (e) => {
        e.preventDefault();
        enviarArquivo(e.dataTransfer.files[0]);
    });
    // soltar o arquivo fora da área não abre o PDF no navegador
    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => e.preventDefault());

    $("#abrir-lateral").addEventListener("click", abrirLateral);
    $("#fechar-lateral").addEventListener("click", fecharLateral);
    $("#sombra-lateral").addEventListener("click", fecharLateral);

    carregarDocumentos().catch((e) => avisar(e.message, "erro"));
    $("#pergunta").focus();
}

iniciar();
