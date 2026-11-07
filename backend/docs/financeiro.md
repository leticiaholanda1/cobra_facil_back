# Vendas e financeiro — Cobra Fácil

## Arquitetura e arquivos

- `apps/vendas/models.py`: Venda e ItemVenda; `services.py`: confirmação e cancelamento transacionais.
- `apps/financeiro/models.py`: Parcela e Pagamento; `services.py`: recebimentos, estornos e resumo financeiro.
- `apps/financeiro/domain.py`: valores monetários, validação de usuário e idempotência.
- `apps/financeiro/base.py`: bloqueio de gravações pelo ORM comum, alterações em lote e exclusões físicas.
- Cada aplicativo possui serializers, views, URLs, Admin e testes próprios.
- `apps/clientes/views.py`: somente acrescenta a ação `resumo-financeiro`.
- `config/urls.py`: inclui as rotas novas.
- Migrações novas: `vendas/0001_initial`, `financeiro/0001_initial` e `financeiro/0002_initial`.

Relacionamentos protegidos com `PROTECT`: Cliente → Venda → ItemVenda/Parcela/Pagamento; usuários responsáveis também são protegidos. Um pagamento de parcela aponta para a venda e a parcela. Uma entrada aponta somente para a venda. Clientes inativos mantêm seu histórico consultável; apenas novas vendas são bloqueadas.

## Regras financeiras

- Valores usam `Decimal`, no máximo 12 dígitos inteiros e duas casas decimais. Os serviços rejeitam `float`, valores não finitos e frações de centavo. Envie dinheiro em strings JSON.
- Venda precisa de itens com descrição, quantidade inteira positiva e preço positivo. O backend calcula totais; `valor_total`, quando enviado, serve apenas para conferir a soma dos itens.
- `valor_financiado`, valores de itens, saldos, usuário responsável e estados não são aceitos como campos de escrita.
- A entrada é um Pagamento de tipo `entrada`, criado na mesma transação da venda, com forma de recebimento e responsável. Não integra pagamentos das parcelas.
- À vista: entrada igual ao total, quantidade de parcelas zero, primeiro vencimento ausente ou `null`. Não há parcelas de valor zero.
- Financiada: saldo positivo, 1 a 1200 parcelas e primeiro vencimento obrigatório. O limite de 1200 evita geração de planos excessivos. Cada parcela precisa valer ao menos R$ 0,01.
- A divisão trunca para centavos e deixa a diferença na última parcela: R$ 100,00 / 3 = R$ 33,33 + R$ 33,33 + R$ 33,34.
- Vencimentos usam meses de calendário, com o dia original como âncora. 31/jan → 28 ou 29/fev → 31/mar → 30/abr. Não são intervalos de 30 dias.
- Uma parcela vencida continua vencida mesmo após pagamento parcial. Vencimento hoje ainda não é atraso. Datas usam `timezone.localdate()` e o fuso já configurado no Django.
- Valor pago, saldo, situação e quitação são derivados dos pagamentos válidos. Estorno retira o pagamento desses cálculos e reabre a parcela quando necessário.
- Datas de pagamento podem ser informadas com fuso, sem data futura; quando omitidas, o backend registra o instante atual. A data de criação preserva quando o lançamento entrou no sistema.
- Nenhum lançamento pode ser editado ou excluído pelas interfaces. Correções exigem estorno com motivo, responsável e data, mantendo o lançamento original. Para corrigir um recebimento, estorne-o e registre outro com nova chave.
- Todas as operações financeiras são atômicas. A ordem dos bloqueios é cliente → venda → parcela/pagamento. O bloqueio do cliente também mantém o resumo consistente e o da venda impede corrida entre cancelamento e recebimento.
- Restrições no PostgreSQL verificam valores positivos, entrada, valor financiado, cálculo dos itens, número único da parcela, entrada única e rastreabilidade dos estornos/cancelamentos. Soma de itens e limite acumulado de pagamentos são garantidos pelos serviços sob transação e bloqueio.

## Idempotência

