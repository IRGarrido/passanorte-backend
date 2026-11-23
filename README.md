# PassaNorte Backend

Backend em adaptação para o MVP. A matriz de rastreabilidade é a fonte de verdade para requisitos; as decisões explícitas do projeto complementam/substituem os pontos indicados no [plano de implementação](docs/planning/PASSANORTE_IMPLEMENTATION_PLAN.md). O código legado não redefine requisitos.

A S1 estabelece build reproduzível, configuração explícita e segurança de sessões. Não representa a conclusão do MVP. Veja [evidências da S1](docs/implementation/S1.md) e [decisões de segurança e operação](docs/architecture/ADR-001-S1-security.md).

## Estado e arquitetura

Sete processos FastAPI independentes, Kong DB-less na borda, PostgreSQL 16/pgvector e RabbitMQ. Imagens fixadas por digest; Python 3.11.17; dependências em `uv.lock`. O runtime roda como UID 10001 e não contém uv, pytest, ruff ou mypy.

| Componente | Porta local | Responsabilidade atual |
| --- | --- | --- |
| Kong | 8000 | Roteamento /api/v1, JWT RS256, CORS, limite de requisições |
| auth | 8001 | Identidade, sessões, perfis e RBAC legado |
| catalog | 8002 | Pontos, categorias, eventos e ingressos |
| validation | 8003 | Validação de visitas |
| gamification | 8004 | Rotas, progresso e resgates legados |
| insights | 8005 | Indicadores e projeções |
| notifications | 8006 | Notificações e consumidor RabbitMQ |
| chatbot | 8007 | Adaptadores existentes; stub por padrão |
| PostgreSQL | 5432 | Persistência |
| RabbitMQ | 5672 / 15672 | AMQP / console administrativo |

Portas de serviços, banco e RabbitMQ são publicadas somente em 127.0.0.1. A porta 8000 é a entrada externa. TLS e políticas de exposição de produção devem ser configurados no ambiente de implantação.

**Transição planejada:** ainda existem sete databases e credencial de banco compartilhada. A S2 migra para **um database com schemas, ownership e usuários por domínio**. `employee` e brindes físicos ainda são legado a remover nas sprints próprias; o destino é Administrador, Fornecedor e Turista, sem brinde físico. Benefícios, Parceiros, Fornecedores e Guaranás seguem o plano. Notificações RabbitMQ pertencem ao MVP. Chatbot com Ollama/RAG é a última etapa, S8.

## Primeiro uso local

Pré-requisitos: Docker com Compose v2 e uv. No Windows, inicie Docker Desktop em modo Linux.

A partir da raiz:

```powershell
Copy-Item .env.example .env
uv sync --frozen
uv run --frozen python scripts/generate_secrets.py
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 180
uv run --frozen python scripts/smoke_s1.py
```

Em Linux/macOS use `cp .env.example .env`. O admin padrão de desenvolvimento usa o **email** admin@example.com; sua senha aleatória está no arquivo local `secrets/admin-password`, nunca nos logs. Leia-a privadamente para entrar. O gerador recusa diretório já existente, preservando chaves persistentes.

O script gera arquivos de desenvolvimento; produção deve provisionar os equivalentes via secret manager. Proteja a pasta com ACLs do host. Os arquivos são legíveis pelo UID do contêiner; no Linux a pasta pai privada restringe acesso no host. Não coloque segredos no Dockerfile, argumentos de build, Git, linha de comando ou logs.

`migrate` aplica Alembic por serviço, `seed` cria o admin somente se ausente, e a stack inicia os serviços após essas etapas. Um email existente de outro papel ou admin desativado causa falha, sem promoção nem reativação implícita.

Para parar mantendo os dados: `docker compose down`. **Não remova volumes ou regenere chaves para corrigir inicialização.** Credenciais de volumes existentes não são alteradas automaticamente pelo Compose; veja o procedimento de transição no ADR.

## Configuração

`.env` serve à **interpolação do Compose**. O contêiner recebe somente as variáveis declaradas em `environment` e os arquivos montados. O Python não carrega `.env` implicitamente. Para execução fora do Docker, use `uv run --env-file CAMINHO ...` com valores/arquivos próprios do host.

