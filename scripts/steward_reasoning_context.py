"""Offline, temporary conceptual context for a controlled agent experiment.

This module neither builds published documents nor writes to PostgreSQL.
"""
from datetime import date, timedelta

from scripts import new_bank_documents as documents


ANCHORS = {
    'temporal.opening_balance': ('enero registra saldo inicial', 'cierre calendario anterior'),
    'temporal.calendar': ('Enero define saldo inicial', 'último día del mes'),
    'rule.growth': ('cierre objetivo', 'tasa agregada'),
    'rule.reconciliation': ('suma firmada', 'cierre'),
    'relationship.balance_movement': ('JOIN directo', 'mes calendario exacto'),
    'relationship.transaction_catalog': ('cve_producto + cve_txn', 'exactamente una definición'),
    'absence.currency': ('no especifican moneda',),
}


def build_context():
    """Validate anchors against the frozen catalog, then derive calendar examples."""
    catalog=documents.load_catalog()
    entries=catalog['entries']
    for key,needles in ANCHORS.items():
        text=' '.join(claim['text'] for claim in entries[key]['claims'])
        if any(needle not in text for needle in needles):
            raise ValueError('Conceptual context source changed: '+key)
    months=['enero','febrero','marzo','abril','mayo','junio']
    examples=[]
    for month in range(1,7):
        previous=(date(2026,month,1)-timedelta(days=1)) if month>1 else None
        examples.append({'month':months[month-1],
                         'meaning':'saldo inicial de la cuenta' if previous is None else
                         'cierre de '+months[previous.month-1],
                         'source_entries':['temporal.opening_balance','temporal.calendar']})
    return {'label':'EXPERIMENTO DE CONTEXTO; no es un documento publicado ni evidencia independiente',
            'source_entries':list(ANCHORS),
            'explanations':[
                'saldo_apertura es una columna física cuyo significado temporal depende del mes: en enero conserva la apertura original; después representa el saldo al comenzar ese mes, que es el cierre del mes calendario inmediatamente anterior.',
                'La continuidad se comprueba por cuenta y producto, enlazando el cierre del mes previo con la apertura del mes siguiente. Si falta el mes intermedio, no se sustituye por cualquier cierre anterior.',
                'Para explicar un movimiento hay que combinar producto y código con su signo; los importes almacenados son positivos. La suma firmada de movimientos del mes transforma la apertura en el cierre.',
                'Un saldo de cierre es un stock a una fecha; los movimientos son flujos del periodo. Agregar movimientos por cuenta, producto y mes evita duplicar el saldo al hacer JOIN.',
                'Una tasa de crecimiento impuesta por el generador describe el objetivo sintético mensual. No acredita interés contractual ni una moneda; el catálogo no especifica divisa.'
            ],'calendar_examples':examples}
