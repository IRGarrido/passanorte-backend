# Gamificação

Opera na porta interna 8004 e reúne check-in, histórico de visitas, inscrições e progresso. O Catálogo fornece pontos e rotas. Benefícios é responsável pelo saldo e pelos lançamentos.

As alterações de Catálogo disparam reavaliação das inscrições. Visitas e inscrições também podem concluir rotas. As consultas de progresso são somente leitura. A outbox publica pedidos assinados de crédito para processamento idempotente em Benefícios.

Consulte as rotas, configuração e ensaios no [contrato da S4](../../../docs/implementation/S4_BACKEND.md).
