from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    purchaseflow_intent_id = fields.Char(
        string="PurchaseFlow Intent ID",
        copy=False,
        readonly=True,
        help="Stable source identity for a PurchaseFlow draft request.",
    )

    _purchaseflow_intent_unique = models.Constraint(
        "unique(purchaseflow_intent_id)",
        "A PurchaseFlow intent can create at most one Odoo purchase order.",
    )
