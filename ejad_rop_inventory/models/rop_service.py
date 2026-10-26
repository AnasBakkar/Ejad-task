from markupsafe import Markup, escape

from odoo import SUPERUSER_ID, _, api, models
from odoo.exceptions import AccessError, ValidationError


class RopService(models.AbstractModel):
    _name = 'ejad.rop.service'
    _description = 'ROP authorization, stock adjustments and notifications'

    @api.model
    def check_reader(self):
        if not self.env.user.has_group('base.group_user'):
            raise AccessError(_('ROP is available to internal users only.'))

    @api.model
    def can_adjust(self):
        return self.env.user.has_group('stock.group_stock_user') or self.env.user.has_group('base.group_system')

    @api.model
    def warehouse(self):
        self.check_reader()
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        if not warehouse:
            raise ValidationError(_('Configure a warehouse for the current company first.'))
        return warehouse

    @api.model
    def products(self, comparison='<', limit=80, offset=0):
        self.check_reader()
        if comparison not in ('<', '>'):
            raise ValidationError(_('Invalid stock comparison.'))
        location = self.warehouse().lot_stock_id
        # Stock-only elevation lets ordinary internal users read the ROP page. The
        # explicit company domain and location context prevent cross-company leakage.
        return self.env['product.product'].sudo().with_company(self.env.company).with_context(
            allowed_company_ids=[self.env.company.id], location=location.id
        ).search([
            ('type', '=', 'product'), ('company_id', 'in', [False, self.env.company.id]),
            ('qty_available', comparison, 5),
        ], limit=limit, offset=offset, order='id')

    @api.model
    def serialize(self, products):
        return [{'id': p.id, 'name': p.display_name, 'quantity': p.qty_available,
                 'has_rop': p.has_rop, 'rop_count': p.rop_count,
                 'image_url': '/ejad/rop/image/%s' % p.id} for p in products]

    @api.model
    def _notify_managers(self, product, body, exclude_self=False, low_stock=False):
        managers = self.env.ref('stock.group_stock_manager').sudo().users.filtered(
            lambda u: u.active and self.env.company in u.company_ids and (not exclude_self or u.id != self.env.uid))
        for user in managers:
            # One outstanding activity per product/manager; repeated Pay clicks
            # cannot flood an administrator's inbox.
            if low_stock:
                activity = self.env['mail.activity'].sudo().search([
                    ('res_model', '=', 'product.product'), ('res_id', '=', product.id),
                    ('user_id', '=', user.id), ('summary', '=', 'ROP stock review'),
                ], limit=1)
                if activity:
                    continue
                product.sudo().activity_schedule('mail.mail_activity_data_todo',
                    user_id=user.id, summary='ROP stock review', note=body)
            product.sudo().message_notify(partner_ids=[user.partner_id.id],
                                          subject=_('ROP stock notification'), body=escape(body))
            self.env['bus.bus']._sendone(user.partner_id, 'simple_notification', {
                'title': _('ROP stock notification'), 'message': body, 'sticky': True, 'type': 'warning' if low_stock else 'info',
            })

    @api.model
    def update_quantity(self, product_id, quantity):
        self.check_reader()
        if not self.can_adjust():
            raise AccessError(_('Only inventory users or administrators can adjust stock.'))
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 0 <= quantity <= 2147483647:
            raise ValidationError(_('Quantity must be a non-negative integer.'))
        warehouse = self.warehouse()
        product = self.env['product.product'].sudo().search([
            ('id', '=', product_id), ('type', '=', 'product'),
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)
        if not product:
            raise ValidationError(_('Stockable product not found in the current company.'))
        if product.tracking != 'none':
            raise ValidationError(_('Use Inventory to adjust products tracked by lots or serial numbers.'))
        # Serialize absolute updates for a product, including its child locations.
        self.env.cr.execute('SELECT id FROM product_product WHERE id = %s FOR UPDATE', [product.id])
        location = warehouse.lot_stock_id
        product = product.with_context(location=location.id, allowed_company_ids=[self.env.company.id])
        old_quantity = product.qty_available
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id), ('location_id', 'child_of', location.id),
            ('owner_id', '=', False), ('company_id', '=', self.env.company.id),
        ])
        if any(quants.mapped('package_id')):
            raise ValidationError(_('Use Inventory to adjust packaged stock.'))
        # Preserve child-location stock; apply the difference to the main location.
        main_quant = quants.filtered(lambda q: q.location_id == location and not q.lot_id)[:1]
        delta = quantity - sum(quants.mapped('quantity'))
        target = (main_quant.quantity if main_quant else 0) + delta
        if target < 0:
            raise ValidationError(_('This target would make main-location stock negative. Adjust the child locations in Inventory.'))
        Quant = self.env['stock.quant'].sudo().with_company(self.env.company).with_context(inventory_mode=True)
        if not main_quant:
            main_quant = Quant.create({'product_id': product.id, 'location_id': location.id})
        main_quant.with_context(inventory_mode=True).inventory_quantity = target
        # The popup explicitly delegates this scoped adjustment to inventory users;
        # Odoo's underlying validation requires a stock-manager identity.
        main_quant.with_user(SUPERUSER_ID)._apply_inventory()
        product.invalidate_recordset(['qty_available'])
        body = _('%(product)s quantity changed from %(old)s to %(new)s by %(user)s.',
                 product=product.display_name, old=old_quantity, new=quantity, user=self.env.user.name)
        product.sudo().message_post(body=Markup('<p>%s</p>') % escape(body))
        self._notify_managers(product, body, exclude_self=True)
        if quantity > 5:
            self.env['mail.activity'].sudo().search([
                ('res_model', '=', 'product.product'), ('res_id', '=', product.id),
                ('summary', '=', 'ROP stock review'),
            ]).action_feedback(feedback=_('Stock replenished above five units.'))
        return {'id': product.id, 'quantity': product.qty_available}
