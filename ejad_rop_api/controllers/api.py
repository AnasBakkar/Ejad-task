from datetime import datetime, time, timedelta

from odoo import fields, http
from odoo.http import request
from odoo.exceptions import AccessError, ValidationError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound


class RopApi(http.Controller):
    def _authorize(self, group=None):
        if not request.env.user.has_group('base.group_user') or (group and not request.env.user.has_group(group)):
            raise Forbidden('This endpoint requires the appropriate internal user permissions.')

    def _pagination(self, limit, offset):
        try:
            limit, offset = int(limit), int(offset)
            if not 1 <= limit <= 200 or offset < 0:
                raise ValueError()
            return limit, offset
        except (ValueError, TypeError) as error:
            raise BadRequest('limit must be 1..200 and offset must be non-negative.') from error

    @http.route('/api/ejad/orders', type='http', auth='user', methods=['GET'], sitemap=False)
    def orders(self, start=None, end=None, limit='80', offset='0', **kw):
        self._authorize()
        if not (request.env.user.has_group('sales_team.group_sale_salesman') and request.env.user.has_group('point_of_sale.group_pos_user')):
            raise Forbidden('Sales and POS read permissions are required.')
        limit, offset = self._pagination(limit, offset)
        try:
            start_date = datetime.strptime(start, '%Y-%m-%d').date()
            end_date = datetime.strptime(end, '%Y-%m-%d').date()
            if start_date > end_date:
                raise ValueError()
            start_dt = datetime.combine(start_date, time.min)
            end_dt = datetime.combine(end_date + timedelta(days=1), time.min)
        except (TypeError, ValueError, OverflowError) as error:
            raise BadRequest('Provide start and end as YYYY-MM-DD with start <= end (UTC).') from error
        domain = [('date_order', '>=', start_dt), ('date_order', '<', end_dt), ('company_id', '=', request.env.company.id)]
        result = {}
        for model, key in [('sale.order', 'sale_orders'), ('pos.order', 'pos_orders')]:
            records = request.env[model].search(domain, limit=limit + 1, offset=offset, order='date_order,id')
            result[key] = {'orders': self._serialize_orders(records[:limit]), 'has_more': len(records) > limit}
        result.update({'limit': limit, 'offset': offset, 'timezone': 'UTC'})
        return request.make_json_response(result, headers=[('Cache-Control', 'no-store')])

    def _serialize_orders(self, orders):
        return [{'id': o.id, 'name': o.name, 'date_order': fields.Datetime.to_string(o.date_order),
                 'state': o.state, 'customer_id': o.partner_id.id, 'amount_total': o.amount_total,
                 'currency': o.currency_id.name} for o in orders]

    @http.route('/api/ejad/products/rop', type='http', auth='user', methods=['GET'], sitemap=False)
    def products(self, limit='80', offset='0', **kw):
        self._authorize('stock.group_stock_user')
        limit, offset = self._pagination(limit, offset)
        products = request.env['product.product'].search([
            ('has_rop', '=', True), ('company_id', 'in', [False, request.env.company.id]),
        ], limit=limit + 1, offset=offset, order='id')
        return request.make_json_response({
            'products': [{'id': p.id, 'name': p.display_name, 'rop_count': p.rop_count} for p in products[:limit]],
            'has_more': len(products) > limit, 'limit': limit, 'offset': offset,
        }, headers=[('Cache-Control', 'no-store')])

    @http.route('/api/ejad/products/<int:product_id>/rop', type='json', auth='user', methods=['POST'])
    def set_rop(self, product_id, rop_count, **kw):
        self._authorize('stock.group_stock_manager')
        if type(rop_count) is not int or not 0 <= rop_count <= 2147483647:
            raise ValidationError('rop_count must be a non-negative integer.')
        product = request.env['product.product'].search([
            ('id', '=', product_id), ('company_id', 'in', [False, request.env.company.id]),
        ], limit=1)
        if not product:
            raise NotFound('Product not found in the current company.')
        product.product_tmpl_id.write({'has_rop': True, 'rop_count': rop_count})
        return {'id': product.id, 'has_rop': True, 'rop_count': product.rop_count}

    @http.route('/api/ejad/pos/sessions/<int:session_id>/orders', type='http', auth='user', methods=['GET'], sitemap=False)
    def session_orders(self, session_id, limit='80', offset='0', **kw):
        self._authorize('point_of_sale.group_pos_user')
        limit, offset = self._pagination(limit, offset)
        session = request.env['pos.session'].search([
            ('id', '=', session_id), ('company_id', '=', request.env.company.id)], limit=1)
        if not session:
            raise NotFound('POS session not found in the current company.')
        orders = request.env['pos.order'].search([('session_id', '=', session.id)],
            limit=limit + 1, offset=offset, order='date_order,id')
        return request.make_json_response({'session_id': session.id, 'orders': self._serialize_orders(orders[:limit]),
            'has_more': len(orders) > limit, 'limit': limit, 'offset': offset}, headers=[('Cache-Control', 'no-store')])