| Variável | Consumidor / política |
| --- | --- |
| APP_ENV | development, test ou production; padrão production. SQLite é permitido apenas em test |
| DATABASE_URL_FILE | Cada serviço recebe seu arquivo; URL postgresql+psycopg obrigatória |
| RABBITMQ_URL_FILE | Todos os serviços; obrigatório fora de test; sem fallback silencioso |
| JWT_PUBLIC_KEYS_DIR | Todos os serviços e Kong; diretório com arquivos KID.pem |
| JWT_PRIVATE_KEY_FILE / JWT_ACTIVE_KID | Somente auth; chave RSA privada correspondente ao KID ativo |
| JWT_ISSUER / JWT_AUDIENCE | Identidade esperada, iguais em todos os verificadores |
| ACCESS_TOKEN_MINUTES / REFRESH_TOKEN_DAYS | Padrões 15 / 7; intervalos aceitos 1–60 / 1–30 |
| PII_ENCRYPTION_KEY_FILE | Somente auth; chave Fernet ou lista ordenada nova,antiga durante rotação |
| PII_HMAC_KEY_FILE | Somente auth; chave independente, pelo menos 32 bytes |
| ADMIN_PASSWORD_FILE | Somente seed; entrada oculta também disponível no CLI interativo |
| DATABASE_URL_TEMPLATE_FILE | Somente migrate; template contendo {svc} |
| CATALOG_SERVICE_URL | validation; obrigatório fora de test |
| VALIDATION_SERVICE_URL | gamification; obrigatório fora de test |
| LLM_PROVIDER | chatbot: stub, ollama ou adaptador legado gemini |
| LLM_OLLAMA_URL / LLM_OLLAMA_MODEL | Nomes reais usados pelo adaptador Ollama |
| LLM_GEMINI_API_KEY_FILE | Somente para uso explícito do adaptador legado; não montado por padrão |
| SECRETS_DIR / ADMIN_EMAIL | Interpolação Compose: pasta de segredos e email do bootstrap |

Segredos também aceitam o nome sem `_FILE` para integração com gerenciadores externos. Definir ambos é erro. URLs, chaves e limites são validados; erros de configuração não incluem os valores sensíveis. Chaves não são geradas na inicialização.

## API e autenticação

Swagger por serviço: http://localhost:8001/docs até http://localhost:8007/docs. O schema está em `/openapi.json`; `/health` é liveness, não comprova conectividade de todas as dependências. A exposição consolidada de documentação via Kong pertence à S2.

Rotas principais de auth, com prefixo `http://localhost:8000/api/v1`:

| Método / rota | Contrato |
| --- | --- |
| POST /tourists | Cadastro legado, público |
| POST /session | email/password; retorna access_token, refresh_token, expires_in |
| POST /session/refresh | Corpo {"refresh_token":"..."}; retorna **novo par** |
| DELETE /session | Mesmo corpo; revoga a família da sessão; não exige access válido |
| GET /me | Authorization: Bearer ACCESS_TOKEN |
| PATCH /me | Atualização de perfil autenticado |

Access tokens usam RS256 e exigem assinatura, algoritmo, kid conhecido, exp, iat, sub, iss, aud, type, role e jti. Kong identifica a chave por `kid`; cada serviço repete a validação completa. Um refresh token não autoriza endpoints de negócio. Senhas: mínimo de 8 caracteres no cadastro e máximo de 72 bytes UTF-8, compatível com bcrypt.

O servidor guarda o hash do jti de refresh, usuário, família, expiração e revogação. Rotação é atômica. Reutilizar refresh consumido revoga a família, inclusive os descendentes: clientes devem serializar a renovação e substituir o par armazenado. Logout é idempotente enquanto o refresh apresentado for válido. Access já emitido continua válido até expirar (máximo configurado de 60 min; padrão 15); revogação imediata distribuída não é prometida.

## Desenvolvimento e verificações

```powershell
uv sync --frozen
uv lock --check
uv run --frozen ruff check src tests scripts
uv run --frozen mypy src
uv run --frozen pytest -q
uv run --frozen python scripts/check_secrets.py
uv run --frozen python scripts/smoke_s1.py
```

O scanner usa Docker/Gitleaks fixado por digest e analisa a árvore de trabalho visível ao Git (incluindo arquivos novos não ignorados), com achados redigidos. Não certifica o histórico Git nem arquivos locais ignorados. Os testes unitários/contrato usam SQLite e chaves efêmeras geradas exclusivamente nas fixtures; o smoke usa PostgreSQL, RabbitMQ e Kong reais.

A [CI](.github/workflows/ci.yml) executa lock, lint, tipagem, testes, scan, build e smoke. Documentos de serviços antigos podem conter nomenclatura anterior; este README e o plano prevalecem até sua revisão nas respectivas sprints.
