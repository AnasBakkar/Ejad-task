from collections import defaultdict
from math import isfinite

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    ejad_cash_partner_id = fields.Many2one('res.partner', string='Cash now customer',
        default=lambda self: self.env.ref('base.user_admin').partner_id,
        help='Defaults to Administrator. The customer must have a phone beginning with +2.')


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _get_pos_ui_res_partner(self, params):
        partners = super()._get_pos_ui_res_partner(params)
        partner = self.config_id.ejad_cash_partner_id
        if partner and partner.id not in [p['id'] for p in partners]:
            partners += partner.read(params['search_params']['fields'])
        return partners

    def ejad_check_stock(self, lines):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('POS access required.'))
        self.check_access_rights('read')
        self.check_access_rule('read')
        if self.state not in ('opened', 'opening_control'):
            raise ValidationError(_('The POS session is not open.'))
        if not isinstance(lines, list) or len(lines) > 1000:
            raise ValidationError(_('Invalid order lines.'))
        quantities = defaultdict(float)
        for line in lines:
            if not isinstance(line, dict) or type(line.get('product_id')) is not int:
                raise ValidationError(_('Invalid product.'))
            qty = line.get('qty')
            if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not isfinite(qty):
                raise ValidationError(_('Invalid quantity.'))
            if qty > 0:
                quantities[line['product_id']] += qty
        location = self.config_id.picking_type_id.default_location_src_id
        if not location:
            raise ValidationError(_('The POS must have a source stock location.'))
        products = self.env['product.product'].with_company(self.company_id).with_context(
            allowed_company_ids=[self.company_id.id], location=location.id).search([
                ('id', 'in', list(quantities)), ('company_id', 'in', [False, self.company_id.id])])
        if set(products.ids) != set(quantities):
            raise ValidationError(_('One or more products are unavailable in this company.'))
        blocked = []
        service = self.env['ejad.rop.service'].with_company(self.company_id)
        for product in products.filtered(lambda p: p.type == 'product'):
            if product.qty_available <= 5 or product.qty_available < quantities[product.id]:
                blocked.append({'id': product.id, 'name': product.display_name, 'quantity': product.qty_available})
                if product.qty_available < 5:
                    service._notify_managers(product,
                        _('%s is below five units. Check its reorder point.', product.display_name), low_stock=True)
        return {'ok': not blocked, 'products': blocked,
                'message': _('This product under of the Re-Order Point measure') if blocked else ''}


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def _ejad_validate_customer(self, partner):
        if not partner:
            raise ValidationError(_('Select a customer before validating payment.'))
        if not partner.phone or not partner.phone.strip():
            raise ValidationError(_('The customer must have a phone number.'))
        if not partner.phone.strip().startswith('+2'):
            raise ValidationError(_('The customer phone number must start with +2.'))

    @api.model
    def create_from_ui(self, orders, draft=False):
        if draft:
            return super().create_from_ui(orders, draft=True)
        results = []
        for order in orders:
            data = order['data']
            # Match Odoo's actual duplicate test; a reused reference with changed
            # lines/payments is a new order and must still pass every validation.
            existing = self.search([('pos_reference', '=', data.get('name')), ('state', '!=', 'draft')])
            duplicate = any(self._is_the_same_order(data, saved) for saved in existing)
            if not duplicate:
                partner = self.env['res.partner'].browse(data.get('partner_id')).exists()
                self._ejad_validate_customer(partner)
                session = self.env['pos.session'].browse(data.get('pos_session_id')).exists()
                if not session:
                    raise ValidationError(_('POS session not found.'))
                lines = [{'product_id': line[2]['product_id'], 'qty': line[2]['qty']} for line in data.get('lines', [])]
                product_ids = sorted({line['product_id'] for line in lines if type(line['product_id']) is int})
                if product_ids:
                    self.env.cr.execute('SELECT id FROM product_product WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(product_ids)])
                    self.env['product.product'].invalidate_model(['qty_available'])
                result = session.ejad_check_stock(lines)
                if not result['ok']:
                    raise ValidationError(result['message'])
            # Process sequentially so a batch sees stock consumed by earlier orders.
            results.extend(super().create_from_ui([order], draft=False))
        return results
