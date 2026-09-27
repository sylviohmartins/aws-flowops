// Presentation adapter for fixed English chrome in pinned third-party components.
// It never changes input values, options, graph state, API keys or result data.
export default function ({ parentElement }) {
  const messages = new Map(Object.entries({
    "Drag and drop file here": "Arraste e solte o arquivo aqui",
    "Drag and drop files here": "Arraste e solte os arquivos aqui",
    "Browse files": "Selecionar arquivo", "Upload": "Selecionar arquivo", "file upload": "Envio de arquivo", "Choose an option": "Escolha uma opção",
    "Choose options": "Escolha as opções", "Choose a date": "Escolha uma data",
    "No results": "Nenhum resultado", "No options": "Nenhuma opção",
    "Press Enter to apply": "Pressione Enter para aplicar",
    "Press Ctrl+Enter to apply": "Pressione Ctrl+Enter para aplicar",
    "Press ⌘+Enter to apply": "Pressione ⌘+Enter para aplicar",
    "Deploy": "Implantar", "Settings": "Configurações", "Rerun": "Executar novamente",
    "Auto rerun": "Atualizar automaticamente", "System": "Sistema", "Light": "Claro", "Dark": "Escuro",
    "Main menu": "Menu da aplicação", "Theme": "Tema", "Record screen": "Gravar tela",
    "Clear cache": "Limpar cache", "Print": "Imprimir", "About": "Sobre",
    "View app source": "Ver código da aplicação", "Record a screencast": "Gravar a tela",
    "Share": "Compartilhar", "Close": "Fechar", "Cancel": "Cancelar",
    "Download": "Baixar", "Search": "Buscar", "Fullscreen": "Tela cheia",
    "Download as CSV": "Baixar como CSV", "Copy to clipboard": "Copiar",
    "Copy": "Copiar", "Copied!": "Copiado!", "Show password text": "Mostrar texto",
    "Hide password text": "Ocultar texto", "Remove file": "Remover arquivo",
    "Edit Edge": "Editar conexão", "Delete Edge": "Excluir conexão",
    "Edit Edge Properties": "Editar propriedades da conexão", "Save Changes": "Salvar alterações",
    "Label": "Ramo da conexão", "Animated": "Animada", "Deletable": "Pode ser excluída",
    "Edge Type": "Tipo de conexão", "Type": "Tipo", "Source": "Origem", "Target": "Destino",
    "Zoom In": "Ampliar", "Zoom Out": "Reduzir", "Fit View": "Ajustar à área",
    "Toggle Interactivity": "Alternar interação", "zoom in": "Ampliar",
    "zoom out": "Reduzir", "fit view": "Ajustar à área", "toggle interactivity": "Alternar interação",
    "React Flow mini map": "Minimapa do fluxo", "Collapse sidebar": "Recolher menu",
    "Expand sidebar": "Expandir menu", "Close dialog": "Fechar janela",
    "Running...": "Executando...", "Stop": "Parar", "Please wait...": "Aguarde..."
  }));
  const observers = new Map();
  const frameListeners = new Map();
  const rootDocument = parentElement.ownerDocument;
  const originalLanguages = new Map();
  const scope = '[data-testid="stFileUploader"], [data-testid="stToolbar"], [data-testid^="stMainMenu"], [data-testid="stElementToolbar"], [data-testid="stInputInstructions"], [data-baseweb="popover"], .react-flow__controls, .btn-group, .btn-group-vertical, .modal';
  function translated(value) {
    const word = value.trim();
    const localized = messages.get(word);
    if (localized) return value.replace(word, localized);
    if (word.startsWith("Made with Streamlit")) return value.replace("Made with Streamlit", "Feito com Streamlit");
    if (/^(?:Limit )?\d+(?:\.\d+)?[KMGT]?B per file/.test(word)) {
      return value.replace(/^Limit /, "Limite de ").replace(" per file", " por arquivo");
    }
    return value;
  }
  function update(doc) {
    // Live execution replaces frames frequently; do not retain detached documents.
    frameListeners.forEach((callback, frame) => {
      if (!frame.isConnected) { frame.removeEventListener("load", callback); frameListeners.delete(frame); }
    });
    observers.forEach((observer, observed) => {
      if (observed === rootDocument) return;
      const frame = observed.defaultView?.frameElement;
      if (!frame?.isConnected || frame.contentDocument !== observed) {
        observer.disconnect(); observers.delete(observed); originalLanguages.delete(observed);
      }
    });
    doc.querySelectorAll(scope).forEach(root => {
      const walker = doc.createTreeWalker(root, 4);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(node => {
        if (node.parentElement?.closest('pre, code, textarea, input, [translate="no"], [data-testid="stJson"], [role="grid"], [role="option"]')) return;
        const value = translated(node.nodeValue);
        if (value !== node.nodeValue) node.nodeValue = value;
      });
    });
    doc.querySelectorAll('button, input, [role="button"], [data-testid="stMainMenuList"], [data-testid="stThemeSwitcher"], .react-flow__minimap').forEach(element => {
      for (const name of ["aria-label", "title", "placeholder"]) {
        const value = element.getAttribute(name);
        if (value && translated(value) !== value) element.setAttribute(name, translated(value));
      }
    });
    doc.querySelectorAll('[data-testid="stMainMenuList"] [data-testid="stIconMaterial"]').forEach(icon => icon.setAttribute("aria-hidden", "true"));
    // Streamlit's upload icon contributes "upload" to the accessible name.
    doc.querySelectorAll('[data-testid="stFileUploaderDropzone"] button').forEach(button => {
      if (button.textContent.includes("Selecionar arquivo") && button.getAttribute("aria-label") !== "Selecionar arquivo") button.setAttribute("aria-label", "Selecionar arquivo");
    });
    doc.querySelectorAll('iframe[title="streamlit_flow.streamlit_flow"]').forEach(frame => {
      const attach = () => { try { if (frame.contentDocument) observe(frame.contentDocument); } catch (_) { /* Cross-origin hosts retain upstream chrome. */ } };
      if (!frameListeners.has(frame)) { frame.addEventListener("load", attach); frameListeners.set(frame, attach); }
      attach();
    });
  }
  function observe(doc) {
    if (observers.has(doc) || !doc.body) return;
    originalLanguages.set(doc, doc.documentElement.lang);
    doc.documentElement.lang = "pt-BR";
    const observer = new MutationObserver(() => update(doc));
    observers.set(doc, observer);
    update(doc);
    observer.observe(doc.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["placeholder", "title", "aria-label"] });
  }
  observe(rootDocument);
  return () => {
    observers.forEach(observer => observer.disconnect());
    frameListeners.forEach((callback, frame) => frame.removeEventListener("load", callback));
    originalLanguages.forEach((language, doc) => { if (doc.documentElement.lang === "pt-BR") doc.documentElement.lang = language; });
  };
}
