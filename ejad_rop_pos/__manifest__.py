{
    'name': 'Ejad ROP Point of Sale', 'version': '17.0.1.0.0', 'license': 'LGPL-3',
    'depends': ['ejad_rop_inventory', 'point_of_sale'],
    'data': ['views/pos_config_views.xml'],
    'assets': {'point_of_sale._assets_pos': ['ejad_rop_pos/static/src/rop_pos.js', 'ejad_rop_pos/static/src/rop_pos.xml']},
    'installable': True,
}