POST de venda e de pagamento exige `chave_idempotencia`, um UUID gerado pelo consumidor. Guarde a chave antes de enviar e reutilize-a em tentativas da mesma operação. Chaves são únicas por tipo de recurso. A mesma chave e os mesmos dados, pelo mesmo usuário, retornam o mesmo registro (HTTP 201 também no replay), sem novo lançamento. A chave com dados diferentes retorna HTTP 400. Após estorno, repetir a chave original retorna o lançamento estornado; não recria o recebimento.

Cancelamento e estorno são idempotentes pelo recurso de destino: repetir o mesmo motivo retorna o registro existente, preservando o responsável e a data originais; outro motivo retorna erro. Use uma chave nova para cada nova venda ou recebimento.

## Cancelamento e decisões conservadoras

Cancelamento não apaga itens, parcelas ou pagamentos. Todos os recebimentos válidos, inclusive entrada, devem ser estornados explicitamente antes de cancelar. O estorno é uma correção contábil rastreável; não executa devolução de dinheiro. A conferência e eventual devolução ao cliente são procedimentos manuais da loja, fora desta tarefa.

Após estornar a entrada de uma venda ainda ativa, o valor reaparece no saldo devedor e no campo `saldo_entrada_estornada`. Não é convertido silenciosamente em novas parcelas. Para refazer o plano ou substituir uma entrada incorreta, estorne os recebimentos, cancele a venda e registre outra. Renegociação, reembolso e recuperação de entrada em venda existente exigem regras futuras.

O resumo considera apenas vendas ativas; vendas canceladas continuam disponíveis nas consultas de histórico. `total_compras` é o total das compras ativas. `parcelas_pendentes` inclui pendentes e parciais que ainda não venceram; vencidas e quitadas têm contadores próprios. A entrada quitada não conta como parcela quitada. O saldo é a soma dos saldos das parcelas mais eventual entrada estornada de venda ativa.

A listagem de parcelas mantém também parcelas de vendas canceladas, com `venda_status` explícito. Seu status financeiro histórico segue valor pago e vencimento; use `venda_status=ativa` para cobrança operacional. O resumo exclui todas as parcelas de vendas canceladas.

Permissões seguem Clientes: qualquer usuário ativo autenticado pode consultar e registrar operações. Separação de funções entre operador, caixa e gerente é uma decisão futura. Não foram criados juros, multas, descontos ou reembolsos automáticos.

## API

Autenticação por sessão Django preservada. Faça login em `/admin/` com o usuário existente. No mesmo navegador, a API navegável utiliza a sessão. Escritas precisam do cookie de sessão e token CSRF; no futuro frontend, envie `X-CSRFToken`. Não há autenticação por senha em cabeçalhos ou novos tokens.

| Método | Endpoint |
|---|---|
| GET, POST | `/api/vendas/` |
| GET | `/api/vendas/{id}/` |
| POST | `/api/vendas/{id}/cancelar/` |
| GET | `/api/vendas/{id}/parcelas/` |
| GET | `/api/parcelas/` |
| GET | `/api/parcelas/{id}/` |
| GET, POST | `/api/pagamentos/` |
| GET | `/api/pagamentos/{id}/` |
| POST | `/api/pagamentos/{id}/estornar/` |
| GET | `/api/clientes/{id}/resumo-financeiro/` |

Listagens paginadas de 25: `{ "count": 4, "next": null, "previous": null, "results": [...] }`. Valores monetários são strings com duas casas. DELETE, PUT e PATCH financeiros retornam 405. Usuário sem sessão recebe 403 conforme SessionAuthentication existente. Validação retorna 400 com campos estruturados; recurso inexistente em URL de detalhe retorna 404.

Filtros:

- Vendas: `cliente`, `status=ativa|cancelada`, `data_inicio`, `data_fim` (data da venda).
- Parcelas: `cliente`, `venda`, `venda_status=ativa|cancelada`, `status=pendente|parcial|vencida|paga`, `vencimento_inicio`, `vencimento_fim`.
- Pagamentos: `cliente`, `venda`, `parcela`, `tipo=entrada|parcela`, `status=valido|estornado`, `data_inicio`, `data_fim` (data do pagamento no fuso configurado).
- Datas no formato `AAAA-MM-DD`; limites inclusivos. `page=2` para avançar.

## Testar o fluxo pela API

