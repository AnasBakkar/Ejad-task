from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _ejad_check_outgoing_date(self):
        for picking in self:
            if (picking.picking_type_code == 'outgoing' and picking.state not in ('done', 'cancel')
                    and picking.scheduled_date
                    and fields.Datetime.context_timestamp(picking, picking.scheduled_date).date()
                    < fields.Date.context_today(picking)):
                raise ValidationError(_('Outgoing transfers must be scheduled today or later.'))

    @api.constrains('scheduled_date', 'picking_type_id')
    def _check_ejad_outgoing_date(self):
        self._ejad_check_outgoing_date()

    def button_validate(self):
        self._ejad_check_outgoing_date()
        return super().button_validate()
