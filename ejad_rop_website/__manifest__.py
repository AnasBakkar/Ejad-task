{
    'name': 'Ejad ROP eCommerce', 'version': '17.0.1.0.0', 'license': 'LGPL-3',
    'depends': ['ejad_rop_inventory', 'website_sale_stock'],
    'data': ['views/rop_templates.xml'],
    'assets': {'web.assets_frontend': ['ejad_rop_website/static/src/rop.js']},
    'installable': True,
}
