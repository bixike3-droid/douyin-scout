"""护栏：配额、熔断、节流。

这三样是「长期稳定」的全部含金量所在。任何一次采集动作都必须先过这三关。
"""

from .circuit import CircuitBreaker, CircuitOpen
from .quota import QuotaExceeded, QuotaManager
from .throttle import Throttle

__all__ = ["QuotaManager", "QuotaExceeded", "CircuitBreaker", "CircuitOpen", "Throttle"]
