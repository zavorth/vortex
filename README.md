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

## Segurança

### Proteção SSRF (Proxy)
As rotas `/api/proxy` e `/api/proxy-image` validam URLs antes de fazer requisições:
- Resolução DNS + validação de IP (bloqueia loopback, private, link-local, multicast, unspecified)
- Redirects manuais com revalidação em cada salto
- Limite de tamanho de resposta (100 MB para proxy, 10 MB para imagens)
- Bloqueio de redirects cross-host

### Autorização de Extensão por ID (Fail-Closed)
O servidor valida o ID de origem (`Origin: chrome-extension://<id>`) em todas as rotas `/api/`.

*   Por padrão, **todas as extensões são bloqueadas** (fail-closed)
*   Crie o arquivo `allowed_extensions.txt` e adicione o ID da sua extensão
*   Para encontrar o ID: `chrome://extensions` → Modo desenvolvedor → copie o ID (24 caracteres)
*   Modo desenvolvimento (permite qualquer extensão): defina a variável de ambiente `VORTEX_DEV_ALLOW_ANY_EXTENSION=true`

### Rate Limiting
Requisições de API possuem limite por IP:
- **Endpoints leves** (proxy, upload de cookies): 60 requisições/minuto
- **Endpoints pesados** (analyze, download, update-ytdl): 10 requisições/minuto
- Ao exceder o limite, retorna HTTP 429 com mensagem de erro

### Segurança de Cookies
*   O frontend envia apenas um `cookie_id` (nome de arquivo), nunca um path absoluto
*   O servidor resolve o `cookie_id` para o path real dentro de `saved_cookies/`
*   Paths absolutos, traversal (`../`), extensões inválidas e arquivos > 5 MB são rejeitados

### Auditoria da Extensão Chrome
A extensão (`extension/popup.js`) **não** envia dados de cookies ou paths para a API. Ela apenas:
1. Abre a URL do Vortex web UI com o link da página atual
2. Faz polling do endpoint `/api/status` (somente leitura)

Nenhuma alteração na extensão é necessária para a segurança de cookies.

### Rodando com HTTPS (Produção)
Se o app for exposto na rede (não apenas local), configure HTTPS via reverse proxy:

**Opção 1: nginx (recomendado)**
```nginx
server {
    listen 443 ssl;
    server_name vortex.local;

    ssl_certificate     /etc/ssl/certs/vortex.pem;
    ssl_certificate_key /etc/ssl/private/vortex.key;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (HLS)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Opção 2: Caddy (mais simples)**
```
vortex.local {
    tls /etc/ssl/certs/vortex.pem /etc/ssl/private/vortex.key
    proxy / 127.0.0.1:8080
}
```

**Opção 3: ngrok (testes rápidos)**
```bash
ngrok http 8080
```
Isso gera uma URL HTTPS pública temporária.

> **Importante:** Ao usar HTTPS, atualize o `host_permissions` no `manifest.json` da extensão para incluir o domínio HTTPS.

## Rodando Testes

```bash
# Com venv ativo:
python -m unittest test_security -v

# Testes cobrem:
# - SSRF: IPs loopback, privados, link-local, multicast, unspecified, IPv6
# - Redirects cross-host e para IPs bloqueados
# - Cookie paths: traversal, absolutos, extensões inválidas
# - Path boundary: directory traversal
```

## Estrutura do Projeto

```
vortex/
├── app.py                  # Servidor Flask principal
├── services/
│   ├── proxy_safety.py     # Validação de URLs e proxy seguro
│   ├── file_safety.py      # Validação de paths e cookies
│   └── rate_limiter.py     # Rate limiting por IP
├── extractors/             # Plugins de extração de mídia
├── extension/              # Extensão Chrome/Edge
├── static/                 # Frontend (JS, CSS, imagens)
├── templates/              # Templates HTML
├── saved_cookies/          # Cookies importados (gitignored)
├── allowed_extensions.txt  # IDs de extensões permitidas
├── test_security.py        # Testes de segurança
└── requirements.txt        # Dependências Python
```
