"""
Autor: ByJhonesDev
Projeto: PocketOptionAPI – Biblioteca Python assíncrona de alto nível para integração com a corretora Pocket Option, fornecendo uma camada confiável, configurável e orientada a eventos para automação operacional e processamento de dados de mercado em tempo real.

Descrição:
Módulo responsável pela centralização e gerenciamento de todas as configurações da biblioteca, incluindo parâmetros de conexão WebSocket, regras operacionais de negociação e controle de logging. A estrutura utiliza dataclasses para organização tipada e permite sobrescrita dinâmica via variáveis de ambiente, facilitando a adaptação em diferentes ambientes (desenvolvimento, produção, containers, CI/CD).

O que ele faz:
- Define configurações de conexão WebSocket (ping, timeout, reconexão e limites)
- Define regras operacionais de trading (valores mínimos/máximos, duração e concorrência)
- Define parâmetros de logging (nível, formato, rotação e retenção)
- Carrega automaticamente configurações via variáveis de ambiente (ENV override)
- Fornece uma interface unificada para acesso às configurações da aplicação
- Exporta as configurações em formato dicionário para integração com outros módulos

Características:
- Estrutura tipada com dataclasses (melhor manutenção e clareza)
- Separação lógica por domínio: conexão, trading e logging
- Suporte a configuração dinâmica via variáveis de ambiente
- Valores padrão seguros e prontos para uso
- Instância global de configuração para acesso centralizado
- Fácil extensão para novos parâmetros sem quebrar compatibilidade

Requisitos:
- Python 3.10+
- dataclasses
- typing
- os (variáveis de ambiente)
"""

import os
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class ConnectionConfig:
    """Configuração de conexão WebSocket"""

    ping_interval: int = 20
    ping_timeout: int = 10
    close_timeout: int = 10
    max_reconnect_attempts: int = 5
    reconnect_delay: int = 5
    message_timeout: int = 30

@dataclass
class TradingConfig:
    """Configuração de negociação"""

    min_order_amount: float = 1.0
    max_order_amount: float = 50000.0
    min_duration: int = 60
    max_duration: int = 43200
    max_concurrent_orders: int = 10
    default_timeout: float = 30.0

@dataclass
class LoggingConfig:
    """Configuração de logging"""

    level: str = "INFO"
    format: str = (
        "{time:DD-MM-YYYY HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
    )
    rotation: str = "1 day"
    retention: str = "7 days"
    log_file: str = "pocketoption_async.log"

class Config:
    """Classe principal de configuração"""

    def __init__(self):
        self.connection = ConnectionConfig()
        self.trading = TradingConfig()
        self.logging = LoggingConfig()

        # Carregar de variáveis de ambiente
        self._load_from_env()

    def _load_from_env(self):
        """Carregar configuração de variáveis de ambiente"""

        # Configurações de conexão
        self.connection.ping_interval = int(
            os.getenv("PING_INTERVAL", self.connection.ping_interval)
        )
        self.connection.ping_timeout = int(
            os.getenv("PING_TIMEOUT", self.connection.ping_timeout)
        )
        self.connection.max_reconnect_attempts = int(
            os.getenv("MAX_RECONNECT_ATTEMPTS", self.connection.max_reconnect_attempts)
        )

        # Configurações de negociação
        self.trading.min_order_amount = float(
            os.getenv("MIN_ORDER_AMOUNT", self.trading.min_order_amount)
        )
        self.trading.max_order_amount = float(
            os.getenv("MAX_ORDER_AMOUNT", self.trading.max_order_amount)
        )
        self.trading.default_timeout = float(
            os.getenv("DEFAULT_TIMEOUT", self.trading.default_timeout)
        )

        # Configurações de logging
        self.logging.level = os.getenv("LOG_LEVEL", self.logging.level)
        self.logging.log_file = os.getenv("LOG_FILE", self.logging.log_file)

    def to_dict(self) -> Dict[str, Any]:
        """Converter configuração para dicionário"""
        return {
            "connection": {
                "ping_interval": self.connection.ping_interval,
                "ping_timeout": self.connection.ping_timeout,
                "close_timeout": self.connection.close_timeout,
                "max_reconnect_attempts": self.connection.max_reconnect_attempts,
                "reconnect_delay": self.connection.reconnect_delay,
                "message_timeout": self.connection.message_timeout,
            },
            "trading": {
                "min_order_amount": self.trading.min_order_amount,
                "max_order_amount": self.trading.max_order_amount,
                "min_duration": self.trading.min_duration,
                "max_duration": self.trading.max_duration,
                "max_concurrent_orders": self.trading.max_concurrent_orders,
                "default_timeout": self.trading.default_timeout,
            },
            "logging": {
                "level": self.logging.level,
                "format": self.logging.format,
                "rotation": self.logging.rotation,
                "retention": self.logging.retention,
                "log_file": self.logging.log_file,
            },
        }

# Instância global de configuração
config = Config()