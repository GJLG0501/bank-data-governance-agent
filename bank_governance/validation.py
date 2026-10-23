"""Historical experimental calendar checks; not a semantic proof."""
import re
import unicodedata
MONTHS=('enero','febrero','marzo','abril','mayo','junio')

def valid_calendar_statement(text):
    """Check explicit month continuity, not general semantic correctness."""
    plain=''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))
    names='|'.join(MONTHS)
    if re.search(r'cierre de ('+names+r') es (?:el |igual al )?cierre de ('+names+r')',plain):
        return False
    if re.search(r'cierre de ('+names+r') es (?:el )?saldo inicial',plain):
        return False
    if re.search(r'cierre de ('+names+r') es (?:el )?(?:saldo al comenzar|cierre del mes calendario anterior)',plain):
        return False
    for pattern in (
        r'(?:saldo_apertura|apertura).{0,65}(?:de|para|en) ('+names+r').{0,90}cierre de ('+names+r')',
        r'(?:para|en) ('+names+r').{0,65}(?:saldo_apertura|apertura).{0,90}cierre de ('+names+r')',
    ):
        for match in re.finditer(pattern,plain):
            month,previous=match.groups()
            if month=='enero' or MONTHS.index(previous)!=MONTHS.index(month)-1:
                return False
    return True
