# Vortex Media Downloader

Vortex é um gerenciador e extrator de downloads de mídia local projetado para rodar em conjunto com uma extensão do navegador Chrome/Edge.

## Funcionalidades
*   **Extração Inteligente de Mídia:** Suporte a plugins extratores específicos para redes sociais e fallback inteligente com scraping genérico de HTML.
*   **Proxy CORS Local:** Rota de proxy integrada com proteção contra SSRF para carregar imagens e mídias ignorando restrições de cabeçalho Referer.
*   **Monitor de Downloads em Tempo Real:** Extensão do navegador integrada com feedback visual de velocidade e progresso percentual.
*   **Gerenciador de Cookies:** Suporte a carregamento de arquivos de cookies Mozilla/Netscape para download de mídias restritas.

## Como Executar

### Pré-requisitos
*   Python 3.10 ou superior
*   Dependências listadas no `requirements.txt`

### Inicialização
1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
2. Execute o servidor Flask localmente:
   ```bash
   python app.py
   ```
   O servidor iniciará em `http://127.0.0.1:8080` por padrão.

## Segurança e Autorização da Extensão

### Autorização de Extensão por ID
Para evitar que outras extensões do Chrome não autorizadas abusem das APIs locais do Vortex, o servidor valida o ID de origem (`Origin: chrome-extension://<id>`).

*   Ao rodar o app pela primeira vez, o arquivo `allowed_extensions.txt` será criado na raiz.
*   Para permitir que sua extensão se comunique com o servidor, adicione o ID gerado pelo Chrome no arquivo `allowed_extensions.txt` (uma entrada por linha).
*   Se o ID não estiver cadastrado, a chamada será bloqueada com um erro `403 Forbidden` e um aviso será registrado no terminal.
