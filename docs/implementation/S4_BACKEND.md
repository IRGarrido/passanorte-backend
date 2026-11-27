# S4 — Rotas, check-in e guaranás

| Fluxo | API sob `/api/v1` |
| --- | --- |
| Rotas | `GET /routes` e `GET /routes/{id}`. Administradores usam `GET /admin/routes` e `POST/PATCH/DELETE` para gerenciar as rotas. A criação exige `points` com pelo menos dois IDs distintos, `category_ids` com pelo menos um tema ativo e `reward_amount` não negativo. |
| Inscrição | `POST /routes/{id}/enrollments`. Consulte progresso em `GET /enrollments` ou `GET /enrollments/{id}`. Use `DELETE /enrollments/{id}` para desistir. As consultas são somente leitura. |
| Check-in | `POST /visits` recebe `tourist_spot_id`, `latitude`, `longitude` e `accuracy_m`. Consulte o histórico em `GET /visits` e `GET /visits/{spot_id}`. |
| Crédito | A resposta de check-in distingue `201` com crédito confirmado, `202` com crédito pendente e `200` com visita já existente. Consulte a intenção em `GET /reward-operations/{id}` ou solicite nova tentativa com `POST /reward-operations/{id}/retry`. |
| Saldo | `GET /me/balance` retorna o saldo do turista autenticado, calculado pelos lançamentos no ledger de Benefícios. |

## Regras adotadas

- **D01:** o raio efetivo usa o override do ponto ou `CHECKIN_RADIUS_M` (100 m por padrão), somado a `CHECKIN_TOLERANCE_M` (0 m). A precisão enviada é registrada junto com a distância e o resultado. A precisão não aumenta o limiar. Pontos fechados ou removidos rejeitam novas visitas.
- **D03:** o progresso usa os pontos ainda válidos. Visitas anteriores contam e uma visita pode concluir mais de uma rota. Uma rota sem pontos válidos não gera conclusão automática. Alterações no Catálogo disparam reavaliação por evento. Conclusões existentes mantêm o valor registrado. Retirar a inscrição ou remover a rota preserva o histórico e o saldo.
- O crédito por visita tem padrão de 1 guaraná e usa `VISIT_REWARD_AMOUNT`. Benefícios valida os comandos via assinatura e usa a origem para deduplicar a chamada direta e o reenvio pelo RabbitMQ. A intenção e a outbox são gravadas na mesma transação da visita ou conclusão. A consulta de uma intenção pendente mostra o saldo apenas quando Benefícios responde.
- A migração remove latitude e longitude do turista e conserva resultados legados. A precisão de visitas antigas fica nula. Rotas legadas recebem recompensa zero e herdam temas dos pontos válidos quando disponíveis. Rotas antigas sem o mínimo exigido ficam inativas para revisão. Conclusões legadas são registradas sem crédito retroativo.

## Validação integrada

Se a pasta `secrets` já existia na S3, execute uma vez:

```powershell
uv run --frozen python scripts/generate_secrets.py --add-s4
```

Com o Docker Desktop aberto, atualize a stack e recarregue o Kong:

```powershell
docker compose --env-file .env.example up --build -d --wait --wait-timeout 180
docker compose --env-file .env.example up -d --no-deps --force-recreate --wait kong
```

O smoke usa uma conta e pontos fictícios em uma stack de desenvolvimento. A opção de falha interrompe e reativa Benefícios e RabbitMQ. O ensaio de migração abaixo usa um banco isolado:

```powershell
uv run --frozen python scripts/smoke_s4.py --exercise-outage
& "C:\Program Files\Git\bin\bash.exe" scripts/verify_s2_migration.sh --s4
```

As telas Android e React permanecem na etapa P4 do [plano de implementação](../planning/PASSANORTE_IMPLEMENTATION_PLAN.md#post_mvp).
