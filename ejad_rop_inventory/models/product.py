from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    has_rop = fields.Boolean('Has ROP')
    rop_count = fields.Integer('ROP Count', default=5)
    same_rop_product_count = fields.Integer(compute='_compute_same_rop_product_count')

    @api.constrains('rop_count')
    def _check_rop_count(self):
        if any(product.rop_count < 0 for product in self):
            raise ValidationError(_('ROP Count cannot be negative.'))

    @api.depends('has_rop', 'rop_count')
    def _compute_same_rop_product_count(self):
        counts = dict(self._read_group(
            [('has_rop', '=', True), ('rop_count', 'in', self.mapped('rop_count'))],
            ['rop_count'], ['__count']))
        for product in self:
            product.same_rop_product_count = max(0, counts.get(product.rop_count, 0) - int(product.active)) if product.has_rop else 0

    def action_same_rop_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Products with the same ROP Count'),
            'res_model': 'product.template', 'view_mode': 'tree,form,kanban',
            'domain': [('id', '!=', self.id), ('has_rop', '=', True), ('rop_count', '=', self.rop_count)],
        }
