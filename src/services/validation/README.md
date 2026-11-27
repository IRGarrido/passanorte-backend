# Validação de visitas

As rotas de visita são executadas no serviço de Gamificação. Elas validam a distância por Haversine e o status do ponto. O banco armazena o resultado, a distância e a precisão, sem guardar latitude ou longitude do turista.

Os endpoints e o comportamento de reenvio estão no [contrato da S4](../../../docs/implementation/S4_BACKEND.md).
