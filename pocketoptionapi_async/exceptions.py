"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, com uma hierarquia padronizada de exceções para tratamento seguro de falhas operacionais.

Descrição:
Módulo responsável pela definição das exceções personalizadas da biblioteca. Fornece uma hierarquia consistente de erros para conexão, autenticação, ordens, timeout, validação de parâmetros e operações WebSocket, permitindo tratamento estruturado de falhas e melhor integração com logs, monitoramento e fluxos de retry.

O que ele faz:
- Define a exceção base da biblioteca
- Padroniza erros relacionados à conexão
- Padroniza erros de autenticação e sessão
- Padroniza erros de ordens e negociação
- Padroniza erros de timeout operacional
- Padroniza erros de validação de parâmetros
- Padroniza erros específicos de transporte WebSocket

Características:
- Hierarquia simples e clara
- Exceção base reutilizável em toda a biblioteca
- Suporte a mensagem e código de erro opcional
- Facilita tratamento especializado por tipo de falha
- Melhora observabilidade e consistência de erros

Requisitos:
- Python 3.10+
"""

class PocketOptionError(Exception):
    """Exceção base para todos os erros da API da PocketOption"""

    from typing import Optional

    def __init__(self, message: str, error_code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code

class ConnectionError(PocketOptionError):
    """Levantada quando a conexão com a PocketOption falha"""

    pass

class AuthenticationError(PocketOptionError):
    """Levantada quando a autenticação falha"""

    pass

class OrderError(PocketOptionError):
    """Levantada quando uma operação de ordem falha"""

    pass

class TimeoutError(PocketOptionError):
    """Levantada quando uma operação atinge o tempo limite"""

    pass

class InvalidParameterError(PocketOptionError):
    """Levantada quando parâmetros inválidos são fornecidos"""

    pass

class WebSocketError(PocketOptionError):
    """Levantada quando operações WebSocket falham"""

    pass