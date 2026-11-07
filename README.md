# Cobra Fácil

Sistema de gestão de crediário próprio e cobranças. O backend permite cadastrar clientes, registrar vendas com entrada e parcelamento, receber pagamentos parciais ou completos, manter estornos rastreáveis e consultar o saldo devedor por cliente.

## Tecnologias

- Python 3.12 (versão local indicada em `backend/.python-version`).
- Django 5.2 e Django REST Framework.
- PostgreSQL 17 e Docker Compose v2.
- Autenticação por sessão Django, com CSRF nas escritas da API.
- Frontend planejado em React + TypeScript; ainda será desenvolvido.

As versões das dependências Python estão fixadas em `backend/requirements.txt`.

## Estrutura

```text
cobra_facil/
├── backend/
│   ├── apps/
│   │   ├── clientes/
│   │   ├── vendas/
│   │   ├── financeiro/
│   │   └── cobrancas/
│   ├── config/
│   ├── docs/financeiro.md
│   ├── .env.example
│   ├── manage.py
│   └── requirements.txt
├── frontend/          # reservado para React + TypeScript
├── infra/
│   ├── .env.example
│   └── compose.yaml
├── docs/              # documentação geral
├── .gitignore
└── README.md
```

`frontend/` e `docs/` contêm um `.gitkeep` para preservar os diretórios no Git.

## Requisitos

Instale Git, Python 3.12 com suporte a `venv`, Docker Engine e Docker Compose v2. Confirme que as portas locais 5433 (PostgreSQL) e 8000 (Django) estão disponíveis. Os comandos abaixo usam Bash e assumem o projeto em `~/cobra_facil`.

## Variáveis de ambiente

Em uma instalação nova, crie os arquivos locais a partir dos exemplos, preservando arquivos já existentes:

```bash
cd ~/cobra_facil
cp -n backend/.env.example backend/.env
cp -n infra/.env.example infra/.env
```

Edite os arquivos locais e substitua os marcadores. Gere uma chave para `SECRET_KEY`, por exemplo com `python -c 'import secrets; print(secrets.token_urlsafe(50))'`, usando o Python 3.12 instalado. Defina uma senha local própria e use o mesmo valor em `infra/.env` (`POSTGRES_PASSWORD`) e em `backend/.env` (`DB_PASSWORD`). Não use os valores ilustrativos como credenciais.

| Arquivo | Variável | Uso local |
|---|---|---|
| `backend/.env` | `DEBUG` | `True` somente no desenvolvimento |
| `backend/.env` | `SECRET_KEY` | chave aleatória local |
| `backend/.env` | `DB_NAME` | `cobra_facil` |
| `backend/.env` | `DB_USER` | `cobra_facil` |
| `backend/.env` | `DB_PASSWORD` | senha correspondente ao PostgreSQL |
| `backend/.env` | `DB_HOST` | `127.0.0.1` |
| `backend/.env` | `DB_PORT` | `5433` |
| `infra/.env` | `POSTGRES_PASSWORD` | senha inicial do PostgreSQL |

O Compose define o nome e o usuário do banco como `cobra_facil`. A senha de inicialização é aplicada quando o volume é criado pela primeira vez; alterar o arquivo de ambiente não muda a senha de um banco já inicializado. Em ambiente existente, mantenha as credenciais que já funcionam e preserve o volume.

Os arquivos `.env` e as credenciais ficam fora do Git. Apenas os exemplos devem ser versionados.

## PostgreSQL

```bash
cd ~/cobra_facil

docker compose --env-file infra/.env -f infra/compose.yaml up -d

docker compose --env-file infra/.env -f infra/compose.yaml ps
```

O PostgreSQL é exposto em `127.0.0.1:5433` e seus dados persistem no volume `postgres_data`. Aguarde o serviço ficar saudável antes de executar migrações ou testes. Para interromper o serviço, use o mesmo comando Compose com `stop`. Não remova o volume para tarefas rotineiras de desenvolvimento ou testes.

## Backend

Na primeira instalação, crie o ambiente virtual (se ele ainda não existir) e instale as dependências:

```bash
cd ~/cobra_facil/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Com o ambiente configurado, confira o projeto e o plano de migrações:

```bash
python manage.py check
python manage.py migrate --plan
```

Aplique as migrações necessárias e inicie o servidor:

```bash
cd ~/cobra_facil/backend
source .venv/bin/activate

python manage.py migrate
python manage.py runserver
```

Acesse o Django em <http://127.0.0.1:8000/>. As rotas disponíveis são `/admin/` e `/api/`; a raiz não possui uma página inicial.

## Django Admin e API

Na primeira instalação, crie seu usuário administrativo:

```bash
python manage.py createsuperuser
```

Acesse <http://127.0.0.1:8000/admin/> com o usuário criado. A API usa a sessão Django e exige token CSRF nas escritas autenticadas. Os registros financeiros no Admin são somente para consulta; use os endpoints da API para operações financeiras.

Consulte [a documentação financeira](backend/docs/financeiro.md) para regras, payloads, endpoints e idempotência.

## Testes

Com PostgreSQL disponível e o ambiente virtual ativo:

```bash
cd ~/cobra_facil/backend
source .venv/bin/activate
python manage.py check
python manage.py test
```

O Django cria e remove um banco separado, por padrão `test_cobra_facil`; o usuário local de testes precisa de permissão para criar esse banco. Antes de executar, confirme que o nome de teste é diferente do principal e que não pertence a outro ambiente. Não confirme a remoção de um banco existente sem verificar sua finalidade. Não use `--keepdb` sem verificar o destino. Não use `flush` no banco principal.

Para executar apenas a integração do crediário:

```bash
python manage.py test apps.financeiro.test_fluxo_crediario_integracao
```

A integração exige PostgreSQL real, confere o banco conectado com prefixo `test_`, controla a data de referência e valida sessão, CSRF, histórico e saldo. A suíte também contém testes de concorrência com conexões reais. Não substitua PostgreSQL por SQLite para validar o comportamento financeiro completo.

## Desenvolvimento e Git

- Use um único repositório na raiz, com branch principal `main`.
- Preserve migrações, testes, documentação e configurações necessárias no versionamento.
- Mantenha ambientes virtuais, dependências instaladas, caches, dados locais e credenciais fora do Git.
- Use strings decimais nos valores monetários da API e os serviços transacionais para escritas financeiras.
- Execute `python manage.py check` e `python manage.py test` antes de preparar uma alteração.
- Revise `git status`, `git diff --cached --stat` e o conteúdo preparado antes de criar um commit.

A preparação inicial não cria commits nem configura um remoto. Após revisar os arquivos, criar o primeiro commit e confirmar a URL de um repositório **privado** no GitHub, os comandos de conexão serão:

```bash
git remote add origin <URL_DO_REPOSITORIO_PRIVADO>
git push -u origin main
```

Esses comandos são instruções para uma etapa posterior; nenhum remoto é necessário para desenvolvimento local.
