"""UX routing guard; tool availability enforces the capability boundary."""
import re
import unicodedata

def unavailable_request(question):
    """Atajo de alcance para la UX; NO es un control de autorizacion."""
    text = "".join(c for c in unicodedata.normalize("NFKD", question.casefold()) if not unicodedata.combining(c))
    return any(re.search(pattern, text) for pattern in (
        r'\b(?:saldo total|mayor saldo|cuantos clientes|cuantos.*anomalias|suma de saldos)\b',
        r'\b(?:promedio|sumatoria|maximo|minimo|suma)\b.{0,50}\b(?:saldo|saldos|clientes|movimientos)\b',
        r"\bsyn-[ctl]-\d+\b",
        r"\b(?:cliente|customer|cuenta|account)\s*(?:numero|number|id|#|:)?\s*\d+\b",
        r"\b(?:mi saldo|mi cuenta|mis transacciones|mis prestamos|my balance|my account)\b",
        r"\b(?:datos|informacion|registros)\s+(?:bancarios\s+)?individuales\b",
        r"\bcliente\s+(?:llamad[oa]|con\s+(?:id|identificador)|de\s+nombre)\b",
        r"\b(?:select|insert|update|delete|truncate|drop)\b",
        r"\b(?:genera|generar|escribe|escribir|ejecuta|ejecutar|generate|write|execute)\b.{0,60}\bsql\b",
    ))
