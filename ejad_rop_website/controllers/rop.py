import base64

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError, ValidationError
from werkzeug.exceptions import Forbidden, BadRequest, NotFound


class RopWebsite(http.Controller):
    def _service(self):
        service = request.env['ejad.rop.service']
        service.check_reader()
        return service

    @http.route(['/rop', '/rop/realtime'], type='http', auth='user', website=True, sitemap=False)
    def rop_page(self, **kw):
        try:
            service = self._service()
        except AccessError as error:
            raise Forbidden(str(error)) from error
        realtime = request.httprequest.path.endswith('/realtime')
        return request.render('ejad_rop_website.rop_page', {
            'realtime': realtime, 'can_adjust': service.can_adjust(),
            'warehouse': service.warehouse(),
        })

    @http.route(['/rop-product', '/ejad/rop/products'], type='http', auth='user', methods=['GET'], sitemap=False)
    def rop_products(self, comparison='<', limit='80', offset='0', **kw):
        try:
            service = self._service()
            # /rop-product always means strictly below five, regardless of query.
            if request.httprequest.path == '/rop-product':
                comparison = '<'
            limit, offset = int(limit), int(offset)
            if not 1 <= limit <= 200 or offset < 0:
                raise ValueError('Invalid pagination')
            products = service.products(comparison, limit + 1, offset)
            return request.make_json_response({
                'products': service.serialize(products[:limit]),
                'has_more': len(products) > limit, 'offset': offset, 'limit': limit,
                'warehouse': service.warehouse().display_name,
            }, headers=[('Cache-Control', 'no-store')])
        except AccessError as error:
            raise Forbidden(str(error)) from error
        except (ValueError, ValidationError) as error:
            raise BadRequest(str(error)) from error

    @http.route('/ejad/rop/update', type='json', auth='user', methods=['POST'])
    def update_quantity(self, product_id, quantity):
        return self._service().update_quantity(product_id, quantity)

    @http.route('/ejad/rop/image/<int:product_id>', type='http', auth='user', methods=['GET'], sitemap=False)
    def product_image(self, product_id):
        try:
            self._service()
        except AccessError as error:
            raise Forbidden(str(error)) from error
        product = request.env['product.product'].sudo().search([
            ('id', '=', product_id), ('company_id', 'in', [False, request.env.company.id]), ('type', '=', 'product'),
        ], limit=1)
        if not product:
            raise NotFound()
        if not product.image_256:
            return request.redirect('/web/static/img/placeholder.png')
        image = base64.b64decode(product.image_256)
        from odoo.tools.mimetypes import guess_mimetype
        return request.make_response(image, headers=[('Content-Type', guess_mimetype(image)), ('Cache-Control', 'private, no-cache')])