Use um cliente ativo real já existente. Os exemplos abaixo são apenas documentação; não são inseridos automaticamente no banco.

1. POST `/api/vendas/`, substituindo o ID do cliente e usando um UUID novo:

```json
{
  "cliente": 1,
  "itens": [{"descricao": "Geladeira", "quantidade": 1, "valor_unitario": "2400.00"}],
  "valor_total": "2400.00",
  "valor_entrada": "400.00",
  "forma_entrada": "pix",
  "quantidade_parcelas": 4,
  "primeiro_vencimento": "2026-12-10",
  "chave_idempotencia": "a94d7a6b-c76e-40a7-952e-93ea2837b32b"
}
```

A resposta 201 inclui IDs, itens e quatro parcelas de R$ 500,00. Trecho ilustrativo:

```json
{
  "id": 1,
  "valor_total": "2400.00",
  "valor_entrada": "400.00",
  "valor_financiado": "2000.00",
  "status": "ativa",
  "parcelas": [{"id": 1, "numero": 1, "valor_original": "500.00", "valor_pago": "0.00", "saldo_restante": "500.00", "status": "pendente"}]
}
```

2. POST `/api/pagamentos/` com o ID real de uma parcela:

```json
{
  "parcela": 1,
  "valor": "200.00",
  "forma_pagamento": "pix",
  "chave_idempotencia": "d55e0331-9816-4d28-9346-586275b237d5"
}
```

3. GET `/api/parcelas/1/`: valor pago R$ 200,00, saldo R$ 300,00, situação parcial ou vencida conforme a data. Registre R$ 300,00 com outra chave para quitar. Os dois pagamentos permanecem no histórico.

4. GET `/api/clientes/1/resumo-financeiro/` após o primeiro pagamento:

```json
{
  "total_compras": "2400.00",
  "total_entradas_recebidas": "400.00",
  "total_pago_parcelas": "200.00",
  "total_efetivamente_pago": "600.00",
  "saldo_devedor": "1800.00",
  "saldo_entrada_estornada": "0.00",
  "parcelas_pendentes": 4,
  "parcelas_vencidas": 0,
  "parcelas_quitadas": 0
}
```

5. Para corrigir: POST `/api/pagamentos/{id}/estornar/` com `{"motivo": "Lançamento incorreto"}`. Consulte novamente parcela e resumo.
6. Para cancelar: estorne explicitamente todos os recebimentos da venda, inclusive sua entrada (consulte `/api/pagamentos/?venda={id}`); POST `/api/vendas/{id}/cancelar/` com `{"motivo": "Venda registrada incorretamente"}`.

## Django Admin

O cadastro de clientes continua com suas operações anteriores. Vendas, parcelas e pagamentos ficam em consulta somente leitura, com filtros, pesquisa e links para detalhes. Detalhe da venda inclui itens e parcelas. Não há cadastro, alteração, exclusão ou ações financeiras pelo Admin; use os endpoints acima, que executam os serviços transacionais. Isso evita rotas de escrita que contornem as regras.

## Verificação e migrações

Na pasta backend:

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --plan
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test --noinput
```

Inspecione sempre o plano antes de aplicar. As migrações desta tarefa criam somente tabelas, relações e restrições novas, sem remoção de tabelas ou dados existentes. Os testes usam o banco separado criado pelo Django, incluindo testes concorrentes com conexões independentes no PostgreSQL. Testes de concorrência são pulados em bancos sem `select_for_update`, portanto use PostgreSQL para a validação completa.

## Resultado da implementação em 02/11/2026

- `manage.py check`: sem problemas.
- `makemigrations --check --dry-run`: nenhuma alteração pendente.
- Plano inspecionado: somente criação de tabelas, relacionamentos e restrições.
- Aplicadas no PostgreSQL: `vendas.0001_initial`, `financeiro.0001_initial`, `financeiro.0002_initial`.
- `manage.py test --noinput`: 85 testes aprovados (57 novos e os 28 de Clientes). Testes de concorrência executados no PostgreSQL, sem pulos.
- Banco de testes separado criado e removido pelo Django; nenhum dado fictício inserido no banco principal.
- Configurações, `.env`, Docker, migração de Clientes e módulo de cobranças preservados. Nenhum commit ou push realizado.
