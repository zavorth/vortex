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

### Produção e HTTPS

Se o app for exposto na rede (não apenas local), configure HTTPS via reverse proxy. O Flask NÃO deve servir HTTPS diretamente — use um reverse proxy.

**nginx com SSL (recomendado)**

```nginx
server {
    listen 443 ssl http2;
    server_name vortex.local;

    ssl_certificate     /etc/letsencrypt/live/vortex.local/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vortex.local/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

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

        # Timeouts para downloads grandes
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name vortex.local;
    return 301 https://$host$request_uri;
}
```

**Let's Encrypt (SSL gratuito)**

Para obter certificados SSL gratuitos via Let's Encrypt:

```bash
# Instalar certbot
sudo apt install certbot python3-certbot-nginx

# Obter certificado (nginx precisa estar rodando na porta 80)
sudo certbot --nginx -d vortex.local

# Auto-renovação (verifica duas vezes ao dia)
sudo systemctl status certbot.timer
```

Os certificados são renovados automaticamente. O caminho dos certificados no config acima (`/etc/letsencrypt/live/vortex.local/`) é o padrão do certbot.

**Opção 2: Caddy (mais simples)**
```
vortex.local {
    reverse_proxy 127.0.0.1:8080
}
```
Caddy gera e renova certificados automaticamente.

**Opção 3: ngrok (testes rápidos)**
```bash
ngrok http 8080
```

> **Importante:** Ao usar HTTPS, atualize o `host_permissions` no `manifest.json` da extensão para incluir o domínio HTTPS.

### Variáveis de Ambiente

| Variável | Descrição | Padrão |
|---|---|---|
| `VORTEX_LOG_LEVEL` | Nível de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `VORTEX_LOG_FILE` | Caminho do arquivo de log (vazio = apenas console) | vazio |

```bash
# Exemplo: log em arquivo com nível DEBUG
export VORTEX_LOG_LEVEL=DEBUG
export VORTEX_LOG_FILE=/var/log/vortex.log
python app.py
```

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
│   ├── download_engine.py  # Motor de downloads com resume/paralelo
│   ├── file_safety.py      # Validação de paths e cookies
│   └── rate_limiter.py     # Rate limiting por IP
├── extractors/             # Plugins de extração de mídia
├── extension/              # Extensão Chrome/Edge
├── static/                 # Frontend (JS, CSS, imagens)
├── templates/              # Templates HTML
├── saved_cookies/          # Cookies importados (gitignored)
├── allowed_extensions.txt  # IDs de extensões permitidas
├── proxy_config.json       # Configuração de proxy (gerado automaticamente)
├── test_security.py        # Testes de segurança
└── requirements.txt        # Dependências Python
```
